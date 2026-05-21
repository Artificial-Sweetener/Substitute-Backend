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
"""Preview discovery and controlled preview file resolution."""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from substitute_backend.features.model_metadata.domain.catalog import ModelFile
from substitute_backend.features.model_metadata.domain.previews import (
    MISSING_PREVIEW,
    LocalPreviewReference,
    PreviewFile,
)
from substitute_backend.features.model_metadata.domain.statuses import PreviewSource

from .time_utils import format_timestamp

_SUPPORTED_PREVIEW_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


class PreviewStore:
    """Discover and resolve local preview images through opaque IDs."""

    def __init__(self, approved_roots: tuple[Path, ...]) -> None:
        """Initialize the store with roots approved for preview serving."""

        self._approved_roots = tuple(root.resolve() for root in approved_roots)
        self._previews: dict[str, PreviewFile] = {}

    def discover(self, model_file: ModelFile) -> LocalPreviewReference:
        """Discover the preferred local preview candidate for a model file."""

        preview = self._find_preview_file(model_file)
        if preview is None:
            return MISSING_PREVIEW
        self._previews[preview.preview_id] = preview
        return LocalPreviewReference(
            available=True,
            preview_id=preview.preview_id,
            url=f"/substitute/v1/previews/{preview.preview_id}",
            source=preview.source,
            modified_at=preview.modified_at,
        )

    def resolve(self, preview_id: str) -> PreviewFile | None:
        """Resolve an opaque preview ID to a validated preview file."""

        preview = self._previews.get(preview_id)
        if preview is None:
            return None
        path = preview.path.resolve()
        if not path.is_file() or not self._is_under_approved_root(path):
            self._previews.pop(preview_id, None)
            return None
        stat = path.stat()
        if (
            stat.st_size != preview.size_bytes
            or format_timestamp(stat.st_mtime) != preview.modified_at
        ):
            self._previews.pop(preview_id, None)
            return None
        return preview

    def _find_preview_file(self, model_file: ModelFile) -> PreviewFile | None:
        """Find the first supported local preview candidate."""

        base = model_file.path.with_suffix("")
        candidates = [base.with_suffix(".preview.png")]
        candidates.extend(
            base.with_suffix(extension) for extension in _SUPPORTED_PREVIEW_EXTENSIONS
        )
        for candidate in candidates:
            path = candidate.resolve()
            if not path.is_file() or not self._is_under_approved_root(path):
                continue
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if not content_type.startswith("image/"):
                continue
            stat = path.stat()
            source = (
                PreviewSource.PREVIEW_SIDECAR
                if path.name.endswith(".preview.png")
                else PreviewSource.SAME_BASENAME_IMAGE
            )
            return PreviewFile(
                preview_id=self._build_preview_id(model_file, path),
                path=path,
                content_type=content_type,
                modified_at=format_timestamp(stat.st_mtime),
                size_bytes=stat.st_size,
                source=source,
            )
        return None

    def _is_under_approved_root(self, path: Path) -> bool:
        """Return whether a file path is under an approved root."""

        for root in self._approved_roots:
            try:
                path.relative_to(root)
            except ValueError:
                continue
            return True
        return False

    @staticmethod
    def _build_preview_id(model_file: ModelFile, preview_path: Path) -> str:
        """Build an opaque preview ID without exposing a filesystem path."""

        digest = hashlib.sha256()
        digest.update(model_file.root_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(model_file.relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(preview_path.name.encode("utf-8"))
        return digest.hexdigest()
