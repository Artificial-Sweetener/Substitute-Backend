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
"""Discover Comfy node classes that depend on model folder filename lists."""

from __future__ import annotations

import importlib
import logging
from collections import defaultdict
from collections.abc import Callable, Mapping
from types import ModuleType
from typing import Any, Protocol, cast


class NodesModule(Protocol):
    """Subset of Comfy's ``nodes`` module needed for dependency discovery."""

    NODE_CLASS_MAPPINGS: Mapping[str, type[object]]


class FolderPathsModule(Protocol):
    """Subset of Comfy's ``folder_paths`` module needed for dependency discovery."""

    folder_names_and_paths: Mapping[str, object]

    def get_filename_list(self, folder_name: str) -> list[str]:
        """Return filenames for one Comfy model folder kind."""


class ComfyNodeModelDependencyScanner:
    """Inspect registered Comfy node INPUT_TYPES calls for model folder usage."""

    def __init__(
        self,
        *,
        nodes_module: NodesModule | None = None,
        folder_paths: FolderPathsModule | None = None,
        logger: logging.Logger,
    ) -> None:
        """Initialize scanner with optional injected Comfy modules."""

        self._nodes_module = nodes_module
        self._folder_paths = folder_paths
        self._logger = logger

    def scan(self) -> dict[str, tuple[str, ...]]:
        """Return ``model_kind -> node classes`` dependencies."""

        nodes_module = self._nodes_module or self._load_nodes_module()
        folder_paths = self._folder_paths or self._load_folder_paths()
        original = folder_paths.get_filename_list
        configured_kinds = frozenset(folder_paths.folder_names_and_paths)
        dependencies: defaultdict[str, set[str]] = defaultdict(set)
        current_node_class = {"value": ""}

        def recording_get_filename_list(folder_name: str) -> list[str]:
            """Record folder kind usage and delegate to Comfy."""

            node_class = current_node_class["value"]
            normalized_kind = folder_name.strip()
            if node_class and normalized_kind in configured_kinds:
                dependencies[normalized_kind].add(node_class)
            try:
                return original(folder_name)
            except Exception:
                return []

        mutable_folder_paths = cast(Any, folder_paths)
        mutable_folder_paths.get_filename_list = recording_get_filename_list
        try:
            for node_class, node_type in nodes_module.NODE_CLASS_MAPPINGS.items():
                current_node_class["value"] = node_class
                self._call_input_types(node_class, node_type)
        finally:
            current_node_class["value"] = ""
            mutable_folder_paths.get_filename_list = original
        return {kind: tuple(sorted(nodes)) for kind, nodes in sorted(dependencies.items())}

    def _call_input_types(self, node_class: str, node_type: type[object]) -> None:
        """Call one node's INPUT_TYPES and keep failures local to that node."""

        input_types = getattr(node_type, "INPUT_TYPES", None)
        if not callable(input_types):
            return
        try:
            cast(Callable[[], Any], input_types)()
        except Exception as exc:
            self._logger.warning(
                "Skipped node model dependency discovery for failing INPUT_TYPES",
                extra={"node_class": node_class, "error": repr(exc)},
            )

    @staticmethod
    def _load_nodes_module() -> NodesModule:
        """Import Comfy's nodes module at the host boundary."""

        module: ModuleType = importlib.import_module("nodes")
        return cast("NodesModule", module)

    @staticmethod
    def _load_folder_paths() -> FolderPathsModule:
        """Import Comfy's folder_paths module at the host boundary."""

        module: ModuleType = importlib.import_module("folder_paths")
        return cast("FolderPathsModule", module)


__all__ = ["ComfyNodeModelDependencyScanner"]
