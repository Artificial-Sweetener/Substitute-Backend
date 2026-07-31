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
"""Authorize exact local files for short-lived Comfy execution."""

from __future__ import annotations

import re
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

_SUPPORTED_NODE_CLASSES = frozenset({"LoadImage", "LoadImageMask"})
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class LocalAssetAuthorizationError(ValueError):
    """Report a rejected or invalid local asset authorization."""


@dataclass(frozen=True, slots=True)
class _FileIdentity:
    """Capture attributes that detect replacement after authorization."""

    size: int
    modified_ns: int
    device: int
    inode: int


@dataclass(frozen=True, slots=True)
class AuthorizedLocalAsset:
    """Describe one exact local file admitted for Comfy execution."""

    token: str
    source_path: Path
    source_node_class: str
    content_hash: str
    identity: _FileIdentity
    created_at: float
    expires_at: float


class LocalAssetAuthorizationService:
    """Own bounded, expiring authorization for local image files."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 3600.0,
        capacity: int = 4096,
        clock: Callable[[], float] = monotonic,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        """Configure authorization lifetime, capacity, and deterministic test seams."""

        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._ttl_seconds = ttl_seconds
        self._capacity = capacity
        self._clock = clock
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._assets: dict[str, AuthorizedLocalAsset] = {}
        self._lock = threading.RLock()

    def authorize(
        self,
        *,
        source_path: str,
        source_node_class: str,
        content_hash: str,
    ) -> AuthorizedLocalAsset:
        """Authorize one existing absolute file without copying its bytes."""

        if source_node_class not in _SUPPORTED_NODE_CLASSES:
            raise LocalAssetAuthorizationError("Unsupported local asset node class.")
        normalized_hash = content_hash.casefold()
        if _SHA256_PATTERN.fullmatch(normalized_hash) is None:
            raise LocalAssetAuthorizationError("Invalid local asset content hash.")
        unresolved_path = Path(source_path)
        if not unresolved_path.is_absolute():
            raise LocalAssetAuthorizationError("Local asset path must be absolute.")
        try:
            resolved_path = unresolved_path.resolve(strict=True)
            identity = _identity_for(resolved_path)
        except (OSError, RuntimeError) as error:
            raise LocalAssetAuthorizationError("Local asset file is unavailable.") from error
        if not resolved_path.is_file():
            raise LocalAssetAuthorizationError("Local asset path is not a file.")

        now = self._clock()
        with self._lock:
            self._purge_expired(now)
            self._make_capacity()
            token = self._unique_token()
            asset = AuthorizedLocalAsset(
                token=token,
                source_path=resolved_path,
                source_node_class=source_node_class,
                content_hash=normalized_hash,
                identity=identity,
                created_at=now,
                expires_at=now + self._ttl_seconds,
            )
            self._assets[token] = asset
            return asset

    def resolve(
        self,
        token: str,
        *,
        expected_node_class: str,
    ) -> AuthorizedLocalAsset:
        """Resolve a live token and reject expired, replaced, or misused files."""

        now = self._clock()
        with self._lock:
            self._purge_expired(now)
            asset = self._assets.get(token)
            if asset is None:
                raise LocalAssetAuthorizationError(
                    "Local asset authorization is invalid or expired."
                )
            if asset.source_node_class != expected_node_class:
                raise LocalAssetAuthorizationError(
                    "Local asset authorization does not match this node."
                )
            try:
                current_identity = _identity_for(asset.source_path)
            except OSError as error:
                self._assets.pop(token, None)
                raise LocalAssetAuthorizationError(
                    "Authorized local asset is no longer available."
                ) from error
            if current_identity != asset.identity:
                self._assets.pop(token, None)
                raise LocalAssetAuthorizationError(
                    "Authorized local asset changed after authorization."
                )
            return asset

    def _purge_expired(self, now: float) -> None:
        """Remove authorizations that can no longer be executed."""

        expired_tokens = [token for token, asset in self._assets.items() if asset.expires_at <= now]
        for token in expired_tokens:
            self._assets.pop(token, None)

    def _make_capacity(self) -> None:
        """Evict the oldest authorization before admitting beyond the bound."""

        while len(self._assets) >= self._capacity:
            oldest_token = min(
                self._assets,
                key=lambda token: self._assets[token].created_at,
            )
            self._assets.pop(oldest_token, None)

    def _unique_token(self) -> str:
        """Return a non-empty token not already present in the registry."""

        for _attempt in range(100):
            token = self._token_factory()
            if token and token not in self._assets:
                return token
        raise RuntimeError("Could not allocate a unique local asset token.")


def _identity_for(path: Path) -> _FileIdentity:
    """Return the stable file identity used across authorization and execution."""

    stat = path.stat()
    return _FileIdentity(
        size=stat.st_size,
        modified_ns=stat.st_mtime_ns,
        device=stat.st_dev,
        inode=stat.st_ino,
    )


__all__ = [
    "AuthorizedLocalAsset",
    "LocalAssetAuthorizationError",
    "LocalAssetAuthorizationService",
]
