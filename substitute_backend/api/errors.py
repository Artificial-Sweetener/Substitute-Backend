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
"""HTTP-facing error helpers for Substitute BackEnd."""

from __future__ import annotations

from dataclasses import dataclass

from aiohttp import web

from substitute_backend.api.serialization import JsonObject


@dataclass(frozen=True)
class BackendHttpError(Exception):
    """Typed error that can be converted into a structured HTTP response."""

    message: str
    status: int = 400
    code: str = "backend-error"


def json_error(error: BackendHttpError) -> web.Response:
    """Build a structured JSON error response."""

    payload: JsonObject = {
        "error": {
            "code": error.code,
            "message": error.message,
        }
    }
    return web.json_response(payload, status=error.status)
