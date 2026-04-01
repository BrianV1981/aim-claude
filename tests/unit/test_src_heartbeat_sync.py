"""
Unit tests for src/heartbeat.py and src/sovereign_sync.py.

Run from the repo root:
    python3 -m pytest tests/unit/test_src_heartbeat_sync.py -v
"""

import sys
import os
import json
import time
import tempfile
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

# ---------------------------------------------------------------------------
# heartbeat — imported after path setup; module-level AIM_ROOT is set at
# import time.  We patch the functions' globals via unittest.mock.patch so
# that every helper reads from a controlled tempdir instead of the real repo.
# ---------------------------------------------------------------------------
import heartbeat
import sovereign_sync


# ============================================================
# Helper: build a minimal fake sqlite3 connection/cursor chain
# ============================================================

def _make_sqlite_mock(fragment_count=5, session_count=2):
    """Return a mock that mimics sqlite3.connect(path)."""
    cursor_mock = MagicMock()
    cursor_mock.fetchone.side_effect = [
        (fragment_count,),  # first fetchone → fragments count
        (session_count,),   # second fetchone → sessions count
    ]
    conn_mock = MagicMock()
    conn_mock.cursor.return_value = cursor_mock
    return conn_mock, cursor_mock


# ============================================================
# Tests: heartbeat.print_status
# ============================================================

class TestPrintStatus(unittest.TestCase):
    """print_status must not raise for any status value."""

    def test_pass_does_not_raise(self):
        heartbeat.print_status("Component", "PASS", "all good")

    def test_warn_does_not_raise(self):
        heartbeat.print_status("Component", "WARN", "something mild")

    def test_fail_does_not_raise(self):
        heartbeat.print_status("Component", "FAIL", "something bad")

    def test_empty_message_does_not_raise(self):
        heartbeat.print_status("Component", "PASS")


# ============================================================
# Tests: heartbeat.check_db
# ============================================================

class TestCheckDb(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Patch AIM_ROOT inside the heartbeat module
        self._root_patch = patch.object(heartbeat, "AIM_ROOT", self.tmp)
        self._root_patch.start()

    def tearDown(self):
        self._root_patch.stop()

    # -- DB file absent --------------------------------------------------------

    def test_missing_db_prints_fail(self):
        """check_db exits gracefully when engram.db does not exist."""
        with patch.object(heartbeat, "print_status") as mock_ps:
            heartbeat.check_db()
        mock_ps.assert_called_once()
        label, status, *_ = mock_ps.call_args[0]
        self.assertEqual(status, "FAIL")

    # -- DB file present, healthy ----------------------------------------------

    def test_healthy_db_prints_pass(self):
        """check_db reports PASS when sqlite3 returns counts."""
        archive_dir = os.path.join(self.tmp, "archive")
        os.makedirs(archive_dir, exist_ok=True)
        db_path = os.path.join(archive_dir, "engram.db")
        open(db_path, "w").close()  # create empty placeholder

        conn_mock, _ = _make_sqlite_mock(fragment_count=42, session_count=3)
        with patch("sqlite3.connect", return_value=conn_mock):
            with patch.object(heartbeat, "print_status") as mock_ps:
                heartbeat.check_db()

        mock_ps.assert_called_once()
        label, status, msg = mock_ps.call_args[0]
        self.assertEqual(status, "PASS")
        self.assertIn("42", msg)
        self.assertIn("3", msg)

    # -- DB present but corrupt ------------------------------------------------

    def test_corrupt_db_prints_fail(self):
        """check_db catches sqlite3 exceptions and prints FAIL."""
        archive_dir = os.path.join(self.tmp, "archive")
        os.makedirs(archive_dir, exist_ok=True)
        db_path = os.path.join(archive_dir, "engram.db")
        open(db_path, "w").close()

        conn_mock = MagicMock()
        conn_mock.cursor.side_effect = Exception("disk I/O error")
        with patch("sqlite3.connect", return_value=conn_mock):
            with patch.object(heartbeat, "print_status") as mock_ps:
                heartbeat.check_db()

        label, status, *_ = mock_ps.call_args[0]
        self.assertEqual(status, "FAIL")


# ============================================================
# Tests: heartbeat.check_failsafe
# ============================================================

class TestCheckFailsafe(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._root_patch = patch.object(heartbeat, "AIM_ROOT", self.tmp)
        self._root_patch.start()

    def tearDown(self):
        self._root_patch.stop()

    def _make_tail(self, age_seconds=0):
        """Create FALLBACK_TAIL.md and optionally back-date its mtime."""
        cont_dir = os.path.join(self.tmp, "continuity")
        os.makedirs(cont_dir, exist_ok=True)
        tail_path = os.path.join(cont_dir, "FALLBACK_TAIL.md")
        with open(tail_path, "w") as f:
            f.write("tail content")
        if age_seconds:
            t = time.time() - age_seconds
            os.utime(tail_path, (t, t))
        return tail_path

    # -- File missing ----------------------------------------------------------

    def test_missing_tail_prints_fail(self):
        with patch.object(heartbeat, "print_status") as mock_ps:
            heartbeat.check_failsafe()
        label, status, *_ = mock_ps.call_args[0]
        self.assertEqual(status, "FAIL")

    # -- File exists and fresh (< 24 h) ----------------------------------------

    def test_fresh_tail_prints_pass(self):
        self._make_tail(age_seconds=3600)  # 1 hour old
        with patch.object(heartbeat, "print_status") as mock_ps:
            heartbeat.check_failsafe()
        label, status, *_ = mock_ps.call_args[0]
        self.assertEqual(status, "PASS")

    # -- File exists but stale (> 24 h) ----------------------------------------

    def test_stale_tail_prints_warn(self):
        self._make_tail(age_seconds=90000)  # 25 hours old
        with patch.object(heartbeat, "print_status") as mock_ps:
            heartbeat.check_failsafe()
        label, status, *_ = mock_ps.call_args[0]
        self.assertEqual(status, "WARN")


# ============================================================
# Tests: heartbeat.check_memory_pipeline
# ============================================================

class TestCheckMemoryPipeline(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._root_patch = patch.object(heartbeat, "AIM_ROOT", self.tmp)
        self._root_patch.start()
        # Create memory/hourly and memory/daily directories
        self.hourly = os.path.join(self.tmp, "memory", "hourly")
        self.daily = os.path.join(self.tmp, "memory", "daily")
        os.makedirs(self.hourly, exist_ok=True)
        os.makedirs(self.daily, exist_ok=True)

    def tearDown(self):
        self._root_patch.stop()

    def _write_log(self, subdir, name, age_seconds=0):
        path = os.path.join(subdir, name)
        with open(path, "w") as f:
            f.write("log entry")
        if age_seconds:
            t = time.time() - age_seconds
            os.utime(path, (t, t))
        return path

    # -- No logs → WARN --------------------------------------------------------

    def test_no_logs_prints_warn(self):
        with patch.object(heartbeat, "print_status") as mock_ps:
            heartbeat.check_memory_pipeline()
        label, status, *_ = mock_ps.call_args[0]
        self.assertEqual(status, "WARN")

    # -- Recent log (< 48 h) → PASS --------------------------------------------

    def test_recent_log_prints_pass(self):
        self._write_log(self.hourly, "2026-03-31T12.md", age_seconds=600)
        with patch.object(heartbeat, "print_status") as mock_ps:
            heartbeat.check_memory_pipeline()
        label, status, *_ = mock_ps.call_args[0]
        self.assertEqual(status, "PASS")

    # -- Stale log (> 48 h) → WARN ---------------------------------------------

    def test_stale_log_prints_warn(self):
        self._write_log(self.daily, "2026-03-28.md", age_seconds=180000)  # 50 h
        with patch.object(heartbeat, "print_status") as mock_ps:
            heartbeat.check_memory_pipeline()
        label, status, *_ = mock_ps.call_args[0]
        self.assertEqual(status, "WARN")

    # -- Mixed logs: one stale, one fresh → PASS (newest wins) ----------------

    def test_newest_log_wins(self):
        self._write_log(self.daily, "old.md", age_seconds=180000)  # stale
        self._write_log(self.hourly, "new.md", age_seconds=1800)   # fresh
        with patch.object(heartbeat, "print_status") as mock_ps:
            heartbeat.check_memory_pipeline()
        label, status, *_ = mock_ps.call_args[0]
        self.assertEqual(status, "PASS")


# ============================================================
# Tests: heartbeat.check_sync
# ============================================================

class TestCheckSync(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._root_patch = patch.object(heartbeat, "AIM_ROOT", self.tmp)
        self._root_patch.start()
        self.sync_dir = os.path.join(self.tmp, "archive", "sync")
        os.makedirs(self.sync_dir, exist_ok=True)

    def tearDown(self):
        self._root_patch.stop()

    def test_no_jsonl_prints_warn(self):
        with patch.object(heartbeat, "print_status") as mock_ps:
            heartbeat.check_sync()
        label, status, *_ = mock_ps.call_args[0]
        self.assertEqual(status, "WARN")

    def test_jsonl_files_present_prints_pass(self):
        for name in ("session-1.jsonl", "session-2.jsonl", "session-3.jsonl"):
            open(os.path.join(self.sync_dir, name), "w").close()
        with patch.object(heartbeat, "print_status") as mock_ps:
            heartbeat.check_sync()
        label, status, msg = mock_ps.call_args[0]
        self.assertEqual(status, "PASS")
        self.assertIn("3", msg)

    def test_non_jsonl_files_ignored(self):
        """Only .jsonl files should be counted."""
        open(os.path.join(self.sync_dir, "notes.txt"), "w").close()
        with patch.object(heartbeat, "print_status") as mock_ps:
            heartbeat.check_sync()
        label, status, *_ = mock_ps.call_args[0]
        self.assertEqual(status, "WARN")


# ============================================================
# Helper: mock db object for sovereign_sync tests
# ============================================================

class MockDb:
    """Minimal duck-typed DB object matching sovereign_sync's usage."""

    def __init__(self, sessions=None, fragments_by_session=None,
                 session_mtimes=None):
        self.sessions = sessions or []           # list of (id, filename, mtime)
        self.fragments_by_session = fragments_by_session or {}
        self.session_mtimes = session_mtimes or {}

        self.cursor = MagicMock()
        self._setup_cursor()

        self.added_sessions = []
        self.added_fragments = []

    def _setup_cursor(self):
        # Each call to execute / fetchall is intercepted via side_effect lists
        self._exec_calls = []
        self.cursor.execute.side_effect = self._on_execute
        self.cursor.fetchall.side_effect = self._on_fetchall

    def _on_execute(self, sql, params=None):
        self._exec_calls.append((sql, params))

    def _on_fetchall(self):
        # Return sessions list on first call, then fragments for subsequent
        if not self._exec_calls:
            return []
        last_sql, last_params = self._exec_calls[-1]
        if "FROM sessions" in last_sql:
            return self.sessions
        elif "FROM fragments" in last_sql:
            session_id = last_params[0] if last_params else None
            return self.fragments_by_session.get(session_id, [])
        return []

    def get_session_mtime(self, session_id):
        return self.session_mtimes.get(session_id, -1)

    def add_session(self, session_id, filename, mtime):
        self.added_sessions.append((session_id, filename, mtime))

    def add_fragments(self, session_id, fragments):
        self.added_fragments.append((session_id, fragments))

    def _blob_to_vec(self, blob):
        """Deserialise a list stored as JSON bytes."""
        return json.loads(blob)


# ============================================================
# Tests: sovereign_sync.export_to_jsonl
# ============================================================

class TestExportToJsonl(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sync_dir = os.path.join(self.tmp, "sync")

    def test_creates_sync_dir_if_absent(self):
        db = MockDb(sessions=[])
        sovereign_sync.export_to_jsonl(db, self.sync_dir)
        self.assertTrue(os.path.isdir(self.sync_dir))

    def test_returns_zero_for_no_sessions(self):
        db = MockDb(sessions=[])
        result = sovereign_sync.export_to_jsonl(db, self.sync_dir)
        self.assertEqual(result, 0)

    def test_creates_one_jsonl_per_session(self):
        db = MockDb(
            sessions=[("sess-1", "chat1.md", 1000.0),
                      ("sess-2", "chat2.md", 2000.0)],
            fragments_by_session={"sess-1": [], "sess-2": []}
        )
        result = sovereign_sync.export_to_jsonl(db, self.sync_dir)
        self.assertEqual(result, 2)
        self.assertTrue(os.path.exists(os.path.join(self.sync_dir, "sess-1.jsonl")))
        self.assertTrue(os.path.exists(os.path.join(self.sync_dir, "sess-2.jsonl")))

    def test_first_line_is_session_metadata(self):
        db = MockDb(
            sessions=[("sess-A", "alpha.md", 9999.0)],
            fragments_by_session={"sess-A": []}
        )
        sovereign_sync.export_to_jsonl(db, self.sync_dir)
        jpath = os.path.join(self.sync_dir, "sess-A.jsonl")
        with open(jpath) as f:
            first = json.loads(f.readline())
        self.assertEqual(first["_record_type"], "session")
        self.assertEqual(first["session_id"], "sess-A")
        self.assertEqual(first["filename"], "alpha.md")
        self.assertEqual(first["mtime"], 9999.0)

    def test_fragment_lines_written_correctly(self):
        embedding_blob = json.dumps([0.1, 0.2, 0.3]).encode()
        fragments = [
            ("thought", "hello world", "2026-01-01T00:00:00",
             embedding_blob, '{"src": "test"}')
        ]
        db = MockDb(
            sessions=[("sess-B", "beta.md", 1111.0)],
            fragments_by_session={"sess-B": fragments}
        )
        sovereign_sync.export_to_jsonl(db, self.sync_dir)
        jpath = os.path.join(self.sync_dir, "sess-B.jsonl")
        with open(jpath) as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 2)  # 1 session + 1 fragment
        frag = json.loads(lines[1])
        self.assertEqual(frag["_record_type"], "fragment")
        self.assertEqual(frag["type"], "thought")
        self.assertEqual(frag["content"], "hello world")
        self.assertEqual(frag["embedding"], [0.1, 0.2, 0.3])
        self.assertEqual(frag["metadata"], {"src": "test"})

    def test_none_embedding_blob_stored_as_null(self):
        fragments = [
            ("note", "no embed", "2026-01-01", None, None)
        ]
        db = MockDb(
            sessions=[("sess-C", "gamma.md", 500.0)],
            fragments_by_session={"sess-C": fragments}
        )
        sovereign_sync.export_to_jsonl(db, self.sync_dir)
        jpath = os.path.join(self.sync_dir, "sess-C.jsonl")
        with open(jpath) as f:
            frag = json.loads(f.readlines()[1])
        self.assertIsNone(frag["embedding"])
        self.assertEqual(frag["metadata"], {})


# ============================================================
# Tests: sovereign_sync.import_from_jsonl
# ============================================================

class TestImportFromJsonl(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sync_dir = os.path.join(self.tmp, "sync")
        os.makedirs(self.sync_dir)

    def _write_jsonl(self, session_id, filename, mtime, fragments=None):
        """Write a well-formed JSONL file into self.sync_dir."""
        path = os.path.join(self.sync_dir, f"{session_id}.jsonl")
        with open(path, "w") as f:
            meta = {"_record_type": "session", "session_id": session_id,
                    "filename": filename, "mtime": mtime}
            f.write(json.dumps(meta) + "\n")
            for frag in (fragments or []):
                f.write(json.dumps(frag) + "\n")
        return path

    # -- sync_dir absent -------------------------------------------------------

    def test_missing_sync_dir_returns_zero(self):
        db = MockDb()
        result = sovereign_sync.import_from_jsonl(db, "/nonexistent/dir")
        self.assertEqual(result, 0)

    # -- DB already up-to-date (db_mtime >= file mtime) ----------------------

    def test_skips_session_when_db_is_newer(self):
        self._write_jsonl("sess-1", "chat.md", mtime=500.0)
        db = MockDb(session_mtimes={"sess-1": 1000.0})  # DB is newer
        result = sovereign_sync.import_from_jsonl(db, self.sync_dir)
        self.assertEqual(result, 0)
        self.assertEqual(db.added_sessions, [])

    def test_skips_session_when_db_mtime_equal(self):
        self._write_jsonl("sess-eq", "eq.md", mtime=700.0)
        db = MockDb(session_mtimes={"sess-eq": 700.0})  # same mtime
        result = sovereign_sync.import_from_jsonl(db, self.sync_dir)
        self.assertEqual(result, 0)

    # -- JSONL is newer → should import ----------------------------------------

    def test_imports_new_session_when_jsonl_newer(self):
        self._write_jsonl("sess-new", "new.md", mtime=9000.0)
        db = MockDb(session_mtimes={"sess-new": 100.0})  # DB is older
        result = sovereign_sync.import_from_jsonl(db, self.sync_dir)
        self.assertEqual(result, 1)
        self.assertEqual(len(db.added_sessions), 1)
        sid, fname, mt = db.added_sessions[0]
        self.assertEqual(sid, "sess-new")
        self.assertEqual(fname, "new.md")
        self.assertEqual(mt, 9000.0)

    # -- Missing session in DB (get_session_mtime returns -1) ----------------

    def test_imports_when_session_not_in_db(self):
        self._write_jsonl("sess-missing", "missing.md", mtime=5000.0)
        db = MockDb()  # session_mtimes empty → returns -1
        result = sovereign_sync.import_from_jsonl(db, self.sync_dir)
        self.assertEqual(result, 1)
        self.assertTrue(len(db.added_sessions) == 1)

    # -- Fragments are passed to add_fragments --------------------------------

    def test_fragments_passed_to_add_fragments(self):
        frags = [
            {"_record_type": "fragment", "type": "note", "content": "hi",
             "timestamp": "2026-01-01", "embedding": None, "metadata": {}}
        ]
        self._write_jsonl("sess-frags", "f.md", mtime=8000.0, fragments=frags)
        db = MockDb()
        sovereign_sync.import_from_jsonl(db, self.sync_dir)
        self.assertEqual(len(db.added_fragments), 1)
        sid, frag_list = db.added_fragments[0]
        self.assertEqual(sid, "sess-frags")
        self.assertEqual(len(frag_list), 1)
        self.assertEqual(frag_list[0]["content"], "hi")

    # -- Multiple sessions, partial import ------------------------------------

    def test_partial_import_mixed_mtimes(self):
        self._write_jsonl("old-sess", "old.md", mtime=100.0)
        self._write_jsonl("new-sess", "new.md", mtime=9999.0)
        db = MockDb(session_mtimes={"old-sess": 500.0, "new-sess": 1.0})
        result = sovereign_sync.import_from_jsonl(db, self.sync_dir)
        self.assertEqual(result, 1)
        imported_ids = [s[0] for s in db.added_sessions]
        self.assertIn("new-sess", imported_ids)
        self.assertNotIn("old-sess", imported_ids)

    # -- Malformed first line → skipped without crash -------------------------

    def test_malformed_session_record_type_skipped(self):
        path = os.path.join(self.sync_dir, "bad.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"_record_type": "fragment", "junk": True}) + "\n")
        db = MockDb()
        result = sovereign_sync.import_from_jsonl(db, self.sync_dir)
        self.assertEqual(result, 0)

    # -- Empty file → skipped without crash ------------------------------------

    def test_empty_jsonl_skipped(self):
        path = os.path.join(self.sync_dir, "empty.jsonl")
        open(path, "w").close()
        db = MockDb()
        result = sovereign_sync.import_from_jsonl(db, self.sync_dir)
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
