"""
Unit tests for A.I.M. skills:
  - skills/advanced_memory_search.py
  - skills/export_datajack_cartridge.py
  - skills/list_recent_sessions.py
  - skills/propose_memory_commit.py

All external I/O (subprocess, sqlite3, embeddings) is mocked.
Module-level scripts are re-executed per test via importlib.
"""
import importlib.util
import io
import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SKILLS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "skills")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_all_json(text):
    """
    Extract every top-level JSON object from a string that may contain
    multiple pretty-printed (indented) JSON objects separated by whitespace.
    Uses raw_decode so multi-line objects are consumed whole.
    """
    decoder = json.JSONDecoder()
    results = []
    idx = 0
    text = text.strip()
    while idx < len(text):
        while idx < len(text) and text[idx] in " \t\n\r":
            idx += 1
        if idx >= len(text):
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
            results.append(obj)
            idx = end
        except json.JSONDecodeError:
            break
    return results


def _exec_skill(name, argv, module_patches=None):
    """
    Load and execute a skill file with the given sys.argv.
    Returns (list_of_parsed_json_objects, loaded_module).

    module_patches: dict of {module_name: mock_object} injected into
                    sys.modules before exec_module fires.
    """
    path = os.path.join(SKILLS_DIR, name)
    spec = importlib.util.spec_from_file_location("_skill_under_test", path)
    mod = importlib.util.module_from_spec(spec)

    patches = module_patches or {}
    with patch.dict(sys.modules, patches), \
         patch("sys.argv", argv), \
         patch("sys.stdout", new_callable=io.StringIO) as mock_out:
        try:
            spec.loader.exec_module(mod)
        except SystemExit:
            pass
        raw = mock_out.getvalue()

    return _parse_all_json(raw), mod


def _make_forensic_stub(semantic=None, lexical=None, embedding=None):
    """Return a sys.modules stub for plugins.datajack.forensic_utils."""
    db_instance = MagicMock()
    db_instance.search_fragments.return_value = semantic if semantic is not None else []
    db_instance.search_lexical.return_value = lexical if lexical is not None else []
    db_instance.close.return_value = None

    ForensicDB_cls = MagicMock(return_value=db_instance)
    get_embedding_fn = MagicMock(
        return_value=embedding if embedding is not None else [0.1, 0.2]
    )

    stub = types.ModuleType("plugins.datajack.forensic_utils")
    stub.ForensicDB = ForensicDB_cls
    stub.get_embedding = get_embedding_fn

    plugins_stub = types.ModuleType("plugins")
    datajack_stub = types.ModuleType("plugins.datajack")

    return {
        "plugins": plugins_stub,
        "plugins.datajack": datajack_stub,
        "plugins.datajack.forensic_utils": stub,
    }, stub


# ─────────────────────────────────────────────────────────────────────────────
# advanced_memory_search.py
# ─────────────────────────────────────────────────────────────────────────────

class TestAdvancedMemorySearchOutput(unittest.TestCase):
    def _run(self, argv, semantic=None, lexical=None, embedding=None):
        mods, stub = _make_forensic_stub(
            semantic=semantic, lexical=lexical, embedding=embedding
        )
        results, _ = _exec_skill("advanced_memory_search.py", argv,
                                  module_patches=mods)
        return results, stub

    def test_default_args_returns_results_key(self):
        results, _ = self._run(["skill"])
        self.assertEqual(len(results), 1)
        self.assertIn("results", results[0])

    def test_empty_results_when_no_matches(self):
        results, _ = self._run(["skill"], semantic=[], lexical=[])
        self.assertEqual(results[0]["results"], [])

    def test_semantic_and_lexical_merged(self):
        sem = [{"id": 1, "text": "semantic hit"}]
        lex = [{"id": 2, "text": "lexical hit"}]
        results, _ = self._run(["skill"], semantic=sem, lexical=lex)
        combined = results[0]["results"]
        self.assertEqual(len(combined), 2)
        self.assertIn(sem[0], combined)
        self.assertIn(lex[0], combined)

    def test_custom_query_passed_to_db(self):
        mods, stub = _make_forensic_stub()
        args = json.dumps({"query": "my custom query", "top_k": 3})
        _exec_skill("advanced_memory_search.py", ["skill", args],
                     module_patches=mods)
        db_inst = stub.ForensicDB.return_value
        db_inst.search_lexical.assert_called_once_with("my custom query", top_k=3)

    def test_custom_top_k_passed_to_search_fragments(self):
        mods, stub = _make_forensic_stub()
        args = json.dumps({"query": "q", "top_k": 7})
        _exec_skill("advanced_memory_search.py", ["skill", args],
                     module_patches=mods)
        db_inst = stub.ForensicDB.return_value
        db_inst.search_fragments.assert_called_once()
        _, kwargs = db_inst.search_fragments.call_args
        self.assertEqual(kwargs.get("top_k"), 7)

    def test_none_embedding_skips_semantic_search(self):
        mods, stub = _make_forensic_stub()
        stub.get_embedding.return_value = None
        args = json.dumps({"query": "test"})
        results, _ = _exec_skill("advanced_memory_search.py", ["skill", args],
                                   module_patches=mods)
        db_inst = stub.ForensicDB.return_value
        db_inst.search_fragments.assert_not_called()
        self.assertIn("results", results[0])

    def test_db_close_called(self):
        mods, stub = _make_forensic_stub()
        _exec_skill("advanced_memory_search.py", ["skill"], module_patches=mods)
        stub.ForensicDB.return_value.close.assert_called_once()

    def test_exception_returns_error_json(self):
        mods, stub = _make_forensic_stub()
        stub.ForensicDB.side_effect = RuntimeError("db exploded")
        results, _ = _exec_skill("advanced_memory_search.py", ["skill"],
                                   module_patches=mods)
        self.assertIn("error", results[0])
        self.assertIn("db exploded", results[0]["error"])

    def test_invalid_json_arg_returns_error(self):
        mods, stub = _make_forensic_stub()
        results, _ = _exec_skill("advanced_memory_search.py",
                                   ["skill", "not-json"], module_patches=mods)
        self.assertIn("error", results[0])

    def test_no_args_uses_defaults(self):
        mods, stub = _make_forensic_stub()
        _exec_skill("advanced_memory_search.py", ["skill"], module_patches=mods)
        db_inst = stub.ForensicDB.return_value
        db_inst.search_lexical.assert_called_once_with("latest changes", top_k=10)


# ─────────────────────────────────────────────────────────────────────────────
# export_datajack_cartridge.py
# ─────────────────────────────────────────────────────────────────────────────

class TestExportDatajackCartridge(unittest.TestCase):
    def _run(self, argv, subprocess_result=None):
        if subprocess_result is None:
            subprocess_result = MagicMock(
                stdout="Exported 5 rows.", stderr="", returncode=0
            )
        with patch("subprocess.run", return_value=subprocess_result) as mock_run:
            results, _ = _exec_skill("export_datajack_cartridge.py", argv)
        return results, mock_run

    def test_json_args_keyword_and_name(self):
        args = json.dumps({"keyword": "myTag", "name": "custom.engram"})
        results, _ = self._run(["skill", args])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "Export Complete")
        self.assertEqual(results[0]["file"], "custom.engram")

    def test_json_args_name_gets_engram_suffix_if_missing(self):
        args = json.dumps({"keyword": "tag", "name": "no_suffix"})
        results, _ = self._run(["skill", args])
        self.assertEqual(results[0]["file"], "no_suffix.engram")

    def test_json_args_name_already_has_engram_suffix(self):
        args = json.dumps({"keyword": "tag", "name": "file.engram"})
        results, _ = self._run(["skill", args])
        self.assertEqual(results[0]["file"], "file.engram")

    def test_default_keyword_expert_dash(self):
        _, mock_run = self._run(["skill", "{}"])
        cmd = mock_run.call_args[0][0]
        self.assertIn("expert-", cmd)

    def test_default_out_name_export_engram(self):
        _, mock_run = self._run(["skill", "{}"])
        cmd = mock_run.call_args[0][0]
        self.assertIn("export.engram", cmd)

    def test_subprocess_stdout_captured(self):
        proc = MagicMock(stdout="Done!", stderr="", returncode=0)
        results, _ = self._run(["skill", "{}"], subprocess_result=proc)
        self.assertEqual(results[0]["output"], "Done!")

    def test_subprocess_stderr_captured(self):
        proc = MagicMock(stdout="", stderr="some warning", returncode=1)
        results, _ = self._run(["skill", "{}"], subprocess_result=proc)
        self.assertEqual(results[0]["error"], "some warning")

    def test_subprocess_called_with_export_subcommand(self):
        args = json.dumps({"keyword": "myKw", "name": "out.engram"})
        _, mock_run = self._run(["skill", args])
        cmd = mock_run.call_args[0][0]
        self.assertIn("export", cmd)
        self.assertIn("myKw", cmd)
        self.assertIn("out.engram", cmd)

    def test_exception_returns_error_json(self):
        with patch("subprocess.run", side_effect=OSError("no such file")):
            results, _ = _exec_skill("export_datajack_cartridge.py",
                                      ["skill", "{}"])
        self.assertIn("error", results[0])
        self.assertIn("no such file", results[0]["error"])

    def test_non_json_arg_fallback(self):
        """Raw string arg (not JSON) triggers fallback: keyword=sys.argv[1]."""
        proc = MagicMock(stdout="ok", stderr="", returncode=0)
        with patch("subprocess.run", return_value=proc) as mock_run:
            _exec_skill("export_datajack_cartridge.py", ["skill", "rawKeyword"])
        cmd = mock_run.call_args[0][0]
        self.assertIn("rawKeyword", cmd)


# ─────────────────────────────────────────────────────────────────────────────
# list_recent_sessions.py
# ─────────────────────────────────────────────────────────────────────────────

class TestListRecentSessions(unittest.TestCase):
    """
    list_recent_sessions.py has a main() function — load the module once,
    call main() per test with a fresh in-memory SQLite DB.
    """

    @classmethod
    def setUpClass(cls):
        path = os.path.join(SKILLS_DIR, "list_recent_sessions.py")
        spec = importlib.util.spec_from_file_location("list_recent_sessions", path)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def _make_db(self, rows=None):
        """Build a real in-memory SQLite DB matching the engram schema."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE sessions (id TEXT, indexed_at TEXT)")
        conn.execute(
            "CREATE TABLE fragments (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT)"
        )
        for r in (rows or []):
            conn.execute(
                "INSERT INTO sessions VALUES (?, ?)",
                (r["session_id"], r["indexed_at"]),
            )
            for _ in range(r.get("fragments", 0)):
                conn.execute(
                    "INSERT INTO fragments (session_id) VALUES (?)",
                    (r["session_id"],),
                )
        conn.commit()
        return conn

    def _run(self, argv, db_exists=True, rows=None):
        conn = self._make_db(rows)
        with patch("sys.argv", argv), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_out, \
             patch("pathlib.Path.exists", return_value=db_exists), \
             patch("sqlite3.connect", return_value=conn):
            try:
                self.mod.main()
            except SystemExit:
                pass
        return _parse_all_json(mock_out.getvalue())

    def test_db_not_found_returns_error(self):
        results = self._run(["skill"], db_exists=False)
        self.assertIn("error", results[0])
        self.assertIn("engram.db not found", results[0]["error"])

    def test_empty_db_returns_empty_list(self):
        results = self._run(["skill"])
        self.assertIn("sessions", results[0])
        self.assertEqual(results[0]["sessions"], [])

    def test_sessions_returned_with_correct_fields(self):
        rows = [
            {"session_id": "abc", "indexed_at": "2026-03-31T00:00:00", "fragments": 3}
        ]
        results = self._run(["skill"], rows=rows)
        sessions = results[0]["sessions"]
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["session_id"], "abc")
        self.assertEqual(sessions[0]["fragments"], 3)

    def test_fragment_count_correct(self):
        rows = [
            {"session_id": "s1", "indexed_at": "2026-03-31", "fragments": 5},
            {"session_id": "s2", "indexed_at": "2026-03-30", "fragments": 0},
        ]
        results = self._run(["skill"], rows=rows)
        by_id = {s["session_id"]: s for s in results[0]["sessions"]}
        self.assertEqual(by_id["s1"]["fragments"], 5)
        self.assertEqual(by_id["s2"]["fragments"], 0)

    def test_default_limit_is_5(self):
        rows = [
            {"session_id": f"s{i}", "indexed_at": f"2026-03-{i:02d}", "fragments": 0}
            for i in range(1, 9)
        ]
        results = self._run(["skill"], rows=rows)
        self.assertLessEqual(len(results[0]["sessions"]), 5)

    def test_custom_limit_from_json_arg(self):
        rows = [
            {"session_id": f"s{i}", "indexed_at": f"2026-03-{i:02d}", "fragments": 0}
            for i in range(1, 9)
        ]
        results = self._run(["skill", json.dumps({"limit": 3})], rows=rows)
        self.assertLessEqual(len(results[0]["sessions"]), 3)

    def test_invalid_json_arg_uses_default_limit(self):
        rows = [
            {"session_id": f"s{i}", "indexed_at": f"2026-03-{i:02d}", "fragments": 0}
            for i in range(1, 9)
        ]
        results = self._run(["skill", "not-json"], rows=rows)
        self.assertIn("sessions", results[0])
        self.assertLessEqual(len(results[0]["sessions"]), 5)

    def test_sessions_ordered_by_indexed_at_desc(self):
        rows = [
            {"session_id": "old", "indexed_at": "2026-03-01", "fragments": 0},
            {"session_id": "new", "indexed_at": "2026-03-31", "fragments": 0},
        ]
        results = self._run(["skill"], rows=rows)
        sessions = results[0]["sessions"]
        self.assertEqual(sessions[0]["session_id"], "new")


# ─────────────────────────────────────────────────────────────────────────────
# propose_memory_commit.py
# ─────────────────────────────────────────────────────────────────────────────

class TestProposeMemoryCommit(unittest.TestCase):
    def _run(self, subprocess_result=None):
        if subprocess_result is None:
            subprocess_result = MagicMock(
                stdout="Memory pipeline complete.", stderr="", returncode=0
            )
        with patch("subprocess.run", return_value=subprocess_result) as mock_run:
            results, _ = _exec_skill("propose_memory_commit.py", ["skill"])
        return results, mock_run

    def test_first_output_is_status_message(self):
        results, _ = self._run()
        self.assertEqual(len(results), 2)
        self.assertIn("status", results[0])
        self.assertIn("Triggering memory refinement", results[0]["status"])

    def test_second_output_has_stdout(self):
        proc = MagicMock(stdout="Pipeline done.", stderr="", returncode=0)
        results, _ = self._run(subprocess_result=proc)
        self.assertEqual(results[1]["stdout"], "Pipeline done.")

    def test_second_output_has_stderr(self):
        proc = MagicMock(stdout="", stderr="WARNING: slow", returncode=0)
        results, _ = self._run(subprocess_result=proc)
        self.assertEqual(results[1]["stderr"], "WARNING: slow")

    def test_subprocess_called_with_memory_subcommand(self):
        _, mock_run = self._run()
        cmd = mock_run.call_args[0][0]
        self.assertIn("memory", cmd)

    def test_subprocess_called_with_aim_cli(self):
        _, mock_run = self._run()
        cmd = mock_run.call_args[0][0]
        self.assertTrue(any("aim_cli" in str(c) for c in cmd))

    def test_exception_returns_error_json(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("aim_cli not found")):
            results, _ = _exec_skill("propose_memory_commit.py", ["skill"])
        error_results = [r for r in results if "error" in r]
        self.assertTrue(len(error_results) > 0)
        self.assertIn("aim_cli not found", error_results[0]["error"])

    def test_subprocess_stdout_and_stderr_stripped(self):
        proc = MagicMock(stdout="  padded  ", stderr="  warn  ", returncode=0)
        results, _ = self._run(subprocess_result=proc)
        self.assertEqual(results[1]["stdout"], "padded")
        self.assertEqual(results[1]["stderr"], "warn")


if __name__ == "__main__":
    unittest.main()
