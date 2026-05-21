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
"""Preview contracts for model catalog entries and preview serving."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from substitute_backend.api.serialization import JsonObject

from .statuses import PreviewSource


@dataclass(frozen=True)
class LocalPreviewReference:
    """Public reference to a locally available preview image."""

    available: bool
    preview_id: str | None = None
    url: str | None = None
    source: PreviewSource | None = None
    modified_at: str | None = None
    width: int | None = None
    height: int | None = None

    def to_payload(self) -> JsonObject:
        """Return the public preview reference payload."""

        return {
            "available": self.available,
            "previewId": self.preview_id,
            "url": self.url,
            "source": self.source.value if self.source else None,
            "modifiedAt": self.modified_at,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class PreviewFile:
    """Internal reference to a preview file validated by the backend."""

    preview_id: str
    path: Path
    content_type: str
    modified_at: str
    size_bytes: int
    source: PreviewSource


MISSING_PREVIEW = LocalPreviewReference(available=False)
