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
"""Optimization report payloads for executable prompt graph rewrites."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OptimizationReplacement:
    """Describe one duplicate node replacement in an executable API prompt."""

    kind: str
    class_type: str
    duplicate_node_id: str
    canonical_node_id: str
    signature_hash: str

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-compatible replacement payload."""

        return {
            "kind": self.kind,
            "classType": self.class_type,
            "duplicateNodeId": self.duplicate_node_id,
            "canonicalNodeId": self.canonical_node_id,
            "signatureHash": self.signature_hash,
        }


@dataclass(frozen=True)
class OptimizationReport:
    """Summarize one optimizer pass over an executable API prompt."""

    optimized: bool
    original_node_count: int
    optimized_node_count: int
    replacements: tuple[OptimizationReplacement, ...] = ()
    failed: bool = False
    error: str | None = None

    @classmethod
    def unchanged(cls, node_count: int) -> OptimizationReport:
        """Return a report for a prompt that did not change."""

        return cls(
            optimized=False,
            original_node_count=node_count,
            optimized_node_count=node_count,
        )

    @classmethod
    def failed_open(cls, node_count: int, error: str) -> OptimizationReport:
        """Return a report for an optimizer failure that preserved the original prompt."""

        return cls(
            optimized=False,
            original_node_count=node_count,
            optimized_node_count=node_count,
            failed=True,
            error=error,
        )

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-compatible optimization report."""

        payload: dict[str, object] = {
            "optimized": self.optimized,
            "failed": self.failed,
            "originalNodeCount": self.original_node_count,
            "optimizedNodeCount": self.optimized_node_count,
            "replacementCount": len(self.replacements),
            "replacements": [replacement.to_payload() for replacement in self.replacements],
        }
        if self.error is not None:
            payload["error"] = self.error
        return payload
