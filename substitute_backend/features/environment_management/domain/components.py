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
"""UI-friendly component models for installed Python packages."""

from __future__ import annotations

from dataclasses import dataclass

from substitute_backend.api.serialization import JsonObject


@dataclass(frozen=True)
class EnvironmentComponent:
    """Describe one installed environment component for graphical display."""

    component_id: str
    display_name: str
    kind: str
    status: str
    packages: tuple[str, ...]
    summary: str | None = None
    installed_version: str | None = None
    available_version: str | None = None
    actions: tuple[str, ...] = ()

    def to_payload(self) -> JsonObject:
        """Return the environment component payload."""

        payload: JsonObject = {
            "id": self.component_id,
            "displayName": self.display_name,
            "kind": self.kind,
            "status": self.status,
            "packages": list(self.packages),
            "actions": list(self.actions),
        }
        if self.summary is not None:
            payload["summary"] = self.summary
        if self.installed_version is not None:
            payload["installedVersion"] = self.installed_version
        if self.available_version is not None:
            payload["availableVersion"] = self.available_version
        return payload
