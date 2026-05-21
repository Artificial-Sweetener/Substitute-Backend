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
"""Tests for Hugging Face download telemetry contracts and patches."""

from __future__ import annotations

import importlib
import logging
import sys
import types
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pytest

from substitute_backend.features.downloads.application.telemetry_service import (
    DownloadContext,
    DownloadTelemetryService,
)
from substitute_backend.features.downloads.domain import (
    DownloadProgressEvent,
    DownloadProvider,
    DownloadState,
)
from substitute_backend.features.downloads.infrastructure.huggingface_patch import (
    _FALLBACK_COMFY_CONTEXT,
    HuggingFaceDownloadPatchInstaller,
)
from substitute_backend.features.downloads.infrastructure.prompt_server_publisher import (
    EVENT_TYPE,
    PromptServerDownloadPublisher,
)
from substitute_backend.features.model_loading.application.telemetry_service import (
    ModelLoadContext,
)
from substitute_backend.features.model_metadata.infrastructure.comfy_model_roots import (
    StaticModelRootsProvider,
)
from substitute_backend.features.preview_assets.application import (
    DownloadResult,
    PreviewAssetServices,
    TaesdAssetService,
)
from substitute_backend.host.extension import build_backend_services
from substitute_backend.host.routes import PromptServerLike, register_routes
from substitute_backend.infrastructure.logging import get_logger


class _CollectingPublisher:
    """Collect download events for assertions."""

    def __init__(self) -> None:
        """Initialize an empty event list."""

        self.events: list[DownloadProgressEvent] = []

    def publish(self, event: DownloadProgressEvent) -> None:
        """Collect one event."""

        self.events.append(event)


class _StaticContextReader:
    """Return a fixed Comfy execution context."""

    def __init__(
        self,
        context: ModelLoadContext | None = None,
    ) -> None:
        """Store the fixed context."""

        self._context = context or ModelLoadContext(
            prompt_id="pid-1",
            node_id="7",
            display_node_id="7",
        )

    def read(self) -> ModelLoadContext:
        """Return the configured context."""

        return self._context


class _SequencedContextReader:
    """Return configured contexts in sequence, then repeat the last one."""

    def __init__(self, contexts: list[ModelLoadContext]) -> None:
        """Store the sequence."""

        self._contexts = contexts
        self._index = 0

    def read(self) -> ModelLoadContext:
        """Return the next context."""

        if self._index >= len(self._contexts):
            return self._contexts[-1]
        context = self._contexts[self._index]
        self._index += 1
        return context


def test_download_event_omits_unknown_optional_fields() -> None:
    """Download payloads should expose only known optional metadata."""

    payload = DownloadProgressEvent(
        provider=DownloadProvider.HUGGINGFACE,
        operation_id="op-1",
        state=DownloadState.STARTED,
        timestamp=1.0,
    ).to_payload()

    assert payload == {
        "version": 1,
        "provider": "huggingface",
        "operation_id": "op-1",
        "state": "started",
        "timestamp": 1.0,
    }


def test_download_event_includes_measured_percent_only_with_positive_maximum() -> None:
    """Measured percentages should require a positive maximum."""

    measured = DownloadProgressEvent(
        provider=DownloadProvider.HUGGINGFACE,
        operation_id="op-1",
        state=DownloadState.RUNNING,
        timestamp=1.0,
        value=50.0,
        maximum=100.0,
        percent=50.0,
    ).to_payload()
    unknown_total = DownloadProgressEvent(
        provider=DownloadProvider.HUGGINGFACE,
        operation_id="op-2",
        state=DownloadState.RUNNING,
        timestamp=1.0,
        value=50.0,
        maximum=0.0,
        percent=50.0,
    ).to_payload()

    assert measured["value"] == 50.0
    assert measured["max"] == 100.0
    assert measured["percent"] == 50.0
    assert unknown_total["value"] == 50.0
    assert "max" not in unknown_total
    assert "percent" not in unknown_total


def test_download_event_clamps_percent() -> None:
    """Measured percentages should be clamped to presentation bounds."""

    payload = DownloadProgressEvent(
        provider=DownloadProvider.HUGGINGFACE,
        operation_id="op-1",
        state=DownloadState.RUNNING,
        timestamp=1.0,
        value=150.0,
        maximum=100.0,
        percent=150.0,
    ).to_payload()

    assert payload["percent"] == 100.0


def test_prompt_server_download_publisher_uses_event_contract() -> None:
    """PromptServer publisher should send the download event type and payload."""

    sent: list[tuple[str, object, str | None]] = []

    class _PromptServer:
        client_id = "client-1"

        def send_sync(self, event: str, data: object, sid: str | None = None) -> None:
            sent.append((event, data, sid))

    publisher = PromptServerDownloadPublisher(
        prompt_server=_PromptServer(),
        logger=logging.getLogger("test.download.publisher"),
    )

    publisher.publish(
        DownloadProgressEvent(
            provider=DownloadProvider.HUGGINGFACE,
            operation_id="op-1",
            state=DownloadState.STARTED,
            timestamp=1.0,
        )
    )

    assert sent == [
        (
            EVENT_TYPE,
            {
                "version": 1,
                "provider": "huggingface",
                "operation_id": "op-1",
                "state": "started",
                "timestamp": 1.0,
            },
            "client-1",
        )
    ]


def test_prompt_server_download_publisher_swallows_send_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """PromptServer failures should not raise into download execution."""

    class _PromptServer:
        client_id = None

        def send_sync(self, _event: str, _data: object, _sid: str | None = None) -> None:
            raise RuntimeError("send failed")

    publisher = PromptServerDownloadPublisher(
        prompt_server=_PromptServer(),
        logger=logging.getLogger("test.download.publisher.failure"),
    )

    with caplog.at_level(logging.ERROR):
        publisher.publish(
            DownloadProgressEvent(
                provider=DownloadProvider.HUGGINGFACE,
                operation_id="op-1",
                state=DownloadState.STARTED,
                timestamp=1.0,
            )
        )

    assert "Failed to publish download telemetry" in caplog.text


def test_download_telemetry_throttles_running_updates() -> None:
    """Running updates should coalesce until percent or time thresholds are crossed."""

    times = iter([0.0, 0.01, 0.02, 0.03, 0.13])
    collector = _CollectingPublisher()
    service = DownloadTelemetryService(
        publisher=collector,
        logger=logging.getLogger("test.download.telemetry"),
        clock=lambda: next(times),
    )
    context = DownloadContext(
        provider=DownloadProvider.HUGGINGFACE,
        operation_id="op-1",
    )

    service.emit(context=context, state=DownloadState.RUNNING, value=1, maximum=100)
    service.emit(context=context, state=DownloadState.RUNNING, value=1.5, maximum=100)
    service.emit(context=context, state=DownloadState.RUNNING, value=2, maximum=100)
    service.emit(context=context, state=DownloadState.RUNNING, value=2.5, maximum=100)
    service.emit(context=context, state=DownloadState.RUNNING, value=2.6, maximum=100)

    assert [event.value for event in collector.events] == [1, 2, 2.6]


def test_download_telemetry_always_emits_terminal_states() -> None:
    """Started, finished, and failed states should bypass running throttling."""

    collector = _CollectingPublisher()
    service = DownloadTelemetryService(
        publisher=collector,
        logger=logging.getLogger("test.download.telemetry.terminal"),
        clock=lambda: 1.0,
    )
    context = DownloadContext(
        provider=DownloadProvider.HUGGINGFACE,
        operation_id="op-1",
    )

    service.emit(context=context, state=DownloadState.STARTED)
    service.emit(context=context, state=DownloadState.FINISHED)
    service.emit(context=context, state=DownloadState.FAILED)

    assert [event.state for event in collector.events] == [
        DownloadState.STARTED,
        DownloadState.FINISHED,
        DownloadState.FAILED,
    ]


def test_huggingface_patch_installer_noops_when_hub_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Installer should disable itself when Hugging Face is unavailable."""

    original_import_module = importlib.import_module

    def fake_import_module(name: str, package: str | None = None) -> types.ModuleType:
        if name.startswith("huggingface_hub"):
            raise ImportError(name)
        return original_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)
    installer = _installer(_CollectingPublisher())

    assert installer.install() is False


def test_huggingface_patch_installer_noops_when_required_internals_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Installer should disable itself when required Hugging Face functions are missing."""

    hub_module = types.ModuleType("huggingface_hub")
    file_download_module = types.ModuleType("huggingface_hub.file_download")
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub_module)
    monkeypatch.setitem(sys.modules, "huggingface_hub.file_download", file_download_module)

    installer = _installer(_CollectingPublisher())

    assert installer.install() is False


def test_huggingface_patch_installer_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Installer should only wrap Hugging Face functions once."""

    hub_module, file_download_module, snapshot_module = _install_fake_huggingface_modules(
        monkeypatch
    )
    installer = _installer(_CollectingPublisher())

    assert installer.install() is True
    first_http_get = file_download_module.http_get
    first_hf_hub_download = file_download_module.hf_hub_download
    assert installer.install() is True

    assert file_download_module.http_get is first_http_get
    assert file_download_module.hf_hub_download is first_hf_hub_download
    assert hub_module.hf_hub_download is first_hf_hub_download
    assert snapshot_module.hf_hub_download is first_hf_hub_download


def test_hf_hub_download_wrapper_emits_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patched ``hf_hub_download`` should emit start, byte progress, and finish."""

    _install_fake_huggingface_modules(monkeypatch)
    collector = _CollectingPublisher()
    installer = _installer(collector)

    assert installer.install() is True
    import huggingface_hub

    assert huggingface_hub.hf_hub_download("owner/repo", "model.bin") == "cached-path"
    payloads = [event.to_payload() for event in collector.events]

    assert [payload["state"] for payload in payloads] == ["started", "running", "finished"]
    assert payloads[0]["repo_id"] == "owner/repo"
    assert payloads[0]["filename"] == "model.bin"
    assert payloads[0]["prompt_id"] == "pid-1"
    assert payloads[1]["value"] == 4.0
    assert payloads[1]["max"] == 4.0
    assert payloads[1]["percent"] == 100.0


def test_http_get_wrapper_reports_progress_with_progress_bar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patched ``http_get`` should support existing Hugging Face progress bars."""

    _hub_module, file_download_module, _snapshot_module = _install_fake_huggingface_modules(
        monkeypatch,
        use_progress_bar=True,
    )
    collector = _CollectingPublisher()
    installer = _installer(collector)
    progress_bar = _FakeProgressBar()

    assert installer.install() is True
    file_download_module.http_get(
        "https://huggingface.co/owner/repo/resolve/main/model.bin",
        BytesIO(),
        expected_size=8,
        displayed_filename="model.bin",
        _tqdm_bar=progress_bar,
    )

    assert progress_bar.updates == [4]
    assert [event.state for event in collector.events] == [
        DownloadState.STARTED,
        DownloadState.RUNNING,
        DownloadState.FINISHED,
    ]
    assert collector.events[1].value == 4.0


def test_failed_hf_hub_download_emits_failed_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patched Hugging Face failures should emit failed without hiding the error."""

    _install_fake_huggingface_modules(monkeypatch, fail_http_get=True)
    collector = _CollectingPublisher()
    installer = _installer(collector)

    assert installer.install() is True
    import huggingface_hub

    with pytest.raises(RuntimeError, match="download failed"):
        huggingface_hub.hf_hub_download("owner/repo", "model.bin")

    assert collector.events[-1].state is DownloadState.FAILED


def test_snapshot_download_propagates_context_into_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Snapshot worker calls should retain the captured Comfy execution context."""

    _hub_module, _file_download_module, snapshot_module = _install_fake_huggingface_modules(
        monkeypatch,
        simulate_thread_context_loss=True,
    )
    collector = _CollectingPublisher()
    installer = HuggingFaceDownloadPatchInstaller(
        telemetry=DownloadTelemetryService(
            publisher=collector,
            logger=logging.getLogger("test.download.snapshot.telemetry"),
        ),
        context_reader=_SequencedContextReader(
            [
                ModelLoadContext(prompt_id="pid-snapshot", node_id="12", display_node_id="12"),
                ModelLoadContext(prompt_id=None, node_id=None, display_node_id=None),
                ModelLoadContext(prompt_id=None, node_id=None, display_node_id=None),
            ]
        ),
        logger=logging.getLogger("test.download.snapshot.patch"),
    )

    assert installer.install() is True
    assert snapshot_module.snapshot_download("owner/repo") == ["cached-path"]

    assert collector.events[0].prompt_id == "pid-snapshot"
    assert collector.events[0].node_id == "12"


def test_backend_capabilities_include_download_telemetry(tmp_path: Path) -> None:
    """Top-level capabilities should advertise backend download telemetry."""

    async def run_capabilities() -> None:
        provider = StaticModelRootsProvider({"loras": (tmp_path,)}, {".safetensors"})
        services = build_backend_services(
            tmp_path,
            model_roots=provider,
            preview_assets=_preview_asset_services(tmp_path),
        )
        prompt_server = _FakePromptServer()

        register_routes(cast("PromptServerLike", prompt_server), services)
        handler = prompt_server.routes.handlers[("GET", "/substitute/v1/capabilities")]
        response = await handler(cast(Any, object()))
        payload = response.text
        assert isinstance(payload, str)

        import json

        body = json.loads(payload)
        assert "download-telemetry" in body["features"]
        assert body["downloadTelemetry"] == {
            "supported": True,
            "eventType": "substitute_download_progress",
            "providers": ["huggingface"],
            "percentMode": "huggingface-byte-progress",
            "scope": "best-effort-runtime-patch",
        }

    import asyncio

    asyncio.run(run_capabilities())


def test_build_backend_services_does_not_import_huggingface(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Service construction should stay lightweight until patch installation."""

    original_import_module = importlib.import_module

    def guarded_import_module(name: str, package: str | None = None) -> types.ModuleType:
        if name.startswith("huggingface_hub"):
            raise AssertionError("huggingface_hub imported during service construction")
        return original_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", guarded_import_module)
    provider = StaticModelRootsProvider({"loras": (tmp_path,)}, {".safetensors"})

    services = build_backend_services(
        tmp_path,
        model_roots=provider,
        preview_assets=_preview_asset_services(tmp_path),
    )

    assert services.downloads.patch_installer is not None


class _FakeProgressBar:
    """Collect progress-bar updates while preserving the original call path."""

    def __init__(self) -> None:
        """Initialize an empty update list."""

        self.updates: list[int | float] = []

    def update(self, amount: int | float = 1) -> None:
        """Collect one update amount."""

        self.updates.append(amount)


def _install_fake_huggingface_modules(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_http_get: bool = False,
    use_progress_bar: bool = False,
    simulate_thread_context_loss: bool = False,
) -> tuple[types.ModuleType, types.ModuleType, types.ModuleType]:
    """Install fake Hugging Face modules into ``sys.modules``."""

    hub_module = types.ModuleType("huggingface_hub")
    file_download_module = types.ModuleType("huggingface_hub.file_download")
    snapshot_module = types.ModuleType("huggingface_hub._snapshot_download")

    def http_get(
        url: str,
        temp_file: BytesIO,
        *,
        expected_size: int | None = None,
        resume_size: int = 0,
        displayed_filename: str | None = None,
        _tqdm_bar: object | None = None,
    ) -> None:
        _ = url, expected_size, resume_size, displayed_filename
        if fail_http_get:
            raise RuntimeError("download failed")
        if use_progress_bar and _tqdm_bar is not None:
            cast(_FakeProgressBar, _tqdm_bar).update(4)
            return
        temp_file.write(b"data")

    def hf_hub_download(
        repo_id: str,
        filename: str,
        *,
        local_dir: str | None = None,
    ) -> str:
        _ = local_dir
        file_download_module.http_get(
            f"https://huggingface.co/{repo_id}/resolve/main/{filename}",
            BytesIO(),
            expected_size=4,
            displayed_filename=filename,
        )
        return "cached-path"

    def thread_map(function: object, items: list[str], **kwargs: object) -> list[object]:
        _ = kwargs
        if simulate_thread_context_loss:
            token = _FALLBACK_COMFY_CONTEXT.set(None)
            try:
                return [cast(Any, function)(item) for item in items]
            finally:
                _FALLBACK_COMFY_CONTEXT.reset(token)
        return [cast(Any, function)(item) for item in items]

    def snapshot_download(repo_id: str, *, local_dir: str | None = None) -> list[object]:
        _ = local_dir
        return cast(
            list[object],
            cast(Any, snapshot_module).thread_map(
                lambda filename: cast(Any, snapshot_module).hf_hub_download(
                    repo_id,
                    filename,
                ),
                ["model.bin"],
            ),
        )

    cast(Any, file_download_module).http_get = http_get
    cast(Any, file_download_module).hf_hub_download = hf_hub_download
    cast(Any, hub_module).hf_hub_download = hf_hub_download
    cast(Any, snapshot_module).hf_hub_download = hf_hub_download
    cast(Any, snapshot_module).thread_map = thread_map
    cast(Any, snapshot_module).snapshot_download = snapshot_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub_module)
    monkeypatch.setitem(sys.modules, "huggingface_hub.file_download", file_download_module)
    monkeypatch.setitem(sys.modules, "huggingface_hub._snapshot_download", snapshot_module)
    return hub_module, file_download_module, snapshot_module


def _installer(collector: _CollectingPublisher) -> HuggingFaceDownloadPatchInstaller:
    """Build a patch installer for tests."""

    return HuggingFaceDownloadPatchInstaller(
        telemetry=DownloadTelemetryService(
            publisher=collector,
            logger=logging.getLogger("test.download.telemetry"),
        ),
        context_reader=_StaticContextReader(),
        logger=logging.getLogger("test.download.patch"),
    )


class _FakeRoutes:
    """Collect route handlers for capabilities tests."""

    def __init__(self) -> None:
        """Initialize route storage."""

        self.handlers: dict[tuple[str, str], Any] = {}

    def get(self, path: str) -> Any:
        """Record a GET handler."""

        return self._record("GET", path)

    def post(self, path: str) -> Any:
        """Record a POST handler."""

        return self._record("POST", path)

    def delete(self, path: str) -> Any:
        """Record a DELETE handler."""

        return self._record("DELETE", path)

    def _record(self, method: str, path: str) -> Any:
        def decorator(handler: Any) -> Any:
            self.handlers[(method, path)] = handler
            return handler

        return decorator


class _FakePromptServer:
    """PromptServer double for capabilities tests."""

    def __init__(self) -> None:
        """Initialize fake routes."""

        self.routes = _FakeRoutes()


class _StaticPathProvider:
    """Resolve the test preview asset root."""

    def __init__(self, root: Path) -> None:
        """Store the root."""

        self._root = root

    def resolve_root(self) -> Path:
        """Return the configured test root."""

        return self._root


class _NoopDownloader:
    """Provide a downloader double for unrelated service composition tests."""

    def download(self, url: str, destination: Path) -> DownloadResult:
        """Return a failed result without touching the network."""

        _ = (url, destination)
        return DownloadResult(succeeded=False, error="noop")


def _preview_asset_services(tmp_path: Path) -> PreviewAssetServices:
    """Build preview asset services without importing ComfyUI ``folder_paths``."""

    return PreviewAssetServices(
        taesd=TaesdAssetService(
            path_provider=_StaticPathProvider(tmp_path / "vae_approx"),
            downloader=_NoopDownloader(),
            logger=get_logger("tests.preview_assets.downloads"),
        )
    )
