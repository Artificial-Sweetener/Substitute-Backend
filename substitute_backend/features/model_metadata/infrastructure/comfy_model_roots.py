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
"""ComfyUI model root adapters for catalog discovery."""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

from substitute_backend.features.model_metadata.domain.catalog import ModelFile


class ModelRootsProvider(Protocol):
    """Interface for resolving ComfyUI-visible model files."""

    def supported_kinds(self) -> tuple[str, ...]:
        """Return supported model kinds."""

    def list_model_files(self, kinds: Iterable[str] | None = None) -> tuple[ModelFile, ...]:
        """Return model files for the requested kinds."""

    def resolve_model_file(self, kind: str, value: str) -> ModelFile | None:
        """Resolve a single model file by kind and exact ComfyUI choice value."""

    def approved_roots(self) -> tuple[Path, ...]:
        """Return root directories approved for model evidence access."""

    def roots_for_kind(self, kind: str) -> tuple[Path, ...]:
        """Return approved root directories for one model kind."""


class FolderPathsModule(Protocol):
    """Subset of ComfyUI's folder_paths module used by this adapter."""

    folder_names_and_paths: dict[str, tuple[list[str], set[str]]]

    def get_filename_list(self, folder_name: str) -> list[str]:
        """Return ComfyUI choice values for a model folder name."""

    def get_full_path(self, folder_name: str, filename: str) -> str | None:
        """Return the full path for a ComfyUI model choice value."""

    def get_folder_paths(self, folder_name: str) -> list[str]:
        """Return configured filesystem roots for a ComfyUI model folder name."""


class ComfyModelRootsProvider:
    """Resolve model files through ComfyUI's folder_paths module."""

    def __init__(self, folder_paths: FolderPathsModule | None = None) -> None:
        """Initialize the provider from ComfyUI's folder_paths module."""

        self._folder_paths = folder_paths or self._load_folder_paths()

    def supported_kinds(self) -> tuple[str, ...]:
        """Return ComfyUI model folder names that can be cataloged."""

        ignored = {"custom_nodes", "configs", "classifiers"}
        return tuple(
            sorted(
                kind for kind in self._folder_paths.folder_names_and_paths if kind not in ignored
            )
        )

    def list_model_files(self, kinds: Iterable[str] | None = None) -> tuple[ModelFile, ...]:
        """Return model files for the requested ComfyUI folder names."""

        selected = tuple(kinds) if kinds is not None else self.supported_kinds()
        files: list[ModelFile] = []
        for kind in selected:
            if kind not in self._folder_paths.folder_names_and_paths:
                continue
            for value in self._folder_paths.get_filename_list(kind):
                model_file = self.resolve_model_file(kind, value)
                if model_file is not None:
                    files.append(model_file)
        return tuple(files)

    def resolve_model_file(self, kind: str, value: str) -> ModelFile | None:
        """Resolve a single model file by ComfyUI kind and choice value."""

        full_path = self._folder_paths.get_full_path(kind, value)
        if full_path is None:
            return None
        path = Path(full_path).resolve()
        root_id, relative_path = self._resolve_source(kind, path)
        return ModelFile(
            kind=kind,
            value=value,
            display_name=Path(value).stem,
            root_id=root_id,
            relative_path=relative_path,
            path=path,
        )

    def approved_roots(self) -> tuple[Path, ...]:
        """Return configured ComfyUI model roots."""

        roots: list[Path] = []
        for kind in self.supported_kinds():
            roots.extend(Path(path).resolve() for path in self._folder_paths.get_folder_paths(kind))
        return tuple(roots)

    def roots_for_kind(self, kind: str) -> tuple[Path, ...]:
        """Return configured roots for one ComfyUI model folder name."""

        if kind not in self._folder_paths.folder_names_and_paths:
            return ()
        return tuple(Path(path).resolve() for path in self._folder_paths.get_folder_paths(kind))

    def _resolve_source(self, kind: str, path: Path) -> tuple[str, str]:
        """Return a stable root ID and relative path for a model file."""

        roots = [Path(root).resolve() for root in self._folder_paths.get_folder_paths(kind)]
        for index, root in enumerate(roots):
            try:
                relative_path = path.relative_to(root)
            except ValueError:
                continue
            return f"{kind}:{index}", relative_path.as_posix()
        return f"{kind}:unknown", Path(path.name).as_posix()

    @staticmethod
    def _load_folder_paths() -> FolderPathsModule:
        """Import ComfyUI's folder_paths module at the host boundary."""

        module: ModuleType = importlib.import_module("folder_paths")
        return cast("FolderPathsModule", module)


class StaticModelRootsProvider:
    """Test and offline provider backed by explicit model roots."""

    def __init__(self, roots: dict[str, tuple[Path, ...]], extensions: set[str]) -> None:
        """Initialize the provider with explicit roots and accepted extensions."""

        self._roots = {
            kind: tuple(root.resolve() for root in kind_roots) for kind, kind_roots in roots.items()
        }
        self._extensions = {extension.lower() for extension in extensions}

    def supported_kinds(self) -> tuple[str, ...]:
        """Return supported static model kinds."""

        return tuple(sorted(self._roots))

    def list_model_files(self, kinds: Iterable[str] | None = None) -> tuple[ModelFile, ...]:
        """Return files under the configured static roots."""

        selected = tuple(kinds) if kinds is not None else self.supported_kinds()
        files: list[ModelFile] = []
        for kind in selected:
            for root_index, root in enumerate(self._roots.get(kind, ())):
                if not root.exists():
                    continue
                for path in sorted(root.rglob("*")):
                    if not path.is_file() or path.suffix.lower() not in self._extensions:
                        continue
                    relative_path = path.relative_to(root).as_posix()
                    value = relative_path.replace("/", os.sep)
                    files.append(
                        ModelFile(
                            kind=kind,
                            value=value,
                            display_name=path.stem,
                            root_id=f"{kind}:{root_index}",
                            relative_path=relative_path,
                            path=path.resolve(),
                        )
                    )
        return tuple(files)

    def resolve_model_file(self, kind: str, value: str) -> ModelFile | None:
        """Resolve a static model file by kind and choice value."""

        normalized = Path(value)
        for root_index, root in enumerate(self._roots.get(kind, ())):
            candidate = (root / normalized).resolve()
            if candidate.is_file() and self._is_under_root(candidate, root):
                return ModelFile(
                    kind=kind,
                    value=value,
                    display_name=candidate.stem,
                    root_id=f"{kind}:{root_index}",
                    relative_path=candidate.relative_to(root).as_posix(),
                    path=candidate,
                )
        return None

    def approved_roots(self) -> tuple[Path, ...]:
        """Return approved static roots."""

        return tuple(root for roots in self._roots.values() for root in roots)

    def roots_for_kind(self, kind: str) -> tuple[Path, ...]:
        """Return approved static roots for one model kind."""

        return self._roots.get(kind, ())

    @staticmethod
    def _is_under_root(path: Path, root: Path) -> bool:
        """Return whether a path remains within a configured model root."""

        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True
