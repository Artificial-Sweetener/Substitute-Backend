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
"""Guarded Hugging Face runtime patch for download telemetry."""

from __future__ import annotations

import contextvars
import importlib
import inspect
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from types import ModuleType
from typing import Any, Protocol, cast

from substitute_backend.features.downloads.application.telemetry_service import (
    DownloadContext,
    DownloadTelemetryService,
)
from substitute_backend.features.downloads.domain import DownloadProvider, DownloadState
from substitute_backend.features.model_loading.application.telemetry_service import (
    ModelLoadContext,
)

_PATCH_MARKER = "_substitute_download_patch"


class _ContextReaderLike(Protocol):
    """Read the active Comfy execution context when available."""

    def read(self) -> ModelLoadContext:
        """Return current Comfy execution context."""


@dataclass(frozen=True)
class _CapturedComfyContext:
    """Capture prompt and node identity for download attribution."""

    prompt_id: str | None
    node_id: str | None
    display_node_id: str | None

    @classmethod
    def from_model_load_context(cls, context: ModelLoadContext) -> _CapturedComfyContext:
        """Create a captured context from the shared Comfy context adapter."""

        return cls(
            prompt_id=context.prompt_id,
            node_id=context.node_id,
            display_node_id=context.display_node_id,
        )


@dataclass
class _ActiveDownload:
    """Track mutable state for one active Hugging Face file download."""

    context: DownloadContext
    value: float | None = None
    maximum: float | None = None
    started: bool = False
    terminal: bool = False


_FALLBACK_COMFY_CONTEXT: contextvars.ContextVar[_CapturedComfyContext | None] = (
    contextvars.ContextVar("substitute_download_fallback_comfy_context", default=None)
)
_ACTIVE_DOWNLOAD: contextvars.ContextVar[_ActiveDownload | None] = contextvars.ContextVar(
    "substitute_active_download",
    default=None,
)


class HuggingFaceDownloadPatchInstaller:
    """Install failure-safe Hugging Face download telemetry patches."""

    def __init__(
        self,
        *,
        telemetry: DownloadTelemetryService,
        context_reader: _ContextReaderLike,
        logger: logging.Logger,
    ) -> None:
        """Initialize installer with telemetry dependencies."""

        self._telemetry = telemetry
        self._context_reader = context_reader
        self._logger = logger
        self._installed = False

    def install(self) -> bool:
        """Install Hugging Face patches when the expected internals are available."""

        if self._installed:
            return True
        try:
            hub_module = importlib.import_module("huggingface_hub")
            file_download_module = importlib.import_module("huggingface_hub.file_download")
        except ImportError:
            self._logger.info("Download telemetry disabled; huggingface_hub unavailable")
            return False

        http_get = getattr(file_download_module, "http_get", None)
        hf_hub_download = getattr(file_download_module, "hf_hub_download", None)
        if not callable(http_get) or not callable(hf_hub_download):
            self._logger.info("Download telemetry disabled; Hugging Face internals missing")
            return False
        if not _http_get_signature_is_compatible(cast(Callable[..., object], http_get)):
            self._logger.info("Download telemetry disabled; http_get signature changed")
            return False
        if not _hf_hub_download_signature_is_compatible(
            cast(Callable[..., object], hf_hub_download)
        ):
            self._logger.info("Download telemetry disabled; hf_hub_download signature changed")
            return False

        original_http_get = cast(Callable[..., object], http_get)
        original_hf_hub_download = cast(Callable[..., object], hf_hub_download)
        patched_http_get = self._patch_http_get(
            module=file_download_module,
            original=original_http_get,
        )
        patched_hf_hub_download = self._patch_hf_hub_download(
            module=file_download_module,
            attribute_name="hf_hub_download",
            original=original_hf_hub_download,
        )
        if getattr(hub_module, "hf_hub_download", None) is original_hf_hub_download:
            cast(Any, hub_module).hf_hub_download = patched_hf_hub_download

        self._patch_snapshot_module(
            original_hf_hub_download=original_hf_hub_download,
            patched_hf_hub_download=patched_hf_hub_download,
        )

        self._installed = True
        self._logger.info(
            "Hugging Face download telemetry patch installed",
            extra={
                "http_get_patched": getattr(patched_http_get, _PATCH_MARKER, False),
                "hf_hub_download_patched": getattr(
                    patched_hf_hub_download,
                    _PATCH_MARKER,
                    False,
                ),
            },
        )
        return True

    def _patch_http_get(
        self,
        *,
        module: ModuleType,
        original: Callable[..., object],
    ) -> Callable[..., object]:
        """Patch Hugging Face ``http_get`` and return the active callable."""

        if getattr(original, _PATCH_MARKER, False):
            return original
        installer = self
        signature = inspect.signature(original)

        def patched_http_get(*args: object, **kwargs: object) -> object:
            """Wrap Hugging Face byte streaming with telemetry."""

            return installer._run_patched_http_get(
                original=original,
                signature=signature,
                args=args,
                kwargs=kwargs,
            )

        setattr(patched_http_get, _PATCH_MARKER, True)
        cast(Any, module).http_get = patched_http_get
        return patched_http_get

    def _patch_hf_hub_download(
        self,
        *,
        module: ModuleType,
        attribute_name: str,
        original: Callable[..., object],
    ) -> Callable[..., object]:
        """Patch one Hugging Face ``hf_hub_download`` reference."""

        if getattr(original, _PATCH_MARKER, False):
            return original
        installer = self
        signature = inspect.signature(original)

        def patched_hf_hub_download(*args: object, **kwargs: object) -> object:
            """Wrap Hugging Face file download setup with operation context."""

            return installer._run_patched_hf_hub_download(
                original=original,
                signature=signature,
                args=args,
                kwargs=kwargs,
            )

        setattr(patched_hf_hub_download, _PATCH_MARKER, True)
        setattr(module, attribute_name, patched_hf_hub_download)
        return patched_hf_hub_download

    def _patch_snapshot_module(
        self,
        *,
        original_hf_hub_download: Callable[..., object],
        patched_hf_hub_download: Callable[..., object],
    ) -> None:
        """Patch optional snapshot-download internals for thread context propagation."""

        try:
            snapshot_module = importlib.import_module("huggingface_hub._snapshot_download")
        except ImportError:
            return

        snapshot_hf_hub_download = getattr(snapshot_module, "hf_hub_download", None)
        if snapshot_hf_hub_download is original_hf_hub_download:
            cast(Any, snapshot_module).hf_hub_download = patched_hf_hub_download
        elif callable(snapshot_hf_hub_download) and _hf_hub_download_signature_is_compatible(
            cast(Callable[..., object], snapshot_hf_hub_download)
        ):
            self._patch_hf_hub_download(
                module=snapshot_module,
                attribute_name="hf_hub_download",
                original=cast(Callable[..., object], snapshot_hf_hub_download),
            )

        snapshot_download = getattr(snapshot_module, "snapshot_download", None)
        if not callable(snapshot_download):
            return
        if getattr(snapshot_download, _PATCH_MARKER, False):
            return
        if not _snapshot_download_signature_is_compatible(
            cast(Callable[..., object], snapshot_download)
        ):
            self._logger.info("Snapshot download context propagation skipped; signature changed")
            return

        installer = self
        original_snapshot_download = cast(Callable[..., object], snapshot_download)

        def patched_snapshot_download(*args: object, **kwargs: object) -> object:
            """Wrap snapshot downloads so worker threads retain Comfy context."""

            return installer._run_patched_snapshot_download(
                snapshot_module=snapshot_module,
                original=original_snapshot_download,
                args=args,
                kwargs=kwargs,
            )

        setattr(patched_snapshot_download, _PATCH_MARKER, True)
        cast(Any, snapshot_module).snapshot_download = patched_snapshot_download

    def _run_patched_hf_hub_download(
        self,
        *,
        original: Callable[..., object],
        signature: inspect.Signature,
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> object:
        """Run ``hf_hub_download`` with active operation metadata."""

        bound = signature.bind_partial(*args, **kwargs)
        repo_id = _string_or_none(bound.arguments.get("repo_id"))
        filename = _string_or_none(bound.arguments.get("filename"))
        active = _ActiveDownload(
            context=DownloadContext(
                provider=DownloadProvider.HUGGINGFACE,
                operation_id=uuid.uuid4().hex,
                repo_id=repo_id,
                filename=filename,
                **self._captured_context_fields(),
            )
        )
        token = _ACTIVE_DOWNLOAD.set(active)
        try:
            result = original(*args, **kwargs)
        except Exception:
            if not active.terminal:
                self._emit_safely(
                    active=active,
                    state=DownloadState.FAILED,
                    detail=filename,
                )
                active.terminal = True
            raise
        finally:
            _ACTIVE_DOWNLOAD.reset(token)
        if active.started and not active.terminal:
            self._emit_safely(
                active=active,
                state=DownloadState.FINISHED,
                value=active.value,
                maximum=active.maximum,
                detail=filename,
            )
            active.terminal = True
        return result

    def _run_patched_http_get(
        self,
        *,
        original: Callable[..., object],
        signature: inspect.Signature,
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> object:
        """Run ``http_get`` while counting streamed bytes."""

        bound = signature.bind_partial(*args, **kwargs)
        url = _string_or_none(bound.arguments.get("url"))
        displayed_filename = _string_or_none(bound.arguments.get("displayed_filename"))
        expected_size = _positive_float_or_none(bound.arguments.get("expected_size"))
        resume_size = _non_negative_float(bound.arguments.get("resume_size"))
        active = _ACTIVE_DOWNLOAD.get()
        owns_active = active is None
        token: contextvars.Token[_ActiveDownload | None] | None = None
        if active is None:
            active = _ActiveDownload(
                context=DownloadContext(
                    provider=DownloadProvider.HUGGINGFACE,
                    operation_id=uuid.uuid4().hex,
                    filename=displayed_filename,
                    url=url,
                    **self._captured_context_fields(),
                )
            )
            token = _ACTIVE_DOWNLOAD.set(active)
        active.context = replace(
            active.context,
            filename=displayed_filename or active.context.filename,
            url=url or active.context.url,
        )
        active.value = resume_size
        active.maximum = expected_size
        self._start_download_if_needed(active=active, detail=active.context.filename)

        progress_bar = bound.arguments.get("_tqdm_bar")
        if progress_bar is not None:
            bound.arguments["_tqdm_bar"] = _TelemetryProgressBar(
                inner=progress_bar,
                on_update=lambda amount: self._record_progress(active, amount),
            )
        else:
            temp_file = bound.arguments.get("temp_file")
            if temp_file is not None:
                bound.arguments["temp_file"] = _TelemetryFile(
                    inner=temp_file,
                    on_write=lambda amount: self._record_progress(active, amount),
                )
        try:
            result = original(*bound.args, **bound.kwargs)
        except Exception:
            if not active.terminal:
                self._emit_safely(
                    active=active,
                    state=DownloadState.FAILED,
                    value=active.value,
                    maximum=active.maximum,
                    detail=active.context.filename,
                )
                active.terminal = True
            raise
        finally:
            if token is not None:
                _ACTIVE_DOWNLOAD.reset(token)
        if not active.terminal:
            self._emit_safely(
                active=active,
                state=DownloadState.FINISHED,
                value=active.value,
                maximum=active.maximum,
                detail=active.context.filename,
            )
            active.terminal = True
        if owns_active:
            return result
        return result

    def _run_patched_snapshot_download(
        self,
        *,
        snapshot_module: ModuleType,
        original: Callable[..., object],
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> object:
        """Run ``snapshot_download`` while propagating context into worker threads."""

        captured = _CapturedComfyContext.from_model_load_context(self._context_reader.read())
        fallback_token = _FALLBACK_COMFY_CONTEXT.set(captured)
        original_thread_map = getattr(snapshot_module, "thread_map", None)
        thread_map_patched = False
        if callable(original_thread_map):
            try:
                cast(Any, snapshot_module).thread_map = _build_context_thread_map(
                    original_thread_map=cast(Callable[..., object], original_thread_map),
                    captured=captured,
                )
                thread_map_patched = True
            except Exception:
                self._logger.exception("Failed to install snapshot download context propagation")
        try:
            return original(*args, **kwargs)
        finally:
            if thread_map_patched:
                cast(Any, snapshot_module).thread_map = original_thread_map
            _FALLBACK_COMFY_CONTEXT.reset(fallback_token)

    def _captured_context_fields(self) -> dict[str, str | None]:
        """Return prompt and node fields for a new download context."""

        context = self._context_reader.read()
        captured = _CapturedComfyContext.from_model_load_context(context)
        fallback = _FALLBACK_COMFY_CONTEXT.get()
        if captured.prompt_id is None and fallback is not None:
            captured = fallback
        return {
            "prompt_id": captured.prompt_id,
            "node_id": captured.node_id,
            "display_node_id": captured.display_node_id,
        }

    def _start_download_if_needed(
        self,
        *,
        active: _ActiveDownload,
        detail: str | None,
    ) -> None:
        """Emit the start event once for an active file download."""

        if active.started:
            return
        active.started = True
        self._emit_safely(
            active=active,
            state=DownloadState.STARTED,
            value=active.value,
            maximum=active.maximum,
            detail=detail,
        )

    def _record_progress(self, active: _ActiveDownload, amount: int) -> None:
        """Record a streamed byte increment for one active download."""

        if amount <= 0 or active.terminal:
            return
        active.value = (active.value or 0.0) + float(amount)
        self._emit_safely(
            active=active,
            state=DownloadState.RUNNING,
            value=active.value,
            maximum=active.maximum,
            detail=active.context.filename,
        )

    def _emit_safely(
        self,
        *,
        active: _ActiveDownload,
        state: DownloadState,
        value: float | None = None,
        maximum: float | None = None,
        detail: str | None = None,
    ) -> None:
        """Emit download telemetry without allowing failures into Hugging Face."""

        try:
            self._telemetry.emit(
                context=active.context,
                state=state,
                value=value,
                maximum=maximum,
                unit="bytes" if value is not None else None,
                detail=detail,
            )
        except Exception:
            self._logger.exception("Download telemetry emission failed")


class _TelemetryFile:
    """Proxy a writable file object and report byte writes."""

    def __init__(self, *, inner: object, on_write: Callable[[int], None]) -> None:
        """Initialize the proxy with its wrapped file object."""

        self._inner = inner
        self._on_write = on_write

    def write(self, data: object) -> object:
        """Write data to the wrapped object and report byte length."""

        result = cast(Any, self._inner).write(data)
        if isinstance(data, bytes | bytearray | memoryview):
            self._on_write(len(data))
        return result

    def __getattr__(self, name: str) -> object:
        """Delegate unknown attributes to the wrapped file object."""

        return getattr(self._inner, name)


class _TelemetryProgressBar:
    """Proxy a Hugging Face progress bar and report byte increments."""

    def __init__(self, *, inner: object, on_update: Callable[[int], None]) -> None:
        """Initialize the proxy with its wrapped progress bar."""

        self._inner = inner
        self._on_update = on_update

    def update(self, amount: int | float = 1) -> object:
        """Update the wrapped progress bar and report byte increments."""

        result = cast(Any, self._inner).update(amount)
        if isinstance(amount, int | float):
            self._on_update(max(0, int(amount)))
        return result

    def __enter__(self) -> _TelemetryProgressBar:
        """Enter the wrapped progress bar context when supported."""

        enter = getattr(self._inner, "__enter__", None)
        if callable(enter):
            enter()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> object:
        """Exit the wrapped progress bar context when supported."""

        exit_method = getattr(self._inner, "__exit__", None)
        if callable(exit_method):
            return exit_method(exc_type, exc, tb)
        return False

    def __getattr__(self, name: str) -> object:
        """Delegate unknown attributes to the wrapped progress bar."""

        return getattr(self._inner, name)


def _build_context_thread_map(
    *,
    original_thread_map: Callable[..., object],
    captured: _CapturedComfyContext,
) -> Callable[..., object]:
    """Return a ``thread_map`` wrapper that restores Comfy context in workers."""

    def wrapped_thread_map(
        function: Callable[..., object], *args: object, **kwargs: object
    ) -> object:
        def context_function(*function_args: object, **function_kwargs: object) -> object:
            token = _FALLBACK_COMFY_CONTEXT.set(captured)
            try:
                return function(*function_args, **function_kwargs)
            finally:
                _FALLBACK_COMFY_CONTEXT.reset(token)

        return original_thread_map(context_function, *args, **kwargs)

    setattr(wrapped_thread_map, _PATCH_MARKER, True)
    return wrapped_thread_map


def _http_get_signature_is_compatible(function: Callable[..., object]) -> bool:
    """Return whether Hugging Face ``http_get`` exposes the parameters we wrap."""

    parameters = inspect.signature(function).parameters
    return (
        "url" in parameters
        and "temp_file" in parameters
        and ("expected_size" in parameters or "_tqdm_bar" in parameters)
    )


def _hf_hub_download_signature_is_compatible(function: Callable[..., object]) -> bool:
    """Return whether ``hf_hub_download`` exposes the parameters we capture."""

    parameters = inspect.signature(function).parameters
    return "repo_id" in parameters and "filename" in parameters


def _snapshot_download_signature_is_compatible(function: Callable[..., object]) -> bool:
    """Return whether ``snapshot_download`` exposes repo identity."""

    return "repo_id" in inspect.signature(function).parameters


def _string_or_none(value: object) -> str | None:
    """Return non-empty string values, coercing simple path-like text."""

    if isinstance(value, str) and value:
        return value
    return None


def _positive_float_or_none(value: object) -> float | None:
    """Return positive numeric values as floats."""

    if isinstance(value, int | float) and value > 0:
        return float(value)
    return None


def _non_negative_float(value: object) -> float:
    """Return non-negative numeric values as floats."""

    if isinstance(value, int | float) and value > 0:
        return float(value)
    return 0.0
