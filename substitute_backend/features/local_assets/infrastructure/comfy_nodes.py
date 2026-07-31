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
"""Adapt authorized local files to execution-only Comfy image loader nodes."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from substitute_backend.features.local_assets.application import (
    LocalAssetAuthorizationError,
    LocalAssetAuthorizationService,
)
from substitute_backend.features.local_assets.domain import (
    LOCAL_LOAD_IMAGE_CLASS,
    LOCAL_LOAD_IMAGE_MASK_CLASS,
)


class ImageTensorDecoder(Protocol):
    """Decode one image path into Comfy IMAGE and MASK values."""

    def load(self, source_path: Path) -> tuple[object, object]:
        """Return Comfy-compatible image and alpha-mask tensors."""


@dataclass(frozen=True)
class TensorPlacement:
    """Describe the dtype and device required by the active ComfyUI host."""

    dtype: Any
    device: Any


def resolve_tensor_placement(torch_module: object) -> TensorPlacement:
    """Use ComfyUI placement controls when present, otherwise use portable CPU tensors."""

    torch = cast(Any, torch_module)
    try:
        model_management = importlib.import_module("comfy.model_management")
    except ModuleNotFoundError:
        return TensorPlacement(dtype=torch.float32, device=torch.device("cpu"))
    try:
        return TensorPlacement(
            dtype=model_management.intermediate_dtype(),
            device=model_management.intermediate_device(),
        )
    except AttributeError:
        return TensorPlacement(dtype=torch.float32, device=torch.device("cpu"))


class LocalImageDecoder:
    """Decode authorized local files without using ComfyUI's path resolver."""

    def load(self, source_path: Path) -> tuple[object, object]:
        """Return IMAGE and inverted-alpha MASK tensors for one local file."""

        import numpy
        import torch
        from PIL import Image, ImageOps, ImageSequence

        placement = resolve_tensor_placement(torch)
        with Image.open(source_path) as opened_image:
            output_images: list[Any] = []
            output_masks: list[Any] = []
            expected_size: tuple[int, int] | None = None
            for frame in ImageSequence.Iterator(opened_image):
                transposed = ImageOps.exif_transpose(frame)
                if transposed.mode == "I":
                    transposed = transposed.point(lambda value: value * (1 / 255))
                image = transposed.convert("RGB")
                if expected_size is None:
                    expected_size = image.size
                if image.size != expected_size:
                    continue
                image_array = numpy.asarray(image).astype(numpy.float32) / 255.0
                image_tensor = torch.from_numpy(image_array)[None,].to(dtype=placement.dtype)
                if "A" in transposed.getbands():
                    alpha = numpy.asarray(transposed.getchannel("A")).astype(numpy.float32) / 255.0
                    mask_tensor = 1.0 - torch.from_numpy(alpha)
                elif transposed.mode == "P" and "transparency" in transposed.info:
                    alpha = (
                        numpy.asarray(transposed.convert("RGBA").getchannel("A")).astype(
                            numpy.float32
                        )
                        / 255.0
                    )
                    mask_tensor = 1.0 - torch.from_numpy(alpha)
                else:
                    mask_tensor = torch.zeros((64, 64), dtype=placement.dtype, device="cpu")
                output_images.append(image_tensor)
                output_masks.append(mask_tensor.unsqueeze(0).to(dtype=placement.dtype))
                if opened_image.format == "MPO":
                    break
        if not output_images:
            raise ValueError("Authorized local image contains no decodable frames.")
        images = torch.cat(output_images, dim=0)
        masks = torch.cat(output_masks, dim=0)
        return (
            images.to(device=placement.device, dtype=placement.dtype),
            masks.to(device=placement.device, dtype=placement.dtype),
        )


def build_local_asset_node_mappings(
    service: LocalAssetAuthorizationService,
    *,
    decoder: ImageTensorDecoder | None = None,
) -> dict[str, type[object]]:
    """Build Comfy node classes bound explicitly to one authorization service."""

    image_decoder = decoder or LocalImageDecoder()

    class AuthorizedLocalImageNode:
        """Load an opaque, pre-authorized local image."""

        RETURN_TYPES = ("IMAGE", "MASK")
        FUNCTION = "load_authorized_image"
        CATEGORY = "Substitute/execution"

        @classmethod
        def INPUT_TYPES(cls) -> dict[str, object]:
            """Declare the opaque authorization token input."""

            return {"required": {"image": ("STRING", {"default": ""})}}

        @classmethod
        def VALIDATE_INPUTS(cls, image: str) -> bool | str:
            """Validate that the token still authorizes a LoadImage source."""

            try:
                service.resolve(image, expected_node_class="LoadImage")
            except LocalAssetAuthorizationError as error:
                return str(error)
            return True

        @classmethod
        def IS_CHANGED(cls, image: str) -> str:
            """Return the authorized source hash for Comfy cache invalidation."""

            return service.resolve(
                image,
                expected_node_class="LoadImage",
            ).content_hash

        def load_authorized_image(self, image: str) -> tuple[object, object]:
            """Decode the exact file associated with a valid token."""

            asset = service.resolve(image, expected_node_class="LoadImage")
            return image_decoder.load(asset.source_path)

    class AuthorizedLocalMaskNode:
        """Load one channel from an opaque, pre-authorized local mask."""

        RETURN_TYPES = ("MASK",)
        FUNCTION = "load_authorized_mask"
        CATEGORY = "Substitute/execution"
        _COLOR_CHANNELS = ("alpha", "red", "green", "blue")

        @classmethod
        def INPUT_TYPES(cls) -> dict[str, object]:
            """Declare authorization token and selected mask channel inputs."""

            return {
                "required": {
                    "image": ("STRING", {"default": ""}),
                    "channel": (cls._COLOR_CHANNELS,),
                }
            }

        @classmethod
        def VALIDATE_INPUTS(cls, image: str, channel: str) -> bool | str:
            """Validate token ownership and the requested color channel."""

            if channel not in cls._COLOR_CHANNELS:
                return "Unsupported local mask channel."
            try:
                service.resolve(image, expected_node_class="LoadImageMask")
            except LocalAssetAuthorizationError as error:
                return str(error)
            return True

        @classmethod
        def IS_CHANGED(cls, image: str, channel: str) -> str:
            """Return a channel-sensitive source cache key."""

            asset = service.resolve(image, expected_node_class="LoadImageMask")
            return f"{asset.content_hash}:{channel}"

        def load_authorized_mask(self, image: str, channel: str) -> tuple[object]:
            """Return the requested channel as a Comfy MASK tensor."""

            asset = service.resolve(image, expected_node_class="LoadImageMask")
            image_tensor, alpha_mask = image_decoder.load(asset.source_path)
            if channel == "alpha":
                return (alpha_mask,)
            channel_index = {"red": 0, "green": 1, "blue": 2}[channel]
            tensor = cast(Any, image_tensor)
            return (tensor[..., channel_index].clone(),)

    return {
        LOCAL_LOAD_IMAGE_CLASS: AuthorizedLocalImageNode,
        LOCAL_LOAD_IMAGE_MASK_CLASS: AuthorizedLocalMaskNode,
    }


__all__ = [
    "LOCAL_LOAD_IMAGE_CLASS",
    "LOCAL_LOAD_IMAGE_MASK_CLASS",
    "ImageTensorDecoder",
    "LocalImageDecoder",
    "TensorPlacement",
    "build_local_asset_node_mappings",
    "resolve_tensor_placement",
]
