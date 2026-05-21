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
"""Tests for backend-managed preview asset preparation."""

from __future__ import annotations

import asyncio
import io
import json
import urllib.error
from pathlib import Path
from typing import cast

import pytest
from aiohttp import web

from substitute_backend.features.preview_assets.api import build_preview_asset_route_handlers
from substitute_backend.features.preview_assets.application import (
    DownloadResult,
    PreviewAssetServices,
    TaesdAssetService,
)
from substitute_backend.features.preview_assets.domain import (
    PreviewAssetError,
    PreviewAssetStatus,
    taesd_asset_manifest,
)
from substitute_backend.features.preview_assets.infrastructure import (
    ComfyVaeApproxPathProvider,
    HttpAssetDownloader,
)
from substitute_backend.infrastructure.logging import get_logger


class StaticPathProvider:
    """Resolve a fixed test root."""

    def __init__(self, root: Path) -> None:
        """Store the fixed root."""

        self.root = root

    def resolve_root(self) -> Path:
        """Return the fixed root."""

        self.root.mkdir(parents=True, exist_ok=True)
        return self.root


class FakeDownloader:
    """Write deterministic asset bytes for tests."""

    def __init__(self, *, failing_filename: str | None = None) -> None:
        """Configure an optional filename that should fail."""

        self.failing_filename = failing_filename
        self.calls: list[tuple[str, Path]] = []

    def download(self, url: str, destination: Path) -> DownloadResult:
        """Record the call and write bytes unless configured to fail."""

        self.calls.append((url, destination))
        if destination.name == self.failing_filename:
            return DownloadResult(succeeded=False, error="network failed")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(f"asset:{destination.name}".encode())
        return DownloadResult(succeeded=True, size_bytes=destination.stat().st_size)


class EmptyFolderPaths:
    """Expose no Comfy model roots."""

    def get_folder_paths(self, folder_name: str) -> list[str]:
        """Return no roots for any folder name."""

        _ = folder_name
        return []


class StaticFolderPaths:
    """Expose fixed Comfy model roots."""

    def __init__(self, roots: list[str]) -> None:
        """Store fixed roots."""

        self._roots = roots

    def get_folder_paths(self, folder_name: str) -> list[str]:
        """Return configured roots for ``vae_approx``."""

        assert folder_name == "vae_approx"
        return list(self._roots)


class UrlOpenResponse(io.BytesIO):
    """Provide the context manager surface returned by urllib."""

    def __enter__(self) -> UrlOpenResponse:
        """Return this response for urllib context management."""

        return self

    def __exit__(self, *_args: object) -> None:
        """Close the response when the context exits."""

        self.close()


def test_taesd_status_reports_missing_assets_without_downloading(tmp_path: Path) -> None:
    """Status should inspect files and avoid network work."""

    downloader = FakeDownloader()
    service = _service(tmp_path / "vae_approx", downloader)

    status = service.status()

    assert status.ready is False
    assert status.missing_count == 4
    assert {asset.status for asset in status.assets} == {PreviewAssetStatus.MISSING}
    assert downloader.calls == []


def test_taesd_status_reports_installed_assets(tmp_path: Path) -> None:
    """Status should report installed files with sizes."""

    root = tmp_path / "vae_approx"
    root.mkdir()
    for asset in taesd_asset_manifest():
        (root / asset.filename).write_bytes(b"ready")
    service = _service(root, FakeDownloader())

    status = service.status()

    assert status.ready is True
    assert status.installed_count == 4
    assert {asset.size_bytes for asset in status.assets} == {5}


def test_taesd_ensure_downloads_missing_and_skips_existing(tmp_path: Path) -> None:
    """Ensure should download missing assets while preserving existing files."""

    root = tmp_path / "vae_approx"
    root.mkdir()
    first = taesd_asset_manifest()[0]
    (root / first.filename).write_bytes(b"existing")
    downloader = FakeDownloader()
    service = _service(root, downloader)

    status = service.ensure()

    assert status.ready is True
    assert status.downloads_attempted is True
    assert len(downloader.calls) == 3
    assert (root / first.filename).read_bytes() == b"existing"


def test_taesd_ensure_reports_partial_failure(tmp_path: Path) -> None:
    """Ensure should return per-file failure details when one download fails."""

    failing = taesd_asset_manifest()[1].filename
    service = _service(tmp_path / "vae_approx", FakeDownloader(failing_filename=failing))

    status = service.ensure()

    failed = [asset for asset in status.assets if asset.status is PreviewAssetStatus.FAILED]
    assert status.ready is False
    assert status.missing_count == 1
    assert len(failed) == 1
    assert failed[0].filename == failing
    assert failed[0].error == "network failed"


def test_path_provider_rejects_missing_folder_paths() -> None:
    """Comfy path provider should fail closed when no vae_approx root exists."""

    provider = ComfyVaeApproxPathProvider(EmptyFolderPaths())

    with pytest.raises(PreviewAssetError) as error:
        provider.resolve_root()

    assert error.value.code == "vae-approx-root-unavailable"


def test_path_provider_creates_first_configured_root(tmp_path: Path) -> None:
    """Comfy path provider should create the first configured missing root."""

    root = tmp_path / "models" / "vae_approx"
    provider = ComfyVaeApproxPathProvider(StaticFolderPaths([str(root)]))

    assert provider.resolve_root() == root.resolve()
    assert root.is_dir()


def test_http_downloader_rejects_non_allowlisted_url(tmp_path: Path) -> None:
    """HTTP downloader should never fetch arbitrary URLs."""

    downloader = HttpAssetDownloader(allowed_urls={"https://example.invalid/asset.pth"})

    result = downloader.download(
        "https://example.invalid/other.pth",
        tmp_path / "asset.pth",
    )

    assert result.succeeded is False
    assert result.error == "Preview asset URL is not allowlisted."
    assert not (tmp_path / "asset.pth").exists()


def test_http_downloader_writes_temp_then_final(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP downloader should write bytes to the final destination."""

    url = "https://example.invalid/asset.pth"

    def fake_urlopen(*_args: object, **_kwargs: object) -> UrlOpenResponse:
        """Return deterministic download bytes."""

        return UrlOpenResponse(b"downloaded")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    destination = tmp_path / "asset.pth"
    downloader = HttpAssetDownloader(allowed_urls={url})

    result = downloader.download(url, destination)

    assert result.succeeded is True
    assert destination.read_bytes() == b"downloaded"
    assert list(tmp_path.glob("*.tmp")) == []


def test_http_downloader_removes_temp_file_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP downloader should clean up temporary files after transport failure."""

    url = "https://example.invalid/asset.pth"

    def fake_urlopen(*_args: object, **_kwargs: object) -> object:
        """Raise a deterministic urllib failure."""

        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    destination = tmp_path / "asset.pth"
    downloader = HttpAssetDownloader(allowed_urls={url})

    result = downloader.download(url, destination)

    assert result.succeeded is False
    assert "offline" in (result.error or "")
    assert not destination.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_preview_asset_routes_return_status_and_ensure_payloads(tmp_path: Path) -> None:
    """Preview asset routes should expose typed status and ensure responses."""

    async def run_routes() -> None:
        service = _service(tmp_path / "vae_approx", FakeDownloader())
        handlers = build_preview_asset_route_handlers(
            PreviewAssetServices(taesd=service),
            logger=get_logger("tests.preview_assets.routes"),
        )

        status_response = await handlers.taesd_status(cast("web.Request", object()))
        status_payload = _response_payload(status_response)
        assert status_payload["ready"] is False
        assert status_payload["missingCount"] == 4

        ensure_response = await handlers.ensure_taesd(cast("web.Request", object()))
        ensure_payload = _response_payload(ensure_response)
        assert ensure_payload["ready"] is True
        assert ensure_payload["installedCount"] == 4
        assert ensure_payload["downloadsAttempted"] is True

    asyncio.run(run_routes())


def _service(root: Path, downloader: FakeDownloader) -> TaesdAssetService:
    """Build a TAESD asset service with deterministic test dependencies."""

    return TaesdAssetService(
        path_provider=StaticPathProvider(root),
        downloader=downloader,
        logger=get_logger("tests.preview_assets.taesd"),
    )


def _response_payload(response: web.StreamResponse) -> dict[str, object]:
    """Decode one JSON response from an aiohttp route."""

    if not isinstance(response, web.Response) or response.text is None:
        raise AssertionError("Expected JSON web response")
    payload = json.loads(response.text)
    assert isinstance(payload, dict)
    return payload
