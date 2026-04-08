"""
Tests for Generalized Debugging Cartridges (#95).

Validates:
1. list_cartridges() discovers .engram files in the engrams/ directory
2. validate_cartridge() checks structure (zip with metadata.json)
3. get_cartridge_info() returns metadata from a valid cartridge
4. Invalid/corrupt cartridges are gracefully handled
"""
import importlib.util
import json
import os
import sys
import types
import zipfile
from pathlib import Path
from unittest.mock import patch

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
    mod_name = "_test_cartridge_95"
    sys.modules.pop(mod_name, None)

    spec = importlib.util.spec_from_file_location(
        mod_name,
        os.path.join(AIM_CLAUDE_ROOT, "src", "plugins", "datajack", "cartridge_utils.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_cartridge(path, metadata=None, add_jsonl=True):
    """Helper: create a minimal .engram file (zip with metadata.json)."""
    if metadata is None:
        metadata = {
            "type": "baked_cartridge",
            "name": "test-cartridge",
            "version": "1.0.0",
            "payload_hash": "abc123",
            "fragments": 42,
        }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("metadata.json", json.dumps(metadata))
        if add_jsonl:
            zf.writestr("1.jsonl", '{"_record_type": "session", "session_id": 1}\n')


# ===========================================================================
# list_cartridges()
# ===========================================================================

class TestListCartridges:

    def test_finds_engram_files(self, tmp_path):
        mod = _load_module()
        engram_dir = tmp_path / "engrams"
        engram_dir.mkdir()
        (engram_dir / "pytest.engram").write_bytes(b"")
        (engram_dir / "django.engram").write_bytes(b"")
        (engram_dir / "readme.txt").write_bytes(b"")  # not an engram

        result = mod.list_cartridges(str(engram_dir))
        assert len(result) == 2
        names = [os.path.basename(p) for p in result]
        assert "pytest.engram" in names
        assert "django.engram" in names

    def test_empty_directory(self, tmp_path):
        mod = _load_module()
        engram_dir = tmp_path / "engrams"
        engram_dir.mkdir()
        assert mod.list_cartridges(str(engram_dir)) == []

    def test_missing_directory(self, tmp_path):
        mod = _load_module()
        assert mod.list_cartridges(str(tmp_path / "nonexistent")) == []


# ===========================================================================
# validate_cartridge()
# ===========================================================================

class TestValidateCartridge:

    def test_valid_cartridge(self, tmp_path):
        mod = _load_module()
        cart = tmp_path / "valid.engram"
        _make_cartridge(str(cart))
        assert mod.validate_cartridge(str(cart)) is True

    def test_missing_metadata(self, tmp_path):
        mod = _load_module()
        cart = tmp_path / "no_meta.engram"
        with zipfile.ZipFile(str(cart), "w") as zf:
            zf.writestr("data.jsonl", "{}\n")
        assert mod.validate_cartridge(str(cart)) is False

    def test_not_a_zip(self, tmp_path):
        mod = _load_module()
        cart = tmp_path / "corrupt.engram"
        cart.write_text("this is not a zip")
        assert mod.validate_cartridge(str(cart)) is False

    def test_nonexistent_file(self, tmp_path):
        mod = _load_module()
        assert mod.validate_cartridge(str(tmp_path / "ghost.engram")) is False


# ===========================================================================
# get_cartridge_info()
# ===========================================================================

class TestGetCartridgeInfo:

    def test_returns_metadata(self, tmp_path):
        mod = _load_module()
        cart = tmp_path / "info.engram"
        meta = {
            "type": "baked_cartridge",
            "name": "pytest",
            "version": "2.0.0",
            "payload_hash": "deadbeef",
            "fragments": 100,
        }
        _make_cartridge(str(cart), metadata=meta)
        info = mod.get_cartridge_info(str(cart))
        assert info["name"] == "pytest"
        assert info["version"] == "2.0.0"
        assert info["fragments"] == 100

    def test_invalid_cartridge_returns_none(self, tmp_path):
        mod = _load_module()
        cart = tmp_path / "bad.engram"
        cart.write_text("not a zip")
        assert mod.get_cartridge_info(str(cart)) is None

    def test_infers_name_from_filename(self, tmp_path):
        """If metadata has no 'name', infer from filename."""
        mod = _load_module()
        cart = tmp_path / "django.engram"
        meta = {"type": "baked_cartridge", "payload_hash": "abc", "fragments": 5}
        _make_cartridge(str(cart), metadata=meta)
        info = mod.get_cartridge_info(str(cart))
        assert info["name"] == "django"
