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
"""Tests for low-resource model folder change detection and publication."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from aiohttp.test_utils import make_mocked_request

from substitute_backend.features.model_metadata.api.routes import (
    build_model_metadata_route_handlers,
)
from substitute_backend.features.model_metadata.application.model_folder_change_monitor import (
    ModelFolderChangeMonitor,
)
from substitute_backend.features.model_metadata.application.model_folder_snapshot_service import (
    ModelFolderSnapshotService,
    known_file_stat_changes,
)
from substitute_backend.features.model_metadata.application.node_model_dependency_index import (
    NodeModelDependencyIndex,
)
from substitute_backend.features.model_metadata.application.services import (
    ModelMetadataServices,
)
from substitute_backend.features.model_metadata.domain.change_events import (
    EVENT_TYPE,
    ModelCatalogChangedEntry,
    ModelCatalogChangeSet,
    ModelFileIdentity,
    ModelFileStatSnapshot,
)
from substitute_backend.features.model_metadata.infrastructure import (
    CachedNodeModelDependencyScanner,
    ComfyFolderCacheInvalidator,
    ComfyNodeModelDependencyScanner,
    PromptServerModelCatalogPublisher,
)
from substitute_backend.features.model_metadata.infrastructure.comfy_model_roots import (
    ComfyModelRootsProvider,
    StaticModelRootsProvider,
)
from substitute_backend.infrastructure.logging import get_logger


class _Publisher:
    """Collect published model catalog events for assertions."""

    def __init__(self) -> None:
        """Initialize an empty event list."""

        self.events: list[ModelCatalogChangeSet] = []

    def publish(self, event: ModelCatalogChangeSet) -> None:
        """Record a published event."""

        self.events.append(event)


class _CacheInvalidator:
    """Collect invalidated kinds for assertions."""

    def __init__(self) -> None:
        """Initialize an empty invalidation list."""

        self.calls: list[tuple[str, ...]] = []

    def invalidate(self, kinds: Iterable[str]) -> None:
        """Record one invalidation call."""

        self.calls.append(tuple(kinds))


class _CatalogRefresh:
    """Collect explicit catalog refresh requests for route tests."""

    def __init__(self, events: list[tuple[str, tuple[str, ...] | None]]) -> None:
        """Store the shared event log."""

        self._events = events

    def refresh(self, kinds: Iterable[str] | None) -> None:
        """Record one explicit refresh request."""

        self._events.append(("refresh", None if kinds is None else tuple(kinds)))


class _CatalogList:
    """Collect catalog list calls for route tests."""

    def __init__(self, events: list[tuple[str, tuple[str, ...] | None]]) -> None:
        """Store the shared event log."""

        self._events = events

    def list_models(self, query: object) -> tuple[object, ...]:
        """Record one catalog list request and return no entries."""

        kinds = getattr(query, "kinds", None)
        self._events.append(("list", None if kinds is None else tuple(kinds)))
        return ()


class _PromptServer:
    """Collect PromptServer events for assertions."""

    def __init__(self) -> None:
        """Initialize an empty send list."""

        self.sent: list[tuple[str, object, str | None]] = []

    def send_sync(self, event: str, data: object, sid: str | None = None) -> None:
        """Record one PromptServer send."""

        self.sent.append((event, data, sid))


class _FolderPathsModule(ModuleType):
    """ModuleType test double exposing Comfy folder cache attributes."""

    filename_list_cache: dict[str, list[str]]
    cache_helper: object


class _CachedFolderPathsModule(ModuleType):
    """Emulate Comfy filename discovery with a persistent per-kind cache."""

    def __init__(self, root: Path) -> None:
        """Register one diffusion-model root and an initially empty cache."""

        super().__init__("folder_paths")
        self._root = root
        self.folder_names_and_paths = {"diffusion_models": ([str(root)], {".safetensors"})}
        self.filename_list_cache: dict[str, list[str]] = {}
        self.cache_helper = type(
            "CacheHelper",
            (),
            {"clear": lambda self: None},
        )()

    def get_folder_paths(self, folder_name: str) -> list[str]:
        """Return the configured root for the registered model kind."""

        if folder_name != "diffusion_models":
            return []
        return [str(self._root)]

    def get_filename_list(self, folder_name: str) -> list[str]:
        """Return and retain the first recursive filename scan for one kind."""

        cached = self.filename_list_cache.get(folder_name)
        if cached is not None:
            return list(cached)
        values = [
            str(path.relative_to(self._root)) for path in sorted(self._root.rglob("*.safetensors"))
        ]
        self.filename_list_cache[folder_name] = values
        return list(values)

    def get_full_path(self, folder_name: str, filename: str) -> str | None:
        """Resolve cached choice values beneath the registered root."""

        if folder_name != "diffusion_models":
            return None
        path = self._root / filename
        return str(path) if path.is_file() else None


class _DelegatingCacheInvalidator:
    """Record invalidations while clearing a concrete Comfy cache."""

    def __init__(self, delegate: ComfyFolderCacheInvalidator) -> None:
        """Store the concrete invalidator and initialize call history."""

        self._delegate = delegate
        self.calls: list[tuple[str, ...]] = []

    def invalidate(self, kinds: Iterable[str]) -> None:
        """Record and forward one scoped invalidation."""

        normalized = tuple(kinds)
        self.calls.append(normalized)
        self._delegate.invalidate(normalized)


class _CountingDependencyScanner:
    """Return deterministic dependencies while counting expensive scans."""

    def __init__(self, dependencies: dict[str, tuple[str, ...]]) -> None:
        """Store the scan result and initialize the call counter."""

        self.dependencies = dependencies
        self.calls = 0

    def scan(self) -> dict[str, tuple[str, ...]]:
        """Record one scan and return deterministic dependencies."""

        self.calls += 1
        return self.dependencies


def test_snapshot_diff_detects_add_remove_modify_and_ignores_unsupported(
    tmp_path: Path,
) -> None:
    """Snapshot diffs report cheap model stat changes only for supported files."""

    root = tmp_path / "loras"
    root.mkdir()
    model = root / "style.safetensors"
    model.write_bytes(b"one")
    (root / "ignore.txt").write_text("ignored", encoding="utf-8")
    provider = StaticModelRootsProvider({"loras": (root,)}, {".safetensors"})
    service = ModelFolderSnapshotService(provider)

    previous = service.build_snapshot()
    assert len(previous.entries) == 1

    model.write_bytes(b"two two")
    added = root / "new.safetensors"
    added.write_bytes(b"new")
    current = service.build_snapshot()
    diff = service.diff(previous, current)

    assert [entry.value for entry in diff.added] == ["new.safetensors"]
    assert [entry.value for entry in diff.modified] == ["style.safetensors"]
    assert diff.removed == ()

    added.unlink()
    model.unlink()
    removed_diff = service.diff(current, service.build_snapshot())

    assert sorted(entry.value for entry in removed_diff.removed) == [
        "new.safetensors",
        "style.safetensors",
    ]


def test_known_file_stat_changes_detects_overwrite_in_place(tmp_path: Path) -> None:
    """The slow safety pass catches changed known files without full rescans."""

    root = tmp_path / "loras"
    root.mkdir()
    model = root / "style.safetensors"
    model.write_bytes(b"one")
    provider = StaticModelRootsProvider({"loras": (root,)}, {".safetensors"})
    snapshot = ModelFolderSnapshotService(provider).build_snapshot()

    model.write_bytes(b"changed")

    assert known_file_stat_changes(snapshot) == ("loras",)


def test_monitor_idle_check_does_not_rescan_when_directories_are_clean(
    tmp_path: Path,
) -> None:
    """Clean idle checks stay cheap after the baseline snapshot."""

    root = tmp_path / "loras"
    root.mkdir()
    (root / "style.safetensors").write_bytes(b"one")
    provider = StaticModelRootsProvider({"loras": (root,)}, {".safetensors"})
    service = ModelFolderSnapshotService(provider)
    publisher = _Publisher()
    invalidator = _CacheInvalidator()
    monitor = ModelFolderChangeMonitor(
        model_roots=provider,
        snapshot_service=service,
        publisher=publisher,
        node_class_resolver=NodeModelDependencyIndex({"loras": ("LoraLoader",)}),
        cache_invalidator=invalidator,
        logger=get_logger("test.model_folder_monitor"),
        poll_interval_seconds=0.01,
        debounce_seconds=0.0,
        safety_scan_interval_seconds=999.0,
    )

    assert monitor.check_once() is None
    assert monitor.check_once() is None

    assert publisher.events == []
    assert invalidator.calls == []


def test_monitor_publishes_stable_added_file_and_invalidates_changed_kind(
    tmp_path: Path,
) -> None:
    """Dirty directory changes publish one coalesced event after stable stats."""

    root = tmp_path / "loras"
    root.mkdir()
    provider = StaticModelRootsProvider({"loras": (root,)}, {".safetensors"})
    service = ModelFolderSnapshotService(provider)
    publisher = _Publisher()
    invalidator = _CacheInvalidator()
    monitor = ModelFolderChangeMonitor(
        model_roots=provider,
        snapshot_service=service,
        publisher=publisher,
        node_class_resolver=NodeModelDependencyIndex({"loras": ("LoraLoader",)}),
        cache_invalidator=invalidator,
        logger=get_logger("test.model_folder_monitor"),
        poll_interval_seconds=0.01,
        debounce_seconds=0.0,
        safety_scan_interval_seconds=999.0,
    )
    monitor.check_once()

    (root / "style.safetensors").write_bytes(b"model")
    os.utime(root, (1000, 1000))
    event = monitor.check_once()

    assert event is not None
    assert event.kinds == ("loras",)
    assert [entry.value for entry in event.added] == ["style.safetensors"]
    assert event.removed == ()
    assert event.modified == ()
    assert event.affected_node_classes == ("LoraLoader",)
    assert publisher.events == [event]
    assert invalidator.calls == [("loras",)]


def test_monitor_invalidates_warm_comfy_cache_before_discovering_added_model(
    tmp_path: Path,
) -> None:
    """A warmed empty Comfy cache must not hide a newly added model file."""

    root = tmp_path / "diffusion_models"
    root.mkdir()
    folder_paths = _CachedFolderPathsModule(root)
    provider = ComfyModelRootsProvider(folder_paths)
    snapshot_service = ModelFolderSnapshotService(provider)
    publisher = _Publisher()
    invalidator = _DelegatingCacheInvalidator(
        ComfyFolderCacheInvalidator(
            folder_paths=folder_paths,
            logger=logging.getLogger("test"),
        )
    )
    monitor = ModelFolderChangeMonitor(
        model_roots=provider,
        snapshot_service=snapshot_service,
        publisher=publisher,
        node_class_resolver=NodeModelDependencyIndex(
            {"diffusion_models": ("SimpleSyrup.SimpleLoadAnima",)}
        ),
        cache_invalidator=invalidator,
        logger=get_logger("test.model_folder_monitor"),
        poll_interval_seconds=0.01,
        debounce_seconds=0.0,
        safety_scan_interval_seconds=999.0,
    )

    assert monitor.check_once() is None
    assert folder_paths.filename_list_cache == {"diffusion_models": []}

    anima_dir = root / "Anima"
    anima_dir.mkdir()
    model = anima_dir / "waiANIMA_v10Base10.safetensors"
    model.write_bytes(b"model")
    event = monitor.check_once()

    assert event is not None
    assert event.kinds == ("diffusion_models",)
    assert [entry.value for entry in event.added] == [str(Path("Anima") / model.name)]
    assert event.affected_node_classes == ("SimpleSyrup.SimpleLoadAnima",)
    assert invalidator.calls == [("diffusion_models",)]


def test_comfy_folder_cache_invalidator_removes_only_requested_kinds() -> None:
    """Comfy cache invalidation is scoped and tolerant of host internals."""

    folder_paths = _FolderPathsModule("folder_paths")
    folder_paths.filename_list_cache = {
        "loras": ["old"],
        "checkpoints": ["kept"],
    }
    clear_calls: list[bool] = []
    folder_paths.cache_helper = type(
        "CacheHelper",
        (),
        {"clear": lambda self: clear_calls.append(True)},
    )()
    invalidator = ComfyFolderCacheInvalidator(
        folder_paths=folder_paths,
        logger=logging.getLogger("test"),
    )

    invalidator.invalidate(("loras",))

    assert folder_paths.filename_list_cache == {"checkpoints": ["kept"]}
    assert clear_calls == [True]


def test_node_model_dependency_scanner_records_folder_path_usage() -> None:
    """Dependency scanning maps Comfy get_filename_list calls back to node classes."""

    class LoraNode:
        """Fake node that depends on LoRA filename choices."""

        @classmethod
        def INPUT_TYPES(cls) -> dict[str, object]:
            """Return fake inputs while requesting LoRA choices."""

            folder_paths.get_filename_list("loras")
            return {}

    class CheckpointNode:
        """Fake node that depends on checkpoint filename choices."""

        @classmethod
        def INPUT_TYPES(cls) -> dict[str, object]:
            """Return fake inputs while requesting checkpoint choices."""

            folder_paths.get_filename_list("checkpoints")
            return {}

    class FailingNode:
        """Fake node whose INPUT_TYPES fails."""

        @classmethod
        def INPUT_TYPES(cls) -> dict[str, object]:
            """Raise to prove failures are local to one node."""

            raise RuntimeError("boom")

    nodes = type(
        "Nodes",
        (),
        {
            "NODE_CLASS_MAPPINGS": {
                "LoraLoader": LoraNode,
                "CheckpointLoaderSimple": CheckpointNode,
                "Broken": FailingNode,
            }
        },
    )()
    folder_paths = type(
        "FolderPaths",
        (),
        {"get_filename_list": lambda self, kind: ["choice"]},
    )()
    original = folder_paths.get_filename_list
    scanner = ComfyNodeModelDependencyScanner(
        nodes_module=nodes,
        folder_paths=folder_paths,
        logger=logging.getLogger("test"),
    )

    dependencies = scanner.scan()

    assert dependencies == {
        "checkpoints": ("CheckpointLoaderSimple",),
        "loras": ("LoraLoader",),
    }
    assert folder_paths.get_filename_list == original


def test_cached_node_model_dependency_scanner_skips_unchanged_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Normal startup should reuse cached node dependencies without INPUT_TYPES scans."""

    monkeypatch.setenv("SUBSTITUTE_BACKEND_DIAGNOSTICS", "startup")
    caplog.set_level(logging.INFO, logger="test")

    class LoraNode:
        """Fake node class with stable source facts."""

    nodes = type("Nodes", (), {"NODE_CLASS_MAPPINGS": {"LoraLoader": LoraNode}})()
    scanner = _CountingDependencyScanner({"loras": ("LoraLoader",)})
    cache_path = tmp_path / "node_model_dependencies.json"
    first = CachedNodeModelDependencyScanner(
        cache_path=cache_path,
        scanner=scanner,
        nodes_module=nodes,
        logger=logging.getLogger("test"),
    )

    assert first.scan() == {"loras": ("LoraLoader",)}
    assert scanner.calls == 1

    second = CachedNodeModelDependencyScanner(
        cache_path=cache_path,
        scanner=scanner,
        nodes_module=nodes,
        logger=logging.getLogger("test"),
    )

    assert second.scan() == {"loras": ("LoraLoader",)}
    assert scanner.calls == 1
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "event=substitute_node_dependency_index_timing" in message
        and "cache_hit=True" in message
        and "signature_unique_module_count=" in message
        and "current_signature=" in message
        and "current_signature.resolve_source_paths=" in message
        and "read_cache=" in message
        for message in messages
    )


def test_cached_node_model_dependency_scanner_reuses_shared_source_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cache validation should stat one shared module source only once."""

    module_name = "fake_shared_comfy_node_source_for_cache_test"
    source_path = tmp_path / "shared_nodes.py"
    source_path.write_text("VALUE = 1\n", encoding="utf-8")
    module = ModuleType(module_name)
    module.__file__ = str(source_path)
    monkeypatch.setitem(sys.modules, module_name, module)
    first_node = type("FirstNode", (), {"__module__": module_name})
    second_node = type("SecondNode", (), {"__module__": module_name})
    nodes = type(
        "Nodes",
        (),
        {
            "NODE_CLASS_MAPPINGS": {
                "FirstNode": first_node,
                "SecondNode": second_node,
            }
        },
    )()
    scanner = _CountingDependencyScanner({"loras": ("FirstNode",)})
    source_fact_paths: list[Path | None] = []
    original_source_facts = CachedNodeModelDependencyScanner._source_facts

    def counting_source_facts(path: Path | None) -> dict[str, object]:
        """Record source-fact lookups while preserving behavior."""

        source_fact_paths.append(path)
        return original_source_facts(path)

    monkeypatch.setattr(
        CachedNodeModelDependencyScanner,
        "_source_facts",
        staticmethod(counting_source_facts),
    )

    CachedNodeModelDependencyScanner(
        cache_path=tmp_path / "node_model_dependencies.json",
        scanner=scanner,
        nodes_module=nodes,
        logger=logging.getLogger("test"),
    ).scan()

    assert source_fact_paths == [source_path.resolve()]


def test_cached_node_model_dependency_scanner_rebuilds_when_nodes_change(
    tmp_path: Path,
) -> None:
    """Changed node registry facts should invalidate the persisted dependency index."""

    class LoraNode:
        """Initial fake node class."""

    class CheckpointNode:
        """Added fake node class."""

    nodes = type("Nodes", (), {"NODE_CLASS_MAPPINGS": {"LoraLoader": LoraNode}})()
    scanner = _CountingDependencyScanner({"loras": ("LoraLoader",)})
    cache_path = tmp_path / "node_model_dependencies.json"
    CachedNodeModelDependencyScanner(
        cache_path=cache_path,
        scanner=scanner,
        nodes_module=nodes,
        logger=logging.getLogger("test"),
    ).scan()
    nodes.NODE_CLASS_MAPPINGS = {
        "CheckpointLoaderSimple": CheckpointNode,
        "LoraLoader": LoraNode,
    }
    scanner.dependencies = {
        "checkpoints": ("CheckpointLoaderSimple",),
        "loras": ("LoraLoader",),
    }

    dependencies = CachedNodeModelDependencyScanner(
        cache_path=cache_path,
        scanner=scanner,
        nodes_module=nodes,
        logger=logging.getLogger("test"),
    ).scan()

    assert dependencies == {
        "checkpoints": ("CheckpointLoaderSimple",),
        "loras": ("LoraLoader",),
    }
    assert scanner.calls == 2


def test_cached_node_model_dependency_scanner_rebuilds_when_source_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changed node source file facts should invalidate the dependency index."""

    module_name = "fake_comfy_node_source_for_cache_test"
    source_path = tmp_path / "fake_node.py"
    source_path.write_text("VALUE = 1\n", encoding="utf-8")
    os.utime(
        source_path,
        ns=(1_700_000_000_100_000_000, 1_700_000_000_100_000_000),
    )
    module = ModuleType(module_name)
    module.__file__ = str(source_path)
    monkeypatch.setitem(sys.modules, module_name, module)
    lora_node = type("LoraNode", (), {"__module__": module_name})
    nodes = type("Nodes", (), {"NODE_CLASS_MAPPINGS": {"LoraLoader": lora_node}})()
    scanner = _CountingDependencyScanner({"loras": ("LoraLoader",)})
    cache_path = tmp_path / "node_model_dependencies.json"
    CachedNodeModelDependencyScanner(
        cache_path=cache_path,
        scanner=scanner,
        nodes_module=nodes,
        logger=logging.getLogger("test"),
    ).scan()

    source_path.write_text("VALUE = 2\n", encoding="utf-8")
    os.utime(
        source_path,
        ns=(1_700_000_000_900_000_000, 1_700_000_000_900_000_000),
    )
    scanner.dependencies = {"loras": ("LoraLoader", "LoraLoaderAdvanced")}
    dependencies = CachedNodeModelDependencyScanner(
        cache_path=cache_path,
        scanner=scanner,
        nodes_module=nodes,
        logger=logging.getLogger("test"),
    ).scan()

    assert dependencies == {"loras": ("LoraLoader", "LoraLoaderAdvanced")}
    assert scanner.calls == 2


def test_prompt_server_publisher_sends_public_payload_without_paths() -> None:
    """PromptServer publisher emits the model catalog event payload."""

    prompt_server = _PromptServer()
    publisher = PromptServerModelCatalogPublisher(
        prompt_server,
        logging.getLogger("test"),
    )
    event = _change_event()

    publisher.publish(event)

    assert len(prompt_server.sent) == 1
    event_type, payload, sid = prompt_server.sent[0]
    assert event_type == EVENT_TYPE
    assert sid is None
    assert isinstance(payload, dict)
    assert payload["revision"] == "rev2"
    assert payload["affectedNodeClasses"] == ["LoraLoader"]
    added = payload["added"]
    assert isinstance(added, list)
    assert added[0]["source"] == {
        "rootId": "loras:0",
        "relativePath": "style.safetensors",
    }


def test_latest_model_changes_route_returns_latest_change_payload() -> None:
    """Reconnect recovery route exposes the latest model catalog event."""

    class _Changes:
        """Fake monitor for route handler tests."""

        revision = "rev2"
        latest_change = _change_event()

    services = ModelMetadataServices(
        catalog=object(),  # type: ignore[arg-type]
        catalog_refresh=object(),  # type: ignore[arg-type]
        capabilities=object(),  # type: ignore[arg-type]
        fingerprints=object(),  # type: ignore[arg-type]
        previews=object(),  # type: ignore[arg-type]
        hash_lookup=object(),  # type: ignore[arg-type]
        downloads=object(),  # type: ignore[arg-type]
        changes=_Changes(),  # type: ignore[arg-type]
    )
    handler = build_model_metadata_route_handlers(services, logging.getLogger("test"))

    response: Any = asyncio.run(
        handler.latest_model_changes(object())  # type: ignore[arg-type]
    )
    payload = response.body.decode("utf-8")

    assert '"revision": "rev2"' in payload
    assert '"latestChange": {' in payload


def test_models_route_refresh_invalidates_before_listing() -> None:
    """Explicit model catalog refresh invalidates requested kinds before listing."""

    class _Changes:
        """Unused fake monitor for route handler tests."""

        revision = "unused"
        latest_change = None

    events: list[tuple[str, tuple[str, ...] | None]] = []
    services = ModelMetadataServices(
        catalog=_CatalogList(events),  # type: ignore[arg-type]
        catalog_refresh=_CatalogRefresh(events),  # type: ignore[arg-type]
        capabilities=object(),  # type: ignore[arg-type]
        fingerprints=object(),  # type: ignore[arg-type]
        previews=object(),  # type: ignore[arg-type]
        hash_lookup=object(),  # type: ignore[arg-type]
        downloads=object(),  # type: ignore[arg-type]
        changes=_Changes(),  # type: ignore[arg-type]
    )
    handler = build_model_metadata_route_handlers(services, logging.getLogger("test"))
    request = make_mocked_request(
        "GET",
        "/substitute/v1/models?kind=loras&refresh=1",
    )

    async def run_request() -> Any:
        """Run the route handler through a concrete coroutine for strict typing."""

        return await handler.list_models(request)

    response: Any = asyncio.run(run_request())

    assert response.status == 200
    assert events == [("refresh", ("loras",)), ("list", ("loras",))]


def test_models_route_normal_list_does_not_invalidate() -> None:
    """Normal model catalog listing must not force cache invalidation."""

    class _Changes:
        """Unused fake monitor for route handler tests."""

        revision = "unused"
        latest_change = None

    events: list[tuple[str, tuple[str, ...] | None]] = []
    services = ModelMetadataServices(
        catalog=_CatalogList(events),  # type: ignore[arg-type]
        catalog_refresh=_CatalogRefresh(events),  # type: ignore[arg-type]
        capabilities=object(),  # type: ignore[arg-type]
        fingerprints=object(),  # type: ignore[arg-type]
        previews=object(),  # type: ignore[arg-type]
        hash_lookup=object(),  # type: ignore[arg-type]
        downloads=object(),  # type: ignore[arg-type]
        changes=_Changes(),  # type: ignore[arg-type]
    )
    handler = build_model_metadata_route_handlers(services, logging.getLogger("test"))
    request = make_mocked_request("GET", "/substitute/v1/models?kind=loras")

    async def run_request() -> Any:
        """Run the route handler through a concrete coroutine for strict typing."""

        return await handler.list_models(request)

    response: Any = asyncio.run(run_request())

    assert response.status == 200
    assert events == [("list", ("loras",))]


def _change_event() -> ModelCatalogChangeSet:
    """Build a representative model catalog change event."""

    entry = ModelCatalogChangedEntry(
        identity=ModelFileIdentity(
            kind="loras",
            value="style.safetensors",
            root_id="loras:0",
            relative_path="style.safetensors",
        ),
        file=ModelFileStatSnapshot(
            size_bytes=10,
            modified_at="2026-05-26T12:00:00Z",
        ),
    )
    return ModelCatalogChangeSet(
        revision="rev2",
        previous_revision="rev1",
        generated_at="2026-05-26T12:00:01Z",
        kinds=("loras",),
        added=(entry,),
        removed=(),
        modified=(),
        affected_node_classes=("LoraLoader",),
        reason="folder-changed",
    )
