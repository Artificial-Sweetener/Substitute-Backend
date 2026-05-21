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
"""Queue and verify backend-owned CivitAI model downloads."""

from __future__ import annotations

import hashlib
import os
import re
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from substitute_backend.features.model_metadata.domain.downloads import (
    ModelDownloadJob,
    ModelDownloadResult,
    ModelDownloadStatus,
)
from substitute_backend.features.model_metadata.infrastructure.comfy_model_roots import (
    ModelRootsProvider,
)
from substitute_backend.features.model_metadata.infrastructure.fingerprint_cache import (
    FileFreshness,
    FingerprintCache,
)
from substitute_backend.features.model_metadata.infrastructure.time_utils import (
    format_timestamp,
    utc_now,
)

_SHA256_RE = re.compile(r"^[0-9A-Fa-f]{64}$")
_WINDOWS_RESERVED_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TOKEN_RE = re.compile(r"\{([^{}]+)\}")
_PATH_SEPARATOR_RE = re.compile(r"[\\/]+")
_SUPPORTED_DOWNLOAD_PATH_TOKEN_NAMES = frozenset(
    {"base_model", "model_name", "version_name", "creator", "file_name", "file_stem"}
)
_CHUNK_SIZE = 1024 * 1024
HttpGet = Callable[..., Any]


class ModelDownloadCancelled(RuntimeError):
    """Raised when a queued backend model download is cancelled by the caller."""


@dataclass(frozen=True)
class CivitaiModelDownloadRequest:
    """Describe one verified model download request from SugarSubstitute."""

    kind: str
    sha256: str
    download_url: str
    file_name: str
    file_type: str
    metadata_format: str
    pickle_scan_result: str
    virus_scan_result: str
    download_path_pattern: str = "{file_name}"
    download_path_tokens: Mapping[str, str] = field(default_factory=dict)
    api_key: str | None = None


class ModelDownloadService:
    """Own safe model downloads into approved Comfy model roots."""

    def __init__(
        self,
        *,
        model_roots: ModelRootsProvider,
        fingerprint_cache: FingerprintCache | None = None,
        http_get: HttpGet = requests.get,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Initialize model download dependencies."""

        self._model_roots = model_roots
        self._fingerprint_cache = fingerprint_cache
        self._http_get = http_get
        self._timeout_seconds = timeout_seconds
        self._jobs: dict[str, ModelDownloadJob] = {}
        self._cancelled_jobs: set[str] = set()
        self._lock = threading.Lock()

    def start_civitai_download(
        self,
        request: CivitaiModelDownloadRequest,
    ) -> ModelDownloadJob:
        """Queue a CivitAI download job and return its initial state."""

        normalized_hash = request.sha256.strip().upper()
        self._validate_request(request, normalized_hash)
        job_id = uuid.uuid4().hex
        initial = ModelDownloadJob(
            job_id=job_id,
            status=ModelDownloadStatus.QUEUED,
            kind=request.kind,
            sha256=normalized_hash,
        )
        self._store_job(initial)
        thread = threading.Thread(
            target=self._run_download,
            args=(job_id, request, normalized_hash),
            name=f"substitute-model-download-{job_id[:8]}",
            daemon=True,
        )
        thread.start()
        return initial

    def get_job(self, job_id: str) -> ModelDownloadJob | None:
        """Return the latest state for one download job."""

        with self._lock:
            return self._jobs.get(job_id)

    def cancel_download(self, job_id: str) -> ModelDownloadJob | None:
        """Request cancellation for one queued or running download job."""

        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status in {
                ModelDownloadStatus.COMPLETE,
                ModelDownloadStatus.FAILED,
                ModelDownloadStatus.CANCELLED,
            }:
                return job
            self._cancelled_jobs.add(job_id)
            cancelled = ModelDownloadJob(
                job_id=job.job_id,
                status=ModelDownloadStatus.CANCELLED,
                kind=job.kind,
                sha256=job.sha256,
                bytes_downloaded=job.bytes_downloaded,
                bytes_total=job.bytes_total,
                detail="Download cancelled.",
            )
            self._jobs[job_id] = cancelled
            return cancelled

    def _run_download(
        self,
        job_id: str,
        request: CivitaiModelDownloadRequest,
        normalized_hash: str,
    ) -> None:
        """Download, verify, and finalize one model file."""

        target_path: Path | None = None
        temp_path: Path | None = None
        try:
            root, root_id = self._select_target_root(request.kind)
            target_path = self._target_path(root, request, normalized_hash)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = target_path.with_name(f".{target_path.name}.{job_id}.tmp")
            self._raise_if_cancelled(job_id)
            self._store_job(
                ModelDownloadJob(
                    job_id=job_id,
                    status=ModelDownloadStatus.RUNNING,
                    kind=request.kind,
                    sha256=normalized_hash,
                    detail=_download_destination_detail(target_path),
                )
            )
            self._download_to_temp(
                job_id=job_id,
                kind=request.kind,
                sha256=normalized_hash,
                url=request.download_url,
                api_key=request.api_key,
                temp_path=temp_path,
                target_path=target_path,
            )
            self._raise_if_cancelled(job_id)
            actual_hash = self._sha256(temp_path)
            self._validate_downloaded_hash(actual_hash, normalized_hash)
            os.replace(temp_path, target_path)
            result = self._result_from_file(
                kind=request.kind,
                root_id=root_id,
                root=root,
                path=target_path,
                sha256=normalized_hash,
            )
            self._store_fingerprint(result)
            self._raise_if_cancelled(job_id)
            self._store_job(
                ModelDownloadJob(
                    job_id=job_id,
                    status=ModelDownloadStatus.COMPLETE,
                    kind=request.kind,
                    sha256=normalized_hash,
                    value=result.value,
                    result=result,
                    bytes_downloaded=result.size_bytes,
                    bytes_total=result.size_bytes,
                    detail="Download complete.",
                )
            )
        except ModelDownloadCancelled as error:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            self._store_job(
                ModelDownloadJob(
                    job_id=job_id,
                    status=ModelDownloadStatus.CANCELLED,
                    kind=request.kind,
                    sha256=normalized_hash,
                    error=str(error),
                    detail="Download cancelled.",
                )
            )
        except (OSError, RuntimeError, ValueError, requests.RequestException) as error:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            self._store_job(
                ModelDownloadJob(
                    job_id=job_id,
                    status=ModelDownloadStatus.FAILED,
                    kind=request.kind,
                    sha256=normalized_hash,
                    error=str(error),
                    detail="Download failed.",
                )
            )

    def _download_to_temp(
        self,
        *,
        job_id: str,
        kind: str,
        sha256: str,
        url: str,
        api_key: str | None,
        temp_path: Path,
        target_path: Path,
    ) -> None:
        """Stream a CivitAI model response into a temporary file."""

        headers = {"User-Agent": "SubstituteBackEnd/1.0"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        with self._http_get(
            url,
            headers=headers,
            timeout=self._timeout_seconds,
            stream=True,
        ) as response:
            response.raise_for_status()
            total_bytes = _content_length(response)
            downloaded_bytes = 0
            self._store_download_progress(
                job_id=job_id,
                kind=kind,
                sha256=sha256,
                bytes_downloaded=downloaded_bytes,
                bytes_total=total_bytes,
                target_path=target_path,
            )
            with temp_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
                    self._raise_if_cancelled(job_id)
                    if chunk:
                        handle.write(chunk)
                        downloaded_bytes += len(chunk)
                        self._store_download_progress(
                            job_id=job_id,
                            kind=kind,
                            sha256=sha256,
                            bytes_downloaded=downloaded_bytes,
                            bytes_total=total_bytes,
                            target_path=target_path,
                        )

    def _validate_request(
        self,
        request: CivitaiModelDownloadRequest,
        normalized_hash: str,
    ) -> None:
        """Validate request safety before a worker thread is started."""

        if not _SHA256_RE.fullmatch(normalized_hash):
            raise ValueError("sha256 must be 64 hexadecimal characters.")
        if request.kind not in self._model_roots.supported_kinds():
            raise ValueError("Unsupported model kind.")
        if not self._model_roots.roots_for_kind(request.kind):
            raise ValueError("No approved model root is configured for this kind.")
        if request.file_type.casefold() != "model":
            raise ValueError("CivitAI file type must be Model.")
        if request.metadata_format.casefold() != "safetensor":
            raise ValueError("CivitAI file format must be SafeTensor.")
        if request.pickle_scan_result.casefold() != "success":
            raise ValueError("CivitAI pickle scan must be successful.")
        if request.virus_scan_result.casefold() != "success":
            raise ValueError("CivitAI virus scan must be successful.")
        if Path(request.file_name).suffix.casefold() != ".safetensors":
            raise ValueError("CivitAI model filename must end with .safetensors.")
        _validate_download_path_pattern(request.download_path_pattern.strip() or "{file_name}")
        parsed = urlparse(request.download_url)
        if parsed.scheme != "https" or parsed.netloc.casefold() != "civitai.com":
            raise ValueError("CivitAI download URL must use https://civitai.com.")
        if not parsed.path.startswith("/api/download/models/"):
            raise ValueError("CivitAI download URL must target a model download.")

    def _select_target_root(self, kind: str) -> tuple[Path, str]:
        """Return the preferred approved root and its public root identifier."""

        roots = self._model_roots.roots_for_kind(kind)
        if not roots:
            raise ValueError("No approved model root is configured for this kind.")
        root_index, root = _preferred_download_root(kind=kind, roots=roots)
        root.mkdir(parents=True, exist_ok=True)
        return root, f"{kind}:{root_index}"

    def _target_path(
        self,
        root: Path,
        request: CivitaiModelDownloadRequest,
        sha256: str,
    ) -> Path:
        """Return a collision-resistant target path under an approved root."""

        relative_path = _render_download_relative_path(request, sha256)
        candidate = (root / relative_path).resolve()
        if not _is_under_root(candidate, root):
            raise ValueError("Download target escaped the approved model root.")
        if candidate.exists():
            stem = candidate.stem
            suffix = candidate.suffix
            candidate = candidate.with_name(f"{stem}-{sha256[:12]}{suffix}").resolve()
            if not _is_under_root(candidate, root):
                raise ValueError("Download target escaped the approved model root.")
        return candidate

    @staticmethod
    def _validate_downloaded_hash(actual_hash: str, expected_hash: str) -> None:
        """Raise when downloaded bytes do not match the recipe hash."""

        if actual_hash != expected_hash:
            raise ValueError("Downloaded model SHA256 did not match recipe hash.")

    @staticmethod
    def _sha256(path: Path) -> str:
        """Return the SHA256 hash for one downloaded file."""

        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
                digest.update(chunk)
        return digest.hexdigest().upper()

    @staticmethod
    def _result_from_file(
        *,
        kind: str,
        root_id: str,
        root: Path,
        path: Path,
        sha256: str,
    ) -> ModelDownloadResult:
        """Build a public result from the finalized downloaded file."""

        relative_path = path.relative_to(root).as_posix()
        stat = path.stat()
        return ModelDownloadResult(
            kind=kind,
            value=relative_path.replace("/", os.sep),
            display_name=path.stem,
            root_id=root_id,
            relative_path=relative_path,
            sha256=sha256,
            extension=path.suffix,
            size_bytes=stat.st_size,
            modified_at=format_timestamp(stat.st_mtime),
            created_at=format_timestamp(stat.st_ctime),
        )

    def _store_job(self, job: ModelDownloadJob) -> None:
        """Persist one in-memory job state."""

        with self._lock:
            current = self._jobs.get(job.job_id)
            if (
                current is not None
                and current.status is ModelDownloadStatus.CANCELLED
                and job.status is not ModelDownloadStatus.CANCELLED
            ):
                return
            self._jobs[job.job_id] = job

    def _store_download_progress(
        self,
        *,
        job_id: str,
        kind: str,
        sha256: str,
        bytes_downloaded: int,
        bytes_total: int | None,
        target_path: Path,
    ) -> None:
        """Persist the latest byte progress for one running download."""

        self._store_job(
            ModelDownloadJob(
                job_id=job_id,
                status=ModelDownloadStatus.RUNNING,
                kind=kind,
                sha256=sha256,
                bytes_downloaded=bytes_downloaded,
                bytes_total=bytes_total,
                detail=_download_destination_detail(target_path),
            )
        )

    def _raise_if_cancelled(self, job_id: str) -> None:
        """Raise when cancellation was requested for the current worker."""

        with self._lock:
            cancelled = job_id in self._cancelled_jobs
        if cancelled:
            raise ModelDownloadCancelled("Download cancelled.")

    def _store_fingerprint(self, result: ModelDownloadResult) -> None:
        """Store verified download hash evidence in the backend fingerprint cache."""

        if self._fingerprint_cache is None:
            return
        self._fingerprint_cache.store_sha256(
            freshness=FileFreshness(
                root_id=result.root_id,
                relative_path=result.relative_path,
                size_bytes=result.size_bytes,
                modified_at=result.modified_at,
            ),
            sha256=result.sha256,
            computed_at=utc_now(),
        )


def _safe_file_name(file_name: str, sha256: str) -> str:
    """Return a filesystem-safe single file name."""

    source_name = Path(file_name).name.strip()
    cleaned = _WINDOWS_RESERVED_CHARS.sub("_", source_name)
    if not cleaned or cleaned in {".", ".."}:
        return f"{sha256}.safetensors"
    if "." not in cleaned:
        return f"{cleaned}.safetensors"
    return cleaned


def _render_download_relative_path(
    request: CivitaiModelDownloadRequest,
    sha256: str,
) -> Path:
    """Render a safe relative download path from request token metadata."""

    pattern = request.download_path_pattern.strip() or "{file_name}"
    _validate_download_path_pattern(pattern)
    parts = tuple(part for part in _PATH_SEPARATOR_RE.split(pattern.rstrip("\\/")) if part)
    if not parts:
        raise ValueError("CivitAI download path pattern must include a file name.")
    values = _download_path_token_values(request, sha256)
    rendered_parts = tuple(
        _render_download_path_component(
            part,
            values=values,
            filename=index == len(parts) - 1,
        )
        for index, part in enumerate(parts)
    )
    if any(part in {"", ".", ".."} for part in rendered_parts):
        raise ValueError("CivitAI download path rendered an unsafe component.")
    relative_path = Path(*rendered_parts)
    if relative_path.is_absolute() or any(part in {".", ".."} for part in relative_path.parts):
        raise ValueError("CivitAI download path must be relative.")
    return relative_path


def _render_download_path_component(
    pattern: str,
    *,
    values: Mapping[str, str],
    filename: bool,
) -> str:
    """Render one sanitized download path component."""

    def replace(match: re.Match[str]) -> str:
        token_name = match.group(1)
        return _safe_component(values[token_name])

    rendered = _TOKEN_RE.sub(replace, pattern)
    sanitized = _safe_component(rendered)
    if filename and not Path(sanitized).suffix:
        suffix = Path(values["file_name"]).suffix
        if suffix:
            sanitized = f"{sanitized}{suffix}"
    return sanitized


def _validate_download_path_pattern(pattern: str) -> None:
    """Reject malformed, absolute, traversal, or unsupported path patterns."""

    if not pattern:
        raise ValueError("CivitAI download path pattern cannot be empty.")
    remainder = _TOKEN_RE.sub("", pattern)
    if "{" in remainder or "}" in remainder:
        raise ValueError("CivitAI download path pattern has malformed token syntax.")
    unknown_tokens = sorted(
        token
        for token in _TOKEN_RE.findall(pattern)
        if token not in _SUPPORTED_DOWNLOAD_PATH_TOKEN_NAMES
    )
    if unknown_tokens:
        joined = ", ".join(f"{{{token}}}" for token in unknown_tokens)
        raise ValueError(f"Unknown CivitAI download path token(s): {joined}.")
    if Path(pattern).is_absolute() or re.match(r"^[A-Za-z]:[\\/]", pattern):
        raise ValueError("CivitAI download path pattern must be relative.")
    if any(part in {".", ".."} for part in _PATH_SEPARATOR_RE.split(pattern)):
        raise ValueError("CivitAI download path pattern cannot contain traversal.")


def _download_path_token_values(
    request: CivitaiModelDownloadRequest,
    sha256: str,
) -> dict[str, str]:
    """Return normalized token values for backend download path rendering."""

    tokens = request.download_path_tokens
    file_name = _safe_file_name(tokens.get("fileName", request.file_name), sha256)
    base_model = _normalize_base_model_bucket(tokens.get("baseModel")) or "Unsorted"
    model_name = tokens.get("modelName", "").strip() or "Unsorted"
    version_name = tokens.get("versionName", "").strip() or "Version"
    creator = tokens.get("creator", "").strip() or "Unknown Creator"
    return {
        "base_model": base_model,
        "model_name": model_name,
        "version_name": version_name,
        "creator": creator,
        "file_name": file_name,
        "file_stem": Path(file_name).stem,
    }


def _normalize_base_model_bucket(value: str | None) -> str:
    """Return a local folder bucket for a CivitAI base model label."""

    if value is None:
        return ""
    text = value.strip()
    folded = text.casefold()
    if not text:
        return ""
    if "anima" in folded:
        return "Anima"
    if "illustrious" in folded:
        return "Illustrious"
    if "pony" in folded:
        return "Pony"
    if "flux" in folded:
        return "Flux"
    if "sdxl" in folded or "stable diffusion xl" in folded:
        return "SDXL"
    if "stable diffusion 1.5" in folded or folded in {"sd 1.5", "sd1.5", "sd15"}:
        return "SD 1.5"
    if "wan" in folded and "2.2" in folded:
        return "WAN 2.2"
    if "wan" in folded and "2.1" in folded:
        return "WAN 2.1"
    return text


def _safe_component(value: str) -> str:
    """Return a filesystem-safe path component."""

    cleaned = _WINDOWS_RESERVED_CHARS.sub("_", value.strip())
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip(" ._")
    return cleaned


def _download_destination_detail(target_path: Path) -> str:
    """Return user-facing destination text for in-progress download jobs."""

    return f"Saving to {target_path}"


def _is_under_root(path: Path, root: Path) -> bool:
    """Return whether a path is contained by an approved root."""

    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _preferred_download_root(*, kind: str, roots: tuple[Path, ...]) -> tuple[int, Path]:
    """Prefer the root named after the Comfy kind over legacy alias roots."""

    normalized_kind = kind.casefold()
    for index, root in enumerate(roots):
        resolved = root.resolve()
        if resolved.name.casefold() == normalized_kind:
            return index, resolved
    return 0, roots[0].resolve()


def _content_length(response: object) -> int | None:
    """Return a positive HTTP content length from a streaming response."""

    headers = getattr(response, "headers", None)
    if not isinstance(headers, Mapping):
        return None
    raw_value = headers.get("Content-Length") or headers.get("content-length")
    if not isinstance(raw_value, str):
        return None
    try:
        value = int(raw_value)
    except ValueError:
        return None
    return value if value > 0 else None
