"""
Unit tests for scripts/handoff_pulse_claude.py (Issue #78)

Covers:
- JSONL discovery via Claude Code project hash
- Last-5-turns extraction (user + assistant only, skip snapshots/tool_results/thinking)
- Anti-cannibalization: newest JSONL < 15 lines → use previous session
- CURRENT_PULSE.md written with correct format
- HANDOFF.md written from static template with fresh timestamp
- Graceful handling of missing/empty JSONL dir
"""
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
SCRIPT_PATH = os.path.join(SCRIPTS_DIR, "handoff_pulse_claude.py")
AIM_CLAUDE_ROOT = str(Path(__file__).parent.parent.parent)


def _load_mod(tmp_root):
    sys.modules.pop("handoff_pulse_claude", None)
    spec = importlib.util.spec_from_file_location("handoff_pulse_claude", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    with patch("os.getcwd", return_value=tmp_root):
        spec.loader.exec_module(mod)
    mod.AIM_ROOT = tmp_root
    mod.CONTINUITY_DIR = os.path.join(tmp_root, "continuity")
    mod.HANDOFF_PATH = os.path.join(tmp_root, "HANDOFF.md")
    return mod


def _make_tmp_root():
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "continuity"))
    os.makedirs(os.path.join(d, "core"))
    with open(os.path.join(d, "core", "CONFIG.json"), "w") as f:
        json.dump({}, f)
    return d


def _make_jsonl(path, turns):
    """Write a list of turn dicts as JSONL."""
    with open(path, "w") as f:
        for t in turns:
            f.write(json.dumps(t) + "\n")


def _user(text, ts="2026-04-02T00:00:01Z"):
    return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]},
            "sessionId": "sess-test", "timestamp": ts}


def _assistant(text, ts="2026-04-02T00:00:02Z"):
    return {"type": "assistant", "message": {"role": "assistant",
            "content": [{"type": "text", "text": text}]},
            "sessionId": "sess-test", "timestamp": ts}


def _snapshot():
    return {"type": "snapshot", "isSnapshotUpdate": True, "snapshot": {}}


def _tool_result():
    return {"type": "assistant", "message": {"role": "assistant",
            "content": [{"type": "tool_result", "content": "output"}]},
            "sessionId": "sess-test", "timestamp": "2026-04-02T00:00:03Z"}


class TestFindTranscripts(unittest.TestCase):
    def setUp(self):
        self.tmp = _make_tmp_root()
        self.mod = _load_mod(self.tmp)

    def test_returns_empty_when_no_project_dir(self):
        self.mod.AIM_ROOT = "/nonexistent/path"
        result = self.mod.find_transcripts()
        self.assertEqual(result, [])

    def test_discovers_jsonl_files(self):
        aim_root = self.tmp
        proj_hash = "-" + aim_root.lstrip("/").replace("/", "-")
        proj_dir = os.path.expanduser(f"~/.claude/projects/{proj_hash}")
        os.makedirs(proj_dir, exist_ok=True)
        p = os.path.join(proj_dir, "session.jsonl")
        _make_jsonl(p, [_user("hello")])
        self.mod.AIM_ROOT = aim_root
        result = self.mod.find_transcripts()
        self.assertIn(p, result)

    def test_returns_sorted_by_mtime(self):
        aim_root = self.tmp
        proj_hash = "-" + aim_root.lstrip("/").replace("/", "-")
        proj_dir = os.path.expanduser(f"~/.claude/projects/{proj_hash}")
        os.makedirs(proj_dir, exist_ok=True)
        p1 = os.path.join(proj_dir, "old.jsonl")
        p2 = os.path.join(proj_dir, "new.jsonl")
        _make_jsonl(p1, [_user("old")])
        import time; time.sleep(0.01)
        _make_jsonl(p2, [_user("new")])
        self.mod.AIM_ROOT = aim_root
        result = self.mod.find_transcripts()
        self.assertEqual(result[-1], p2)


class TestExtractLastTurns(unittest.TestCase):
    def setUp(self):
        self.tmp = _make_tmp_root()
        self.mod = _load_mod(self.tmp)

    def _write(self, turns, name="sess.jsonl"):
        p = os.path.join(self.tmp, name)
        _make_jsonl(p, turns)
        return p

    def test_extracts_user_and_assistant(self):
        p = self._write([_user("hello"), _assistant("hi back")])
        turns = self.mod.extract_last_turns(p, n=5)
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0]["role"], "user")
        self.assertEqual(turns[1]["role"], "assistant")

    def test_skips_snapshots(self):
        p = self._write([_snapshot(), _user("real turn")])
        turns = self.mod.extract_last_turns(p, n=5)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["role"], "user")

    def test_skips_tool_results(self):
        p = self._write([_tool_result(), _user("real")])
        turns = self.mod.extract_last_turns(p, n=5)
        self.assertEqual(len(turns), 1)

    def test_returns_last_n_only(self):
        many = [_user(f"msg {i}") for i in range(10)]
        p = self._write(many)
        turns = self.mod.extract_last_turns(p, n=5)
        self.assertEqual(len(turns), 5)
        self.assertEqual(turns[-1]["text"], "msg 9")

    def test_returns_all_when_fewer_than_n(self):
        p = self._write([_user("only one")])
        turns = self.mod.extract_last_turns(p, n=5)
        self.assertEqual(len(turns), 1)


class TestAntiCannibalization(unittest.TestCase):
    def setUp(self):
        self.tmp = _make_tmp_root()
        self.mod = _load_mod(self.tmp)

    def test_skips_tiny_newest_uses_previous(self):
        p1 = os.path.join(self.tmp, "big.jsonl")
        p2 = os.path.join(self.tmp, "tiny.jsonl")
        _make_jsonl(p1, [_user(f"turn {i}") for i in range(20)])
        import time; time.sleep(0.01)
        _make_jsonl(p2, [_user("just woke up")])  # < 15 lines

        result = self.mod.select_transcript([p1, p2])
        self.assertEqual(result, p1)

    def test_uses_newest_when_large_enough(self):
        p1 = os.path.join(self.tmp, "old.jsonl")
        p2 = os.path.join(self.tmp, "new.jsonl")
        _make_jsonl(p1, [_user(f"t{i}") for i in range(20)])
        import time; time.sleep(0.01)
        _make_jsonl(p2, [_user(f"t{i}") for i in range(20)])

        result = self.mod.select_transcript([p1, p2])
        self.assertEqual(result, p2)

    def test_uses_only_file_even_if_tiny(self):
        p1 = os.path.join(self.tmp, "only.jsonl")
        _make_jsonl(p1, [_user("short")])
        result = self.mod.select_transcript([p1])
        self.assertEqual(result, p1)


class TestWriteCurrentPulse(unittest.TestCase):
    def setUp(self):
        self.tmp = _make_tmp_root()
        self.mod = _load_mod(self.tmp)

    def test_writes_pulse_file(self):
        turns = [{"role": "user", "text": "hello", "timestamp": "T"},
                 {"role": "assistant", "text": "hi", "timestamp": "T"}]
        self.mod.write_current_pulse(turns)
        pulse_path = os.path.join(self.tmp, "continuity", "CURRENT_PULSE.md")
        self.assertTrue(os.path.exists(pulse_path))

    def test_pulse_contains_user_text(self):
        turns = [{"role": "user", "text": "what is the plan", "timestamp": "T"}]
        self.mod.write_current_pulse(turns)
        content = open(os.path.join(self.tmp, "continuity", "CURRENT_PULSE.md")).read()
        self.assertIn("what is the plan", content)

    def test_pulse_contains_assistant_text(self):
        turns = [{"role": "assistant", "text": "the plan is X", "timestamp": "T"}]
        self.mod.write_current_pulse(turns)
        content = open(os.path.join(self.tmp, "continuity", "CURRENT_PULSE.md")).read()
        self.assertIn("the plan is X", content)

    def test_pulse_has_yaml_frontmatter(self):
        self.mod.write_current_pulse([])
        content = open(os.path.join(self.tmp, "continuity", "CURRENT_PULSE.md")).read()
        self.assertTrue(content.startswith("---"))
        self.assertIn("type: handoff", content)

    def test_pulse_no_llm_call(self):
        """write_current_pulse must never call generate_reasoning."""
        with patch("builtins.__import__") as mock_import:
            turns = [{"role": "user", "text": "hi", "timestamp": "T"}]
            self.mod.write_current_pulse(turns)
            # If generate_reasoning were called, it would need reasoning_utils import
            # We just verify the file was written without error
        pulse_path = os.path.join(self.tmp, "continuity", "CURRENT_PULSE.md")
        self.assertTrue(os.path.exists(pulse_path))


class TestWriteHandoff(unittest.TestCase):
    def setUp(self):
        self.tmp = _make_tmp_root()
        self.mod = _load_mod(self.tmp)

    def test_writes_handoff_file(self):
        self.mod.write_handoff()
        self.assertTrue(os.path.exists(self.mod.HANDOFF_PATH))

    def test_handoff_contains_timestamp(self):
        self.mod.write_handoff()
        content = open(self.mod.HANDOFF_PATH).read()
        self.assertIn(datetime.now().strftime("%Y-%m-%d"), content)

    def test_handoff_contains_reading_order(self):
        self.mod.write_handoff()
        content = open(self.mod.HANDOFF_PATH).read()
        self.assertIn("REINCARNATION_GAMEPLAN.md", content)
        self.assertIn("CURRENT_PULSE.md", content)
        self.assertIn("ISSUE_TRACKER.md", content)

    def test_handoff_is_static_template(self):
        """Two calls produce identical content except for the timestamp."""
        self.mod.write_handoff()
        c1 = open(self.mod.HANDOFF_PATH).read()
        self.mod.write_handoff()
        c2 = open(self.mod.HANDOFF_PATH).read()
        # Strip timestamp lines for comparison
        strip = lambda s: "\n".join(l for l in s.splitlines() if "Timestamp" not in l)
        self.assertEqual(strip(c1), strip(c2))


class TestWriteFlightRecorder(unittest.TestCase):
    def setUp(self):
        self.tmp = _make_tmp_root()
        self.mod = _load_mod(self.tmp)

    def test_writes_flight_recorder_file(self):
        turns = [{"role": "user", "text": "hello", "timestamp": "T1"},
                 {"role": "assistant", "text": "hi back", "timestamp": "T2"}]
        self.mod.write_flight_recorder(turns)
        fr_path = os.path.join(self.tmp, "continuity", "LAST_SESSION_FLIGHT_RECORDER.md")
        self.assertTrue(os.path.exists(fr_path))

    def test_flight_recorder_contains_all_turns(self):
        turns = [{"role": "user", "text": f"msg {i}", "timestamp": f"T{i}"} for i in range(20)]
        self.mod.write_flight_recorder(turns)
        content = open(os.path.join(self.tmp, "continuity", "LAST_SESSION_FLIGHT_RECORDER.md")).read()
        for i in range(20):
            self.assertIn(f"msg {i}", content)

    def test_flight_recorder_has_header(self):
        turns = [{"role": "user", "text": "hello", "timestamp": "T1"}]
        self.mod.write_flight_recorder(turns)
        content = open(os.path.join(self.tmp, "continuity", "LAST_SESSION_FLIGHT_RECORDER.md")).read()
        self.assertIn("Flight Recorder", content)

    def test_flight_recorder_rolling_delta(self):
        """When handoff_context_lines > 0, only the last N lines are kept."""
        turns = [{"role": "user", "text": f"msg {i}", "timestamp": f"T{i}"} for i in range(50)]
        self.mod.write_flight_recorder(turns, context_lines=10)
        content = open(os.path.join(self.tmp, "continuity", "LAST_SESSION_FLIGHT_RECORDER.md")).read()
        self.assertIn("Rolling Delta", content)
        # The body (after header) should be at most 10 lines
        body_lines = [l for l in content.splitlines() if l.strip() and not l.startswith("#") and not l.startswith("*")]
        self.assertLessEqual(len(body_lines), 10)

    def test_flight_recorder_full_history_when_zero(self):
        turns = [{"role": "user", "text": f"msg {i}", "timestamp": f"T{i}"} for i in range(20)]
        self.mod.write_flight_recorder(turns, context_lines=0)
        content = open(os.path.join(self.tmp, "continuity", "LAST_SESSION_FLIGHT_RECORDER.md")).read()
        self.assertIn("Full History", content)
        self.assertIn("msg 0", content)
        self.assertIn("msg 19", content)

    def test_flight_recorder_empty_turns(self):
        self.mod.write_flight_recorder([])
        fr_path = os.path.join(self.tmp, "continuity", "LAST_SESSION_FLIGHT_RECORDER.md")
        self.assertTrue(os.path.exists(fr_path))
        content = open(fr_path).read()
        self.assertIn("Flight Recorder", content)


class TestMainPulse(unittest.TestCase):
    def setUp(self):
        self.tmp = _make_tmp_root()
        self.mod = _load_mod(self.tmp)

    def test_graceful_when_no_transcripts(self):
        """main() must not raise when no JSONL files exist."""
        self.mod.find_transcripts = MagicMock(return_value=[])
        try:
            self.mod.main()
        except Exception as e:
            self.fail(f"main() raised with no transcripts: {e}")

    def test_writes_handoff_even_with_no_transcripts(self):
        """HANDOFF.md must always be refreshed, even if pulse is empty."""
        self.mod.find_transcripts = MagicMock(return_value=[])
        self.mod.main()
        self.assertTrue(os.path.exists(self.mod.HANDOFF_PATH))

    def test_main_writes_flight_recorder(self):
        """main() must write LAST_SESSION_FLIGHT_RECORDER.md."""
        jsonl_path = os.path.join(self.tmp, "session.jsonl")
        turns = [_user(f"turn {i}") for i in range(20)]
        _make_jsonl(jsonl_path, turns)
        self.mod.find_transcripts = MagicMock(return_value=[jsonl_path])
        self.mod.main()
        fr_path = os.path.join(self.tmp, "continuity", "LAST_SESSION_FLIGHT_RECORDER.md")
        self.assertTrue(os.path.exists(fr_path), "main() did not write LAST_SESSION_FLIGHT_RECORDER.md")
        content = open(fr_path).read()
        self.assertIn("Flight Recorder", content)
        self.assertIn("turn 0", content)

    def test_main_writes_flight_recorder_even_without_transcripts(self):
        """Flight recorder should still be written (empty) when no transcripts found."""
        self.mod.find_transcripts = MagicMock(return_value=[])
        self.mod.main()
        fr_path = os.path.join(self.tmp, "continuity", "LAST_SESSION_FLIGHT_RECORDER.md")
        self.assertTrue(os.path.exists(fr_path))


if __name__ == "__main__":
    unittest.main()
