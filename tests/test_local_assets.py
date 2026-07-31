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
"""Exercise hostile local asset authorization and execution-node scenarios."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest
from aiohttp import web

from substitute_backend.features.local_assets import (
    LOCAL_LOAD_IMAGE_CLASS,
    LOCAL_LOAD_IMAGE_MASK_CLASS,
    LocalAssetAuthorizationError,
    LocalAssetAuthorizationService,
    build_local_asset_node_mappings,
    build_local_asset_route_handlers,
)
from substitute_backend.features.local_assets.infrastructure import (
    TensorPlacement,
    resolve_tensor_placement,
)


@dataclass
class _Clock:
    """Provide a controllable monotonic clock."""

    now: float = 100.0

    def __call__(self) -> float:
        """Return the current test time."""

        return self.now


class _Request:
    """Provide the route's request surface without an aiohttp server."""

    def __init__(self, *, remote: str | None, payload: object) -> None:
        """Store peer address and decoded body."""

        self.remote = remote
        self._payload = payload

    async def json(self) -> object:
        """Return the configured JSON body or raise it when requested."""

        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


@dataclass(frozen=True)
class _Tensor:
    """Record channel extraction from a fake image tensor."""

    value: object

    def __getitem__(self, key: object) -> _Tensor:
        """Return a channel-selection tensor."""

        return _Tensor((self.value, key))

    def clone(self) -> _Tensor:
        """Return an independent semantic tensor."""

        return _Tensor(("clone", self.value))


class _Decoder:
    """Record decoded paths and return semantic tensors."""

    def __init__(self) -> None:
        """Initialize an empty call list."""

        self.paths: list[Path] = []

    def load(self, source_path: Path) -> tuple[object, object]:
        """Return deterministic image and alpha-mask values."""

        self.paths.append(source_path)
        return _Tensor("image"), _Tensor("alpha")


class _TorchModule:
    """Provide the torch surface needed to test portable tensor placement."""

    float32 = "float32"

    def device(self, name: str) -> str:
        """Return a recognizable fake device value."""

        return f"device:{name}"


def test_tensor_placement_falls_back_when_host_omits_comfy_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy hosts should decode with portable CPU float32 tensors."""

    monkeypatch.setattr(importlib, "import_module", lambda _name: object())

    placement = resolve_tensor_placement(_TorchModule())

    assert placement == TensorPlacement(dtype="float32", device="device:cpu")


def test_authorization_uses_source_in_place_without_creating_files(
    tmp_path: Path,
) -> None:
    """Authorizing a file should preserve its bytes and directory contents."""

    source = tmp_path / "source image.png"
    source.write_bytes(b"pixels")
    before = tuple(tmp_path.iterdir())
    service = LocalAssetAuthorizationService(token_factory=lambda: "opaque-token")

    asset = service.authorize(
        source_path=str(source),
        source_node_class="LoadImage",
        content_hash=_sha256(source),
    )

    assert asset.token == "opaque-token"
    assert asset.source_path == source.resolve()
    assert tuple(tmp_path.iterdir()) == before
    assert source.read_bytes() == b"pixels"
    assert service.resolve("opaque-token", expected_node_class="LoadImage") == asset


@pytest.mark.parametrize(
    ("source_value", "node_class", "content_hash"),
    [
        ("relative.png", "LoadImage", "0" * 64),
        ("relative.png", "UnknownLoader", "0" * 64),
        ("relative.png", "LoadImage", "not-a-hash"),
    ],
)
def test_authorization_rejects_untrusted_request_shapes(
    source_value: str,
    node_class: str,
    content_hash: str,
) -> None:
    """Malformed paths, node classes, and hashes should fail closed."""

    service = LocalAssetAuthorizationService()

    with pytest.raises(LocalAssetAuthorizationError):
        service.authorize(
            source_path=source_value,
            source_node_class=node_class,
            content_hash=content_hash,
        )


def test_authorization_rejects_missing_files_and_directories(tmp_path: Path) -> None:
    """Only existing regular files should be admitted."""

    service = LocalAssetAuthorizationService()
    for path in (tmp_path / "missing.png", tmp_path):
        with pytest.raises(LocalAssetAuthorizationError):
            service.authorize(
                source_path=str(path),
                source_node_class="LoadImage",
                content_hash="0" * 64,
            )


def test_authorization_expires_and_invalidates_replaced_files(tmp_path: Path) -> None:
    """Expiry and post-authorization replacement should revoke the token."""

    clock = _Clock()
    source = tmp_path / "mask.png"
    source.write_bytes(b"first")
    service = LocalAssetAuthorizationService(
        ttl_seconds=5.0,
        clock=clock,
        token_factory=iter(("replace-token", "expiry-token")).__next__,
    )
    replaced = service.authorize(
        source_path=str(source),
        source_node_class="LoadImageMask",
        content_hash=_sha256(source),
    )
    source.write_bytes(b"replacement-is-longer")

    with pytest.raises(LocalAssetAuthorizationError, match="changed"):
        service.resolve(replaced.token, expected_node_class="LoadImageMask")

    expiring = service.authorize(
        source_path=str(source),
        source_node_class="LoadImageMask",
        content_hash=_sha256(source),
    )
    clock.now += 5.0
    with pytest.raises(LocalAssetAuthorizationError, match="expired"):
        service.resolve(expiring.token, expected_node_class="LoadImageMask")


def test_authorization_cannot_cross_image_and_mask_nodes(tmp_path: Path) -> None:
    """A token issued for one loader class should not authorize the other."""

    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    service = LocalAssetAuthorizationService(token_factory=lambda: "token")
    asset = service.authorize(
        source_path=str(source),
        source_node_class="LoadImage",
        content_hash=_sha256(source),
    )

    with pytest.raises(LocalAssetAuthorizationError, match="does not match"):
        service.resolve(asset.token, expected_node_class="LoadImageMask")


def test_capacity_evicts_oldest_token_and_concurrent_tokens_are_unique(
    tmp_path: Path,
) -> None:
    """Flooding should stay bounded while concurrent admission remains collision-free."""

    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    digest = _sha256(source)
    service = LocalAssetAuthorizationService(capacity=4)
    first = service.authorize(
        source_path=str(source),
        source_node_class="LoadImage",
        content_hash=digest,
    )
    with ThreadPoolExecutor(max_workers=8) as executor:
        assets = tuple(
            executor.map(
                lambda _index: service.authorize(
                    source_path=str(source),
                    source_node_class="LoadImage",
                    content_hash=digest,
                ),
                range(32),
            )
        )

    assert len({asset.token for asset in assets}) == 32
    with pytest.raises(LocalAssetAuthorizationError):
        service.resolve(first.token, expected_node_class="LoadImage")
    survivors = 0
    for asset in assets:
        try:
            service.resolve(asset.token, expected_node_class="LoadImage")
        except LocalAssetAuthorizationError:
            continue
        survivors += 1
    assert survivors == 4


def test_execution_nodes_accept_only_live_tokens_and_decode_original_path(
    tmp_path: Path,
) -> None:
    """Execution nodes should resolve opaque tokens without exposing source paths."""

    image_path = tmp_path / "image.png"
    mask_path = tmp_path / "mask.png"
    image_path.write_bytes(b"image")
    mask_path.write_bytes(b"mask")
    tokens = iter(("image-token", "mask-token"))
    service = LocalAssetAuthorizationService(token_factory=tokens.__next__)
    image_asset = service.authorize(
        source_path=str(image_path),
        source_node_class="LoadImage",
        content_hash=_sha256(image_path),
    )
    mask_asset = service.authorize(
        source_path=str(mask_path),
        source_node_class="LoadImageMask",
        content_hash=_sha256(mask_path),
    )
    decoder = _Decoder()
    mappings = build_local_asset_node_mappings(service, decoder=decoder)
    image_node_type = cast(Any, mappings[LOCAL_LOAD_IMAGE_CLASS])
    mask_node_type = cast(Any, mappings[LOCAL_LOAD_IMAGE_MASK_CLASS])

    assert image_node_type.VALIDATE_INPUTS(image_asset.token) is True
    assert "invalid or expired" in str(image_node_type.VALIDATE_INPUTS("path.png"))
    assert image_node_type.IS_CHANGED(image_asset.token) == _sha256(image_path)
    assert image_node_type().load_authorized_image(image_asset.token) == (
        _Tensor("image"),
        _Tensor("alpha"),
    )
    assert mask_node_type.VALIDATE_INPUTS(mask_asset.token, "red") is True
    assert mask_node_type.VALIDATE_INPUTS(mask_asset.token, "bogus") == (
        "Unsupported local mask channel."
    )
    red_mask = mask_node_type().load_authorized_mask(mask_asset.token, "red")[0]
    alpha_mask = mask_node_type().load_authorized_mask(mask_asset.token, "alpha")[0]
    assert isinstance(red_mask, _Tensor)
    assert isinstance(red_mask.value, tuple)
    assert red_mask.value[0] == "clone"
    assert isinstance(alpha_mask, _Tensor)
    assert alpha_mask.value == "alpha"
    assert decoder.paths == [
        image_path.resolve(),
        mask_path.resolve(),
        mask_path.resolve(),
    ]


@pytest.mark.parametrize("remote", ["192.168.1.4", None, "not-an-address"])
def test_authorization_route_rejects_non_loopback_peers(
    tmp_path: Path,
    remote: str | None,
) -> None:
    """The file authorization surface should never be remotely callable."""

    source = tmp_path / "image.png"
    source.write_bytes(b"image")
    handler = build_local_asset_route_handlers(LocalAssetAuthorizationService())

    response = asyncio.run(
        handler.authorize(
            cast(
                web.Request,
                _Request(
                    remote=remote,
                    payload={
                        "sourcePath": str(source),
                        "nodeClass": "LoadImage",
                        "contentHash": _sha256(source),
                    },
                ),
            )
        )
    )

    assert response.status == 403


@pytest.mark.parametrize("remote", ["127.0.0.1", "::1", "::ffff:127.0.0.1"])
def test_authorization_route_returns_opaque_token_to_loopback(
    tmp_path: Path,
    remote: str,
) -> None:
    """IPv4, IPv6, and mapped loopback callers should receive no path disclosure."""

    source = tmp_path / "image.png"
    source.write_bytes(b"image")
    handler = build_local_asset_route_handlers(
        LocalAssetAuthorizationService(token_factory=lambda: "opaque")
    )

    response = asyncio.run(
        handler.authorize(
            cast(
                web.Request,
                _Request(
                    remote=remote,
                    payload={
                        "sourcePath": str(source),
                        "nodeClass": "LoadImage",
                        "contentHash": _sha256(source),
                    },
                ),
            )
        )
    )

    assert response.status == 200
    assert response.text is not None
    payload = json.loads(response.text)
    assert payload == {
        "token": "opaque",
        "nodeClass": "LoadImage",
        "executionNodeClass": "SubstituteBackendLoadImage",
        "contentHash": _sha256(source),
    }
    assert str(source) not in response.text


def _sha256(path: Path) -> str:
    """Return the digest used in authorization fixtures."""

    return hashlib.sha256(path.read_bytes()).hexdigest()
