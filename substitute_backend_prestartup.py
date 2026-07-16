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
"""Apply BackEnd-owned model configuration before normal custom-node imports."""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

_CONFIG_RELATIVE_PATH = Path(".substitute") / "model_root.json"
_LEGACY_CONFIG_RELATIVE_PATH = Path(".substitute") / "managed_model_root.json"
_LEGACY_HOOK_DIRECTORY = "SubstituteManagedModelRoot"
_SCHEMA_VERSION = 1
_LOGGER = logging.getLogger("substitute_backend.prestartup")


def apply_model_root(comfy_root: Path, folder_paths: Any) -> Path:
    """Apply the persisted root and return the model root active after startup."""

    _migrate_legacy_configuration(comfy_root)
    old_root = Path(str(folder_paths.models_dir)).resolve()
    configured_root = _read_configured_root(comfy_root)
    new_root = configured_root or (comfy_root / "models").resolve()
    new_root.mkdir(parents=True, exist_ok=True)
    if new_root != old_root:
        _redirect_registered_paths(folder_paths, old_root, new_root)
        folder_paths.models_dir = str(new_root)
        _clear_caches(folder_paths)
        _LOGGER.info("Substitute BackEnd configured ComfyUI model root: %s", new_root)
    _remove_legacy_hook(comfy_root)
    return new_root


def _migrate_legacy_configuration(comfy_root: Path) -> None:
    """Adopt desktop-owned persisted state before the normal startup read."""

    canonical_path = comfy_root / _CONFIG_RELATIVE_PATH
    legacy_path = comfy_root / _LEGACY_CONFIG_RELATIVE_PATH
    if not legacy_path.exists():
        return
    if canonical_path.exists():
        legacy_path.unlink()
        _LOGGER.info("Removed superseded legacy Substitute model-root configuration.")
        return
    payload = json.loads(legacy_path.read_text(encoding="utf-8"))
    value = payload.get("model_root")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Legacy Substitute model-root configuration is invalid.")
    model_root = Path(value).expanduser()
    if not model_root.is_absolute():
        raise ValueError("Legacy Substitute model root must be absolute.")
    _write_configuration(canonical_path, model_root.resolve())
    legacy_path.unlink()
    _LOGGER.info("Migrated legacy Substitute model-root configuration.")


def _write_configuration(config_path: Path, model_root: Path) -> None:
    """Atomically write the lightweight prestartup configuration shape."""

    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = config_path.with_name(f".{config_path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(
            json.dumps(
                {"schemaVersion": _SCHEMA_VERSION, "modelRoot": str(model_root)},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, config_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _remove_legacy_hook(comfy_root: Path) -> None:
    """Remove the superseded desktop-generated custom node after migration."""

    hook_directory = comfy_root / "custom_nodes" / _LEGACY_HOOK_DIRECTORY
    if not hook_directory.exists():
        return
    try:
        shutil.rmtree(hook_directory)
    except OSError as exc:
        _LOGGER.warning(
            "Could not remove legacy Substitute model-root hook: %s",
            exc,
        )
        return
    _LOGGER.info("Removed legacy Substitute model-root startup hook.")


def _read_configured_root(comfy_root: Path) -> Path | None:
    """Read the lightweight configuration without importing BackEnd services."""

    config_path = comfy_root / _CONFIG_RELATIVE_PATH
    if not config_path.exists():
        return None
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != _SCHEMA_VERSION:
        raise ValueError("Unsupported Substitute BackEnd model-root schema.")
    value = payload.get("modelRoot")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Substitute BackEnd model-root configuration is invalid.")
    configured_root = Path(value).expanduser()
    if not configured_root.is_absolute():
        raise ValueError("Substitute BackEnd model root must be absolute.")
    return configured_root.resolve()


def _redirect_registered_paths(
    folder_paths: Any,
    old_root: Path,
    new_root: Path,
) -> None:
    """Move default-root registry entries while preserving external additions."""

    registry = getattr(folder_paths, "folder_names_and_paths", {})
    for folder_name, values in list(registry.items()):
        paths, extensions = values
        rewritten: list[str] = []
        changed = False
        for raw_path in paths:
            path = Path(str(raw_path)).resolve()
            try:
                relative = path.relative_to(old_root)
            except ValueError:
                rewritten.append(str(raw_path))
                continue
            rewritten.append(str(new_root / relative))
            changed = True
        if changed:
            registry[folder_name] = (rewritten, extensions)


def _clear_caches(folder_paths: Any) -> None:
    """Clear supported Comfy filename caches after registry redirection."""

    for attribute in ("filename_list_cache", "cache_helper"):
        cache = getattr(folder_paths, attribute, None)
        clear = getattr(cache, "clear", None)
        if callable(clear):
            clear()


__all__ = ["apply_model_root"]
