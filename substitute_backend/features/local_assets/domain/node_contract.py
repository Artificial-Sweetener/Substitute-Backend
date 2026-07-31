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
"""Define the source-to-execution node mapping owned by Substitute BackEnd."""

from __future__ import annotations

LOCAL_LOAD_IMAGE_CLASS = "SubstituteBackendLoadImage"
LOCAL_LOAD_IMAGE_MASK_CLASS = "SubstituteBackendLoadImageMask"

_EXECUTION_NODE_CLASSES = {
    "LoadImage": LOCAL_LOAD_IMAGE_CLASS,
    "LoadImageMask": LOCAL_LOAD_IMAGE_MASK_CLASS,
}


def local_execution_node_class(source_node_class: str) -> str | None:
    """Return the execution node class for one supported core loader."""

    return _EXECUTION_NODE_CLASSES.get(source_node_class)


__all__ = [
    "LOCAL_LOAD_IMAGE_CLASS",
    "LOCAL_LOAD_IMAGE_MASK_CLASS",
    "local_execution_node_class",
]
