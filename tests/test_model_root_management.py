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
"""Tests for authoritative Comfy model-root management."""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

from substitute_backend.features.environment_management.application.model_root_service import (
    ModelRootService,
)
from substitute_backend.features.environment_management.domain.model_root import ModelRootMode
from substitute_backend.features.environment_management.infrastructure.model_root_runtime import (
    ModelRootRuntime,
)
from substitute_backend.features.environment_management.infrastructure.model_root_store import (
    ModelRootStore,
)
from substitute_backend_prestartup import apply_model_root


class MutableModelRootRuntime(ModelRootRuntime):
    """Expose a mutable active root for restart-transition tests."""

    def __init__(self, active_root: Path) -> None:
        """Initialize the active root."""

        self.active_root = active_root

    def active_model_root(self) -> Path:
        """Return the current active root."""

        return self.active_root.resolve()


class ClearTracker:
    """Record Comfy cache invalidation calls."""

    def __init__(self) -> None:
        """Initialize an uncleared tracker."""

        self.cleared = False

    def clear(self) -> None:
        """Record cache invalidation."""

        self.cleared = True


def test_store_defaults_to_comfy_models_without_configuration(tmp_path: Path) -> None:
    """An unconfigured host uses its own models directory."""

    runtime = MutableModelRootRuntime(tmp_path / "models")
    service = ModelRootService(tmp_path, ModelRootStore(tmp_path), runtime)

    status = service.get_status()

    assert status.uses_default is True
    assert status.default_model_root == (tmp_path / "models").resolve()
    assert status.active_model_root == (tmp_path / "models").resolve()
    assert status.restart_required is False


def test_custom_root_is_persisted_atomically_and_requires_restart(tmp_path: Path) -> None:
    """A custom selection is durable while active state remains process-owned."""

    runtime = MutableModelRootRuntime(tmp_path / "models")
    store = ModelRootStore(tmp_path)
    service = ModelRootService(tmp_path, store, runtime)
    custom_root = tmp_path / "shared models"

    status = service.configure(ModelRootMode.CUSTOM, str(custom_root))

    assert status.configured_model_root == custom_root.resolve()
    assert status.active_model_root == (tmp_path / "models").resolve()
    assert status.restart_required is True
    assert store.load() == custom_root.resolve()
    assert not tuple(store.config_path.parent.glob("*.tmp"))

    runtime.active_root = custom_root
    assert service.get_status().restart_required is False


def test_default_mode_removes_only_owned_configuration(tmp_path: Path) -> None:
    """Resetting to default preserves unrelated Substitute host state."""

    store = ModelRootStore(tmp_path)
    store.save(tmp_path / "shared")
    unrelated = store.config_path.parent / "other.json"
    unrelated.write_text("{}", encoding="utf-8")
    service = ModelRootService(
        tmp_path,
        store,
        MutableModelRootRuntime(tmp_path / "shared"),
    )

    status = service.configure(ModelRootMode.DEFAULT, None)

    assert status.uses_default is True
    assert status.restart_required is True
    assert not store.config_path.exists()
    assert unrelated.exists()


@pytest.mark.parametrize("value", ["models", "", "."])
def test_custom_root_rejects_relative_paths(tmp_path: Path, value: str) -> None:
    """Host configuration never interprets relative paths ambiguously."""

    service = ModelRootService(
        tmp_path,
        ModelRootStore(tmp_path),
        MutableModelRootRuntime(tmp_path / "models"),
    )

    with pytest.raises(ValueError, match=r"absolute|requires"):
        service.configure(ModelRootMode.CUSTOM, value)


def test_prestartup_redirects_default_categories_and_preserves_external_paths(
    tmp_path: Path,
) -> None:
    """Prestartup moves Comfy defaults without consuming extra model paths."""

    comfy_root = tmp_path / "ComfyUI"
    old_root = comfy_root / "models"
    new_root = tmp_path / "shared-models"
    external_root = tmp_path / "external-loras"
    config_path = comfy_root / ".substitute" / "model_root.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps({"schemaVersion": 1, "modelRoot": str(new_root)}),
        encoding="utf-8",
    )
    folder_paths = cast(Any, ModuleType("folder_paths"))
    folder_paths.models_dir = str(old_root)
    folder_paths.folder_names_and_paths = {
        "checkpoints": ([str(old_root / "checkpoints")], {".safetensors"}),
        "loras": (
            [str(old_root / "loras"), str(external_root)],
            {".safetensors"},
        ),
    }
    filename_cache = ClearTracker()
    helper_cache = ClearTracker()
    folder_paths.filename_list_cache = filename_cache
    folder_paths.cache_helper = helper_cache

    active_root = apply_model_root(comfy_root, folder_paths)

    assert active_root == new_root.resolve()
    assert Path(folder_paths.models_dir) == new_root.resolve()
    assert folder_paths.folder_names_and_paths["checkpoints"][0] == [str(new_root / "checkpoints")]
    assert folder_paths.folder_names_and_paths["loras"][0] == [
        str(new_root / "loras"),
        str(external_root),
    ]
    assert filename_cache.cleared is True
    assert helper_cache.cleared is True


def test_prestartup_uses_default_without_configuration(tmp_path: Path) -> None:
    """The BackEnd hook does not require SugarSubstitute launch state."""

    comfy_root = tmp_path / "ComfyUI"
    folder_paths = cast(Any, ModuleType("folder_paths"))
    folder_paths.models_dir = str(comfy_root / "models")
    folder_paths.folder_names_and_paths = {}

    assert apply_model_root(comfy_root, folder_paths) == (comfy_root / "models").resolve()


def test_prestartup_migrates_legacy_desktop_state_and_hook(tmp_path: Path) -> None:
    """BackEnd adopts the previous owner before removing its generated hook."""

    comfy_root = tmp_path / "ComfyUI"
    legacy_config = comfy_root / ".substitute" / "managed_model_root.json"
    legacy_hook = comfy_root / "custom_nodes" / "SubstituteManagedModelRoot"
    custom_root = tmp_path / "legacy-models"
    legacy_config.parent.mkdir(parents=True)
    legacy_config.write_text(
        json.dumps({"schema_version": 1, "model_root": str(custom_root)}),
        encoding="utf-8",
    )
    legacy_hook.mkdir(parents=True)
    (legacy_hook / "prestartup_script.py").write_text("", encoding="utf-8")
    folder_paths = cast(Any, ModuleType("folder_paths"))
    folder_paths.models_dir = str(comfy_root / "models")
    folder_paths.folder_names_and_paths = {}

    assert apply_model_root(comfy_root, folder_paths) == custom_root.resolve()
    assert not legacy_config.exists()
    assert not legacy_hook.exists()
    assert ModelRootStore(comfy_root).load() == custom_root.resolve()


def test_prestartup_keeps_canonical_selection_over_legacy_state(tmp_path: Path) -> None:
    """Canonical BackEnd state should win and remove a leftover desktop file."""

    comfy_root = tmp_path / "ComfyUI"
    canonical_root = tmp_path / "canonical-models"
    ModelRootStore(comfy_root).save(canonical_root)
    legacy_config = comfy_root / ".substitute" / "managed_model_root.json"
    legacy_config.write_text("not valid anymore", encoding="utf-8")
    folder_paths = cast(Any, ModuleType("folder_paths"))
    folder_paths.models_dir = str(comfy_root / "models")
    folder_paths.folder_names_and_paths = {}

    assert apply_model_root(comfy_root, folder_paths) == canonical_root.resolve()
    assert not legacy_config.exists()
