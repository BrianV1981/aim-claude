"""
Tests for Forum & Issue Ingestion Pipeline (#94).

Validates:
1. parse_github_issue() extracts structured fragments from issue JSON
2. deduplicate_against_existing() prevents re-ingesting known content
3. format_as_fragments() produces engram-compatible fragment dicts
"""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

AIM_CLAUDE_ROOT = str(Path(__file__).parent.parent.parent)


def _load_module():
    mod_name = "_test_ingestion_94"
    sys.modules.pop(mod_name, None)
    spec = importlib.util.spec_from_file_location(
        mod_name,
        os.path.join(AIM_CLAUDE_ROOT, "src", "issue_ingestion.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SAMPLE_ISSUE = {
    "number": 42,
    "title": "Fix memory leak in retriever",
    "body": "The retriever leaks memory when processing large queries.",
    "labels": [{"name": "bug"}],
    "state": "open",
    "comments": [
        {"body": "I can reproduce this with 10k fragments."},
        {"body": "Fixed in PR #43."},
    ],
}


class TestParseGithubIssue:

    def test_extracts_title_and_body(self):
        mod = _load_module()
        fragments = mod.parse_github_issue(SAMPLE_ISSUE)
        content = " ".join(f["content"] for f in fragments)
        assert "memory leak" in content.lower()

    def test_includes_comments(self):
        mod = _load_module()
        fragments = mod.parse_github_issue(SAMPLE_ISSUE)
        content = " ".join(f["content"] for f in fragments)
        assert "reproduce" in content.lower()

    def test_fragment_type_is_community_knowledge(self):
        mod = _load_module()
        fragments = mod.parse_github_issue(SAMPLE_ISSUE)
        for f in fragments:
            assert f["type"] == "community_knowledge"

    def test_includes_issue_number(self):
        mod = _load_module()
        fragments = mod.parse_github_issue(SAMPLE_ISSUE)
        assert any(f.get("source", "").endswith("#42") for f in fragments)

    def test_empty_body_handled(self):
        mod = _load_module()
        issue = {"number": 1, "title": "Title only", "body": None, "labels": [], "state": "open", "comments": []}
        fragments = mod.parse_github_issue(issue)
        assert len(fragments) >= 1


class TestDeduplicateAgainstExisting:

    def test_removes_known_content(self):
        mod = _load_module()
        existing_hashes = {"abc123"}
        fragments = [
            {"content": "new stuff", "content_hash": "new456"},
            {"content": "old stuff", "content_hash": "abc123"},
        ]
        result = mod.deduplicate_against_existing(fragments, existing_hashes)
        assert len(result) == 1
        assert result[0]["content"] == "new stuff"

    def test_keeps_all_if_no_overlap(self):
        mod = _load_module()
        fragments = [
            {"content": "a", "content_hash": "h1"},
            {"content": "b", "content_hash": "h2"},
        ]
        result = mod.deduplicate_against_existing(fragments, set())
        assert len(result) == 2

    def test_empty_fragments(self):
        mod = _load_module()
        assert mod.deduplicate_against_existing([], {"h1"}) == []
