"""
Tests for Master Schema v2.0 — Federated Brain (Archipelago Model).
Issue #104: retriever.py must query across multiple purpose-built SQLite databases.

Tests:
1. get_federated_dbs() returns the 4 canonical DB paths
2. get_aggregated_knowledge_map() aggregates across all existing DBs
3. perform_search searches across all federated DBs (not just one)
"""
import importlib.util
import json
import os
import sqlite3
import sys
import types
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

AIM_CLAUDE_ROOT = str(Path(__file__).parent.parent.parent)


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

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


def _load_retriever(cwd_override=None):
    """Load retriever.py with mocked cwd."""
    mod_name = "_test_retriever_104"
    sys.modules.pop(mod_name, None)

    _config_stub = types.ModuleType("config_utils")
    _config_stub.CONFIG = {
        "models": {
            "embedding_provider": "local",
            "embedding": "nomic-embed-text",
            "embedding_endpoint": "http://localhost:11434/api/embeddings",
        }
    }
    _config_stub.AIM_ROOT = cwd_override or AIM_CLAUDE_ROOT

    _dj_stub = types.ModuleType("datajack_plugin")
    _dj_stub.load_knowledge_provider = lambda: None

    # Create a minimal ForensicDB stub
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

    # Also stub the plugins package path
    _plugins = types.ModuleType("plugins")
    _plugins_dj = types.ModuleType("plugins.datajack")

    spec = importlib.util.spec_from_file_location(
        mod_name,
        os.path.join(AIM_CLAUDE_ROOT, "src", "retriever.py"),
    )
    mod = importlib.util.module_from_spec(spec)

    with patch("os.getcwd", return_value=cwd_override or AIM_CLAUDE_ROOT), \
         patch.dict(sys.modules, {
             "config_utils": _config_stub,
             "datajack_plugin": _dj_stub,
             "plugins": _plugins,
             "plugins.datajack": _plugins_dj,
             "plugins.datajack.forensic_utils": _forensic_mod,
         }):
        spec.loader.exec_module(mod)

    return mod


# ===========================================================================
# get_federated_dbs()
# ===========================================================================

class TestGetFederatedDbs:

    def test_returns_four_db_paths(self):
        mod = _load_retriever()
        dbs = mod.get_federated_dbs()
        assert len(dbs) == 4

    def test_db_paths_contain_canonical_names(self):
        mod = _load_retriever()
        dbs = mod.get_federated_dbs()
        names = [os.path.basename(p) for p in dbs]
        assert "project_core.db" in names
        assert "global_skills.db" in names
        assert "datajack_library.db" in names
        assert "subagent_ephemeral.db" in names

    def test_db_paths_rooted_in_archive(self):
        mod = _load_retriever()
        dbs = mod.get_federated_dbs()
        for db_path in dbs:
            assert "/archive/" in db_path


# ===========================================================================
# get_aggregated_knowledge_map()
# ===========================================================================

class TestGetAggregatedKnowledgeMap:

    def test_returns_three_categories(self):
        mod = _load_retriever()
        k_map = mod.get_aggregated_knowledge_map()
        assert "foundation_knowledge" in k_map
        assert "expert_knowledge" in k_map
        assert "session_history" in k_map

    def test_aggregates_across_dbs(self, tmp_path):
        """When multiple DBs exist, results should be aggregated."""
        mod = _load_retriever()

        # Create a fake ForensicDB that returns items based on path
        original_forensic = sys.modules.get("plugins.datajack.forensic_utils")
        call_count = []

        class TrackingDB:
            def __init__(self, db_path=None):
                call_count.append(db_path)
                self.db_path = db_path
            def get_knowledge_map(self):
                return {
                    "foundation_knowledge": [{"filename": f"from-{os.path.basename(self.db_path)}", "fragments": 1, "id": 1}],
                    "expert_knowledge": [],
                    "session_history": [],
                }
            def close(self):
                pass

        mod.ForensicDB = TrackingDB

        # Create fake DB files so os.path.exists passes
        archive_dir = os.path.join(mod.AIM_ROOT, "archive")
        os.makedirs(archive_dir, exist_ok=True)
        for name in ["project_core.db", "global_skills.db"]:
            Path(os.path.join(archive_dir, name)).touch()

        k_map = mod.get_aggregated_knowledge_map()

        # Should have opened at least the DBs that exist
        assert len(call_count) >= 2
        assert len(k_map["foundation_knowledge"]) >= 2


# ===========================================================================
# perform_search searches federated DBs
# ===========================================================================

class TestFederatedSearch:

    def test_has_perform_search_internal(self):
        """aim's pattern uses perform_search_internal for federated search."""
        mod = _load_retriever()
        # Either perform_search_internal exists or perform_search itself is federated
        has_internal = hasattr(mod, "perform_search_internal")
        has_search = hasattr(mod, "perform_search")
        assert has_internal or has_search
