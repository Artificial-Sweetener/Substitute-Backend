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
"""Tests for opt-in Substitute BackEnd diagnostic logging."""

from __future__ import annotations

import logging

import pytest

from substitute_backend.infrastructure.diagnostics import (
    CUBE_LIBRARY_DIAGNOSTICS,
    DIAGNOSTICS_ENV_VAR,
    DiagnosticContext,
    diagnostics_from_environment,
)


def test_diagnostics_are_disabled_without_environment(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Diagnostics should stay silent unless explicitly enabled."""

    monkeypatch.delenv(DIAGNOSTICS_ENV_VAR, raising=False)
    diagnostics = diagnostics_from_environment(logging.getLogger("test.diagnostics"))
    context = DiagnosticContext(feature=CUBE_LIBRARY_DIAGNOSTICS, trace_id="trace-1")

    with caplog.at_level(logging.DEBUG):
        diagnostics.debug(context, "event", {"value": 1})

    assert caplog.records == []


def test_diagnostics_parse_comma_separated_features(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Diagnostics should accept normalized feature names from the environment."""

    monkeypatch.setenv(DIAGNOSTICS_ENV_VAR, "other, CUBE-LIBRARY ")
    diagnostics = diagnostics_from_environment(logging.getLogger("test.diagnostics"))
    context = DiagnosticContext(feature=CUBE_LIBRARY_DIAGNOSTICS, trace_id="trace-1")

    with caplog.at_level(logging.DEBUG):
        diagnostics.debug(context, "event", {"value": 1})

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert getattr(record, "diagnostic_feature", "") == CUBE_LIBRARY_DIAGNOSTICS
    assert getattr(record, "diagnostic_event", "") == "event"
    assert getattr(record, "trace_id", "") == "trace-1"
    assert getattr(record, "value", 0) == 1


def test_diagnostics_support_all_feature_flag(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The all flag should enable diagnostics for every feature context."""

    monkeypatch.setenv(DIAGNOSTICS_ENV_VAR, "all")
    diagnostics = diagnostics_from_environment(logging.getLogger("test.diagnostics"))

    with caplog.at_level(logging.DEBUG):
        diagnostics.debug(DiagnosticContext(feature="unknown"), "event", {})

    assert len(caplog.records) == 1
    assert getattr(caplog.records[0], "diagnostic_feature", "") == "unknown"


def test_diagnostics_respect_debug_level(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enabled diagnostics should still obey normal logger levels."""

    monkeypatch.setenv(DIAGNOSTICS_ENV_VAR, "cube-library")
    diagnostics = diagnostics_from_environment(logging.getLogger("test.diagnostics"))

    with caplog.at_level(logging.INFO):
        diagnostics.debug(DiagnosticContext(feature=CUBE_LIBRARY_DIAGNOSTICS), "event", {})

    assert caplog.records == []
