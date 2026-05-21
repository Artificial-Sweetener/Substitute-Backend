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
"""Opt-in diagnostic logging helpers for targeted backend debugging."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass

DIAGNOSTICS_ENV_VAR = "SUBSTITUTE_BACKEND_DIAGNOSTICS"
ALL_DIAGNOSTICS = "all"
CUBE_LIBRARY_DIAGNOSTICS = "cube-library"


@dataclass(frozen=True)
class DiagnosticContext:
    """Describe one diagnostic logging context."""

    feature: str
    trace_id: str = ""


class DiagnosticLogger:
    """Emit opt-in debug diagnostics without affecting normal runtime logs."""

    def __init__(self, *, logger: logging.Logger, enabled_features: frozenset[str]) -> None:
        """Initialize diagnostics from a concrete logger and enabled feature set."""

        self._logger = logger
        self._enabled_features = enabled_features

    def enabled(self, context: DiagnosticContext) -> bool:
        """Return whether the diagnostic context should emit logs."""

        if not self._logger.isEnabledFor(logging.DEBUG):
            return False
        feature = context.feature.casefold()
        return ALL_DIAGNOSTICS in self._enabled_features or feature in self._enabled_features

    def debug(
        self,
        context: DiagnosticContext,
        event: str,
        fields: Mapping[str, object],
    ) -> None:
        """Emit one structured diagnostic event when the context is enabled."""

        if not self.enabled(context):
            return
        extra: dict[str, object] = {
            "diagnostic_feature": context.feature,
            "diagnostic_event": event,
        }
        if context.trace_id:
            extra["trace_id"] = context.trace_id
        extra.update(fields)
        self._logger.debug("Substitute diagnostic event", extra=extra)


def diagnostics_from_environment(logger: logging.Logger) -> DiagnosticLogger:
    """Build a diagnostic logger from process environment configuration."""

    return DiagnosticLogger(
        logger=logger,
        enabled_features=_enabled_diagnostic_features(os.environ.get(DIAGNOSTICS_ENV_VAR, "")),
    )


def _enabled_diagnostic_features(raw_value: str) -> frozenset[str]:
    """Parse enabled diagnostic feature names from an environment value."""

    return frozenset(value.strip().casefold() for value in raw_value.split(",") if value.strip())
