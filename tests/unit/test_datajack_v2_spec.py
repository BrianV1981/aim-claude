"""
Tests for DataJack v2 Packaging Spec (#97).

Validates:
1. Schema version is embedded in manifests (CARTRIDGE_SCHEMA_VERSION)
2. check_embedding_compatibility() validates model match
3. generate_manifest() includes schema_version field
4. validate_manifest() requires schema_version for v2 cartridges
"""
import importlib.util
import os
import sys
import types
from pathlib import Path

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


def _load_module():
    mod_name = "_test_cart_utils_97"
    sys.modules.pop(mod_name, None)
    spec = importlib.util.spec_from_file_location(
        mod_name,
        os.path.join(AIM_CLAUDE_ROOT, "src", "plugins", "datajack", "cartridge_utils.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSchemaVersion:

    def test_module_has_schema_version_constant(self):
        mod = _load_module()
        assert hasattr(mod, "CARTRIDGE_SCHEMA_VERSION")
        assert isinstance(mod.CARTRIDGE_SCHEMA_VERSION, str)

    def test_manifest_includes_schema_version(self):
        mod = _load_module()
        manifest = mod.generate_manifest(
            name="test", version="1.0.0",
            embedding_model="nomic-embed-text", fragment_count=1,
        )
        assert "schema_version" in manifest
        assert manifest["schema_version"] == mod.CARTRIDGE_SCHEMA_VERSION

    def test_schema_version_is_semver(self):
        """Schema version should look like X.Y.Z."""
        mod = _load_module()
        parts = mod.CARTRIDGE_SCHEMA_VERSION.split(".")
        assert len(parts) == 3
        for p in parts:
            assert p.isdigit()


class TestEmbeddingCompatibility:

    def test_same_model_is_compatible(self):
        mod = _load_module()
        assert mod.check_embedding_compatibility("nomic-embed-text", "nomic-embed-text") is True

    def test_different_model_is_incompatible(self):
        mod = _load_module()
        assert mod.check_embedding_compatibility("nomic-embed-text", "text-embedding-3-small") is False

    def test_none_cartridge_model_is_compatible(self):
        """Legacy cartridges with no model info should be accepted (best-effort)."""
        mod = _load_module()
        assert mod.check_embedding_compatibility(None, "nomic-embed-text") is True

    def test_none_local_model_is_incompatible(self):
        """If we don't know our own model, reject."""
        mod = _load_module()
        assert mod.check_embedding_compatibility("nomic-embed-text", None) is False
