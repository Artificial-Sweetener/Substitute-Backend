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
"""Parse known Comfy model-loading log messages into telemetry metadata."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from substitute_backend.features.model_loading.application.telemetry_service import (
    ModelLoadingTelemetryService,
)
from substitute_backend.features.model_loading.domain.events import (
    ModelLoadPhase,
    ModelLoadState,
)
from substitute_backend.features.model_loading.infrastructure.comfy_context import (
    ComfyExecutionContextReader,
)


@dataclass(frozen=True)
class ParsedModelLoadLog:
    """Represent model-loading details parsed from one Comfy log line."""

    phase: ModelLoadPhase
    state: ModelLoadState
    model_class: str | None = None
    staged_mb: float | None = None
    patches_attached: int | None = None
    detail: str | None = None


class ComfyModelLoadLogParser:
    """Parse only the Comfy model-loading messages we intentionally support."""

    _REQUESTED = re.compile(r"^Requested to load (?P<model_class>.+)$")
    _DYNAMIC_STAGED = re.compile(
        r"^Model (?P<model_class>.+) prepared for dynamic VRAM loading\. "
        r"(?P<staged_mb>\d+(?:\.\d+)?)MB Staged\. "
        r"(?P<patches>\d+) patches attached\."
    )
    _PARTIAL = re.compile(r"^(?P<model_class>.+) loaded partially; (?P<detail>.+)$")
    _COMPLETE = re.compile(r"^(?P<model_class>.+) loaded completely; (?P<detail>.+)$")

    def parse(self, message: str) -> ParsedModelLoadLog | None:
        """Return parsed model-loading metadata, or None for unrelated messages."""

        requested = self._REQUESTED.match(message)
        if requested is not None:
            return ParsedModelLoadLog(
                phase=ModelLoadPhase.REQUESTED,
                state=ModelLoadState.RUNNING,
                model_class=requested.group("model_class"),
            )

        staged = self._DYNAMIC_STAGED.match(message)
        if staged is not None:
            staged_mb = float(staged.group("staged_mb"))
            patches_attached = int(staged.group("patches"))
            return ParsedModelLoadLog(
                phase=ModelLoadPhase.DYNAMIC_VRAM_STAGING,
                state=ModelLoadState.FINISHED,
                model_class=staged.group("model_class"),
                staged_mb=staged_mb,
                patches_attached=patches_attached,
                detail=f"{staged_mb:g}MB staged; {patches_attached} patches attached",
            )

        partial = self._PARTIAL.match(message)
        if partial is not None:
            return ParsedModelLoadLog(
                phase=ModelLoadPhase.LOADED_PARTIALLY,
                state=ModelLoadState.UNKNOWN,
                model_class=partial.group("model_class"),
                detail=partial.group("detail"),
            )

        complete = self._COMPLETE.match(message)
        if complete is not None:
            return ParsedModelLoadLog(
                phase=ModelLoadPhase.LOADED_COMPLETELY,
                state=ModelLoadState.FINISHED,
                model_class=complete.group("model_class"),
                detail=complete.group("detail"),
            )

        return None


class ComfyModelLoadLogObserver:
    """Install a narrow logging handler for Comfy model-loading milestones."""

    _HANDLER_NAME = "substitute_model_load_log_observer"

    def __init__(
        self,
        *,
        parser: ComfyModelLoadLogParser,
        telemetry: ModelLoadingTelemetryService,
        context_reader: ComfyExecutionContextReader,
        logger: logging.Logger,
    ) -> None:
        """Initialize observer dependencies."""

        self._parser = parser
        self._telemetry = telemetry
        self._context_reader = context_reader
        self._logger = logger
        self._installed = False

    def install(self) -> bool:
        """Attach the model-loading log handler to the root logger once."""

        if self._installed:
            return True
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            if getattr(handler, "name", None) == self._HANDLER_NAME:
                self._installed = True
                return True
        handler = _ComfyModelLoadLogHandler(
            parser=self._parser,
            telemetry=self._telemetry,
            context_reader=self._context_reader,
            logger=self._logger,
        )
        handler.name = self._HANDLER_NAME
        root_logger.addHandler(handler)
        self._installed = True
        self._logger.info("Model-load log observer installed")
        return True


class _ComfyModelLoadLogHandler(logging.Handler):
    """Convert selected Comfy log records into telemetry milestones."""

    def __init__(
        self,
        *,
        parser: ComfyModelLoadLogParser,
        telemetry: ModelLoadingTelemetryService,
        context_reader: ComfyExecutionContextReader,
        logger: logging.Logger,
    ) -> None:
        """Initialize logging handler dependencies."""

        super().__init__(level=logging.INFO)
        self._parser = parser
        self._telemetry = telemetry
        self._context_reader = context_reader
        self._logger = logger

    def emit(self, record: logging.LogRecord) -> None:
        """Publish telemetry for a matching Comfy model-loading log record."""

        try:
            parsed = self._parser.parse(record.getMessage())
            if parsed is None:
                return
            detail = parsed.detail
            if detail is None and parsed.staged_mb is not None:
                detail = f"{parsed.staged_mb:g}MB staged"
            self._telemetry.emit(
                phase=parsed.phase,
                state=parsed.state,
                context=self._context_reader.read(),
                model_class=parsed.model_class,
                detail=detail,
            )
        except Exception:
            self._logger.exception("Failed to process Comfy model-loading log record")
