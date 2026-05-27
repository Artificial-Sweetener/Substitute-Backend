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
"""Best-effort invalidation for ComfyUI folder_paths filename caches."""

from __future__ import annotations

import importlib
import logging
from collections.abc import Iterable
from types import ModuleType


class ComfyFolderCacheInvalidator:
    """Clear Comfy filename-list caches for changed model kinds when available."""

    def __init__(
        self,
        *,
        folder_paths: ModuleType | None = None,
        logger: logging.Logger,
    ) -> None:
        """Initialize with an optional injected Comfy ``folder_paths`` module."""

        self._folder_paths = folder_paths
        self._logger = logger

    def invalidate(self, kinds: Iterable[str]) -> None:
        """Invalidate Comfy filename-list caches for the requested kinds."""

        normalized = tuple(dict.fromkeys(kind.strip() for kind in kinds if kind.strip()))
        if not normalized:
            return
        folder_paths = self._folder_paths or self._load_folder_paths()
        self._clear_filename_list_cache(folder_paths, normalized)
        self._clear_cache_helper(folder_paths)

    def _clear_filename_list_cache(
        self,
        folder_paths: ModuleType,
        kinds: tuple[str, ...],
    ) -> None:
        """Remove requested kinds from Comfy's filename cache if present."""

        cache = getattr(folder_paths, "filename_list_cache", None)
        if not isinstance(cache, dict):
            self._logger.debug("Comfy filename_list_cache unavailable; skipping")
            return
        for kind in kinds:
            cache.pop(kind, None)

    def _clear_cache_helper(self, folder_paths: ModuleType) -> None:
        """Clear Comfy's active cache helper when it exposes a compatible API."""

        cache_helper = getattr(folder_paths, "cache_helper", None)
        clear = getattr(cache_helper, "clear", None)
        if not callable(clear):
            return
        try:
            clear()
        except Exception as exc:
            self._logger.warning(
                "Failed to clear Comfy folder cache helper",
                extra={"error": repr(exc)},
            )

    @staticmethod
    def _load_folder_paths() -> ModuleType:
        """Import Comfy's folder_paths module at the host boundary."""

        return importlib.import_module("folder_paths")


__all__ = ["ComfyFolderCacheInvalidator"]
