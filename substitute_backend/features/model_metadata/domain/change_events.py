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
"""Public contracts for Comfy-visible model catalog change events."""

from __future__ import annotations

from dataclasses import dataclass

from substitute_backend.api.serialization import JsonObject

EVENT_TYPE = "substitute_model_catalog_changed"
MODEL_CATALOG_CHANGE_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ModelFileIdentity:
    """Identify one Comfy-visible model without exposing absolute paths."""

    kind: str
    value: str
    root_id: str
    relative_path: str

    def stable_key(self) -> tuple[str, str, str]:
        """Return the stable key used for add/remove/modify comparisons."""

        return self.kind, self.root_id, self.relative_path

    def to_payload(self) -> JsonObject:
        """Return the public source payload for this model."""

        return {
            "kind": self.kind,
            "value": self.value,
            "source": {
                "rootId": self.root_id,
                "relativePath": self.relative_path,
            },
        }


@dataclass(frozen=True, slots=True)
class ModelFileStatSnapshot:
    """Represent cheap file evidence used for change detection."""

    size_bytes: int
    modified_at: str

    def stable_key(self) -> tuple[int, str]:
        """Return the file stat key used for modified-in-place detection."""

        return self.size_bytes, self.modified_at

    def to_payload(self) -> JsonObject:
        """Return the public file stat payload."""

        return {
            "sizeBytes": self.size_bytes,
            "modifiedAt": self.modified_at,
        }


@dataclass(frozen=True, slots=True)
class ModelCatalogChangedEntry:
    """Describe one added, removed, or modified model file."""

    identity: ModelFileIdentity
    file: ModelFileStatSnapshot

    @property
    def kind(self) -> str:
        """Return the model kind for grouping and filtering."""

        return self.identity.kind

    @property
    def value(self) -> str:
        """Return the Comfy-visible model value."""

        return self.identity.value

    def stable_key(self) -> tuple[str, str, str]:
        """Return the identity key used for catalog diffing."""

        return self.identity.stable_key()

    def to_payload(self) -> JsonObject:
        """Return the public changed-entry payload."""

        payload = self.identity.to_payload()
        payload["file"] = self.file.to_payload()
        return payload


@dataclass(frozen=True, slots=True)
class ModelCatalogChangeSet:
    """Describe one coalesced model catalog change notification."""

    revision: str
    previous_revision: str
    generated_at: str
    kinds: tuple[str, ...]
    added: tuple[ModelCatalogChangedEntry, ...]
    removed: tuple[ModelCatalogChangedEntry, ...]
    modified: tuple[ModelCatalogChangedEntry, ...]
    affected_node_classes: tuple[str, ...]
    reason: str
    schema_version: int = MODEL_CATALOG_CHANGE_SCHEMA_VERSION

    def to_payload(self) -> JsonObject:
        """Return the versioned public websocket and route payload."""

        return {
            "schemaVersion": self.schema_version,
            "revision": self.revision,
            "previousRevision": self.previous_revision,
            "generatedAt": self.generated_at,
            "reason": self.reason,
            "kinds": list(self.kinds),
            "affectedNodeClasses": list(self.affected_node_classes),
            "added": [entry.to_payload() for entry in self.added],
            "removed": [entry.to_payload() for entry in self.removed],
            "modified": [entry.to_payload() for entry in self.modified],
        }


__all__ = [
    "EVENT_TYPE",
    "MODEL_CATALOG_CHANGE_SCHEMA_VERSION",
    "ModelCatalogChangeSet",
    "ModelCatalogChangedEntry",
    "ModelFileIdentity",
    "ModelFileStatSnapshot",
]
