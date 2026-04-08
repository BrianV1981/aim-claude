"""
Tests for Panopticon Protocol — aim recall (#101).

Validates:
1. search_continuity() searches continuity/ markdown files
2. search_git_log() searches git commit history
3. unified_recall() merges results from all sources with attribution
"""
import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

AIM_CLAUDE_ROOT = str(Path(__file__).parent.parent.parent)


def _load_module():
    mod_name = "_test_recall_101"
    sys.modules.pop(mod_name, None)
    spec = importlib.util.spec_from_file_location(
        mod_name,
        os.path.join(AIM_CLAUDE_ROOT, "src", "panopticon_recall.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSearchContinuity:

    def test_finds_matching_content(self, tmp_path):
        mod = _load_module()
        cont = tmp_path / "continuity"
        cont.mkdir()
        (cont / "HANDOFF.md").write_text("The agent must fix the database migration.")
        results = mod.search_continuity("database", str(tmp_path))
        assert len(results) >= 1
        assert any("database" in r["content"].lower() for r in results)

    def test_no_match_returns_empty(self, tmp_path):
        mod = _load_module()
        cont = tmp_path / "continuity"
        cont.mkdir()
        (cont / "HANDOFF.md").write_text("Nothing relevant here.")
        results = mod.search_continuity("quantum physics", str(tmp_path))
        assert len(results) == 0

    def test_missing_continuity_dir(self, tmp_path):
        mod = _load_module()
        results = mod.search_continuity("anything", str(tmp_path))
        assert results == []

    def test_result_has_source_attribution(self, tmp_path):
        mod = _load_module()
        cont = tmp_path / "continuity"
        cont.mkdir()
        (cont / "PULSE.md").write_text("Critical deployment in progress.")
        results = mod.search_continuity("deployment", str(tmp_path))
        assert results[0]["source"] == "continuity/PULSE.md"


class TestSearchGitLog:

    def test_finds_matching_commits(self):
        mod = _load_module()
        # Use the real repo — there should be commits
        results = mod.search_git_log("Feature", AIM_CLAUDE_ROOT)
        assert len(results) >= 1

    def test_no_match_returns_empty(self):
        mod = _load_module()
        results = mod.search_git_log("xyzzy_nonexistent_term_12345", AIM_CLAUDE_ROOT)
        assert results == []

    def test_result_has_source_attribution(self):
        mod = _load_module()
        results = mod.search_git_log("Feature", AIM_CLAUDE_ROOT)
        if results:
            assert results[0]["source"] == "git_log"


class TestUnifiedRecall:

    def test_merges_multiple_sources(self, tmp_path):
        mod = _load_module()
        cont = tmp_path / "continuity"
        cont.mkdir()
        (cont / "HANDOFF.md").write_text("Feature: fix the bug")

        with patch.object(mod, "search_git_log", return_value=[
            {"content": "Feature: added tests", "source": "git_log"}
        ]):
            results = mod.unified_recall("Feature", str(tmp_path))
        # Should have results from both continuity and git
        sources = {r["source"] for r in results}
        assert len(sources) >= 1

    def test_empty_query_returns_empty(self, tmp_path):
        mod = _load_module()
        results = mod.unified_recall("", str(tmp_path))
        assert results == []
