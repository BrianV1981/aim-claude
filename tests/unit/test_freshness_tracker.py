"""
Tests for Self-Upgrading Engrams — Freshness Tracker (#98).

Validates:
1. hash_source_files() creates a dict of file -> sha256 hash
2. detect_stale_files() compares stored vs current hashes
3. Handles new files, modified files, deleted files
4. Empty directory returns empty dict
"""
import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest

AIM_CLAUDE_ROOT = str(Path(__file__).parent.parent.parent)


def _load_module():
    mod_name = "_test_freshness_98"
    sys.modules.pop(mod_name, None)
    spec = importlib.util.spec_from_file_location(
        mod_name,
        os.path.join(AIM_CLAUDE_ROOT, "src", "plugins", "datajack", "freshness_tracker.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestHashSourceFiles:

    def test_hashes_files_in_directory(self, tmp_path):
        mod = _load_module()
        (tmp_path / "readme.md").write_text("hello")
        (tmp_path / "code.py").write_text("print(1)")
        result = mod.hash_source_files(str(tmp_path))
        assert len(result) == 2
        assert "readme.md" in result
        assert "code.py" in result

    def test_hash_is_sha256_hex(self, tmp_path):
        mod = _load_module()
        (tmp_path / "a.md").write_text("test")
        result = mod.hash_source_files(str(tmp_path))
        assert len(result["a.md"]) == 64  # sha256 hex length

    def test_empty_directory(self, tmp_path):
        mod = _load_module()
        assert mod.hash_source_files(str(tmp_path)) == {}

    def test_ignores_non_text_files(self, tmp_path):
        mod = _load_module()
        (tmp_path / "doc.md").write_text("text")
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        result = mod.hash_source_files(str(tmp_path))
        assert "doc.md" in result
        assert "image.png" not in result

    def test_recursive_subdirectories(self, tmp_path):
        mod = _load_module()
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.py").write_text("x = 1")
        result = mod.hash_source_files(str(tmp_path))
        assert any("nested.py" in k for k in result)


class TestDetectStaleFiles:

    def test_no_changes(self, tmp_path):
        mod = _load_module()
        (tmp_path / "a.md").write_text("hello")
        stored = mod.hash_source_files(str(tmp_path))
        result = mod.detect_stale_files(stored, str(tmp_path))
        assert result["modified"] == []
        assert result["added"] == []
        assert result["deleted"] == []

    def test_modified_file(self, tmp_path):
        mod = _load_module()
        f = tmp_path / "a.md"
        f.write_text("version 1")
        stored = mod.hash_source_files(str(tmp_path))
        f.write_text("version 2")
        result = mod.detect_stale_files(stored, str(tmp_path))
        assert "a.md" in result["modified"]

    def test_added_file(self, tmp_path):
        mod = _load_module()
        stored = mod.hash_source_files(str(tmp_path))
        (tmp_path / "new.py").write_text("new code")
        result = mod.detect_stale_files(stored, str(tmp_path))
        assert "new.py" in result["added"]

    def test_deleted_file(self, tmp_path):
        mod = _load_module()
        f = tmp_path / "old.md"
        f.write_text("old content")
        stored = mod.hash_source_files(str(tmp_path))
        f.unlink()
        result = mod.detect_stale_files(stored, str(tmp_path))
        assert "old.md" in result["deleted"]

    def test_mixed_changes(self, tmp_path):
        mod = _load_module()
        (tmp_path / "keep.md").write_text("same")
        (tmp_path / "change.py").write_text("v1")
        (tmp_path / "remove.txt").write_text("bye")
        stored = mod.hash_source_files(str(tmp_path))

        (tmp_path / "change.py").write_text("v2")
        (tmp_path / "remove.txt").unlink()
        (tmp_path / "brand_new.md").write_text("hi")

        result = mod.detect_stale_files(stored, str(tmp_path))
        assert "change.py" in result["modified"]
        assert "remove.txt" in result["deleted"]
        assert "brand_new.md" in result["added"]
        assert "keep.md" not in result["modified"]
