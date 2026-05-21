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
"""In-memory store for the active environment maintenance plan."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import count

from substitute_backend.features.environment_management.domain.maintenance_plan import (
    MaintenancePlanItem,
)


@dataclass(frozen=True)
class MaintenancePlanRecord:
    """Store the mutable core of the active maintenance plan."""

    plan_id: str
    environment_id: str
    revision: int
    items: tuple[MaintenancePlanItem, ...]


class MaintenancePlanStore:
    """Keep one editable maintenance queue for the running backend process."""

    def __init__(self, *, environment_id: str) -> None:
        """Initialize the plan store for one Comfy environment."""

        self._environment_id = environment_id
        self._record = MaintenancePlanRecord(
            plan_id="current",
            environment_id=environment_id,
            revision=0,
            items=(),
        )
        self._ids = count(1)

    def get(self) -> MaintenancePlanRecord:
        """Return the current maintenance-plan record."""

        return self._record

    def save(self, items: tuple[MaintenancePlanItem, ...]) -> MaintenancePlanRecord:
        """Persist replacement items and increment the plan revision."""

        self._record = MaintenancePlanRecord(
            plan_id=self._record.plan_id,
            environment_id=self._record.environment_id,
            revision=self._record.revision + 1,
            items=items,
        )
        return self._record

    def next_item_id(self) -> str:
        """Return a stable id for a new plan item."""

        return f"plan-item-{next(self._ids)}"

    def environment_id(self) -> str:
        """Return the environment identity this store belongs to."""

        return self._environment_id
