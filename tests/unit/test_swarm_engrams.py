"""
Tests for Swarm-Synthesized Live Engrams (#100).

Validates:
1. create_fragment_contribution() creates a well-formed contribution
2. deduplicate_fragments() removes duplicate content
3. score_fragment_trust() assigns trust based on source agent
4. merge_contributions() combines fragments from multiple agents
"""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

AIM_CLAUDE_ROOT = str(Path(__file__).parent.parent.parent)


def _load_module():
    mod_name = "_test_swarm_100"
    sys.modules.pop(mod_name, None)
    spec = importlib.util.spec_from_file_location(
        mod_name,
        os.path.join(AIM_CLAUDE_ROOT, "src", "swarm_engrams.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestCreateFragmentContribution:

    def test_has_required_fields(self):
        mod = _load_module()
        frag = mod.create_fragment_contribution(
            content="pytest uses fixtures for dependency injection",
            source_agent="aim-claude",
            domain="testing",
        )
        assert "content" in frag
        assert "source_agent" in frag
        assert "domain" in frag
        assert "timestamp" in frag
        assert "content_hash" in frag

    def test_content_hash_is_deterministic(self):
        mod = _load_module()
        f1 = mod.create_fragment_contribution("same text", "agent1", "d")
        f2 = mod.create_fragment_contribution("same text", "agent2", "d")
        assert f1["content_hash"] == f2["content_hash"]

    def test_different_content_different_hash(self):
        mod = _load_module()
        f1 = mod.create_fragment_contribution("text A", "agent1", "d")
        f2 = mod.create_fragment_contribution("text B", "agent1", "d")
        assert f1["content_hash"] != f2["content_hash"]


class TestDeduplicateFragments:

    def test_removes_exact_duplicates(self):
        mod = _load_module()
        frags = [
            mod.create_fragment_contribution("duplicate", "a1", "d"),
            mod.create_fragment_contribution("duplicate", "a2", "d"),
            mod.create_fragment_contribution("unique", "a1", "d"),
        ]
        result = mod.deduplicate_fragments(frags)
        assert len(result) == 2

    def test_keeps_unique_fragments(self):
        mod = _load_module()
        frags = [
            mod.create_fragment_contribution("alpha", "a1", "d"),
            mod.create_fragment_contribution("beta", "a2", "d"),
        ]
        result = mod.deduplicate_fragments(frags)
        assert len(result) == 2

    def test_empty_list(self):
        mod = _load_module()
        assert mod.deduplicate_fragments([]) == []


class TestScoreFragmentTrust:

    def test_known_agent_gets_higher_trust(self):
        mod = _load_module()
        known = {"aim-claude": 1.0, "aim-codex": 0.8}
        score = mod.score_fragment_trust("aim-claude", known)
        assert score == 1.0

    def test_unknown_agent_gets_default_trust(self):
        mod = _load_module()
        known = {"aim-claude": 1.0}
        score = mod.score_fragment_trust("unknown-agent", known)
        assert 0 < score < 1.0


class TestMergeContributions:

    def test_merges_from_multiple_agents(self):
        mod = _load_module()
        batch1 = [mod.create_fragment_contribution("from claude", "aim-claude", "d")]
        batch2 = [mod.create_fragment_contribution("from codex", "aim-codex", "d")]
        merged = mod.merge_contributions([batch1, batch2])
        assert len(merged) == 2

    def test_deduplicates_across_batches(self):
        mod = _load_module()
        batch1 = [mod.create_fragment_contribution("shared knowledge", "aim-claude", "d")]
        batch2 = [mod.create_fragment_contribution("shared knowledge", "aim-codex", "d")]
        merged = mod.merge_contributions([batch1, batch2])
        assert len(merged) == 1
