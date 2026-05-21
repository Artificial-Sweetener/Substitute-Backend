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
"""Tests for model catalog assembly."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import cast

from substitute_backend.api.serialization import JsonObject
from substitute_backend.features.model_metadata.application.catalog_service import (
    CatalogQuery,
    CatalogService,
)
from substitute_backend.features.model_metadata.infrastructure.comfy_model_roots import (
    StaticModelRootsProvider,
)
from substitute_backend.features.model_metadata.infrastructure.fingerprint_cache import (
    FingerprintCache,
)
from substitute_backend.features.model_metadata.infrastructure.preview_store import (
    PreviewStore,
)
from substitute_backend.features.model_metadata.infrastructure.sidecar_reader import (
    SidecarReader,
)
from substitute_backend.infrastructure.logging import get_logger


def test_catalog_returns_safe_model_evidence_without_inline_hashing(
    tmp_path: Path,
) -> None:
    """Catalog entries expose safe local evidence and no absolute paths."""

    model_root = tmp_path / "models" / "loras"
    model_root.mkdir(parents=True)
    model_path = model_root / "characters" / "example_lora.safetensors"
    model_path.parent.mkdir()
    model_path.write_bytes(b"not a real safetensors file")
    model_path.with_suffix(".json").write_text(
        json.dumps(
            {
                "modelId": 123,
                "modelVersionId": 456,
                "sha256": "abc123",
                "activation text": "trigger, second",
                "description": "Local description",
                "sd version": "SDXL",
            }
        ),
        encoding="utf-8",
    )
    model_path.with_suffix(".preview.png").write_bytes(b"fake image")
    provider = StaticModelRootsProvider({"loras": (model_root,)}, {".safetensors"})
    service = CatalogService(
        model_roots=provider,
        fingerprint_cache=FingerprintCache(tmp_path / "cache.sqlite3"),
        sidecar_reader=SidecarReader(),
        preview_store=PreviewStore(provider.approved_roots()),
        logger=get_logger("test.catalog"),
    )

    entries = service.list_models(CatalogQuery(kinds=("loras",)))

    assert len(entries) == 1
    payload = entries[0].to_payload()
    source = cast("JsonObject", payload["source"])
    fingerprint = cast("JsonObject", payload["fingerprint"])
    sidecar = cast("JsonObject", payload["sidecar"])
    local_preview = cast("JsonObject", payload["localPreview"])
    assert payload["kind"] == "loras"
    assert str(payload["value"]).endswith("example_lora.safetensors")
    assert source["rootId"] == "loras:0"
    assert source["relativePath"] == "characters/example_lora.safetensors"
    assert "models" not in source
    assert fingerprint["status"] == "ready"
    assert fingerprint["sha256"] == "ABC123"
    assert sidecar["modelId"] == 123
    assert sidecar["activationText"] == "trigger, second"
    assert local_preview["available"] is True
    assert "/substitute/v1/previews/" in str(local_preview["url"])


def test_malformed_sidecar_becomes_structured_warning(tmp_path: Path) -> None:
    """Sidecar parse failures are returned per entry instead of breaking catalog."""

    model_root = tmp_path / "models" / "loras"
    model_root.mkdir(parents=True)
    model_path = model_root / "broken.safetensors"
    model_path.write_bytes(b"model")
    model_path.with_suffix(".json").write_text("{bad json", encoding="utf-8")
    provider = StaticModelRootsProvider({"loras": (model_root,)}, {".safetensors"})
    service = CatalogService(
        model_roots=provider,
        fingerprint_cache=FingerprintCache(tmp_path / "cache.sqlite3"),
        sidecar_reader=SidecarReader(),
        preview_store=PreviewStore(provider.approved_roots()),
        logger=get_logger("test.catalog"),
    )

    payload = service.list_models(CatalogQuery(kinds=("loras",)))[0].to_payload()
    sidecar = cast("JsonObject", payload["sidecar"])
    warnings = cast("list[JsonObject]", payload["warnings"])

    assert sidecar["found"] is False
    assert warnings == [
        {
            "code": "sidecar-parse-failed",
            "message": warnings[0]["message"],
        }
    ]


def test_sidecar_hash_is_stale_when_model_is_newer(tmp_path: Path) -> None:
    """Sidecar SHA256 evidence is marked stale when the model changed later."""
    model_root = tmp_path / "models" / "loras"
    model_root.mkdir(parents=True)
    model_path = model_root / "changed.safetensors"
    model_path.write_bytes(b"model")
    sidecar_path = model_path.with_suffix(".json")
    sidecar_path.write_text(json.dumps({"sha256": "abc123"}), encoding="utf-8")
    os.utime(sidecar_path, (1, 1))
    os.utime(model_path, (2, 2))
    provider = StaticModelRootsProvider({"loras": (model_root,)}, {".safetensors"})
    service = CatalogService(
        model_roots=provider,
        fingerprint_cache=FingerprintCache(tmp_path / "cache.sqlite3"),
        sidecar_reader=SidecarReader(),
        preview_store=PreviewStore(provider.approved_roots()),
        logger=get_logger("test.catalog"),
    )

    payload = service.list_models(CatalogQuery(kinds=("loras",)))[0].to_payload()
    fingerprint = cast("JsonObject", payload["fingerprint"])

    assert fingerprint["status"] == "stale"
    assert fingerprint["sha256"] == "ABC123"
