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
"""Cache model-folder to node-class dependencies for targeted refreshes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from threading import RLock


class NodeModelDependencyIndex:
    """Serve affected node classes from a cached model dependency mapping."""

    def __init__(self, dependencies: Mapping[str, Iterable[str]] | None = None) -> None:
        """Initialize the index with optional precomputed dependencies."""

        self._dependencies: dict[str, tuple[str, ...]] = {}
        self._lock = RLock()
        if dependencies is not None:
            self.install(dependencies)

    def install(self, dependencies: Mapping[str, Iterable[str]]) -> None:
        """Replace the dependency mapping with normalized sorted values."""

        normalized = {
            kind: tuple(sorted({node for node in nodes if node.strip()}))
            for kind, nodes in dependencies.items()
            if kind.strip()
        }
        with self._lock:
            self._dependencies = normalized

    def affected_node_classes(self, kinds: Iterable[str]) -> tuple[str, ...]:
        """Return node classes whose list choices depend on any changed kind."""

        selected = tuple(dict.fromkeys(kind.strip() for kind in kinds if kind.strip()))
        affected: set[str] = set()
        with self._lock:
            for kind in selected:
                affected.update(self._dependencies.get(kind, ()))
        return tuple(sorted(affected))


__all__ = ["NodeModelDependencyIndex"]
