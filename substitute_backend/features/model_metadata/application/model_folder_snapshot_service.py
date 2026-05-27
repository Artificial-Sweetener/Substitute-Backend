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
"""Build cheap model folder snapshots and diffs for catalog refresh events."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from substitute_backend.features.model_metadata.domain.change_events import (
    ModelCatalogChangedEntry,
    ModelFileIdentity,
    ModelFileStatSnapshot,
)
from substitute_backend.features.model_metadata.infrastructure.comfy_model_roots import (
    ModelRootsProvider,
)
from substitute_backend.features.model_metadata.infrastructure.time_utils import (
    format_timestamp,
)


@dataclass(frozen=True, slots=True)
class ModelFolderSnapshot:
    """Store one cheap model catalog generation grouped by stable file identity."""

    entries: Mapping[tuple[str, str, str], ModelCatalogChangedEntry]
    paths: Mapping[tuple[str, str, str], Path]

    def entries_for_kinds(self, kinds: Iterable[str]) -> tuple[ModelCatalogChangedEntry, ...]:
        """Return entries whose kind is in the requested set."""

        selected = set(kinds)
        return tuple(entry for entry in self.entries.values() if entry.kind in selected)

    def replace_kinds(
        self,
        *,
        kinds: Iterable[str],
        replacement: ModelFolderSnapshot,
    ) -> ModelFolderSnapshot:
        """Return a snapshot with selected kinds replaced by new entries."""

        selected = set(kinds)
        entries = {key: entry for key, entry in self.entries.items() if entry.kind not in selected}
        paths = {
            key: path
            for key, path in self.paths.items()
            if self.entries.get(key) is not None and self.entries[key].kind not in selected
        }
        for key, entry in replacement.entries.items():
            entries[key] = entry
        for key, path in replacement.paths.items():
            paths[key] = path
        return ModelFolderSnapshot(entries=entries, paths=paths)


@dataclass(frozen=True, slots=True)
class ModelFolderSnapshotDiff:
    """Describe cheap add/remove/modify differences between two snapshots."""

    added: tuple[ModelCatalogChangedEntry, ...]
    removed: tuple[ModelCatalogChangedEntry, ...]
    modified: tuple[ModelCatalogChangedEntry, ...]

    @property
    def has_changes(self) -> bool:
        """Return whether this diff contains any model changes."""

        return bool(self.added or self.removed or self.modified)

    @property
    def changed_kinds(self) -> tuple[str, ...]:
        """Return sorted kinds touched by this diff."""

        return tuple(sorted({entry.kind for entry in (*self.added, *self.removed, *self.modified)}))


class ModelFolderSnapshotService:
    """Create cheap snapshots from Comfy-visible model files."""

    def __init__(self, model_roots: ModelRootsProvider) -> None:
        """Store the authoritative model root provider."""

        self._model_roots = model_roots

    def build_snapshot(
        self,
        kinds: Iterable[str] | None = None,
    ) -> ModelFolderSnapshot:
        """Build a full or kind-limited snapshot without hashing model files."""

        entries: dict[tuple[str, str, str], ModelCatalogChangedEntry] = {}
        paths: dict[tuple[str, str, str], Path] = {}
        for model_file in self._model_roots.list_model_files(kinds):
            stat = model_file.path.stat()
            entry = ModelCatalogChangedEntry(
                identity=ModelFileIdentity(
                    kind=model_file.kind,
                    value=model_file.value,
                    root_id=model_file.root_id,
                    relative_path=model_file.relative_path,
                ),
                file=ModelFileStatSnapshot(
                    size_bytes=stat.st_size,
                    modified_at=format_timestamp(stat.st_mtime),
                ),
            )
            key = entry.stable_key()
            entries[key] = entry
            paths[key] = model_file.path
        return ModelFolderSnapshot(entries=entries, paths=paths)

    @staticmethod
    def diff(
        previous: ModelFolderSnapshot,
        current: ModelFolderSnapshot,
    ) -> ModelFolderSnapshotDiff:
        """Return added, removed, and stat-modified entries."""

        previous_keys = set(previous.entries)
        current_keys = set(current.entries)
        added = tuple(current.entries[key] for key in sorted(current_keys - previous_keys))
        removed = tuple(previous.entries[key] for key in sorted(previous_keys - current_keys))
        modified: list[ModelCatalogChangedEntry] = []
        for key in sorted(previous_keys & current_keys):
            old_entry = previous.entries[key]
            new_entry = current.entries[key]
            if old_entry.file.stable_key() != new_entry.file.stable_key():
                modified.append(new_entry)
        return ModelFolderSnapshotDiff(
            added=added,
            removed=removed,
            modified=tuple(modified),
        )


def known_file_stat_changes(
    previous: ModelFolderSnapshot,
) -> tuple[str, ...]:
    """Return kinds whose known files changed without requiring a full rescan."""

    changed: set[str] = set()
    for key, entry in previous.entries.items():
        path = previous.paths.get(key)
        if path is None:
            continue
        try:
            stat = path.stat()
        except OSError:
            changed.add(entry.kind)
            continue
        if (
            stat.st_size,
            format_timestamp(stat.st_mtime),
        ) != entry.file.stable_key():
            changed.add(entry.kind)
    return tuple(sorted(changed))


__all__ = [
    "ModelFolderSnapshot",
    "ModelFolderSnapshotDiff",
    "ModelFolderSnapshotService",
    "known_file_stat_changes",
]
