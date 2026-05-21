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
"""Tests for fingerprint caching and preview serving safety."""

from __future__ import annotations

from collections.abc import Iterator
from hashlib import sha256
from pathlib import Path
from threading import Event
from time import sleep

import pytest

from substitute_backend.features.model_metadata.application.fingerprint_service import (
    FingerprintRefreshEntry,
    FingerprintService,
)
from substitute_backend.features.model_metadata.application.hash_lookup_service import (
    HashLookupQuery,
    HashLookupService,
)
from substitute_backend.features.model_metadata.application.model_download_service import (
    CivitaiModelDownloadRequest,
    ModelDownloadService,
)
from substitute_backend.features.model_metadata.application.preview_service import (
    PreviewService,
)
from substitute_backend.features.model_metadata.domain.catalog import ModelFile
from substitute_backend.features.model_metadata.domain.downloads import (
    ModelDownloadJob,
    ModelDownloadStatus,
)
from substitute_backend.features.model_metadata.domain.statuses import HashLookupStatus
from substitute_backend.features.model_metadata.infrastructure.comfy_model_roots import (
    StaticModelRootsProvider,
)
from substitute_backend.features.model_metadata.infrastructure.fingerprint_cache import (
    FileFreshness,
    FingerprintCache,
)
from substitute_backend.features.model_metadata.infrastructure.fingerprint_worker import (
    FingerprintWorker,
)
from substitute_backend.features.model_metadata.infrastructure.preview_store import (
    PreviewStore,
)
from substitute_backend.features.model_metadata.infrastructure.sidecar_reader import (
    SidecarReader,
)
from substitute_backend.features.model_metadata.infrastructure.time_utils import (
    format_timestamp,
)
from substitute_backend.infrastructure.logging import get_logger


def test_fingerprint_refresh_computes_sha256_in_background(tmp_path: Path) -> None:
    """Fingerprint refresh jobs compute and cache SHA256 values."""

    model_root = tmp_path / "loras"
    model_root.mkdir()
    model_path = model_root / "example.safetensors"
    model_path.write_bytes(b"model bytes")
    provider = StaticModelRootsProvider({"loras": (model_root,)}, {".safetensors"})
    cache = FingerprintCache(tmp_path / "cache.sqlite3")
    worker = FingerprintWorker(cache)
    service = FingerprintService(provider, cache, worker)

    job = service.refresh((FingerprintRefreshEntry(kind="loras", value="example.safetensors"),))
    completed = None
    for _ in range(50):
        completed = service.get_job(job.job_id)
        if completed is not None and completed.status.value in {"complete", "failed"}:
            break
        sleep(0.02)
    worker.shutdown()

    assert completed is not None
    assert completed.status.value == "complete"
    assert completed.entries[0].sha256 is not None
    assert len(completed.entries[0].sha256) == 64


def test_fingerprint_refresh_rejects_stale_request(tmp_path: Path) -> None:
    """Fingerprint refresh rejects entries whose freshness no longer matches."""

    model_root = tmp_path / "loras"
    model_root.mkdir()
    model_path = model_root / "example.safetensors"
    model_path.write_bytes(b"model bytes")
    provider = StaticModelRootsProvider({"loras": (model_root,)}, {".safetensors"})
    service = FingerprintService(
        provider,
        FingerprintCache(tmp_path / "cache.sqlite3"),
        FingerprintWorker(FingerprintCache(tmp_path / "cache.sqlite3")),
    )

    job = service.refresh(
        (
            FingerprintRefreshEntry(
                kind="loras",
                value="example.safetensors",
                size_bytes=999,
                modified_at=format_timestamp(model_path.stat().st_mtime),
            ),
        )
    )

    assert job.job_id == "no-work"
    assert job.status.value == "complete"


def test_hash_lookup_returns_sidecar_match_without_hashing(tmp_path: Path) -> None:
    """Hash lookup can use fresh sidecar SHA256 evidence immediately."""

    model_root = tmp_path / "loras"
    model_root.mkdir()
    model_path = model_root / "example.safetensors"
    model_path.write_bytes(b"model bytes")
    expected_hash = sha256(b"model bytes").hexdigest().upper()
    (model_root / "example.json").write_text(
        f'{{"sha256": "{expected_hash}"}}',
        encoding="utf-8",
    )
    service, worker = _hash_lookup_service(tmp_path, model_root)

    result = service.lookup(HashLookupQuery(kind="loras", sha256=expected_hash.lower()))
    worker.shutdown()

    assert result.status is HashLookupStatus.COMPLETE
    assert result.matches[0].value == "example.safetensors"
    assert result.matches[0].source.relative_path == "example.safetensors"


def test_hash_lookup_queues_hashing_for_unhashed_candidates(tmp_path: Path) -> None:
    """Hash lookup queues background hashing instead of hashing inline."""

    model_root = tmp_path / "loras"
    model_root.mkdir()
    (model_root / "example.safetensors").write_bytes(b"model bytes")
    service, worker = _hash_lookup_service(tmp_path, model_root)

    result = service.lookup(HashLookupQuery(kind="loras", sha256="A" * 64))
    worker.shutdown()

    assert result.status is HashLookupStatus.HASHING_REQUIRED
    assert result.job_id is not None
    assert result.matches == ()


def test_hash_lookup_returns_not_found_after_cached_nonmatch(tmp_path: Path) -> None:
    """Hash lookup avoids CivitAI fallback only after all local candidates are hashed."""

    model_root = tmp_path / "loras"
    model_root.mkdir()
    model_path = model_root / "example.safetensors"
    model_path.write_bytes(b"model bytes")
    provider = StaticModelRootsProvider({"loras": (model_root,)}, {".safetensors"})
    cache = FingerprintCache(tmp_path / "cache.sqlite3")
    model_file = provider.resolve_model_file("loras", "example.safetensors")
    assert model_file is not None
    cache.store_sha256(
        freshness=cache_freshness(model_file),
        sha256=sha256(b"model bytes").hexdigest().upper(),
        computed_at="2026-01-01T00:00:00Z",
    )
    worker = FingerprintWorker(cache)
    fingerprints = FingerprintService(provider, cache, worker)
    service = HashLookupService(
        model_roots=provider,
        fingerprint_cache=cache,
        sidecar_reader=SidecarReader(),
        fingerprints=fingerprints,
        logger=get_logger("tests.hash_lookup"),
    )

    result = service.lookup(HashLookupQuery(kind="loras", sha256="B" * 64))
    worker.shutdown()

    assert result.status is HashLookupStatus.NOT_FOUND
    assert result.matches == ()


def test_preview_store_uses_opaque_ids_and_fails_closed(tmp_path: Path) -> None:
    """Preview IDs are opaque and invalidated when the file changes."""

    model_root = tmp_path / "loras"
    model_root.mkdir()
    model_path = model_root / "example.safetensors"
    preview_path = model_root / "example.preview.png"
    model_path.write_bytes(b"model")
    preview_path.write_bytes(b"preview")
    provider = StaticModelRootsProvider({"loras": (model_root,)}, {".safetensors"})
    model_file = provider.resolve_model_file("loras", "example.safetensors")
    assert model_file is not None
    store = PreviewStore(provider.approved_roots())
    service = PreviewService(store)

    reference = store.discover(model_file)
    assert reference.preview_id is not None
    assert "example" not in reference.preview_id
    assert service.resolve(reference.preview_id) is not None

    preview_path.write_bytes(b"changed preview")

    assert service.resolve(reference.preview_id) is None


def test_model_download_verifies_hash_and_finalizes_in_model_root(tmp_path: Path) -> None:
    """Backend model downloads should finalize only verified model bytes."""

    model_root = tmp_path / "checkpoints"
    payload = b"downloaded model"
    expected_hash = sha256(payload).hexdigest().upper()
    provider = StaticModelRootsProvider({"checkpoints": (model_root,)}, {".safetensors"})
    service = ModelDownloadService(
        model_roots=provider,
        http_get=lambda *_args, **_kwargs: _FakeDownloadResponse(payload),
    )

    job = service.start_civitai_download(
        CivitaiModelDownloadRequest(
            kind="checkpoints",
            sha256=expected_hash,
            download_url="https://civitai.com/api/download/models/123",
            file_name="model.safetensors",
            file_type="Model",
            metadata_format="SafeTensor",
            pickle_scan_result="Success",
            virus_scan_result="Success",
        )
    )
    completed = None
    for _ in range(50):
        completed = service.get_job(job.job_id)
        if completed is not None and completed.status is ModelDownloadStatus.COMPLETE:
            break
        sleep(0.02)

    assert completed is not None
    assert completed.status is ModelDownloadStatus.COMPLETE
    assert completed.result is not None
    assert completed.result.value == "model.safetensors"
    assert (model_root / "model.safetensors").read_bytes() == payload


def test_model_download_prefers_root_named_for_comfy_kind(tmp_path: Path) -> None:
    """Downloads should avoid legacy alias roots when a canonical kind root exists."""

    legacy_root = tmp_path / "unet"
    kind_root = tmp_path / "diffusion_models"
    payload = b"downloaded model"
    expected_hash = sha256(payload).hexdigest().upper()
    provider = StaticModelRootsProvider(
        {"diffusion_models": (legacy_root, kind_root)},
        {".safetensors"},
    )
    service = ModelDownloadService(
        model_roots=provider,
        http_get=lambda *_args, **_kwargs: _FakeDownloadResponse(payload),
    )

    job = service.start_civitai_download(
        CivitaiModelDownloadRequest(
            kind="diffusion_models",
            sha256=expected_hash,
            download_url="https://civitai.com/api/download/models/123",
            file_name="model.safetensors",
            file_type="Model",
            metadata_format="SafeTensor",
            pickle_scan_result="Success",
            virus_scan_result="Success",
        )
    )
    completed = None
    for _ in range(50):
        completed = service.get_job(job.job_id)
        if completed is not None and completed.status is ModelDownloadStatus.COMPLETE:
            break
        sleep(0.02)

    assert completed is not None
    assert completed.result is not None
    assert completed.result.root_id == "diffusion_models:1"
    assert not (legacy_root / "model.safetensors").exists()
    assert (kind_root / "model.safetensors").read_bytes() == payload


def test_model_download_renders_relative_path_pattern(tmp_path: Path) -> None:
    """Downloads should render configured paths under the selected model root."""

    model_root = tmp_path / "diffusion_models"
    payload = b"downloaded model"
    expected_hash = sha256(payload).hexdigest().upper()
    provider = StaticModelRootsProvider(
        {"diffusion_models": (model_root,)},
        {".safetensors"},
    )
    service = ModelDownloadService(
        model_roots=provider,
        http_get=lambda *_args, **_kwargs: _FakeDownloadResponse(payload),
    )

    job = service.start_civitai_download(
        CivitaiModelDownloadRequest(
            kind="diffusion_models",
            sha256=expected_hash,
            download_url="https://civitai.com/api/download/models/123",
            file_name="anima_baseV10.safetensors",
            file_type="Model",
            metadata_format="SafeTensor",
            pickle_scan_result="Success",
            virus_scan_result="Success",
            download_path_pattern="{base_model}\\{file_name}",
            download_path_tokens={
                "baseModel": "Anima",
                "modelName": "Anima",
                "versionName": "base-v1.0",
                "creator": "creator",
                "fileName": "anima_baseV10.safetensors",
            },
        )
    )
    completed = _wait_for_download(service, job.job_id, ModelDownloadStatus.COMPLETE)

    assert completed is not None
    assert completed.result is not None
    assert completed.result.value == str(Path("Anima") / "anima_baseV10.safetensors")
    assert completed.result.relative_path == "Anima/anima_baseV10.safetensors"
    assert (model_root / "Anima" / "anima_baseV10.safetensors").read_bytes() == payload


def test_model_download_path_pattern_rejects_unsafe_paths(tmp_path: Path) -> None:
    """Backend path rendering should fail closed for unsafe patterns."""

    model_root = tmp_path / "loras"
    provider = StaticModelRootsProvider({"loras": (model_root,)}, {".safetensors"})
    service = ModelDownloadService(model_roots=provider)
    request = CivitaiModelDownloadRequest(
        kind="loras",
        sha256="A" * 64,
        download_url="https://civitai.com/api/download/models/123",
        file_name="lora.safetensors",
        file_type="Model",
        metadata_format="SafeTensor",
        pickle_scan_result="Success",
        virus_scan_result="Success",
        download_path_pattern="{model_type}\\{file_name}",
    )

    with pytest.raises(ValueError, match="Unknown"):
        service.start_civitai_download(request)

    with pytest.raises(ValueError, match="traversal"):
        service.start_civitai_download(
            CivitaiModelDownloadRequest(
                kind="loras",
                sha256="A" * 64,
                download_url="https://civitai.com/api/download/models/123",
                file_name="lora.safetensors",
                file_type="Model",
                metadata_format="SafeTensor",
                pickle_scan_result="Success",
                virus_scan_result="Success",
                download_path_pattern="..\\{file_name}",
            )
        )


def test_model_download_path_sanitizes_tokens_and_keeps_file_name_single_component(
    tmp_path: Path,
) -> None:
    """Token values and file names should not create unintended path segments."""

    model_root = tmp_path / "loras"
    payload = b"downloaded model"
    expected_hash = sha256(payload).hexdigest().upper()
    provider = StaticModelRootsProvider({"loras": (model_root,)}, {".safetensors"})
    service = ModelDownloadService(
        model_roots=provider,
        http_get=lambda *_args, **_kwargs: _FakeDownloadResponse(payload),
    )

    job = service.start_civitai_download(
        CivitaiModelDownloadRequest(
            kind="loras",
            sha256=expected_hash,
            download_url="https://civitai.com/api/download/models/123",
            file_name="lora.safetensors",
            file_type="Model",
            metadata_format="SafeTensor",
            pickle_scan_result="Success",
            virus_scan_result="Success",
            download_path_pattern="{creator}\\{model_name}\\{file_name}",
            download_path_tokens={
                "baseModel": "SDXL 1.0",
                "modelName": "Bad:Model/Name",
                "creator": "Creator<Name>",
                "fileName": "..\\lora:name.safetensors",
            },
        )
    )
    completed = _wait_for_download(service, job.job_id, ModelDownloadStatus.COMPLETE)

    assert completed is not None
    assert completed.result is not None
    assert completed.result.relative_path == ("Creator_Name/Bad_Model_Name/lora_name.safetensors")
    assert (model_root / "Creator_Name" / "Bad_Model_Name" / "lora_name.safetensors").exists()


def test_model_download_removes_temp_file_after_hash_mismatch(tmp_path: Path) -> None:
    """Failed downloads should not leave finalized model files behind."""

    model_root = tmp_path / "loras"
    provider = StaticModelRootsProvider({"loras": (model_root,)}, {".safetensors"})
    service = ModelDownloadService(
        model_roots=provider,
        http_get=lambda *_args, **_kwargs: _FakeDownloadResponse(b"wrong"),
    )

    job = service.start_civitai_download(
        CivitaiModelDownloadRequest(
            kind="loras",
            sha256="A" * 64,
            download_url="https://civitai.com/api/download/models/123",
            file_name="lora.safetensors",
            file_type="Model",
            metadata_format="SafeTensor",
            pickle_scan_result="Success",
            virus_scan_result="Success",
        )
    )
    completed = None
    for _ in range(50):
        completed = service.get_job(job.job_id)
        if completed is not None and completed.status is ModelDownloadStatus.FAILED:
            break
        sleep(0.02)

    assert completed is not None
    assert completed.status is ModelDownloadStatus.FAILED
    assert not (model_root / "lora.safetensors").exists()
    assert tuple(model_root.glob("*.tmp")) == ()


def test_model_download_rejects_unsafe_civitai_metadata(tmp_path: Path) -> None:
    """Direct backend callers must provide safe CivitAI file metadata."""

    model_root = tmp_path / "loras"
    provider = StaticModelRootsProvider({"loras": (model_root,)}, {".safetensors"})
    service = ModelDownloadService(model_roots=provider)

    with pytest.raises(ValueError, match="pickle scan"):
        service.start_civitai_download(
            CivitaiModelDownloadRequest(
                kind="loras",
                sha256="A" * 64,
                download_url="https://civitai.com/api/download/models/123",
                file_name="lora.safetensors",
                file_type="Model",
                metadata_format="SafeTensor",
                pickle_scan_result="",
                virus_scan_result="Success",
            )
        )


def test_model_download_stores_verified_hash_in_fingerprint_cache(tmp_path: Path) -> None:
    """Successful downloads should seed backend fingerprint evidence."""

    model_root = tmp_path / "checkpoints"
    payload = b"downloaded model"
    expected_hash = sha256(payload).hexdigest().upper()
    provider = StaticModelRootsProvider({"checkpoints": (model_root,)}, {".safetensors"})
    cache = FingerprintCache(tmp_path / "cache.sqlite3")
    service = ModelDownloadService(
        model_roots=provider,
        fingerprint_cache=cache,
        http_get=lambda *_args, **_kwargs: _FakeDownloadResponse(payload),
    )

    job = service.start_civitai_download(
        CivitaiModelDownloadRequest(
            kind="checkpoints",
            sha256=expected_hash,
            download_url="https://civitai.com/api/download/models/123",
            file_name="model.safetensors",
            file_type="Model",
            metadata_format="SafeTensor",
            pickle_scan_result="Success",
            virus_scan_result="Success",
        )
    )
    completed = None
    for _ in range(50):
        completed = service.get_job(job.job_id)
        if completed is not None and completed.status is ModelDownloadStatus.COMPLETE:
            break
        sleep(0.02)

    assert completed is not None
    assert completed.result is not None
    fingerprint = cache.get_sha256(
        FileFreshness(
            root_id=completed.result.root_id,
            relative_path=completed.result.relative_path,
            size_bytes=completed.result.size_bytes,
            modified_at=completed.result.modified_at,
        )
    )
    assert fingerprint.sha256 == expected_hash


def test_model_download_reports_byte_progress(tmp_path: Path) -> None:
    """Download jobs should expose byte counts while streaming model files."""

    model_root = tmp_path / "checkpoints"
    payload = b"downloaded model"
    expected_hash = sha256(payload).hexdigest().upper()
    provider = StaticModelRootsProvider({"checkpoints": (model_root,)}, {".safetensors"})
    service = ModelDownloadService(
        model_roots=provider,
        http_get=lambda *_args, **_kwargs: _FakeDownloadResponse(
            payload,
            chunk_size=4,
        ),
    )

    job = service.start_civitai_download(
        CivitaiModelDownloadRequest(
            kind="checkpoints",
            sha256=expected_hash,
            download_url="https://civitai.com/api/download/models/123",
            file_name="model.safetensors",
            file_type="Model",
            metadata_format="SafeTensor",
            pickle_scan_result="Success",
            virus_scan_result="Success",
        )
    )

    completed = None
    for _ in range(50):
        completed = service.get_job(job.job_id)
        if completed is not None and completed.status is ModelDownloadStatus.COMPLETE:
            break
        sleep(0.02)

    assert completed is not None
    assert completed.status is ModelDownloadStatus.COMPLETE
    assert completed.bytes_downloaded == len(payload)
    assert completed.bytes_total == len(payload)


def test_model_download_progress_reports_exact_destination(tmp_path: Path) -> None:
    """Running download jobs should expose the resolved destination path."""

    model_root = tmp_path / "checkpoints"
    payload = b"downloaded model"
    expected_hash = sha256(payload).hexdigest().upper()
    first_chunk_written = Event()
    provider = StaticModelRootsProvider({"checkpoints": (model_root,)}, {".safetensors"})
    service = ModelDownloadService(
        model_roots=provider,
        http_get=lambda *_args, **_kwargs: _FakeDownloadResponse(
            payload,
            chunk_size=4,
            delay_seconds=0.05,
            first_chunk_written=first_chunk_written,
        ),
    )

    job = service.start_civitai_download(
        CivitaiModelDownloadRequest(
            kind="checkpoints",
            sha256=expected_hash,
            download_url="https://civitai.com/api/download/models/123",
            file_name="model.safetensors",
            file_type="Model",
            metadata_format="SafeTensor",
            pickle_scan_result="Success",
            virus_scan_result="Success",
        )
    )

    assert first_chunk_written.wait(timeout=2.0)
    running = service.get_job(job.job_id)

    assert running is not None
    assert running.status is ModelDownloadStatus.RUNNING
    assert running.detail == f"Saving to {(model_root / 'model.safetensors').resolve()}"


def test_model_download_cancel_removes_temp_file(tmp_path: Path) -> None:
    """Cancelled downloads should stop streaming and remove temporary bytes."""

    model_root = tmp_path / "checkpoints"
    payload = b"a" * (1024 * 1024 * 2)
    expected_hash = sha256(payload).hexdigest().upper()
    first_chunk_written = Event()
    provider = StaticModelRootsProvider({"checkpoints": (model_root,)}, {".safetensors"})
    service = ModelDownloadService(
        model_roots=provider,
        http_get=lambda *_args, **_kwargs: _FakeDownloadResponse(
            payload,
            chunk_size=1024,
            delay_seconds=0.01,
            first_chunk_written=first_chunk_written,
        ),
    )

    job = service.start_civitai_download(
        CivitaiModelDownloadRequest(
            kind="checkpoints",
            sha256=expected_hash,
            download_url="https://civitai.com/api/download/models/123",
            file_name="model.safetensors",
            file_type="Model",
            metadata_format="SafeTensor",
            pickle_scan_result="Success",
            virus_scan_result="Success",
        )
    )

    assert first_chunk_written.wait(timeout=1.0)
    cancelled = service.cancel_download(job.job_id)
    assert cancelled is not None
    completed = None
    for _ in range(50):
        completed = service.get_job(job.job_id)
        if completed is not None and completed.status is ModelDownloadStatus.CANCELLED:
            break
        sleep(0.02)

    assert completed is not None
    assert completed.status is ModelDownloadStatus.CANCELLED
    for _ in range(50):
        if not tuple(model_root.glob("*.tmp")):
            break
        sleep(0.02)
    assert not (model_root / "model.safetensors").exists()
    assert tuple(model_root.glob("*.tmp")) == ()


def _hash_lookup_service(
    tmp_path: Path,
    model_root: Path,
) -> tuple[HashLookupService, FingerprintWorker]:
    """Build hash lookup dependencies for tests."""

    provider = StaticModelRootsProvider({"loras": (model_root,)}, {".safetensors"})
    cache = FingerprintCache(tmp_path / "cache.sqlite3")
    worker = FingerprintWorker(cache)
    fingerprints = FingerprintService(provider, cache, worker)
    return (
        HashLookupService(
            model_roots=provider,
            fingerprint_cache=cache,
            sidecar_reader=SidecarReader(),
            fingerprints=fingerprints,
            logger=get_logger("tests.hash_lookup"),
        ),
        worker,
    )


def cache_freshness(model_file: ModelFile) -> FileFreshness:
    """Return freshness for a test model file without exposing production internals."""

    stat = model_file.path.stat()
    return FileFreshness(
        root_id=model_file.root_id,
        relative_path=model_file.relative_path,
        size_bytes=stat.st_size,
        modified_at=format_timestamp(stat.st_mtime),
    )


def _wait_for_download(
    service: ModelDownloadService,
    job_id: str,
    status: ModelDownloadStatus,
) -> ModelDownloadJob | None:
    """Wait briefly for a download job to reach one expected status."""

    completed = None
    for _ in range(50):
        completed = service.get_job(job_id)
        if completed is not None and completed.status is status:
            break
        sleep(0.02)
    return completed


class _FakeDownloadResponse:
    """Provide the streaming response surface used by model downloads."""

    def __init__(
        self,
        payload: bytes,
        *,
        chunk_size: int | None = None,
        delay_seconds: float = 0.0,
        first_chunk_written: Event | None = None,
    ) -> None:
        """Store response bytes."""

        self._payload = payload
        self._chunk_size = chunk_size
        self._delay_seconds = delay_seconds
        self._first_chunk_written = first_chunk_written
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self) -> _FakeDownloadResponse:
        """Return this response for context-manager use."""

        return self

    def __exit__(self, *_args: object) -> None:
        """Close nothing for the fake response."""

    def raise_for_status(self) -> None:
        """Accept the fake response."""

    def iter_content(self, *, chunk_size: int) -> Iterator[bytes]:
        """Return response bytes as one or more chunks."""

        effective_chunk_size = self._chunk_size or chunk_size
        for index in range(0, len(self._payload), effective_chunk_size):
            if self._delay_seconds:
                sleep(self._delay_seconds)
            if index == 0 and self._first_chunk_written is not None:
                self._first_chunk_written.set()
            yield self._payload[index : index + effective_chunk_size]
