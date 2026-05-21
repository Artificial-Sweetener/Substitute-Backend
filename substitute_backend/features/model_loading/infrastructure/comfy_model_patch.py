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
"""Guarded Comfy runtime patch for model-loading telemetry."""

from __future__ import annotations

import importlib
import inspect
import logging
import time
from collections.abc import Callable, Mapping
from os import PathLike
from pathlib import PurePath
from typing import Any, Protocol, cast

from substitute_backend.features.model_loading.application.source_resolver import (
    ModelLoadSource,
    ModelLoadSourceResolver,
)
from substitute_backend.features.model_loading.application.telemetry_service import (
    ModelLoadContext,
    ModelLoadingTelemetryService,
)
from substitute_backend.features.model_loading.domain.events import (
    ModelLoadPhase,
    ModelLoadState,
)
from substitute_backend.features.model_loading.infrastructure.comfy_context import (
    ComfyExecutionContextReader,
    ComfyPromptGraphReader,
)


class _ModelPatcherDynamicLike(Protocol):
    """Subset of ModelPatcherDynamic used by telemetry instrumentation."""

    model: object


class _VBarLike(Protocol):
    """Subset of Comfy's dynamic VRAM bar used by ModelPatcherDynamic.load."""

    def alloc(self, size: int) -> object:
        """Allocate a dynamic VRAM segment."""

    def prioritize(self) -> object:
        """Prioritize the dynamic VRAM bar."""


class _PromptGraphReaderLike(Protocol):
    """Read an active prompt graph for a running Comfy prompt."""

    def read(self, prompt_id: str | None) -> object:
        """Return the active prompt graph for ``prompt_id`` when available."""


class ComfyModelLoadPatchInstaller:
    """Install a failure-safe runtime patch for Comfy dynamic model loading."""

    def __init__(
        self,
        telemetry: ModelLoadingTelemetryService,
        context_reader: ComfyExecutionContextReader,
        logger: logging.Logger,
        prompt_graph_reader: _PromptGraphReaderLike | None = None,
        source_resolver: ModelLoadSourceResolver | None = None,
    ) -> None:
        """Initialize installer with telemetry dependencies."""

        self._telemetry = telemetry
        self._context_reader = context_reader
        self._logger = logger
        self._prompt_graph_reader = prompt_graph_reader or ComfyPromptGraphReader()
        self._source_resolver = source_resolver or ModelLoadSourceResolver()
        self._installed = False

    def install(self) -> bool:
        """Install the patch when Comfy internals expose the expected shape."""

        if self._installed:
            return True
        try:
            model_patcher: Any = importlib.import_module("comfy.model_patcher")
        except ImportError:
            self._logger.info("Model-load telemetry disabled; comfy.model_patcher unavailable")
            return False

        target_class = getattr(model_patcher, "ModelPatcherDynamic", None)
        if target_class is None:
            self._logger.info("Model-load telemetry disabled; ModelPatcherDynamic missing")
            return False
        original_load = getattr(target_class, "load", None)
        if not callable(original_load):
            self._logger.info("Model-load telemetry disabled; ModelPatcherDynamic.load missing")
            return False
        if getattr(original_load, "_substitute_model_load_patch", False):
            self._installed = True
            return True
        if not self._load_signature_is_compatible(original_load):
            self._logger.info("Model-load telemetry disabled; load signature changed")
            return False

        installer = self

        def patched_load(
            instance: _ModelPatcherDynamicLike,
            *args: object,
            **kwargs: object,
        ) -> object:
            """Wrap ModelPatcherDynamic.load with telemetry publication."""

            return installer._run_patched_load(
                instance=instance,
                original_load=cast(Callable[..., object], original_load),
                args=args,
                kwargs=kwargs,
            )

        setattr(patched_load, "_substitute_model_load_patch", True)  # noqa: B010
        setattr(target_class, "load", patched_load)  # noqa: B010
        self._installed = True
        self._logger.info("Model-load telemetry patch installed")
        return True

    @staticmethod
    def _load_signature_is_compatible(load_function: Callable[..., object]) -> bool:
        """Return whether the target load signature has the arguments we wrap."""

        parameters = inspect.signature(load_function).parameters
        return "device_to" in parameters

    def _run_patched_load(
        self,
        *,
        instance: _ModelPatcherDynamicLike,
        original_load: Callable[..., object],
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> object:
        """Run the original load while emitting best-effort telemetry."""

        context = self._context_reader.read()
        model_class = instance.model.__class__.__name__
        model_name = self._model_name_from_instance(instance)
        source = self._resolve_model_source(context=context, model_name=model_name)
        total_size = self._estimate_dynamic_stage_size(instance)

        self._emit_safely(
            phase=ModelLoadPhase.DYNAMIC_VRAM_STAGING,
            state=ModelLoadState.RUNNING,
            context=context,
            value=0.0 if total_size is not None else None,
            maximum=float(total_size) if total_size is not None else None,
            percent=0.0 if total_size is not None else None,
            unit="bytes" if total_size is not None else None,
            model_class=model_class,
            model_name=model_name,
            source=source,
            detail="Dynamic VRAM staging started",
        )

        original_vbar_get = getattr(instance, "_vbar_get", None)
        if callable(original_vbar_get):
            allocated_holder = {"value": 0}
            throttle_state = {"last_percent": -1.0, "last_emit": 0.0}

            def get_allocated_size() -> int:
                return allocated_holder["value"]

            def set_allocated_size(value: int) -> None:
                allocated_holder["value"] = value

            def wrapped_vbar_get(*vbar_args: object, **vbar_kwargs: object) -> object:
                vbar = original_vbar_get(*vbar_args, **vbar_kwargs)
                if vbar is None or total_size is None or total_size <= 0:
                    return vbar

                def on_alloc(size: int) -> None:
                    next_value = get_allocated_size() + max(0, size)
                    set_allocated_size(next_value)
                    percent = 100.0 * next_value / total_size
                    now = time.monotonic()
                    should_emit = (
                        percent >= 100.0
                        or percent - throttle_state["last_percent"] >= 1.0
                        or now - throttle_state["last_emit"] >= 0.1
                    )
                    if not should_emit:
                        return
                    throttle_state["last_percent"] = percent
                    throttle_state["last_emit"] = now
                    self._emit_safely(
                        phase=ModelLoadPhase.DYNAMIC_VRAM_STAGING,
                        state=ModelLoadState.RUNNING,
                        context=context,
                        value=float(next_value),
                        maximum=float(total_size),
                        percent=percent,
                        unit="bytes",
                        model_class=model_class,
                        model_name=model_name,
                        source=source,
                        detail=f"{next_value} of {total_size} bytes staged",
                    )

                return _TelemetryVBar(inner=cast(_VBarLike, vbar), on_alloc=on_alloc)

            setattr(instance, "_vbar_get", wrapped_vbar_get)  # noqa: B010
        try:
            result = original_load(instance, *args, **kwargs)
        except Exception:
            self._emit_safely(
                phase=ModelLoadPhase.FAILED,
                state=ModelLoadState.FINISHED,
                context=context,
                model_class=model_class,
                model_name=model_name,
                source=source,
                detail="Dynamic VRAM staging failed",
            )
            raise
        finally:
            if callable(original_vbar_get):
                setattr(instance, "_vbar_get", original_vbar_get)  # noqa: B010

        self._emit_safely(
            phase=ModelLoadPhase.DYNAMIC_VRAM_STAGING,
            state=ModelLoadState.FINISHED,
            context=context,
            value=float(total_size) if total_size is not None else None,
            maximum=float(total_size) if total_size is not None else None,
            percent=100.0 if total_size is not None else None,
            unit="bytes" if total_size is not None else None,
            model_class=model_class,
            model_name=model_name,
            source=source,
            detail="Dynamic VRAM staging finished",
        )
        return result

    def _resolve_model_source(
        self,
        *,
        context: ModelLoadContext,
        model_name: str | None,
    ) -> ModelLoadSource | None:
        """Resolve source metadata without allowing resolver failures into loads."""

        if model_name is None:
            self._logger.debug("Model-load source unresolved; model name unavailable")
            return None
        prompt_graph = self._prompt_graph_reader.read(context.prompt_id)
        if not isinstance(prompt_graph, Mapping):
            self._logger.debug("Model-load source unresolved; prompt graph unavailable")
            return None
        try:
            source = self._source_resolver.resolve(
                prompt_graph=prompt_graph,
                executing_node_id=context.node_id,
                model_name=model_name,
            )
        except Exception:
            self._logger.exception("Model-load source resolution failed")
            return None
        if source is None:
            self._logger.debug("Model-load source unresolved; no unique prompt input matched")
            return None
        self._logger.debug(
            "Model-load source resolved",
            extra={
                "source_node_id": source.node_id,
                "source_input_key": source.input_key,
                "model_name": model_name,
            },
        )
        return source

    @staticmethod
    def _model_name_from_instance(instance: _ModelPatcherDynamicLike) -> str | None:
        """Return one unambiguous model basename from Comfy patcher metadata."""

        cached_patcher_init = getattr(instance, "cached_patcher_init", None)
        if not isinstance(cached_patcher_init, list | tuple) or len(cached_patcher_init) < 2:
            return None
        raw_args = cached_patcher_init[1]
        candidates = {
            PurePath(candidate.replace("\\", "/")).name
            for candidate in _model_file_path_candidates(raw_args)
        }
        if len(candidates) != 1:
            return None
        return next(iter(candidates))

    def _estimate_dynamic_stage_size(
        self,
        instance: _ModelPatcherDynamicLike,
    ) -> int | None:
        """Estimate dynamic staging bytes using Comfy internals when available."""

        try:
            memory_management: Any = importlib.import_module("comfy.memory_management")
            model_patcher: Any = importlib.import_module("comfy.model_patcher")
        except ImportError:
            return None

        load_list = getattr(instance, "_load_list", None)
        if not callable(load_list):
            return None
        try:
            entries = list(load_list(for_dynamic=True))
            total = 0
            for entry in entries:
                *_, node_name, module, _params = entry
                if not hasattr(module, "comfy_cast_weights"):
                    continue
                for param_key in ("weight", "bias"):
                    key_builder = getattr(model_patcher, "key_param_name_to_key", None)
                    get_key_weight = getattr(model_patcher, "get_key_weight", None)
                    quantized_tensor = getattr(model_patcher, "QuantizedTensor", None)
                    if not callable(key_builder) or not callable(get_key_weight):
                        return None
                    key = key_builder(node_name, param_key)
                    weight, _, _ = get_key_weight(instance.model, key)
                    if weight is None:
                        continue
                    if isinstance(quantized_tensor, type) and isinstance(
                        weight,
                        quantized_tensor,
                    ):
                        geometry = weight
                    else:
                        model_dtype = (
                            getattr(module, f"{param_key}_comfy_model_dtype", None) or weight.dtype
                        )
                        geometry = memory_management.TensorGeometry(
                            shape=weight.shape,
                            dtype=model_dtype,
                        )
                    total += memory_management.vram_aligned_size(geometry)
        except Exception:
            self._logger.exception("Failed to estimate dynamic model-load size")
            return None
        else:
            return total if total > 0 else None

    def _emit_safely(
        self,
        *,
        phase: ModelLoadPhase,
        state: ModelLoadState,
        context: ModelLoadContext,
        percent: float | None = None,
        value: float | None = None,
        maximum: float | None = None,
        unit: str | None = None,
        model_class: str | None = None,
        model_name: str | None = None,
        source: ModelLoadSource | None = None,
        detail: str | None = None,
    ) -> None:
        """Emit telemetry without allowing telemetry failures into Comfy execution."""

        try:
            self._telemetry.emit(
                phase=phase,
                state=state,
                context=context,
                percent=percent,
                value=value,
                maximum=maximum,
                unit=unit,
                model_class=model_class,
                model_name=model_name,
                source_node_id=source.node_id if source is not None else None,
                source_input_key=source.input_key if source is not None else None,
                detail=detail,
            )
        except Exception:
            self._logger.exception("Model-load telemetry emission failed")


_MODEL_FILE_EXTENSIONS = frozenset(
    {
        ".bin",
        ".ckpt",
        ".gguf",
        ".pt",
        ".pth",
        ".safetensors",
        ".sft",
    }
)


def _model_file_path_candidates(value: object) -> list[str]:
    """Return model file path candidates from a Comfy cached patcher argument."""

    if isinstance(value, str):
        return [value] if _looks_like_model_file(value) else []
    if isinstance(value, PathLike):
        string_value = str(value)
        return [string_value] if _looks_like_model_file(string_value) else []
    if isinstance(value, list | tuple):
        candidates: list[str] = []
        for item in value:
            candidates.extend(_model_file_path_candidates(item))
        return candidates
    return []


def _looks_like_model_file(value: str) -> bool:
    """Return whether a path-like value names a known model file."""

    stripped_value = value.strip()
    if not stripped_value:
        return False
    return PurePath(stripped_value.replace("\\", "/")).suffix.casefold() in _MODEL_FILE_EXTENSIONS


class _TelemetryVBar:
    """Wrap Comfy's dynamic VRAM bar and report allocation progress."""

    def __init__(self, inner: _VBarLike, on_alloc: Callable[[int], None]) -> None:
        """Initialize wrapper with the original vbar and allocation hook."""

        self._inner = inner
        self._on_alloc = on_alloc

    def alloc(self, size: int) -> object:
        """Allocate through the real vbar, then emit allocation progress."""

        result = self._inner.alloc(size)
        self._on_alloc(size)
        return result

    def prioritize(self) -> object:
        """Delegate priority changes to the wrapped vbar."""

        return self._inner.prioritize()

    def __getattr__(self, name: str) -> object:
        """Delegate other vbar attributes to the wrapped object."""

        return getattr(self._inner, name)
