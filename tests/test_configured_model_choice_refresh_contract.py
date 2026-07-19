#    Substitute BackEnd - backend liaison services for SugarSubstitute and ComfyUI
#    Copyright (C) 2026  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Guard generic refresh targeting for Comfy-configured model choices."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from pathlib import Path

from substitute_backend.features.model_metadata.application.model_folder_change_monitor import (
    ModelFolderChangeMonitor,
)
from substitute_backend.features.model_metadata.application.model_folder_snapshot_service import (
    ModelFolderSnapshotService,
)
from substitute_backend.features.model_metadata.application.node_model_dependency_index import (
    NodeModelDependencyIndex,
)
from substitute_backend.features.model_metadata.domain.change_events import (
    ModelCatalogChangeSet,
)
from substitute_backend.features.model_metadata.infrastructure import (
    ComfyNodeModelDependencyScanner,
)
from substitute_backend.features.model_metadata.infrastructure.comfy_model_roots import (
    ComfyModelRootsProvider,
    StaticModelRootsProvider,
)


class _FolderPaths:
    """Expose configured Comfy kinds and record filename-list requests."""

    folder_names_and_paths: Mapping[str, object]

    def __init__(self) -> None:
        """Configure upscale, diffusion, and VAE model folders."""

        self.folder_names_and_paths = {
            "upscale_models": object(),
            "diffusion_models": object(),
            "vae": object(),
            "face_models": object(),
        }

    def get_filename_list(self, folder_name: str) -> list[str]:
        """Return representative choices, including a literal sentinel."""

        return ["auto"] if folder_name == "vae" else []


class _Publisher:
    """Collect published change sets."""

    def __init__(self) -> None:
        """Initialize empty publication history."""

        self.events: list[ModelCatalogChangeSet] = []

    def publish(self, event: ModelCatalogChangeSet) -> None:
        """Record one catalog change."""

        self.events.append(event)


class _Invalidator:
    """Collect exact Comfy filename-cache invalidations."""

    def __init__(self) -> None:
        """Initialize empty invalidation history."""

        self.calls: list[tuple[str, ...]] = []

    def invalidate(self, kinds: Iterable[str]) -> None:
        """Record one normalized invalidation."""

        self.calls.append(tuple(kinds))


def test_dependency_scan_targets_upscalers_and_multi_folder_nodes_without_names() -> None:
    """Only actual configured get_filename_list calls establish dependencies."""

    folder_paths = _FolderPaths()

    class ArbitrarilyNamedUpscaler:
        """Represent an upscaler node without a useful class or field name."""

        @classmethod
        def INPUT_TYPES(cls) -> dict[str, object]:
            """Request Comfy's configured upscaler choices."""

            return {
                "required": {
                    "anything": (folder_paths.get_filename_list("upscale_models"),),
                }
            }

    class SimpleAnima:
        """Represent a node that combines model files and literal sentinels."""

        @classmethod
        def INPUT_TYPES(cls) -> dict[str, object]:
            """Request two model folders and one unconfigured pseudo-kind."""

            folder_paths.get_filename_list("diffusion_models")
            folder_paths.get_filename_list("vae")
            folder_paths.get_filename_list("runtime_modes")
            return {"required": {"mode": (["auto"],)}}

    class CustomDetector:
        """Represent a custom node with a custom registered model kind."""

        @classmethod
        def INPUT_TYPES(cls) -> dict[str, object]:
            """Request the custom configured model folder."""

            folder_paths.get_filename_list("face_models")
            return {}

    nodes = type(
        "Nodes",
        (),
        {
            "NODE_CLASS_MAPPINGS": {
                "TotallyArbitrary": ArbitrarilyNamedUpscaler,
                "SimpleSyrup.SimpleLoadAnima": SimpleAnima,
                "CustomFaceDetector": CustomDetector,
            }
        },
    )()
    original = folder_paths.get_filename_list

    dependencies = ComfyNodeModelDependencyScanner(
        nodes_module=nodes,
        folder_paths=folder_paths,
        logger=logging.getLogger("test.configured_model_dependencies"),
    ).scan()

    assert dependencies == {
        "diffusion_models": ("SimpleSyrup.SimpleLoadAnima",),
        "face_models": ("CustomFaceDetector",),
        "upscale_models": ("TotallyArbitrary",),
        "vae": ("SimpleSyrup.SimpleLoadAnima",),
    }
    assert folder_paths.get_filename_list == original


def test_comfy_model_roots_include_every_default_and_extra_configured_root(
    tmp_path: Path,
) -> None:
    """Extra-model-path roots participate through Comfy's own folder registry."""

    default_root = tmp_path / "models" / "upscale_models"
    extra_root = tmp_path / "extra" / "upscale_models"
    default_root.mkdir(parents=True)
    extra_root.mkdir(parents=True)

    class ConfiguredFolderPaths:
        """Expose the roots Comfy assembled from all configuration sources."""

        def __init__(self) -> None:
            """Store the default and extra roots in Comfy's registry shape."""

            self.folder_names_and_paths: dict[str, tuple[list[str], set[str]]] = {
                "upscale_models": (
                    [str(default_root), str(extra_root)],
                    {".pth"},
                )
            }

        def get_folder_paths(self, folder_name: str) -> list[str]:
            """Return all configured roots for the requested kind."""

            return list(self.folder_names_and_paths[folder_name][0])

        def get_filename_list(self, _folder_name: str) -> list[str]:
            """Return no files for this root-only contract."""

            return []

        def get_full_path(self, _folder_name: str, _filename: str) -> str | None:
            """Return no file for this root-only contract."""

            return None

    provider = ComfyModelRootsProvider(ConfiguredFolderPaths())

    assert provider.supported_kinds() == ("upscale_models",)
    assert provider.roots_for_kind("upscale_models") == (
        default_root.resolve(),
        extra_root.resolve(),
    )


def test_upscaler_changes_invalidate_cache_and_target_every_dependent_node(
    tmp_path: Path,
) -> None:
    """Add, modify, and remove transitions publish every dependent class."""

    root = tmp_path / "upscale_models"
    root.mkdir()
    provider = StaticModelRootsProvider(
        {"upscale_models": (root,)},
        {".pth", ".safetensors"},
    )
    publisher = _Publisher()
    invalidator = _Invalidator()
    monitor = ModelFolderChangeMonitor(
        model_roots=provider,
        snapshot_service=ModelFolderSnapshotService(provider),
        publisher=publisher,
        node_class_resolver=NodeModelDependencyIndex(
            {
                "upscale_models": (
                    "UpscaleModelLoader",
                    "SimpleSyrup.DiffusionUpscale",
                )
            }
        ),
        cache_invalidator=invalidator,
        logger=logging.getLogger("test.upscaler_refresh"),
        debounce_seconds=0.0,
        safety_scan_interval_seconds=999.0,
    )
    assert monitor.check_once() is None

    model = root / "4x-AnimeSharp.pth"
    model.write_bytes(b"model")
    event = monitor.check_once()

    assert event is not None
    assert event.kinds == ("upscale_models",)
    assert tuple(entry.value for entry in event.added) == (model.name,)
    assert event.affected_node_classes == (
        "SimpleSyrup.DiffusionUpscale",
        "UpscaleModelLoader",
    )
    assert invalidator.calls == [("upscale_models",)]
    assert publisher.events == [event]

    model.write_bytes(b"updated model")
    modified_event = monitor.check_once(force_safety_scan=True)

    assert modified_event is not None
    assert tuple(entry.value for entry in modified_event.modified) == (model.name,)
    assert modified_event.affected_node_classes == event.affected_node_classes

    model.unlink()
    removed_event = monitor.check_once(force_safety_scan=True)

    assert removed_event is not None
    assert tuple(entry.value for entry in removed_event.removed) == (model.name,)
    assert removed_event.affected_node_classes == event.affected_node_classes
    assert invalidator.calls == [("upscale_models",)] * 3
    assert publisher.events == [event, modified_event, removed_event]
