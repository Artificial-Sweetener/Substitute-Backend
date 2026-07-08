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
"""Persist Comfy node model-folder dependency scans across startups."""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from time import perf_counter
from typing import Protocol, cast

_DIAGNOSTICS_ENV_VAR = "SUBSTITUTE_BACKEND_DIAGNOSTICS"
_STARTUP_DIAGNOSTICS = "startup"
_ALL_DIAGNOSTICS = "all"


class NodeDependencyScanner(Protocol):
    """Scan Comfy node classes for model-folder list dependencies."""

    def scan(self) -> dict[str, tuple[str, ...]]:
        """Return ``model_kind -> node_classes`` dependencies."""


class NodesModule(Protocol):
    """Expose the Comfy node-class registry used for cache validation."""

    NODE_CLASS_MAPPINGS: Mapping[str, type[object]]


class CachedNodeModelDependencyScanner:
    """Reuse dependency scans while Comfy node class source facts are unchanged."""

    _SCHEMA_VERSION = 1

    def __init__(
        self,
        *,
        cache_path: Path,
        scanner: NodeDependencyScanner,
        logger: logging.Logger,
        nodes_module: NodesModule | None = None,
    ) -> None:
        """Initialize the cached scanner with explicit host-boundary collaborators."""

        self._cache_path = cache_path
        self._scanner = scanner
        self._logger = logger
        self._nodes_module = nodes_module

    def scan(self) -> dict[str, tuple[str, ...]]:
        """Return cached dependencies, rebuilding when node source facts change."""

        started_at = perf_counter()
        phase_started_at = started_at
        phase_timings: dict[str, float] = {}

        def record_phase(name: str) -> None:
            """Record elapsed milliseconds for one cache scan phase."""

            nonlocal phase_started_at
            now = perf_counter()
            phase_timings[name] = round((now - phase_started_at) * 1000, 3)
            phase_started_at = now

        signature_result = self._current_signature()
        signature = signature_result.signature
        phase_timings.update(
            {
                f"current_signature.{key}": value
                for key, value in signature_result.phase_timings.items()
            }
        )
        record_phase("current_signature")
        cached = self._read_cache()
        record_phase("read_cache")
        if cached is not None and cached.signature == signature:
            self._logger.debug(
                "Using cached Comfy node model dependency index",
                extra={"node_count": len(signature)},
            )
            _log_startup_timing(
                self._logger,
                total_duration_ms=round((perf_counter() - started_at) * 1000, 3),
                cache_hit=True,
                node_count=len(signature),
                dependency_kind_count=len(cached.dependencies),
                phase_timings=phase_timings,
                extra_fields=signature_result.metrics,
            )
            return cached.dependencies

        dependencies = self._scanner.scan()
        record_phase("scan_dependencies")
        self._write_cache(signature=signature, dependencies=dependencies)
        record_phase("write_cache")
        _log_startup_timing(
            self._logger,
            total_duration_ms=round((perf_counter() - started_at) * 1000, 3),
            cache_hit=False,
            node_count=len(signature),
            dependency_kind_count=len(dependencies),
            phase_timings=phase_timings,
            extra_fields=signature_result.metrics,
        )
        return dependencies

    def _current_signature(self) -> _CurrentSignatureResult:
        """Return cheap source facts for the currently registered node classes."""

        diagnostics_enabled = _startup_diagnostics_enabled()
        started_at = perf_counter()
        source_path_duration_ms = 0.0
        source_fact_duration_ms = 0.0
        row_build_duration_ms = 0.0
        nodes_module = self._nodes_module or self._load_nodes_module()
        load_nodes_module_ms = round((perf_counter() - started_at) * 1000, 3)
        sort_started_at = perf_counter()
        node_items = sorted(nodes_module.NODE_CLASS_MAPPINGS.items())
        sort_nodes_ms = round((perf_counter() - sort_started_at) * 1000, 3)
        source_paths_by_module: dict[str, Path | None] = {}
        source_facts_by_path: dict[Path, dict[str, object]] = {}
        rows: list[dict[str, object]] = []
        missing_source_count = 0
        missing_source_facts: dict[str, object] = {"path": "", "mtimeNs": 0, "sizeBytes": 0}
        for node_class, node_type in node_items:
            module_name = getattr(node_type, "__module__", "")
            qualified_name = getattr(node_type, "__qualname__", "")
            module_key = str(module_name)
            if module_key not in source_paths_by_module:
                source_path_started_at = perf_counter()
                source_paths_by_module[module_key] = self._source_path(module_name)
                if diagnostics_enabled:
                    source_path_duration_ms += (perf_counter() - source_path_started_at) * 1000
            source_path = source_paths_by_module[module_key]
            if source_path is None:
                missing_source_count += 1
                source_facts = missing_source_facts
            else:
                cached_source_facts = source_facts_by_path.get(source_path)
                if cached_source_facts is None:
                    source_fact_started_at = perf_counter()
                    source_facts = self._source_facts(source_path)
                    if diagnostics_enabled:
                        source_fact_duration_ms += (perf_counter() - source_fact_started_at) * 1000
                    source_facts_by_path[source_path] = source_facts
                else:
                    source_facts = cached_source_facts
            row_started_at = perf_counter()
            rows.append(
                {
                    "nodeClass": node_class,
                    "module": str(module_name),
                    "qualname": str(qualified_name),
                    "source": source_facts,
                }
            )
            if diagnostics_enabled:
                row_build_duration_ms += (perf_counter() - row_started_at) * 1000
        return _CurrentSignatureResult(
            signature=tuple(rows),
            metrics={
                "signature_unique_module_count": len(source_paths_by_module),
                "signature_unique_source_path_count": len(source_facts_by_path),
                "signature_missing_source_count": missing_source_count,
            },
            phase_timings={
                "load_nodes_module": load_nodes_module_ms,
                "sort_nodes": sort_nodes_ms,
                "resolve_source_paths": round(source_path_duration_ms, 3),
                "read_source_facts": round(source_fact_duration_ms, 3),
                "build_rows": round(row_build_duration_ms, 3),
            },
        )

    def _source_path(self, module_name: object) -> Path | None:
        """Return the absolute module source path when it is available."""

        if not isinstance(module_name, str) or not module_name:
            return None
        module = sys.modules.get(module_name)
        if module is None:
            return None
        module_file = getattr(module, "__file__", None)
        if not isinstance(module_file, str) or not module_file:
            return None
        return Path(os.path.abspath(module_file))

    @staticmethod
    def _source_facts(path: Path | None) -> dict[str, object]:
        """Return stable file facts without reading source content."""

        if path is None:
            return {"path": "", "mtimeNs": 0, "sizeBytes": 0}
        try:
            stat = path.stat()
        except OSError:
            return {"path": str(path), "mtimeNs": 0, "sizeBytes": 0}
        return {
            "path": str(path),
            "mtimeNs": stat.st_mtime_ns,
            "sizeBytes": stat.st_size,
        }

    def _read_cache(self) -> _DependencyCacheEntry | None:
        """Return a valid cache entry or treat invalid data as a miss."""

        try:
            raw = self._cache_path.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("schemaVersion") != self._SCHEMA_VERSION:
            return None
        raw_signature = payload.get("signature")
        raw_dependencies = payload.get("dependencies")
        if not isinstance(raw_signature, list) or not isinstance(raw_dependencies, dict):
            return None
        signature = tuple(
            cast("dict[str, object]", row) for row in raw_signature if isinstance(row, dict)
        )
        if len(signature) != len(raw_signature):
            return None
        dependencies: dict[str, tuple[str, ...]] = {}
        for kind, nodes in raw_dependencies.items():
            if not isinstance(kind, str) or not isinstance(nodes, list):
                return None
            if not all(isinstance(node, str) for node in nodes):
                return None
            dependencies[kind] = tuple(nodes)
        return _DependencyCacheEntry(
            signature=signature,
            dependencies=dependencies,
        )

    def _write_cache(
        self,
        *,
        signature: tuple[dict[str, object], ...],
        dependencies: Mapping[str, tuple[str, ...]],
    ) -> None:
        """Persist one dependency scan result, downgrading write failures."""

        payload = {
            "schemaVersion": self._SCHEMA_VERSION,
            "signature": list(signature),
            "dependencies": {kind: list(nodes) for kind, nodes in sorted(dependencies.items())},
        }
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self._cache_path.with_suffix(f".{os.getpid()}.tmp")
            temp_path.write_text(
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            temp_path.replace(self._cache_path)
        except OSError as exc:
            self._logger.debug(
                "Failed to persist Comfy node model dependency index",
                extra={"cache_path": str(self._cache_path), "error": repr(exc)},
            )

    @staticmethod
    def _load_nodes_module() -> NodesModule:
        """Import Comfy's nodes module at the host boundary."""

        module = __import__("nodes")
        return cast("NodesModule", module)


class _DependencyCacheEntry:
    """Store one validated dependency cache payload."""

    def __init__(
        self,
        *,
        signature: tuple[dict[str, object], ...],
        dependencies: dict[str, tuple[str, ...]],
    ) -> None:
        """Initialize one immutable cache result container."""

        self.signature = signature
        self.dependencies = dependencies


class _CurrentSignatureResult:
    """Capture the node dependency cache signature and diagnostic attribution."""

    def __init__(
        self,
        *,
        signature: tuple[dict[str, object], ...],
        metrics: Mapping[str, int],
        phase_timings: Mapping[str, float],
    ) -> None:
        """Initialize one signature build result."""

        self.signature = signature
        self.metrics = metrics
        self.phase_timings = phase_timings


def _log_startup_timing(
    logger: logging.Logger,
    *,
    total_duration_ms: float,
    cache_hit: bool,
    node_count: int,
    dependency_kind_count: int,
    phase_timings: Mapping[str, float],
    extra_fields: Mapping[str, object],
) -> None:
    """Emit opt-in startup diagnostics for node dependency cache validation."""

    if not _startup_diagnostics_enabled():
        return
    fields = " ".join(
        [
            *(f"{key}={value}" for key, value in sorted(extra_fields.items())),
            *(f"{key}={value}" for key, value in sorted(phase_timings.items())),
        ]
    )
    logger.info(
        "Substitute startup diagnostic "
        "event=substitute_node_dependency_index_timing "
        "total_duration_ms=%s cache_hit=%s node_count=%s "
        "dependency_kind_count=%s %s",
        total_duration_ms,
        cache_hit,
        node_count,
        dependency_kind_count,
        fields,
    )


def _startup_diagnostics_enabled() -> bool:
    """Return whether startup timing diagnostics should be logged."""

    enabled = {
        value.strip().casefold()
        for value in os.environ.get(_DIAGNOSTICS_ENV_VAR, "").split(",")
        if value.strip()
    }
    return _ALL_DIAGNOSTICS in enabled or _STARTUP_DIAGNOSTICS in enabled


__all__ = ["CachedNodeModelDependencyScanner", "NodeDependencyScanner"]
