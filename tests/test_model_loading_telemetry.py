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
"""Tests for model-loading telemetry contracts and adapters."""

from __future__ import annotations

import logging
import sys
import types
from pathlib import Path
from typing import Any, cast

import pytest

from substitute_backend.features.model_loading.application.source_resolver import (
    ModelLoadSourceResolver,
)
from substitute_backend.features.model_loading.application.telemetry_service import (
    ModelLoadContext,
    ModelLoadingTelemetryService,
)
from substitute_backend.features.model_loading.domain.events import (
    ModelLoadPhase,
    ModelLoadProgressEvent,
    ModelLoadState,
)
from substitute_backend.features.model_loading.infrastructure.comfy_context import (
    ComfyExecutionContextReader,
    ComfyPromptGraphReader,
)
from substitute_backend.features.model_loading.infrastructure.comfy_log_parser import (
    ComfyModelLoadLogObserver,
    ComfyModelLoadLogParser,
)
from substitute_backend.features.model_loading.infrastructure.comfy_model_patch import (
    ComfyModelLoadPatchInstaller,
)
from substitute_backend.features.model_loading.infrastructure.prompt_server_publisher import (
    EVENT_TYPE,
    PromptServerModelLoadPublisher,
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
from substitute_backend.infrastructure.logging import get_logger


class _CollectingPublisher:
    """Collect events published by the telemetry service."""

    def __init__(self) -> None:
        """Initialize an empty event list."""

        self.events: list[ModelLoadProgressEvent] = []

    def publish(self, event: ModelLoadProgressEvent) -> None:
        """Collect the event for assertions."""

        self.events.append(event)


def test_model_load_event_omits_unmeasured_percent() -> None:
    """Event payloads should not expose percent without measured value and maximum."""

    payload = ModelLoadProgressEvent(
        phase=ModelLoadPhase.REQUESTED,
        state=ModelLoadState.RUNNING,
        timestamp=1.0,
        percent=50.0,
    ).to_payload()

    assert "percent" not in payload
    assert "value" not in payload
    assert "max" not in payload
    assert "source_node_id" not in payload
    assert "source_input_key" not in payload


def test_model_load_event_includes_source_fields_when_present() -> None:
    """Event payloads should carry optional source routing fields."""

    payload = ModelLoadProgressEvent(
        phase=ModelLoadPhase.DYNAMIC_VRAM_STAGING,
        state=ModelLoadState.RUNNING,
        timestamp=1.0,
        source_node_id="3",
        source_input_key="ckpt_name",
    ).to_payload()

    assert payload["version"] == 1
    assert payload["source_node_id"] == "3"
    assert payload["source_input_key"] == "ckpt_name"


def test_model_load_event_clamps_measured_percent() -> None:
    """Measured event percentages should be clamped to UI-safe bounds."""

    payload = ModelLoadProgressEvent(
        phase=ModelLoadPhase.DYNAMIC_VRAM_STAGING,
        state=ModelLoadState.RUNNING,
        timestamp=1.0,
        percent=150.0,
        value=15.0,
        maximum=10.0,
    ).to_payload()

    assert payload["percent"] == 100.0
    assert payload["value"] == 15.0
    assert payload["max"] == 10.0


def test_prompt_server_publisher_uses_event_contract() -> None:
    """PromptServer publisher should send the telemetry event type and payload."""

    sent: list[tuple[str, object, str | None]] = []

    class _PromptServer:
        client_id = "client-1"

        def send_sync(self, event: str, data: object, sid: str | None = None) -> None:
            sent.append((event, data, sid))

    publisher = PromptServerModelLoadPublisher(
        prompt_server=_PromptServer(),
        logger=logging.getLogger("test"),
    )

    publisher.publish(
        ModelLoadProgressEvent(
            phase=ModelLoadPhase.REQUESTED,
            state=ModelLoadState.RUNNING,
            timestamp=1.0,
        )
    )

    assert sent == [
        (
            EVENT_TYPE,
            {
                "version": 1,
                "phase": "requested",
                "state": "running",
                "timestamp": 1.0,
            },
            "client-1",
        )
    ]


def test_prompt_server_publisher_swallows_send_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """PromptServer failures should not raise into Comfy execution."""

    class _PromptServer:
        client_id = None

        def send_sync(self, _event: str, _data: object, _sid: str | None = None) -> None:
            raise RuntimeError("send failed")

    publisher = PromptServerModelLoadPublisher(
        prompt_server=_PromptServer(),
        logger=logging.getLogger("test.publisher"),
    )

    with caplog.at_level(logging.ERROR):
        publisher.publish(
            ModelLoadProgressEvent(
                phase=ModelLoadPhase.REQUESTED,
                state=ModelLoadState.RUNNING,
                timestamp=1.0,
            )
        )

    assert "Failed to publish model-load telemetry" in caplog.text


def test_log_parser_parses_known_model_loading_messages() -> None:
    """Known Comfy model-loading messages should map to telemetry phases."""

    parser = ComfyModelLoadLogParser()

    requested = parser.parse("Requested to load SDXL")
    staged = parser.parse(
        "Model SDXL prepared for dynamic VRAM loading. 4897MB Staged. 0 patches attached."
    )
    unrelated = parser.parse("this is an unrelated log line")

    assert requested is not None
    assert requested.phase == ModelLoadPhase.REQUESTED
    assert requested.model_class == "SDXL"
    assert staged is not None
    assert staged.phase == ModelLoadPhase.DYNAMIC_VRAM_STAGING
    assert staged.state == ModelLoadState.FINISHED
    assert staged.staged_mb == 4897.0
    assert staged.patches_attached == 0
    assert unrelated is None


def test_log_observer_publishes_only_known_model_loading_messages() -> None:
    """Log observer should keep root logging noise out of telemetry."""

    collector = _CollectingPublisher()
    telemetry = ModelLoadingTelemetryService(collector)
    parser = ComfyModelLoadLogParser()
    logger = logging.getLogger("test.model_loading_logs")
    observer = ComfyModelLoadLogObserver(
        parser=parser,
        telemetry=telemetry,
        context_reader=ComfyExecutionContextReader(),
        logger=logger,
    )

    assert observer.install() is True
    root_logger = logging.getLogger()
    previous_level = root_logger.level
    root_logger.setLevel(logging.INFO)
    try:
        root_logger.info("unrelated message")
        root_logger.info("Requested to load SDXL")
    finally:
        root_logger.setLevel(previous_level)
        for handler in list(root_logger.handlers):
            if getattr(handler, "name", None) == "substitute_model_load_log_observer":
                root_logger.removeHandler(handler)

    assert [event.phase for event in collector.events] == [ModelLoadPhase.REQUESTED]


def test_source_resolver_matches_direct_current_node_input() -> None:
    """Resolver should match a model selector on the executing node itself."""

    resolver = ModelLoadSourceResolver()

    source = resolver.resolve(
        prompt_graph={
            "1": {
                "class_type": "AnyModelNode",
                "inputs": {"model_name": "E:/models/checkpoints/example.safetensors"},
            }
        },
        executing_node_id="1",
        model_name="example.safetensors",
    )

    assert source is not None
    assert source.node_id == "1"
    assert source.input_key == "model_name"


def test_source_resolver_matches_upstream_sampler_input() -> None:
    """Resolver should walk upstream links without knowing sampler or loader classes."""

    resolver = ModelLoadSourceResolver()

    source = resolver.resolve(
        prompt_graph={
            "4": {"class_type": "KSampler", "inputs": {"model": ["2", 0]}},
            "2": {"class_type": "Loader", "inputs": {"ckpt_name": "example.safetensors"}},
        },
        executing_node_id="4",
        model_name="E:/models/checkpoints/example.safetensors",
    )

    assert source is not None
    assert source.node_id == "2"
    assert source.input_key == "ckpt_name"


def test_source_resolver_matches_upstream_decode_input() -> None:
    """Resolver should follow non-sampler graph paths such as VAE decode chains."""

    resolver = ModelLoadSourceResolver()

    source = resolver.resolve(
        prompt_graph={
            "8": {"class_type": "VAEDecode", "inputs": {"vae": ["7", 0], "samples": ["6", 0]}},
            "7": {"class_type": "VAELoader", "inputs": {"vae_name": "vae-ft.safetensors"}},
            "6": {"class_type": "Sampler", "inputs": {}},
        },
        executing_node_id="8",
        model_name="vae-ft.safetensors",
    )

    assert source is not None
    assert source.node_id == "7"
    assert source.input_key == "vae_name"


def test_source_resolver_returns_none_for_missing_or_ambiguous_matches() -> None:
    """Resolver should only return source metadata for one confident input match."""

    resolver = ModelLoadSourceResolver()
    graph = {
        "1": {
            "class_type": "Ambiguous",
            "inputs": {
                "first": "example.safetensors",
                "second": "E:/models/checkpoints/example.safetensors",
            },
        }
    }

    assert (
        resolver.resolve(
            prompt_graph=graph,
            executing_node_id="1",
            model_name=None,
        )
        is None
    )
    assert (
        resolver.resolve(
            prompt_graph=graph,
            executing_node_id="1",
            model_name="example.safetensors",
        )
        is None
    )
    assert (
        resolver.resolve(
            prompt_graph={"1": {"inputs": {"text": "not a model"}}},
            executing_node_id="1",
            model_name="example.safetensors",
        )
        is None
    )


def test_source_resolver_handles_cycles_and_malformed_inputs() -> None:
    """Resolver should tolerate graph cycles and malformed node inputs."""

    resolver = ModelLoadSourceResolver()

    source = resolver.resolve(
        prompt_graph={
            "1": {"inputs": {"next": ["2", 0]}},
            "2": {"inputs": {"previous": ["1", 0], "model": "example.safetensors"}},
            "3": {"inputs": object()},
        },
        executing_node_id="1",
        model_name="example.safetensors",
    )

    assert source is not None
    assert source.node_id == "2"
    assert source.input_key == "model"


def test_prompt_graph_reader_reads_running_prompt_from_comfy_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prompt graph reader should use Comfy's running queue when available."""

    prompt_graph: dict[str, object] = {"1": {"inputs": {}}}
    server_module = types.ModuleType("server")

    class _PromptQueue:
        def get_current_queue_volatile(self) -> tuple[list[tuple[object, ...]], list[object]]:
            return (
                [
                    (1, "other", {"2": {"inputs": {}}}, {}, []),
                    (2, "pid-1", prompt_graph, {}, []),
                ],
                [],
            )

    class _PromptServer:
        instance = types.SimpleNamespace(prompt_queue=_PromptQueue())

    cast(Any, server_module).PromptServer = _PromptServer
    monkeypatch.setitem(sys.modules, "server", server_module)

    assert ComfyPromptGraphReader().read("pid-1") == prompt_graph


def test_patch_installer_noops_when_target_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patch installer should disable itself when Comfy internals are absent."""

    comfy_module = types.ModuleType("comfy")
    model_patcher_module = types.ModuleType("comfy.model_patcher")
    monkeypatch.setitem(sys.modules, "comfy", comfy_module)
    monkeypatch.setitem(sys.modules, "comfy.model_patcher", model_patcher_module)

    telemetry = ModelLoadingTelemetryService(_CollectingPublisher())
    installer = ComfyModelLoadPatchInstaller(
        telemetry=telemetry,
        context_reader=ComfyExecutionContextReader(),
        logger=logging.getLogger("test.patch"),
    )

    assert installer.install() is False


def test_patch_installer_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch installer should only wrap a compatible load function once."""

    comfy_module = types.ModuleType("comfy")
    model_patcher_module = types.ModuleType("comfy.model_patcher")

    class _ModelPatcherDynamic:
        def load(self, device_to: object | None = None) -> str:
            _ = device_to
            return "loaded"

    cast(Any, model_patcher_module).ModelPatcherDynamic = _ModelPatcherDynamic
    cast(Any, comfy_module).model_patcher = model_patcher_module
    monkeypatch.setitem(sys.modules, "comfy", comfy_module)
    monkeypatch.setitem(sys.modules, "comfy.model_patcher", model_patcher_module)

    telemetry = ModelLoadingTelemetryService(_CollectingPublisher())
    installer = ComfyModelLoadPatchInstaller(
        telemetry=telemetry,
        context_reader=ComfyExecutionContextReader(),
        logger=logging.getLogger("test.patch"),
    )

    assert installer.install() is True
    first_load = _ModelPatcherDynamic.load
    assert installer.install() is True
    assert _ModelPatcherDynamic.load is first_load


def test_backend_capabilities_include_model_loading_telemetry(tmp_path: Path) -> None:
    """Top-level services should include the model-loading telemetry feature."""

    provider = StaticModelRootsProvider({"loras": (tmp_path,)}, {".safetensors"})
    services = build_backend_services(
        tmp_path,
        model_roots=provider,
        preview_assets=_preview_asset_services(tmp_path),
    )

    assert services.model_loading.log_parser.parse("unrelated") is None
    assert services.model_loading.patch_installer is not None


class _StaticPathProvider:
    """Resolve the test preview asset root without ComfyUI globals."""

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
            logger=get_logger("tests.preview_assets.model_loading"),
        )
    )


def test_patch_wrapper_emits_measured_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compatible dynamic load wrapping should emit measured staging progress."""

    comfy_module = types.ModuleType("comfy")
    model_patcher_module = types.ModuleType("comfy.model_patcher")
    memory_module = types.ModuleType("comfy.memory_management")

    class _TensorGeometry:
        def __init__(self, *, shape: tuple[int, ...], dtype: str) -> None:
            self.shape = shape
            self.dtype = dtype

    class _Weight:
        shape = (2, 2)
        dtype = "float32"

    class _VBar:
        def prioritize(self) -> None:
            return None

        def alloc(self, size: int) -> object:
            return object()

    class _Model:
        pass

    class _ModelPatcherDynamic:
        def __init__(self) -> None:
            self.model = _Model()
            self.cached_patcher_init = (
                object(),
                (
                    "E:/models/checkpoints/example.safetensors",
                    "E:/models/embeddings",
                ),
            )

        def _load_list(
            self,
            *,
            for_dynamic: bool,
            default_device: object | None = None,
        ) -> list[tuple[object, ...]]:
            _ = for_dynamic, default_device
            return [(0, 0, 0, "layer", types.SimpleNamespace(comfy_cast_weights=True), [])]

        def _vbar_get(self, *, create: bool = False) -> _VBar:
            _ = create
            return _VBar()

        def load(self, device_to: object | None = None) -> str:
            _ = device_to
            vbar = self._vbar_get(create=True)
            vbar.prioritize()
            vbar.alloc(16)
            return "loaded"

    def key_param_name_to_key(node_name: str, param_key: str) -> str:
        return f"{node_name}.{param_key}"

    def get_key_weight(_model: object, _key: str) -> tuple[_Weight, None, None]:
        return (_Weight(), None, None)

    def vram_aligned_size(_geometry: _TensorGeometry) -> int:
        return 16

    cast(Any, model_patcher_module).ModelPatcherDynamic = _ModelPatcherDynamic
    cast(Any, model_patcher_module).key_param_name_to_key = key_param_name_to_key
    cast(Any, model_patcher_module).get_key_weight = get_key_weight
    cast(Any, model_patcher_module).QuantizedTensor = type("QuantizedTensor", (), {})
    cast(Any, memory_module).TensorGeometry = _TensorGeometry
    cast(Any, memory_module).vram_aligned_size = vram_aligned_size
    cast(Any, comfy_module).model_patcher = model_patcher_module
    cast(Any, comfy_module).memory_management = memory_module
    monkeypatch.setitem(sys.modules, "comfy", comfy_module)
    monkeypatch.setitem(sys.modules, "comfy.model_patcher", model_patcher_module)
    monkeypatch.setitem(sys.modules, "comfy.memory_management", memory_module)

    class _ContextReader:
        def read(self) -> ModelLoadContext:
            return ModelLoadContext(prompt_id="pid-1", node_id="4", display_node_id="4")

    class _PromptGraphReader:
        def read(self, prompt_id: str | None) -> object:
            assert prompt_id == "pid-1"
            return {
                "4": {"class_type": "KSampler", "inputs": {"model": ["2", 0]}},
                "2": {
                    "class_type": "Loader",
                    "inputs": {"ckpt_name": "example.safetensors"},
                },
            }

    collector = _CollectingPublisher()
    telemetry = ModelLoadingTelemetryService(collector)
    installer = ComfyModelLoadPatchInstaller(
        telemetry=telemetry,
        context_reader=cast(ComfyExecutionContextReader, _ContextReader()),
        logger=logging.getLogger("test.patch"),
        prompt_graph_reader=_PromptGraphReader(),
    )

    assert installer.install() is True
    assert cast(Any, _ModelPatcherDynamic()).load() == "loaded"
    payloads = [event.to_payload() for event in collector.events]

    assert [payload["state"] for payload in payloads] == ["running", "running", "finished"]
    assert payloads[1]["percent"] == 50.0
    assert payloads[1]["model_name"] == "example.safetensors"
    assert payloads[1]["source_node_id"] == "2"
    assert payloads[1]["source_input_key"] == "ckpt_name"
    assert payloads[-1]["percent"] == 100.0
