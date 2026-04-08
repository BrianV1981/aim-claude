"""
Tests for Heuristic Search Mandate (#96).

Validates:
1. Low-relevance results are pruned below semantic_pruning_threshold
2. Mandate results bypass the threshold (always included)
3. The threshold is configurable via CONFIG
"""
import importlib.util
import os
import sys
import types
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


def _load_retriever(threshold=0.85):
    mod_name = "_test_retriever_96"
    sys.modules.pop(mod_name, None)

    _config_stub = types.ModuleType("config_utils")
    _config_stub.CONFIG = {
        "models": {
            "embedding_provider": "local",
            "embedding": "nomic-embed-text",
            "embedding_endpoint": "http://localhost:11434/api/embeddings",
        },
        "settings": {
            "semantic_pruning_threshold": threshold,
        }
    }
    _config_stub.AIM_ROOT = AIM_CLAUDE_ROOT

    _forensic_mod = types.ModuleType("plugins.datajack.forensic_utils")
    _forensic_mod.get_embedding = MagicMock(return_value=[0.1] * 768)

    class FakeForensicDB:
        def __init__(self, db_path=None):
            self.db_path = db_path
        def get_knowledge_map(self):
            return {"foundation_knowledge": [], "expert_knowledge": [], "session_history": []}
        def search_fragments(self, *a, **k):
            return []
        def search_lexical(self, *a, **k):
            return []
        def search_by_source_keyword(self, *a, **k):
            return []
        def close(self):
            pass

    _forensic_mod.ForensicDB = FakeForensicDB

    _plugins = types.ModuleType("plugins")
    _plugins_dj = types.ModuleType("plugins.datajack")

    spec = importlib.util.spec_from_file_location(
        mod_name,
        os.path.join(AIM_CLAUDE_ROOT, "src", "retriever.py"),
    )
    mod = importlib.util.module_from_spec(spec)

    with patch("os.getcwd", return_value=AIM_CLAUDE_ROOT), \
         patch.dict(sys.modules, {
             "config_utils": _config_stub,
             "plugins": _plugins,
             "plugins.datajack": _plugins_dj,
             "plugins.datajack.forensic_utils": _forensic_mod,
         }):
        spec.loader.exec_module(mod)

    return mod


class TestSemanticPruningThreshold:

    def test_low_score_results_pruned(self):
        """Results below semantic_pruning_threshold should be excluded."""
        mod = _load_retriever(threshold=0.5)
        results = [
            {"content": "high", "score": 0.9, "type": "session", "priority": False},
            {"content": "low", "score": 0.2, "type": "session", "priority": False},
        ]
        pruned = mod.apply_relevance_threshold(results, threshold=0.5)
        assert len(pruned) == 1
        assert pruned[0]["content"] == "high"

    def test_mandate_results_bypass_threshold(self):
        """Mandate (priority) results should never be pruned."""
        mod = _load_retriever(threshold=0.8)
        results = [
            {"content": "mandate", "score": 0.3, "type": "foundation_knowledge", "priority": True},
            {"content": "normal", "score": 0.3, "type": "session", "priority": False},
        ]
        pruned = mod.apply_relevance_threshold(results, threshold=0.8)
        assert len(pruned) == 1
        assert pruned[0]["content"] == "mandate"

    def test_threshold_zero_keeps_all(self):
        """Threshold of 0 should keep everything."""
        mod = _load_retriever(threshold=0.0)
        results = [
            {"content": "a", "score": 0.01, "type": "session", "priority": False},
            {"content": "b", "score": 0.99, "type": "session", "priority": False},
        ]
        pruned = mod.apply_relevance_threshold(results, threshold=0.0)
        assert len(pruned) == 2

    def test_threshold_loaded_from_config(self):
        """The threshold should be readable from CONFIG."""
        mod = _load_retriever(threshold=0.42)
        threshold = mod.CONFIG.get("settings", {}).get("semantic_pruning_threshold", 0.85)
        assert threshold == 0.42
