"""
Integration tests: engram creation -> search pipeline.

Covers:
- ForensicDB schema initialisation in a temp DB
- Fragment insertion via add_session / add_fragments
- Semantic search (cosine similarity against a fake embedding)
- Lexical / BM25 search via FTS5
- perform_search end-to-end with embedding endpoint mocked

No real LLM or network calls are made.
"""

import importlib.util
import io
import json
import os
import sqlite3
import struct
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Stub heavy deps so ForensicDB can be imported without google/keyring/requests
# ---------------------------------------------------------------------------

def _stub_module(name):
    mod = types.ModuleType(name)
    sys.modules.setdefault(name, mod)
    return mod

for _m in ["google", "google.genai"]:
    _stub_module(_m)
# Note: requests IS installed — do not stub it.
# keyring is NOT installed — stub it with the attributes unit tests patch.
if "keyring" not in sys.modules:
    _kr = types.ModuleType("keyring")
    _kr.get_password = lambda *a, **k: None
    _kr.set_password = lambda *a, **k: None
    sys.modules["keyring"] = _kr

# Stub config_utils before any aim src import
_config_stub = types.ModuleType("config_utils")
_config_stub.CONFIG = {
    "models": {
        "embedding_provider": "local",
        "embedding": "nomic-embed-text",
        "embedding_endpoint": "http://localhost:11434/api/embeddings",
    }
}

AIM_SRC = str(Path(__file__).parent.parent.parent / "src")  # symlink -> /home/kingb/aim/src
_config_stub.AIM_ROOT = str(Path(AIM_SRC).parent)
sys.modules["config_utils"] = _config_stub

# Make sure aim src is importable
if AIM_SRC not in sys.path:
    sys.path.insert(0, AIM_SRC)

# Stub plugins package skeleton so sub-imports resolve
for _pkg in ["plugins", "plugins.datajack"]:
    sys.modules.setdefault(_pkg, types.ModuleType(_pkg))

# Now load the real ForensicDB from source
_forensic_spec = importlib.util.spec_from_file_location(
    "plugins.datajack.forensic_utils",
    os.path.join(AIM_SRC, "plugins", "datajack", "forensic_utils.py"),
)
_forensic_mod = importlib.util.module_from_spec(_forensic_spec)
# Patch internal imports that forensic_utils needs
with patch.dict(sys.modules, {"config_utils": _config_stub}):
    _forensic_spec.loader.exec_module(_forensic_mod)

sys.modules["plugins.datajack.forensic_utils"] = _forensic_mod
ForensicDB = _forensic_mod.ForensicDB
cosine_similarity = _forensic_mod.cosine_similarity

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_DIM = 4  # tiny embedding dimension for speed

def _make_vec(*values):
    return list(values)

def _unit_vec(index, dim=FAKE_DIM):
    """Returns a unit vector with 1.0 at `index` and 0.0 elsewhere."""
    v = [0.0] * dim
    v[index] = 1.0
    return v


# ---------------------------------------------------------------------------
# 1. ForensicDB schema and basic CRUD
# ---------------------------------------------------------------------------

class TestForensicDBSchema(unittest.TestCase):

    def setUp(self):
        # Use an in-memory SQLite for isolation (pass ":memory:" via custom_path)
        self.db = ForensicDB(custom_path=":memory:")

    def tearDown(self):
        self.db.close()

    def _table_names(self):
        rows = self.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'shadow')"
        ).fetchall()
        return {r[0] for r in rows}

    def test_sessions_table_exists(self):
        self.assertIn("sessions", self._table_names())

    def test_fragments_table_exists(self):
        self.assertIn("fragments", self._table_names())

    def test_fts5_virtual_table_exists(self):
        self.assertIn("fragments_fts", self._table_names())

    def test_add_session_persists(self):
        self.db.add_session("sess-001", "test.jsonl", 1234567890.0)
        row = self.db.conn.execute(
            "SELECT id, filename FROM sessions WHERE id = ?", ("sess-001",)
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[1], "test.jsonl")

    def test_add_fragments_persists(self):
        self.db.add_session("sess-001", "test.jsonl", 0)
        self.db.add_fragments("sess-001", [
            {"type": "expert_knowledge", "content": "Fragment Alpha", "embedding": None}
        ])
        row = self.db.conn.execute(
            "SELECT content FROM fragments WHERE session_id = ?", ("sess-001",)
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "Fragment Alpha")

    def test_add_fragments_populates_fts(self):
        self.db.add_session("sess-002", "fts_test.jsonl", 0)
        self.db.add_fragments("sess-002", [
            {"type": "expert_knowledge", "content": "Forensic memory Alpha", "embedding": None}
        ])
        rows = self.db.conn.execute(
            "SELECT content FROM fragments_fts WHERE fragments_fts MATCH 'Forensic'",
        ).fetchall()
        self.assertTrue(len(rows) >= 1)

    def test_add_fragments_replaces_on_reingest(self):
        self.db.add_session("sess-003", "test.jsonl", 0)
        self.db.add_fragments("sess-003", [
            {"type": "expert_knowledge", "content": "Original", "embedding": None}
        ])
        # Re-ingest with different content
        self.db.add_fragments("sess-003", [
            {"type": "expert_knowledge", "content": "Updated", "embedding": None}
        ])
        rows = self.db.conn.execute(
            "SELECT content FROM fragments WHERE session_id = ?", ("sess-003",)
        ).fetchall()
        contents = [r[0] for r in rows]
        self.assertIn("Updated", contents)
        self.assertNotIn("Original", contents)


# ---------------------------------------------------------------------------
# 2. Semantic search (cosine similarity via search_fragments)
# ---------------------------------------------------------------------------

class TestSemanticSearch(unittest.TestCase):

    def setUp(self):
        self.db = ForensicDB(custom_path=":memory:")

    def tearDown(self):
        self.db.close()

    def _insert(self, session_id, content, embedding):
        self.db.add_session(session_id, f"{session_id}.jsonl", 0)
        self.db.add_fragments(session_id, [
            {"type": "expert_knowledge", "content": content, "embedding": embedding}
        ])

    def test_perfect_match_returns_score_1(self):
        vec = _unit_vec(0)
        self._insert("s1", "perfect match fragment", vec)
        results = self.db.search_fragments(vec, top_k=5)
        self.assertEqual(len(results), 1)
        self.assertAlmostEqual(results[0]["score"], 1.0, places=4)

    def test_orthogonal_vector_returns_score_0(self):
        self._insert("s2", "unrelated fragment", _unit_vec(0))
        results = self.db.search_fragments(_unit_vec(1), top_k=5)
        self.assertEqual(len(results), 1)
        self.assertAlmostEqual(results[0]["score"], 0.0, places=4)

    def test_results_sorted_by_score_descending(self):
        self._insert("s3", "close fragment", _make_vec(1.0, 0.5, 0.0, 0.0))
        self._insert("s4", "far fragment",  _make_vec(0.0, 0.0, 1.0, 0.0))
        query = _make_vec(1.0, 0.5, 0.0, 0.0)
        results = self.db.search_fragments(query, top_k=5)
        self.assertGreaterEqual(results[0]["score"], results[1]["score"])

    def test_top_k_limits_results(self):
        for i in range(5):
            self._insert(f"s{i+10}", f"fragment {i}", _unit_vec(i % FAKE_DIM))
        results = self.db.search_fragments(_unit_vec(0), top_k=2)
        self.assertLessEqual(len(results), 2)

    def test_fragment_without_embedding_scores_zero(self):
        self._insert("s20", "no embedding fragment", None)
        results = self.db.search_fragments(_unit_vec(0), top_k=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["score"], 0.0)

    def test_result_contains_expected_fields(self):
        self._insert("s21", "test content", _unit_vec(0))
        results = self.db.search_fragments(_unit_vec(0), top_k=1)
        r = results[0]
        self.assertIn("score", r)
        self.assertIn("content", r)
        self.assertIn("type", r)


# ---------------------------------------------------------------------------
# 3. Lexical / BM25 search via FTS5
# ---------------------------------------------------------------------------

class TestLexicalSearch(unittest.TestCase):

    def setUp(self):
        self.db = ForensicDB(custom_path=":memory:")
        self.db.add_session("lex-01", "lexical.jsonl", 0)
        self.db.add_fragments("lex-01", [
            {"type": "expert_knowledge", "content": "Hybrid RAG pipeline with BM25 ranking", "embedding": None},
            {"type": "expert_knowledge", "content": "Temporal decay exponential function", "embedding": None},
        ])

    def tearDown(self):
        self.db.close()

    def test_exact_term_match_returns_result(self):
        results = self.db.search_lexical("BM25", top_k=5)
        self.assertTrue(len(results) >= 1)
        self.assertTrue(any("BM25" in r["content"] for r in results))

    def test_non_matching_term_returns_empty(self):
        results = self.db.search_lexical("XYZZY_NONEXISTENT_TOKEN", top_k=5)
        self.assertEqual(results, [])

    def test_lexical_result_has_score_field(self):
        results = self.db.search_lexical("Hybrid", top_k=5)
        self.assertTrue(len(results) >= 1)
        self.assertIn("score", results[0])

    def test_lexical_result_has_is_lexical_flag(self):
        results = self.db.search_lexical("Hybrid", top_k=5)
        self.assertTrue(results[0].get("is_lexical", False))

    def test_score_is_normalised_to_0_1_range(self):
        results = self.db.search_lexical("Hybrid", top_k=5)
        for r in results:
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 1.0)

    def test_case_insensitive_match(self):
        results = self.db.search_lexical("hybrid", top_k=5)
        self.assertTrue(len(results) >= 1)


# ---------------------------------------------------------------------------
# 4. perform_search end-to-end (mocked embedding endpoint)
# ---------------------------------------------------------------------------

class TestPerformSearchIntegration(unittest.TestCase):
    """
    Loads retriever.py via importlib so we can swap its DB and embedding
    dependencies without polluting other tests.
    """

    def _load_retriever(self):
        retriever_path = os.path.join(AIM_SRC, "retriever.py")
        spec = importlib.util.spec_from_file_location("retriever_integration", retriever_path)
        mod = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "config_utils": _config_stub,
            "plugins.datajack.forensic_utils": _forensic_mod,
        }):
            spec.loader.exec_module(mod)
        return mod

    def setUp(self):
        self.db = ForensicDB(custom_path=":memory:")
        # Insert two fragments with distinct embeddings
        self.db.add_session("integ-01", "policy_handbook.md", 0)
        self.db.add_fragments("integ-01", [
            {
                "type": "expert_knowledge",
                "content": "The hybrid RAG pipeline combines semantic and BM25 search.",
                "embedding": _unit_vec(0),
                "timestamp": None,
            }
        ])
        self.db.add_session("integ-02", "session_history.jsonl", 0)
        self.db.add_fragments("integ-02", [
            {
                "type": "session",
                "content": "Temporal decay penalises older memories.",
                "embedding": _unit_vec(1),
                "timestamp": None,
            }
        ])

    def tearDown(self):
        self.db.close()

    def _run(self, query, query_vec=None, top_k=10):
        """Run perform_search with mocked DB and embedding."""
        retriever = self._load_retriever()
        fake_vec = query_vec if query_vec is not None else _unit_vec(0)

        with patch.object(retriever, "ForensicDB", return_value=self.db), \
             patch.object(retriever, "get_embedding", return_value=fake_vec), \
             patch("sys.stdout", new_callable=io.StringIO) as captured:
            retriever.perform_search(query, top_k=top_k)
        return captured.getvalue()

    def test_matching_fragment_appears_in_output(self):
        output = self._run("hybrid RAG pipeline", query_vec=_unit_vec(0))
        self.assertIn("hybrid RAG pipeline", output)

    def test_output_contains_score_line(self):
        output = self._run("hybrid RAG pipeline", query_vec=_unit_vec(0))
        self.assertIn("Score:", output)

    def test_no_results_message_when_db_empty(self):
        empty_db = ForensicDB(custom_path=":memory:")
        retriever = self._load_retriever()
        with patch.object(retriever, "ForensicDB", return_value=empty_db), \
             patch.object(retriever, "get_embedding", return_value=_unit_vec(0)), \
             patch("sys.stdout", new_callable=io.StringIO) as captured:
            retriever.perform_search("anything", top_k=5)
        empty_db.close()
        self.assertIn("No forensic record", captured.getvalue())

    def test_failed_embedding_prints_error(self):
        retriever = self._load_retriever()
        with patch.object(retriever, "ForensicDB", return_value=self.db), \
             patch.object(retriever, "get_embedding", return_value=None), \
             patch("sys.stdout", new_callable=io.StringIO) as captured:
            retriever.perform_search("query", top_k=5)
        self.assertIn("Error", captured.getvalue())

    def test_both_semantic_and_lexical_are_called(self):
        """
        Verify the hybrid pipeline calls both search_fragments (semantic)
        and search_lexical (BM25) on the DB provider.
        """
        retriever = self._load_retriever()
        spy_db = MagicMock(wraps=self.db)
        with patch.object(retriever, "ForensicDB", return_value=spy_db), \
             patch.object(retriever, "get_embedding", return_value=_unit_vec(0)), \
             patch("sys.stdout", new_callable=io.StringIO):
            retriever.perform_search("hybrid", top_k=5)
        spy_db.search_fragments.assert_called_once()
        spy_db.search_lexical.assert_called_once()

    def test_top_k_caps_output_results(self):
        """With top_k=1 only the highest scoring result should be printed."""
        # Insert a third session so there is genuine competition
        self.db.add_session("integ-03", "extra.jsonl", 0)
        self.db.add_fragments("integ-03", [
            {"type": "session", "content": "Extra fragment content.", "embedding": _unit_vec(2), "timestamp": None}
        ])
        retriever = self._load_retriever()
        with patch.object(retriever, "ForensicDB", return_value=self.db), \
             patch.object(retriever, "get_embedding", return_value=_unit_vec(0)), \
             patch("sys.stdout", new_callable=io.StringIO) as captured:
            retriever.perform_search("query", top_k=1)
        output = captured.getvalue()
        # Only one [1] block should appear
        self.assertEqual(output.count("[1]"), 1)
        self.assertEqual(output.count("[2]"), 0)

    def test_deduplication_prevents_double_results(self):
        """
        If the same fragment appears in both semantic and lexical results,
        it should only be printed once.
        """
        # Insert fragment that will match both semantic (vec=unit_vec(0)) and
        # lexical ("hybrid" keyword)
        self.db.add_session("integ-04", "dedup_test.jsonl", 0)
        self.db.add_fragments("integ-04", [
            {
                "type": "expert_knowledge",
                "content": "hybrid search dedup test marker",
                "embedding": _unit_vec(0),
                "timestamp": None,
            }
        ])
        retriever = self._load_retriever()
        with patch.object(retriever, "ForensicDB", return_value=self.db), \
             patch.object(retriever, "get_embedding", return_value=_unit_vec(0)), \
             patch("sys.stdout", new_callable=io.StringIO) as captured:
            retriever.perform_search("hybrid", top_k=20)
        output = captured.getvalue()
        self.assertEqual(output.count("hybrid search dedup test marker"), 1)


if __name__ == "__main__":
    unittest.main()
