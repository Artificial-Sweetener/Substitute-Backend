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
"""Expose the execution-node contract for authorized local assets."""

from substitute_backend.features.local_assets.domain.node_contract import (
    LOCAL_LOAD_IMAGE_CLASS,
    LOCAL_LOAD_IMAGE_MASK_CLASS,
    local_execution_node_class,
)

__all__ = [
    "LOCAL_LOAD_IMAGE_CLASS",
    "LOCAL_LOAD_IMAGE_MASK_CLASS",
    "local_execution_node_class",
]
