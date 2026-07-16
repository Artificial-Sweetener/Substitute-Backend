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
"""Configure BackEnd model-root state before a newly installed Comfy can start."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_EXTENSION_ROOT = Path(__file__).resolve().parent
if str(_EXTENSION_ROOT) not in sys.path:
    sys.path.insert(0, str(_EXTENSION_ROOT))

from substitute_backend.features.environment_management.infrastructure.model_root_store import (  # noqa: E402
    ModelRootStore,
)


def main(argv: list[str] | None = None) -> int:
    """Persist a model-root selection for an offline Comfy installation."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--comfy-root", required=True, type=Path)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--default", action="store_true")
    selection.add_argument("--path", type=Path)
    arguments = parser.parse_args(argv)
    store = ModelRootStore(arguments.comfy_root)
    store.save(None if arguments.default else arguments.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
