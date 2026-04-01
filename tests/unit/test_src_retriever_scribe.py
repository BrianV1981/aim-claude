"""
Unit tests for:
  - src/retriever.py     (calculate_temporal_decay, get_fragment_hash, perform_search)
  - src/history_scribe.py (HistoryDB, save_split_markdown, scribe_all_sessions)
"""
import hashlib
import io
import json
import math
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

# ── stub heavy deps before importing retriever ────────────────────────────────
for _mod in ["keyring", "requests", "google", "google.genai"]:
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)

_forensic_stub = types.ModuleType("plugins.datajack.forensic_utils")
_forensic_stub.get_embedding = MagicMock(return_value=[0.1, 0.2])
_forensic_stub.ForensicDB = object
_forensic_stub.chunk_text = lambda *a, **k: []
sys.modules.setdefault("plugins", types.ModuleType("plugins"))
sys.modules.setdefault("plugins.datajack", types.ModuleType("plugins.datajack"))
sys.modules["plugins.datajack.forensic_utils"] = _forensic_stub

SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import retriever
import history_scribe


# ─────────────────────────────────────────────────────────────────────────────
# retriever — calculate_temporal_decay
# ─────────────────────────────────────────────────────────────────────────────

class TestCalculateTemporalDecay(unittest.TestCase):
    def _ts(self, days_ago):
        dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
        return dt.isoformat()

    def test_zero_days_no_decay(self):
        score = retriever.calculate_temporal_decay(1.0, self._ts(0))
        self.assertAlmostEqual(score, 1.0, places=2)

    def test_score_decays_with_age(self):
        score_old = retriever.calculate_temporal_decay(1.0, self._ts(70))
        score_new = retriever.calculate_temporal_decay(1.0, self._ts(1))
        self.assertLess(score_old, score_new)

    def test_decay_is_exponential_not_linear(self):
        # At 70 days with rate=0.01, decay_factor ≈ e^(-0.7) ≈ 0.497
        score = retriever.calculate_temporal_decay(1.0, self._ts(70))
        expected = math.exp(-0.01 * 70)
        self.assertAlmostEqual(score, expected, places=2)

    def test_score_never_below_zero(self):
        score = retriever.calculate_temporal_decay(1.0, self._ts(10000))
        self.assertGreaterEqual(score, 0.0)

    def test_none_timestamp_returns_original_score(self):
        score = retriever.calculate_temporal_decay(0.75, None)
        self.assertEqual(score, 0.75)

    def test_empty_timestamp_returns_original_score(self):
        score = retriever.calculate_temporal_decay(0.5, "")
        self.assertEqual(score, 0.5)

    def test_invalid_timestamp_returns_original_score(self):
        score = retriever.calculate_temporal_decay(0.9, "not-a-date")
        self.assertEqual(score, 0.9)

    def test_z_suffix_timestamp_handled(self):
        ts = (datetime.now(timezone.utc) - timedelta(days=10)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
        score = retriever.calculate_temporal_decay(1.0, ts)
        expected = math.exp(-0.01 * 10)
        self.assertAlmostEqual(score, expected, delta=0.05)

    def test_custom_decay_rate(self):
        score = retriever.calculate_temporal_decay(1.0, self._ts(10), decay_rate=0.1)
        expected = math.exp(-0.1 * 10)
        self.assertAlmostEqual(score, expected, places=3)


# ─────────────────────────────────────────────────────────────────────────────
# retriever — get_fragment_hash
# ─────────────────────────────────────────────────────────────────────────────

class TestGetFragmentHash(unittest.TestCase):
    def _frag(self, content="text", f_type="session", session="s1"):
        return {"content": content, "type": f_type, "session_id": session}

    def test_returns_32_char_hex_string(self):
        h = retriever.get_fragment_hash(self._frag())
        self.assertEqual(len(h), 32)
        self.assertRegex(h, r"^[0-9a-f]{32}$")

    def test_same_inputs_same_hash(self):
        f = self._frag()
        self.assertEqual(retriever.get_fragment_hash(f), retriever.get_fragment_hash(f))

    def test_different_content_different_hash(self):
        h1 = retriever.get_fragment_hash(self._frag(content="aaa"))
        h2 = retriever.get_fragment_hash(self._frag(content="bbb"))
        self.assertNotEqual(h1, h2)

    def test_different_session_different_hash(self):
        h1 = retriever.get_fragment_hash(self._frag(session="s1"))
        h2 = retriever.get_fragment_hash(self._frag(session="s2"))
        self.assertNotEqual(h1, h2)

    def test_fallback_to_session_id_alias(self):
        frag = {"content": "x", "type": "t", "sessionId": "alias_session"}
        h = retriever.get_fragment_hash(frag)
        self.assertIsNotNone(h)
        self.assertEqual(len(h), 32)

    def test_missing_session_uses_global(self):
        frag = {"content": "x", "type": "t"}
        h = retriever.get_fragment_hash(frag)
        # Should use 'Global' as session fallback
        expected = hashlib.md5("t:Global:x".encode()).hexdigest()
        self.assertEqual(h, expected)


# ─────────────────────────────────────────────────────────────────────────────
# retriever — perform_search
# ─────────────────────────────────────────────────────────────────────────────

class TestPerformSearch(unittest.TestCase):
    def _make_provider(self, semantic=None, lexical=None):
        db = MagicMock()
        db.search_fragments.return_value = semantic or []
        db.search_lexical.return_value = lexical or []
        db.search_by_source_keyword.return_value = []
        db.get_knowledge_map.return_value = {
            "foundation_knowledge": [], "expert_knowledge": [], "session_history": []
        }
        db.close.return_value = None
        return db

    def _run_search(self, query, semantic=None, lexical=None, embedding=None):
        mock_provider = self._make_provider(semantic, lexical)
        mock_embed = MagicMock(return_value=embedding or [0.1, 0.2])
        with patch("retriever.load_knowledge_provider", return_value=mock_provider), \
             patch("retriever.get_embedding", mock_embed), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            retriever.perform_search(query)
        return mock_out.getvalue(), mock_provider

    def test_no_results_prints_no_matches_message(self):
        output, _ = self._run_search("unknown query")
        self.assertIn("No forensic record", output)

    def test_results_printed_with_score(self):
        frag = {"content": "relevant content", "type": "session",
                "session_id": "s1", "score": 0.9, "timestamp": None,
                "source": "test.md"}
        output, _ = self._run_search("query", semantic=[frag])
        self.assertIn("Score:", output)
        self.assertIn("relevant content", output)

    def test_deduplication_removes_duplicate_fragments(self):
        frag = {"content": "same content", "type": "session",
                "session_id": "s1", "score": 0.9, "timestamp": None, "source": "f.md"}
        # Same fragment in both semantic and lexical results
        output, provider = self._run_search("query", semantic=[frag], lexical=[frag])
        # Should appear once, not twice
        self.assertEqual(output.count("same content"), 1)

    def test_empty_embedding_prints_error(self):
        mock_provider = self._make_provider()
        with patch("retriever.load_knowledge_provider", return_value=mock_provider), \
             patch("retriever.get_embedding", return_value=None), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            retriever.perform_search("query")
        self.assertIn("Error", mock_out.getvalue())

    def test_foundation_knowledge_boosted(self):
        frag = {"content": "foundation text", "type": "foundation_knowledge",
                "session_id": "Global", "score": 0.5, "timestamp": None, "source": "SOUL.md"}
        output, _ = self._run_search("query", semantic=[frag])
        # Score 0.5 * 1.35 = 0.675 — should appear boosted in output
        self.assertIn("foundation text", output)

    def test_db_close_called(self):
        _, provider = self._run_search("query")
        provider.close.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# history_scribe — HistoryDB
# ─────────────────────────────────────────────────────────────────────────────

class TestHistoryDB(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "history.db")

    def _make_db(self):
        with patch.object(history_scribe, "HISTORY_DB", self.db_path):
            return history_scribe.HistoryDB()

    def test_creates_history_table(self):
        db = self._make_db()
        tables = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = [t[0] for t in tables]
        self.assertIn("history", names)
        db.conn.close()

    def test_creates_fts5_table(self):
        db = self._make_db()
        tables = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = [t[0] for t in tables]
        self.assertIn("history_fts", names)
        db.conn.close()

    def test_add_session_inserts_record(self):
        db = self._make_db()
        db.add_session("sess1", "2026-03-31", "content here")
        row = db.conn.execute(
            "SELECT session_id, content FROM history WHERE session_id=?", ("sess1",)
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[1], "content here")
        db.conn.close()

    def test_add_session_inserts_into_fts(self):
        db = self._make_db()
        db.add_session("sess2", "2026-03-31", "searchable text")
        row = db.conn.execute(
            "SELECT content FROM history_fts WHERE session_id=?", ("sess2",)
        ).fetchone()
        self.assertIsNotNone(row)
        db.conn.close()

    def test_add_session_replaces_on_duplicate(self):
        db = self._make_db()
        db.add_session("sess1", "2026-03-31", "original")
        db.add_session("sess1", "2026-03-31", "updated")
        row = db.conn.execute(
            "SELECT content FROM history WHERE session_id=?", ("sess1",)
        ).fetchone()
        self.assertEqual(row[0], "updated")
        db.conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# history_scribe — save_split_markdown
# ─────────────────────────────────────────────────────────────────────────────

class TestSaveSplitMarkdown(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_short_content_writes_single_file(self):
        content = "\n".join(f"line {i}" for i in range(10))
        base = os.path.join(self.tmpdir, "session.md")
        result = history_scribe.save_split_markdown("s1", content, base)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], base)
        self.assertTrue(os.path.exists(base))

    def test_long_content_splits_into_parts(self):
        content = "\n".join(f"line {i}" for i in range(4500))
        base = os.path.join(self.tmpdir, "session.md")
        result = history_scribe.save_split_markdown("s1", content, base, line_limit=2000)
        self.assertEqual(len(result), 3)
        for part in result:
            self.assertTrue(os.path.exists(part))

    def test_part_files_named_correctly(self):
        content = "\n".join(f"line {i}" for i in range(4500))
        base = os.path.join(self.tmpdir, "session.md")
        result = history_scribe.save_split_markdown("s1", content, base, line_limit=2000)
        basenames = [os.path.basename(p) for p in result]
        self.assertIn("session_part1.md", basenames)
        self.assertIn("session_part2.md", basenames)
        self.assertIn("session_part3.md", basenames)

    def test_each_part_has_correct_line_count(self):
        content = "\n".join(f"line {i}" for i in range(2500))
        base = os.path.join(self.tmpdir, "session.md")
        result = history_scribe.save_split_markdown("s1", content, base, line_limit=2000)
        with open(result[0]) as f:
            self.assertEqual(len(f.readlines()), 2000)
        with open(result[1]) as f:
            self.assertEqual(len(f.readlines()), 500)

    def test_exact_limit_uses_single_file(self):
        content = "\n".join(f"line {i}" for i in range(2000))
        base = os.path.join(self.tmpdir, "session.md")
        result = history_scribe.save_split_markdown("s1", content, base, line_limit=2000)
        self.assertEqual(len(result), 1)

    def test_returns_list_of_paths(self):
        content = "single line"
        base = os.path.join(self.tmpdir, "s.md")
        result = history_scribe.save_split_markdown("s1", content, base)
        self.assertIsInstance(result, list)


# ─────────────────────────────────────────────────────────────────────────────
# history_scribe — scribe_all_sessions
# ─────────────────────────────────────────────────────────────────────────────

class TestScribeAllSessions(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "history.db")
        self.history_dir = os.path.join(self.tmpdir, "history")
        self.raw_dir = os.path.join(self.tmpdir, "raw")
        os.makedirs(self.raw_dir)

    def test_handles_missing_extract_signal_gracefully(self):
        with patch.object(history_scribe, "extract_signal", None), \
             patch.object(history_scribe, "HISTORY_DB", self.db_path), \
             patch.object(history_scribe, "HISTORY_DIR", self.history_dir), \
             patch.object(history_scribe, "RAW_DIR", self.raw_dir), \
             patch("sys.stdout", new_callable=io.StringIO) as out:
            history_scribe.scribe_all_sessions()
        self.assertIn("ERROR", out.getvalue())

    def test_processes_zero_sessions_when_dirs_empty(self):
        mock_extract = MagicMock(return_value=[])
        mock_skeleton = MagicMock(return_value="# Empty")
        with patch.object(history_scribe, "extract_signal", mock_extract), \
             patch.object(history_scribe, "skeleton_to_markdown", mock_skeleton), \
             patch.object(history_scribe, "HISTORY_DB", self.db_path), \
             patch.object(history_scribe, "HISTORY_DIR", self.history_dir), \
             patch.object(history_scribe, "RAW_DIR", self.raw_dir), \
             patch("glob.glob", return_value=[]), \
             patch("sys.stdout", new_callable=io.StringIO) as out:
            history_scribe.scribe_all_sessions()
        self.assertIn("0", out.getvalue())

    def test_skips_sessions_already_scribed(self):
        os.makedirs(self.history_dir)
        # Create a pre-existing scribed file
        existing_md = os.path.join(self.history_dir, "existing_session.md")
        with open(existing_md, "w") as f:
            f.write("already done")
        # Create a matching raw transcript
        transcript = os.path.join(self.raw_dir, "t.json")
        with open(transcript, "w") as f:
            json.dump({"sessionId": "existing_session"}, f)

        mock_extract = MagicMock(return_value=["turn1"])
        mock_skeleton = MagicMock(return_value="# Content")
        with patch.object(history_scribe, "extract_signal", mock_extract), \
             patch.object(history_scribe, "skeleton_to_markdown", mock_skeleton), \
             patch.object(history_scribe, "HISTORY_DB", self.db_path), \
             patch.object(history_scribe, "HISTORY_DIR", self.history_dir), \
             patch.object(history_scribe, "RAW_DIR", self.raw_dir), \
             patch("glob.glob", side_effect=lambda p: [transcript] if "raw" in p else []), \
             patch("sys.stdout", new_callable=io.StringIO):
            history_scribe.scribe_all_sessions()
        # extract_signal should NOT have been called (file already exists)
        mock_extract.assert_not_called()


if __name__ == "__main__":
    unittest.main()
