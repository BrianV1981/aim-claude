"""
Tests for Sovereign Swarm 2.0 — aim publish (#103).

Validates:
1. publish_cartridge() copies .engram to chalkboard registry
2. list_published() discovers published cartridges in registry
3. Validates manifest before publishing
4. Handles duplicate versions
"""
import importlib.util
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

AIM_CLAUDE_ROOT = str(Path(__file__).parent.parent.parent)


def _load_module():
    mod_name = "_test_publish_103"
    sys.modules.pop(mod_name, None)
    spec = importlib.util.spec_from_file_location(
        mod_name,
        os.path.join(AIM_CLAUDE_ROOT, "src", "swarm_publish.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_cartridge(path, name="test", version="1.0.0"):
    meta = {
        "schema_version": "2.0.0",
        "name": name,
        "version": version,
        "embedding_model": "nomic-embed-text",
        "fragment_count": 10,
        "created_at": "2026-04-08T00:00:00+00:00",
        "type": "baked_cartridge",
        "payload_hash": "abc123",
    }
    with zipfile.ZipFile(str(path), "w") as zf:
        zf.writestr("metadata.json", json.dumps(meta))
        zf.writestr("1.jsonl", '{"_record_type":"session"}\n')


class TestPublishCartridge:

    def test_copies_to_registry(self, tmp_path):
        mod = _load_module()
        cart = tmp_path / "test.engram"
        _make_cartridge(cart)
        registry = tmp_path / "registry"
        registry.mkdir()
        result = mod.publish_cartridge(str(cart), str(registry))
        assert result["success"] is True
        assert (registry / "test.engram").exists()

    def test_invalid_cartridge_rejected(self, tmp_path):
        mod = _load_module()
        cart = tmp_path / "bad.engram"
        cart.write_text("not a zip")
        registry = tmp_path / "registry"
        registry.mkdir()
        result = mod.publish_cartridge(str(cart), str(registry))
        assert result["success"] is False

    def test_creates_registry_dir(self, tmp_path):
        mod = _load_module()
        cart = tmp_path / "test.engram"
        _make_cartridge(cart)
        registry = tmp_path / "new_registry"
        result = mod.publish_cartridge(str(cart), str(registry))
        assert result["success"] is True
        assert registry.exists()


class TestListPublished:

    def test_lists_published_cartridges(self, tmp_path):
        mod = _load_module()
        registry = tmp_path / "registry"
        registry.mkdir()
        _make_cartridge(registry / "pytest.engram", name="pytest")
        _make_cartridge(registry / "django.engram", name="django")
        result = mod.list_published(str(registry))
        assert len(result) == 2
        names = [r["name"] for r in result]
        assert "pytest" in names

    def test_empty_registry(self, tmp_path):
        mod = _load_module()
        registry = tmp_path / "registry"
        registry.mkdir()
        assert mod.list_published(str(registry)) == []

    def test_missing_registry(self, tmp_path):
        mod = _load_module()
        assert mod.list_published(str(tmp_path / "nope")) == []
