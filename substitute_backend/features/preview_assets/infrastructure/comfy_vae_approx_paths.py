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
"""Resolve ComfyUI's configured approximate VAE model root."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast
from uuid import uuid4

from substitute_backend.features.preview_assets.domain import PreviewAssetError


class FolderPathsModule(Protocol):
    """Subset of ComfyUI's ``folder_paths`` module required by this adapter."""

    def get_folder_paths(self, folder_name: str) -> list[str]:
        """Return configured filesystem roots for a ComfyUI model folder name."""


class ComfyVaeApproxPathProvider:
    """Resolve the first writable ComfyUI ``vae_approx`` root."""

    def __init__(self, folder_paths: FolderPathsModule | None = None) -> None:
        """Initialize the provider with an optional test double."""

        self._folder_paths = folder_paths or self._load_folder_paths()

    def resolve_root(self) -> Path:
        """Return a writable destination root for TAESD preview assets."""

        roots = tuple(
            Path(path).resolve() for path in self._folder_paths.get_folder_paths("vae_approx")
        )
        if not roots:
            raise PreviewAssetError(
                message="ComfyUI did not expose a vae_approx model root.",
                code="vae-approx-root-unavailable",
                status=409,
            )
        for root in roots:
            if root.is_dir() and self._is_writable(root):
                return root
        first_root = roots[0]
        try:
            first_root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise PreviewAssetError(
                message="ComfyUI vae_approx model root could not be created.",
                code="vae-approx-root-unavailable",
                status=409,
            ) from error
        if self._is_writable(first_root):
            return first_root
        raise PreviewAssetError(
            message="ComfyUI vae_approx model root is not writable.",
            code="vae-approx-root-unavailable",
            status=409,
        )

    @staticmethod
    def _is_writable(root: Path) -> bool:
        """Return whether a root accepts a short probe write."""

        probe = root / f".substitute_write_probe_{uuid4().hex}.tmp"
        try:
            probe.write_bytes(b"")
            probe.unlink(missing_ok=True)
        except OSError:
            return False
        return True

    @staticmethod
    def _load_folder_paths() -> FolderPathsModule:
        """Import ComfyUI's ``folder_paths`` module at the host boundary."""

        module: ModuleType = importlib.import_module("folder_paths")
        return cast("FolderPathsModule", module)
