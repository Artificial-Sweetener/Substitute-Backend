#    Substitute BackEnd - backend liaison services for SugarSubstitute and ComfyUI
#    Copyright (C) 2026  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""Monitor Comfy model folders and publish low-cost catalog change events."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from substitute_backend.features.model_metadata.application.model_folder_snapshot_service import (
    ModelFolderSnapshot,
    ModelFolderSnapshotDiff,
    ModelFolderSnapshotService,
    known_file_stat_changes,
)
from substitute_backend.features.model_metadata.domain.change_events import (
    ModelCatalogChangeSet,
)
from substitute_backend.features.model_metadata.infrastructure.comfy_model_roots import (
    ModelRootsProvider,
)

MODEL_FOLDER_CHANGED_REASON = "folder-changed"
DEFAULT_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_DEBOUNCE_SECONDS = 1.5
DEFAULT_SAFETY_SCAN_INTERVAL_SECONDS = 180.0


class ModelCatalogChangePublisher(Protocol):
    """Publish model catalog change events to interested clients."""

    def publish(self, event: ModelCatalogChangeSet) -> None:
        """Publish one model catalog change event."""


class ModelFolderCacheInvalidator(Protocol):
    """Invalidate Comfy filename-list caches for changed model kinds."""

    def invalidate(self, kinds: Iterable[str]) -> None:
        """Invalidate cached filename lists for the given kinds."""


class AffectedNodeClassResolver(Protocol):
    """Resolve model folder kinds to node classes using those lists."""

    def affected_node_classes(self, kinds: Iterable[str]) -> tuple[str, ...]:
        """Return affected node classes for changed model kinds."""


class ModelFolderChangeMonitor:
    """Poll model roots with cheap idle checks and publish coalesced deltas."""

    def __init__(
        self,
        *,
        model_roots: ModelRootsProvider,
        snapshot_service: ModelFolderSnapshotService,
        publisher: ModelCatalogChangePublisher,
        node_class_resolver: AffectedNodeClassResolver,
        cache_invalidator: ModelFolderCacheInvalidator,
        logger: logging.Logger,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
        safety_scan_interval_seconds: float = DEFAULT_SAFETY_SCAN_INTERVAL_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize the monitor without starting background work."""

        self._model_roots = model_roots
        self._snapshot_service = snapshot_service
        self._publisher = publisher
        self._node_class_resolver = node_class_resolver
        self._cache_invalidator = cache_invalidator
        self._logger = logger
        self._poll_interval_seconds = poll_interval_seconds
        self._debounce_seconds = debounce_seconds
        self._safety_scan_interval_seconds = safety_scan_interval_seconds
        self._sleep = sleep
        self._monotonic = monotonic
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._snapshot: ModelFolderSnapshot | None = None
        self._directory_mtimes_by_kind: dict[str, dict[str, float]] = {}
        self._last_safety_scan_at = 0.0
        self._last_revision = ""
        self._latest_change: ModelCatalogChangeSet | None = None

    @property
    def is_running(self) -> bool:
        """Return whether the monitor thread is alive."""

        thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def latest_change(self) -> ModelCatalogChangeSet | None:
        """Return the latest published change for reconnect recovery."""

        with self._lock:
            return self._latest_change

    @property
    def revision(self) -> str:
        """Return the latest known catalog revision."""

        with self._lock:
            return self._last_revision

    def start(self) -> None:
        """Start the background polling thread once."""

        with self._lock:
            if self.is_running:
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="SubstituteModelFolderChangeMonitor",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Request monitor shutdown and wait briefly for the thread to exit."""

        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=min(1.0, max(0.01, self._poll_interval_seconds)))

    def check_once(self, *, force_safety_scan: bool = False) -> ModelCatalogChangeSet | None:
        """Run one polling turn and return a published change when present."""

        with self._lock:
            if self._snapshot is None:
                self._snapshot = self._snapshot_service.build_snapshot()
                self._directory_mtimes_by_kind = self._directory_mtimes()
                self._last_safety_scan_at = self._monotonic()
                self._last_revision = self._new_revision()
                self._logger.debug("Initialized model folder change monitor")
                return None
            previous = self._snapshot

        dirty_kinds = set(self._dirty_kinds_by_directory_mtime())
        if force_safety_scan or self._safety_scan_due():
            dirty_kinds.update(known_file_stat_changes(previous))
            self._last_safety_scan_at = self._monotonic()
        if not dirty_kinds:
            return None

        sorted_dirty_kinds = tuple(sorted(dirty_kinds))
        self._cache_invalidator.invalidate(sorted_dirty_kinds)
        stable_snapshot = self._stable_dirty_snapshot(sorted_dirty_kinds)
        if stable_snapshot is None:
            self._logger.debug(
                "Model folder change deferred until files are stable",
                extra={"dirty_kinds": sorted_dirty_kinds},
            )
            return None
        current = previous.replace_kinds(
            kinds=dirty_kinds,
            replacement=stable_snapshot,
        )
        diff = self._snapshot_service.diff(previous, current)
        with self._lock:
            self._directory_mtimes_by_kind = self._directory_mtimes()
            self._snapshot = current
        if not diff.has_changes:
            return None
        changed_kinds = diff.changed_kinds
        affected_node_classes = self._affected_node_classes(changed_kinds)
        event = self._build_event(
            changed_kinds=changed_kinds,
            affected_node_classes=affected_node_classes,
            diff=diff,
        )
        with self._lock:
            self._last_revision = event.revision
            self._latest_change = event
        self._publisher.publish(event)
        self._logger.info(
            "Published model catalog change",
            extra={
                "revision": event.revision,
                "previous_revision": event.previous_revision,
                "kinds": event.kinds,
                "added": len(event.added),
                "removed": len(event.removed),
                "modified": len(event.modified),
                "affected_node_classes": event.affected_node_classes,
            },
        )
        return event

    def _run(self) -> None:
        """Run the polling loop until shutdown is requested."""

        while not self._stop_event.is_set():
            try:
                self.check_once()
            except Exception:
                self._logger.exception("Model folder change monitor polling failed")
            self._stop_event.wait(self._poll_interval_seconds)

    def _stable_dirty_snapshot(
        self,
        dirty_kinds: tuple[str, ...],
    ) -> ModelFolderSnapshot | None:
        """Return a dirty-kind snapshot only after two matching stat reads."""

        if self._debounce_seconds > 0:
            self._sleep(self._debounce_seconds)
        first = self._snapshot_service.build_snapshot(dirty_kinds)
        if self._debounce_seconds > 0:
            self._sleep(self._debounce_seconds)
        second = self._snapshot_service.build_snapshot(dirty_kinds)
        if self._snapshot_service.diff(first, second).has_changes:
            return None
        return second

    def _dirty_kinds_by_directory_mtime(self) -> tuple[str, ...]:
        """Return kinds whose directory mtime maps changed since the last turn."""

        current = self._directory_mtimes()
        dirty = [
            kind
            for kind, mtimes in current.items()
            if mtimes != self._directory_mtimes_by_kind.get(kind)
        ]
        missing = [kind for kind in self._directory_mtimes_by_kind if kind not in current]
        return tuple(sorted(set(dirty + missing)))

    def _directory_mtimes(self) -> dict[str, dict[str, float]]:
        """Return cheap per-kind directory mtime maps without reading files."""

        result: dict[str, dict[str, float]] = {}
        for kind in self._model_roots.supported_kinds():
            mtimes: dict[str, float] = {}
            for root in self._model_roots.roots_for_kind(kind):
                mtimes.update(_directory_mtimes(root))
            result[kind] = mtimes
        return result

    def _safety_scan_due(self) -> bool:
        """Return whether the known-file stat validation pass should run."""

        return (self._monotonic() - self._last_safety_scan_at) >= self._safety_scan_interval_seconds

    def _affected_node_classes(self, kinds: tuple[str, ...]) -> tuple[str, ...]:
        """Return affected node classes, falling back to no broad refresh on failure."""

        try:
            return self._node_class_resolver.affected_node_classes(kinds)
        except Exception as exc:
            self._logger.warning(
                "Failed to resolve affected node classes for model change",
                extra={"kinds": kinds, "error": repr(exc)},
            )
            return ()

    def _build_event(
        self,
        *,
        changed_kinds: tuple[str, ...],
        affected_node_classes: tuple[str, ...],
        diff: ModelFolderSnapshotDiff,
    ) -> ModelCatalogChangeSet:
        """Build one public model catalog change event."""

        revision = self._new_revision()
        return ModelCatalogChangeSet(
            revision=revision,
            previous_revision=self._last_revision,
            generated_at=datetime.now(UTC).isoformat(),
            kinds=changed_kinds,
            added=diff.added,
            removed=diff.removed,
            modified=diff.modified,
            affected_node_classes=affected_node_classes,
            reason=MODEL_FOLDER_CHANGED_REASON,
        )

    @staticmethod
    def _new_revision() -> str:
        """Return an opaque revision token for reconnect recovery."""

        return uuid4().hex


def _directory_mtimes(root: Path) -> dict[str, float]:
    """Return mtime values for existing directories under one root."""

    if not root.is_dir():
        return {}
    mtimes: dict[str, float] = {}
    for dirpath, dirnames, _filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name != ".git"]
        path = Path(dirpath)
        try:
            mtimes[str(path.resolve())] = path.stat().st_mtime
        except OSError:
            continue
    return mtimes


__all__ = [
    "DEFAULT_DEBOUNCE_SECONDS",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "DEFAULT_SAFETY_SCAN_INTERVAL_SECONDS",
    "MODEL_FOLDER_CHANGED_REASON",
    "AffectedNodeClassResolver",
    "ModelCatalogChangePublisher",
    "ModelFolderCacheInvalidator",
    "ModelFolderChangeMonitor",
]
