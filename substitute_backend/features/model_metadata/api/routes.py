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
"""HTTP route handlers for Substitute BackEnd model metadata APIs."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from aiohttp import web

from substitute_backend.api.errors import BackendHttpError, json_error
from substitute_backend.features.model_metadata.application.catalog_service import (
    CatalogQuery,
)
from substitute_backend.features.model_metadata.application.fingerprint_service import (
    FingerprintRefreshEntry,
)
from substitute_backend.features.model_metadata.application.hash_lookup_service import (
    HashLookupQuery,
)
from substitute_backend.features.model_metadata.application.model_download_service import (
    CivitaiModelDownloadRequest,
)
from substitute_backend.features.model_metadata.application.services import (
    ModelMetadataServices,
)

RouteHandler = Callable[[web.Request], Awaitable[web.StreamResponse]]


@dataclass(frozen=True)
class ModelMetadataRouteHandlers:
    """Concrete route callables used for registration and tests."""

    capabilities: RouteHandler
    list_models: RouteHandler
    lookup_model_by_hash: RouteHandler
    start_civitai_model_download: RouteHandler
    get_model_download_job: RouteHandler
    cancel_model_download_job: RouteHandler
    refresh_fingerprints: RouteHandler
    get_fingerprint_job: RouteHandler
    latest_model_changes: RouteHandler
    get_preview: RouteHandler


def build_model_metadata_route_handlers(
    services: ModelMetadataServices,
    logger: logging.Logger,
) -> ModelMetadataRouteHandlers:
    """Build thin HTTP handlers over model metadata services."""

    async def capabilities(request: web.Request) -> web.Response:
        """Return backend and feature capabilities."""

        _ = request
        return web.json_response(services.capabilities.get_capabilities().to_payload())

    async def list_models(request: web.Request) -> web.Response:
        """Return model catalog entries for requested model kinds."""

        try:
            kinds = _parse_kind_query(request)
            query = CatalogQuery(
                kinds=kinds,
                include_hashes=_parse_bool(request.query.get("includeHashes"), False),
                include_local_metadata=_parse_bool(
                    request.query.get("includeLocalMetadata"),
                    True,
                ),
                include_previews=_parse_bool(request.query.get("includePreviews"), True),
            )
            if _parse_bool(request.query.get("refresh"), False):
                services.catalog_refresh.refresh(kinds)
            entries = services.catalog.list_models(query)
            return web.json_response(
                {
                    "schemaVersion": 1,
                    "models": [entry.to_payload() for entry in entries],
                }
            )
        except BackendHttpError as exc:
            return json_error(exc)
        except Exception:  # pragma: no cover - defensive host boundary.
            logger.exception(
                "model catalog route failed",
                extra={"operation": "catalog-list", "route": "/substitute/v1/models"},
            )
            return json_error(
                BackendHttpError(
                    message="Model catalog unavailable.",
                    status=500,
                    code="catalog-unavailable",
                )
            )

    async def refresh_fingerprints(request: web.Request) -> web.Response:
        """Queue background fingerprint refresh work."""

        try:
            body = await request.json()
            entries = _parse_refresh_entries(body)
            job = services.fingerprints.refresh(entries)
            return web.json_response(job.to_payload(), status=202)
        except BackendHttpError as exc:
            return json_error(exc)
        except Exception:  # pragma: no cover - defensive host boundary.
            logger.exception(
                "fingerprint refresh route failed",
                extra={
                    "operation": "fingerprint-refresh",
                    "route": "/substitute/v1/models/fingerprints/refresh",
                },
            )
            return json_error(
                BackendHttpError(
                    message="Fingerprint refresh failed.",
                    status=500,
                    code="fingerprint-refresh-failed",
                )
            )

    async def lookup_model_by_hash(request: web.Request) -> web.Response:
        """Find local model files by SHA256 or queue missing fingerprint work."""

        try:
            sha256 = request.match_info.get("sha256", "")
            kind = _parse_required_query_str(request, "kind")
            result = services.hash_lookup.lookup(HashLookupQuery(kind=kind, sha256=sha256))
            return web.json_response(result.to_payload())
        except BackendHttpError as exc:
            return json_error(exc)
        except Exception:  # pragma: no cover - defensive host boundary.
            logger.exception(
                "hash lookup route failed",
                extra={
                    "operation": "hash-lookup",
                    "route": "/substitute/v1/models/by-hash/{sha256}",
                },
            )
            return json_error(
                BackendHttpError(
                    message="Hash lookup unavailable.",
                    status=500,
                    code="hash-lookup-unavailable",
                )
            )

    async def start_civitai_model_download(request: web.Request) -> web.Response:
        """Queue a verified CivitAI model download into an approved model root."""

        try:
            body = await request.json()
            download_request = _parse_civitai_download_request(body)
            job = services.downloads.start_civitai_download(download_request)
            return web.json_response(job.to_payload(), status=202)
        except BackendHttpError as exc:
            return json_error(exc)
        except ValueError as exc:
            return json_error(
                BackendHttpError(
                    message=str(exc),
                    status=400,
                    code="invalid-model-download-request",
                )
            )
        except Exception:  # pragma: no cover - defensive host boundary.
            logger.exception(
                "model download route failed",
                extra={
                    "operation": "model-download-start",
                    "route": "/substitute/v1/models/downloads/civitai",
                },
            )
            return json_error(
                BackendHttpError(
                    message="Model download unavailable.",
                    status=500,
                    code="model-download-unavailable",
                )
            )

    async def get_model_download_job(request: web.Request) -> web.Response:
        """Return a backend model download job state."""

        job_id = request.match_info.get("jobId", "")
        job = services.downloads.get_job(job_id)
        if job is None:
            return json_error(
                BackendHttpError(
                    message="Model download job not found.",
                    status=404,
                    code="model-download-job-not-found",
                )
            )
        return web.json_response(job.to_payload())

    async def cancel_model_download_job(request: web.Request) -> web.Response:
        """Request cancellation for a backend model download job."""

        job_id = request.match_info.get("jobId", "")
        job = services.downloads.cancel_download(job_id)
        if job is None:
            return json_error(
                BackendHttpError(
                    message="Model download job not found.",
                    status=404,
                    code="model-download-job-not-found",
                )
            )
        return web.json_response(job.to_payload())

    async def get_fingerprint_job(request: web.Request) -> web.Response:
        """Return the current state for a fingerprint job."""

        job_id = request.match_info.get("jobId", "")
        job = services.fingerprints.get_job(job_id)
        if job is None:
            return json_error(
                BackendHttpError(
                    message="Fingerprint job not found.",
                    status=404,
                    code="fingerprint-job-not-found",
                )
            )
        return web.json_response(job.to_payload())

    async def get_preview(request: web.Request) -> web.StreamResponse:
        """Serve a validated local preview image by opaque ID."""

        preview_id = request.match_info.get("previewId", "")
        preview = services.previews.resolve(preview_id)
        if preview is None:
            return web.Response(status=404)
        return web.FileResponse(
            preview.path,
            headers={
                "Cache-Control": "private, max-age=60",
                "Content-Type": preview.content_type,
            },
        )

    async def latest_model_changes(request: web.Request) -> web.Response:
        """Return the latest model catalog change for reconnect recovery."""

        _ = request
        latest_change = services.changes.latest_change
        return web.json_response(
            {
                "schemaVersion": 1,
                "revision": services.changes.revision,
                "latestChange": (latest_change.to_payload() if latest_change is not None else None),
            }
        )

    return ModelMetadataRouteHandlers(
        capabilities=capabilities,
        list_models=list_models,
        lookup_model_by_hash=lookup_model_by_hash,
        start_civitai_model_download=start_civitai_model_download,
        get_model_download_job=get_model_download_job,
        cancel_model_download_job=cancel_model_download_job,
        refresh_fingerprints=refresh_fingerprints,
        get_fingerprint_job=get_fingerprint_job,
        latest_model_changes=latest_model_changes,
        get_preview=get_preview,
    )


def _parse_kind_query(request: web.Request) -> tuple[str, ...] | None:
    """Parse repeated or comma-separated model kind query values."""

    values = request.query.getall("kind", [])
    kinds: list[str] = []
    for value in values:
        kinds.extend(part.strip() for part in value.split(",") if part.strip())
    return tuple(kinds) if kinds else None


def _parse_bool(value: str | None, default: bool) -> bool:
    """Parse a boolean query value."""

    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise BackendHttpError(
        message=f"Invalid boolean query value: {value}",
        status=400,
        code="invalid-query-value",
    )


def _parse_required_query_str(request: web.Request, key: str) -> str:
    """Parse a required non-empty query string value."""

    value = request.query.get(key, "")
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise BackendHttpError(
        message=f"'{key}' is required.",
        status=400,
        code="invalid-hash-lookup-query",
    )


def _parse_refresh_entries(body: object) -> tuple[FingerprintRefreshEntry, ...]:
    """Parse a fingerprint refresh request body."""

    if not isinstance(body, dict):
        raise BackendHttpError(
            message="Request body must be a JSON object.",
            status=400,
            code="invalid-request-body",
        )
    raw_entries = body.get("entries")
    if not isinstance(raw_entries, list):
        raise BackendHttpError(
            message="'entries' must be a list.",
            status=400,
            code="invalid-request-body",
        )
    entries: list[FingerprintRefreshEntry] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            raise BackendHttpError(
                message="Each fingerprint entry must be a JSON object.",
                status=400,
                code="invalid-request-body",
            )
        entry = _parse_refresh_entry(raw_entry)
        entries.append(entry)
    return tuple(entries)


def _parse_civitai_download_request(body: object) -> CivitaiModelDownloadRequest:
    """Parse one CivitAI model download request body."""

    if not isinstance(body, dict):
        raise BackendHttpError(
            message="Request body must be a JSON object.",
            status=400,
            code="invalid-model-download-request",
        )
    kind = _required_body_str(body, "kind")
    sha256 = _required_body_str(body, "sha256")
    download_url = _required_body_str(body, "downloadUrl")
    file_name = _required_body_str(body, "fileName")
    api_key = body.get("apiKey")
    return CivitaiModelDownloadRequest(
        kind=kind,
        sha256=sha256,
        download_url=download_url,
        file_name=file_name,
        file_type=_required_body_str(body, "fileType"),
        metadata_format=_required_body_str(body, "metadataFormat"),
        pickle_scan_result=_required_body_str(body, "pickleScanResult"),
        virus_scan_result=_required_body_str(body, "virusScanResult"),
        download_path_pattern=_optional_body_str(
            body,
            "downloadPathPattern",
            default="{file_name}",
        ),
        download_path_tokens=_parse_download_path_tokens(body.get("downloadPathTokens")),
        api_key=api_key if isinstance(api_key, str) and api_key.strip() else None,
    )


def _parse_download_path_tokens(value: object) -> dict[str, str]:
    """Parse optional CivitAI download path token values."""

    if value is None:
        return {}
    if not isinstance(value, dict):
        raise BackendHttpError(
            message="'downloadPathTokens' must be an object.",
            status=400,
            code="invalid-model-download-request",
        )
    tokens: dict[str, str] = {}
    for key, raw_value in value.items():
        if isinstance(key, str) and isinstance(raw_value, str):
            tokens[key] = raw_value
    return tokens


def _optional_body_str(
    body: dict[object, object],
    key: str,
    *,
    default: str,
) -> str:
    """Read one optional request body string with a fallback."""

    value = body.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _required_body_str(body: dict[object, object], key: str) -> str:
    """Read one required non-empty request body string."""

    value = body.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise BackendHttpError(
        message=f"'{key}' is required.",
        status=400,
        code="invalid-model-download-request",
    )


def _parse_refresh_entry(entry: dict[object, object]) -> FingerprintRefreshEntry:
    """Parse one fingerprint refresh request entry."""

    kind = entry.get("kind")
    value = entry.get("value")
    if not isinstance(kind, str) or not kind.strip():
        raise BackendHttpError("'kind' is required.", status=400, code="invalid-entry")
    if not isinstance(value, str) or not value.strip():
        raise BackendHttpError("'value' is required.", status=400, code="invalid-entry")
    size_bytes = entry.get("sizeBytes")
    modified_at = entry.get("modifiedAt")
    return FingerprintRefreshEntry(
        kind=kind.strip(),
        value=value.strip(),
        size_bytes=size_bytes if isinstance(size_bytes, int) else None,
        modified_at=modified_at if isinstance(modified_at, str) else None,
    )
