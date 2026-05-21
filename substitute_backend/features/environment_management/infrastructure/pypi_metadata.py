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
"""Optional PyPI summary enrichment for installed package inventory."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from types import TracebackType
from typing import Protocol, runtime_checkable

from substitute_backend.features.environment_management.domain.packages import (
    PackageSummarySource,
)
from substitute_backend.features.environment_management.infrastructure.package_metadata import (
    PackageSummary,
)
from substitute_backend.features.environment_management.infrastructure.pip_inspector import (
    normalize_package_name,
)


class UrlOpen(Protocol):
    """Protocol for an injectable URL opener."""

    def __call__(self, url: str, *, timeout: float) -> object:
        """Open one URL and return a response object."""


@runtime_checkable
class UrlResponse(Protocol):
    """Protocol for the subset of HTTP response behavior this adapter needs."""

    def __enter__(self) -> UrlResponse:
        """Return the opened response."""

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """Close the response context."""

    def read(self) -> bytes:
        """Read response bytes."""


class PypiSummaryProvider:
    """Read package summaries from the PyPI JSON API with a local cache."""

    def __init__(
        self,
        cache_path: Path,
        *,
        urlopen: UrlOpen = urllib.request.urlopen,
        timeout_seconds: float = 5.0,
    ) -> None:
        """Initialize the PyPI provider with explicit network policy."""

        self._cache_path = cache_path
        self._urlopen = urlopen
        self._timeout_seconds = timeout_seconds
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)

    def summary_for_package(self, package_name: str) -> PackageSummary:
        """Return one PyPI summary or an unavailable summary on failure."""

        normalized_name = normalize_package_name(package_name)
        cache = self._read_cache()
        cached_summary = cache.get(normalized_name)
        if isinstance(cached_summary, str) and cached_summary.strip():
            return PackageSummary(
                summary=cached_summary.strip(),
                source=PackageSummarySource.PYPI,
            )
        try:
            summary = self._fetch_summary(package_name)
        except (OSError, ValueError, urllib.error.URLError):
            return PackageSummary(summary=None, source=PackageSummarySource.UNAVAILABLE)
        if summary is None:
            return PackageSummary(summary=None, source=PackageSummarySource.UNAVAILABLE)
        cache[normalized_name] = summary
        self._write_cache(cache)
        return PackageSummary(summary=summary, source=PackageSummarySource.PYPI)

    def _fetch_summary(self, package_name: str) -> str | None:
        """Fetch one package summary from PyPI."""

        response = self._urlopen(
            f"https://pypi.org/pypi/{package_name}/json",
            timeout=self._timeout_seconds,
        )
        if not isinstance(response, UrlResponse):
            raise TypeError("PyPI response does not implement the expected protocol.")
        with response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            return None
        info = payload.get("info")
        if not isinstance(info, dict):
            return None
        summary = info.get("summary")
        return summary.strip() if isinstance(summary, str) and summary.strip() else None

    def _read_cache(self) -> dict[str, str]:
        """Return cached PyPI summaries."""

        if not self._cache_path.exists():
            return {}
        try:
            payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(key): str(value)
            for key, value in payload.items()
            if isinstance(key, str) and isinstance(value, str)
        }

    def _write_cache(self, cache: dict[str, str]) -> None:
        """Persist PyPI summary cache data."""

        self._cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
