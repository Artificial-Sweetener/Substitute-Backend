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
"""Download allowlisted preview assets with bounded filesystem writes."""

from __future__ import annotations

import shutil
import urllib.error
import urllib.request
from collections.abc import Collection
from pathlib import Path
from uuid import uuid4

from substitute_backend.features.preview_assets.application import DownloadResult


class HttpAssetDownloader:
    """Download preview assets from allowlisted URLs into final model paths."""

    def __init__(
        self,
        *,
        allowed_urls: Collection[str],
        timeout_seconds: float = 30.0,
    ) -> None:
        """Initialize the downloader with fixed URL policy and timeout."""

        self._allowed_urls = frozenset(allowed_urls)
        self._timeout_seconds = timeout_seconds

    def download(self, url: str, destination: Path) -> DownloadResult:
        """Download one allowlisted asset without overwriting existing files."""

        if url not in self._allowed_urls:
            return DownloadResult(
                succeeded=False,
                error="Preview asset URL is not allowlisted.",
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            return DownloadResult(
                succeeded=destination.is_file(),
                size_bytes=destination.stat().st_size if destination.is_file() else None,
                error=None if destination.is_file() else "Destination exists and is not a file.",
            )
        temporary_path = destination.with_name(f"{destination.name}.{uuid4().hex}.tmp")
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Substitute-BackEnd/preview-assets"},
            method="GET",
        )
        try:
            with (
                urllib.request.urlopen(request, timeout=self._timeout_seconds) as response,
                temporary_path.open("wb") as target,
            ):
                shutil.copyfileobj(response, target)
            if not temporary_path.is_file() or temporary_path.stat().st_size <= 0:
                temporary_path.unlink(missing_ok=True)
                return DownloadResult(
                    succeeded=False,
                    error="Downloaded preview asset was empty.",
                )
            if destination.exists():
                temporary_path.unlink(missing_ok=True)
                return DownloadResult(
                    succeeded=destination.is_file(),
                    size_bytes=destination.stat().st_size if destination.is_file() else None,
                    error=(
                        None if destination.is_file() else "Destination exists and is not a file."
                    ),
                )
            temporary_path.replace(destination)
            return DownloadResult(succeeded=True, size_bytes=destination.stat().st_size)
        except (OSError, urllib.error.URLError) as error:
            temporary_path.unlink(missing_ok=True)
            return DownloadResult(succeeded=False, error=repr(error))
