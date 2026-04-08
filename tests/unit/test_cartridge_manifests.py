"""
Tests for Cartridge Manifests (#93).

Validates:
1. generate_manifest() produces a valid manifest dict with required fields
2. validate_manifest() accepts valid and rejects incomplete manifests
3. aim_bake.py injects manifest into metadata.json during bake
4. aim_exchange.py validates manifest on import
"""
import importlib.util
import json
import os
import sys
import types
import zipfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

AIM_CLAUDE_ROOT = str(Path(__file__).parent.parent.parent)


def _ensure_stub(name, **attrs):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod
    return sys.modules[name]


_ensure_stub("keyring", get_password=lambda *a, **k: None, set_password=lambda *a, **k: None)
_ensure_stub("google")
_ensure_stub("google.genai")


def _load_cartridge_utils():
    mod_name = "_test_cart_utils_93"
    sys.modules.pop(mod_name, None)
    spec = importlib.util.spec_from_file_location(
        mod_name,
        os.path.join(AIM_CLAUDE_ROOT, "src", "plugins", "datajack", "cartridge_utils.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MANIFEST_REQUIRED_FIELDS = [
    "name", "version", "embedding_model", "fragment_count", "created_at"
]


# ===========================================================================
# generate_manifest()
# ===========================================================================

class TestGenerateManifest:

    def test_contains_required_fields(self):
        mod = _load_cartridge_utils()
        manifest = mod.generate_manifest(
            name="pytest",
            version="1.0.0",
            embedding_model="nomic-embed-text",
            fragment_count=42,
        )
        for field in MANIFEST_REQUIRED_FIELDS:
            assert field in manifest, f"Missing required field: {field}"

    def test_name_and_version(self):
        mod = _load_cartridge_utils()
        manifest = mod.generate_manifest(
            name="django",
            version="2.1.0",
            embedding_model="nomic-embed-text",
            fragment_count=100,
        )
        assert manifest["name"] == "django"
        assert manifest["version"] == "2.1.0"

    def test_optional_source_repo(self):
        mod = _load_cartridge_utils()
        manifest = mod.generate_manifest(
            name="test",
            version="1.0.0",
            embedding_model="nomic-embed-text",
            fragment_count=1,
            source_repo="https://github.com/example/repo",
        )
        assert manifest["source_repo"] == "https://github.com/example/repo"

    def test_created_at_is_iso_format(self):
        mod = _load_cartridge_utils()
        manifest = mod.generate_manifest(
            name="test", version="1.0.0",
            embedding_model="nomic-embed-text", fragment_count=1,
        )
        # Should be parseable as ISO datetime
        from datetime import datetime
        datetime.fromisoformat(manifest["created_at"])


# ===========================================================================
# validate_manifest()
# ===========================================================================

class TestValidateManifest:

    def test_valid_manifest_passes(self):
        mod = _load_cartridge_utils()
        manifest = mod.generate_manifest(
            name="test", version="1.0.0",
            embedding_model="nomic-embed-text", fragment_count=5,
        )
        assert mod.validate_manifest(manifest) is True

    def test_missing_name_fails(self):
        mod = _load_cartridge_utils()
        manifest = {"version": "1.0.0", "embedding_model": "x", "fragment_count": 1, "created_at": "2026-01-01"}
        assert mod.validate_manifest(manifest) is False

    def test_missing_version_fails(self):
        mod = _load_cartridge_utils()
        manifest = {"name": "test", "embedding_model": "x", "fragment_count": 1, "created_at": "2026-01-01"}
        assert mod.validate_manifest(manifest) is False

    def test_missing_embedding_model_fails(self):
        mod = _load_cartridge_utils()
        manifest = {"name": "test", "version": "1.0.0", "fragment_count": 1, "created_at": "2026-01-01"}
        assert mod.validate_manifest(manifest) is False

    def test_none_input_fails(self):
        mod = _load_cartridge_utils()
        assert mod.validate_manifest(None) is False

    def test_empty_dict_fails(self):
        mod = _load_cartridge_utils()
        assert mod.validate_manifest({}) is False
