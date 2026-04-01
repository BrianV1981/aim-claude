"""
Unit tests for Claude Code hooks:
  - hooks/cognitive_mantra.py
  - hooks/context_injector.py
  - hooks/failsafe_context_snapshot.py

All hooks communicate via stdin JSON → stdout JSON.
Tests mock filesystem I/O and do not touch real state files.
"""
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, mock_open, patch

# ─────────────────────────────────────────────────────────────────────────────
# Module loading helpers
# ─────────────────────────────────────────────────────────────────────────────

HOOKS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "hooks")


def _load_hook(name):
    """Load a hook module without running __main__."""
    path = os.path.join(HOOKS_DIR, name)
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─────────────────────────────────────────────────────────────────────────────
# cognitive_mantra.py
# ─────────────────────────────────────────────────────────────────────────────

class TestCognitiveMantraEmptyInput(unittest.TestCase):
    def setUp(self):
        self.mod = _load_hook("cognitive_mantra.py")

    def _run(self, stdin_text):
        with patch("sys.stdin", io.StringIO(stdin_text)):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                self.mod.main()
                return json.loads(mock_out.getvalue())

    def test_empty_stdin_returns_empty_dict(self):
        result = self._run("")
        self.assertEqual(result, {})

    def test_invalid_json_returns_empty_dict(self):
        result = self._run("not-json")
        self.assertEqual(result, {})


class TestCognitiveMantraNewSession(unittest.TestCase):
    def setUp(self):
        self.mod = _load_hook("cognitive_mantra.py")
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = os.path.join(self.tmpdir, "mantra_state.json")

    def _run(self, stdin_data, state_on_disk=None, claude_md_content=None):
        if state_on_disk is not None:
            with open(self.state_path, "w") as f:
                json.dump(state_on_disk, f)

        patches = [
            patch.object(self.mod, "state_file", self.state_path),
            patch.object(self.mod, "continuity_dir", self.tmpdir),
        ]
        if claude_md_content is not None:
            claude_path = os.path.join(self.tmpdir, "CLAUDE.md")
            with open(claude_path, "w") as f:
                f.write(claude_md_content)
            patches.append(patch.object(self.mod, "claude_md_path", claude_path))
        else:
            # Point to a non-existent path so we get empty content
            patches.append(patch.object(self.mod, "claude_md_path",
                                        os.path.join(self.tmpdir, "NO_CLAUDE.md")))

        with patch("sys.stdin", io.StringIO(json.dumps(stdin_data))):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                for p in patches:
                    p.start()
                try:
                    self.mod.main()
                finally:
                    for p in patches:
                        p.stop()
                return json.loads(mock_out.getvalue())

    def test_first_call_no_state_file_returns_empty(self):
        result = self._run({"session_id": "abc123"})
        self.assertEqual(result, {})

    def test_first_call_saves_state(self):
        self._run({"session_id": "abc123"})
        with open(self.state_path) as f:
            state = json.load(f)
        self.assertEqual(state["session_id"], "abc123")
        self.assertEqual(state["tool_count"], 1)

    def test_new_session_id_resets_counter(self):
        # Prime state with old session
        old_state = {"session_id": "OLD", "tool_count": 40,
                     "last_whisper": 25, "last_mantra": 0}
        result = self._run({"session_id": "NEW"}, state_on_disk=old_state)
        # Counter should reset — tool_count=1, no threshold hit
        self.assertEqual(result, {})
        with open(self.state_path) as f:
            state = json.load(f)
        self.assertEqual(state["tool_count"], 1)
        self.assertEqual(state["session_id"], "NEW")

    def test_continuing_session_increments_counter(self):
        existing = {"session_id": "s1", "tool_count": 5,
                    "last_whisper": 0, "last_mantra": 0}
        self._run({"session_id": "s1"}, state_on_disk=existing)
        with open(self.state_path) as f:
            state = json.load(f)
        self.assertEqual(state["tool_count"], 6)


class TestCognitiveMantraWhisper(unittest.TestCase):
    def setUp(self):
        self.mod = _load_hook("cognitive_mantra.py")
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = os.path.join(self.tmpdir, "mantra_state.json")

    def _run(self, stdin_data, state_on_disk=None):
        if state_on_disk is not None:
            with open(self.state_path, "w") as f:
                json.dump(state_on_disk, f)

        with patch.object(self.mod, "state_file", self.state_path), \
             patch.object(self.mod, "continuity_dir", self.tmpdir), \
             patch.object(self.mod, "claude_md_path",
                          os.path.join(self.tmpdir, "NO_CLAUDE.md")), \
             patch("sys.stdin", io.StringIO(json.dumps(stdin_data))), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            self.mod.main()
            return json.loads(mock_out.getvalue())

    def test_whisper_fires_at_25(self):
        # tool_count will become 25 after increment
        state = {"session_id": "s1", "tool_count": 24,
                 "last_whisper": 0, "last_mantra": 0}
        result = self._run({"session_id": "s1"}, state_on_disk=state)
        ctx = result.get("hookSpecificOutput", {}).get("additionalContext", "")
        self.assertIn("SUBCONSCIOUS WHISPER", ctx)
        self.assertIn("25", ctx)

    def test_whisper_updates_last_whisper(self):
        state = {"session_id": "s1", "tool_count": 24,
                 "last_whisper": 0, "last_mantra": 0}
        self._run({"session_id": "s1"}, state_on_disk=state)
        with open(self.state_path) as f:
            saved = json.load(f)
        self.assertEqual(saved["last_whisper"], 25)

    def test_whisper_does_not_fire_before_25(self):
        state = {"session_id": "s1", "tool_count": 20,
                 "last_whisper": 0, "last_mantra": 0}
        result = self._run({"session_id": "s1"}, state_on_disk=state)
        self.assertEqual(result, {})

    def test_whisper_fires_again_at_50_if_no_mantra(self):
        # last_mantra=0 but last_whisper=25; tool_count=49 → hits 50 → mantra takes priority
        # Test whisper at 50 w/ last_mantra already advanced beyond
        # Actually at count=50, MANTRA_INTERVAL fires (50-0 >= 50). Let's test second whisper at 75.
        state = {"session_id": "s1", "tool_count": 74,
                 "last_whisper": 50, "last_mantra": 50}
        result = self._run({"session_id": "s1"}, state_on_disk=state)
        ctx = result.get("hookSpecificOutput", {}).get("additionalContext", "")
        self.assertIn("SUBCONSCIOUS WHISPER", ctx)


class TestCognitiveMantraMantra(unittest.TestCase):
    def setUp(self):
        self.mod = _load_hook("cognitive_mantra.py")
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = os.path.join(self.tmpdir, "mantra_state.json")
        self.claude_path = os.path.join(self.tmpdir, "CLAUDE.md")
        with open(self.claude_path, "w") as f:
            f.write("# PRIME DIRECTIVES\nDo not guess.")

    def _run(self, stdin_data, state_on_disk=None):
        if state_on_disk is not None:
            with open(self.state_path, "w") as f:
                json.dump(state_on_disk, f)

        with patch.object(self.mod, "state_file", self.state_path), \
             patch.object(self.mod, "continuity_dir", self.tmpdir), \
             patch.object(self.mod, "claude_md_path", self.claude_path), \
             patch("sys.stdin", io.StringIO(json.dumps(stdin_data))), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            self.mod.main()
            return json.loads(mock_out.getvalue())

    def test_mantra_fires_at_50(self):
        state = {"session_id": "s1", "tool_count": 49,
                 "last_whisper": 25, "last_mantra": 0}
        result = self._run({"session_id": "s1"}, state_on_disk=state)
        ctx = result.get("hookSpecificOutput", {}).get("additionalContext", "")
        self.assertIn("MANTRA PROTOCOL", ctx)
        self.assertIn("50", ctx)

    def test_mantra_includes_claude_md_content(self):
        state = {"session_id": "s1", "tool_count": 49,
                 "last_whisper": 25, "last_mantra": 0}
        result = self._run({"session_id": "s1"}, state_on_disk=state)
        ctx = result.get("hookSpecificOutput", {}).get("additionalContext", "")
        self.assertIn("PRIME DIRECTIVES", ctx)
        self.assertIn("Do not guess.", ctx)

    def test_mantra_fires_without_claude_md(self):
        """Mantra should still fire even if CLAUDE.md is missing (empty content)."""
        state = {"session_id": "s1", "tool_count": 49,
                 "last_whisper": 25, "last_mantra": 0}
        # Temporarily remove the file
        with patch.object(self.mod, "claude_md_path",
                          os.path.join(self.tmpdir, "MISSING.md")):
            with patch.object(self.mod, "state_file", self.state_path), \
                 patch.object(self.mod, "continuity_dir", self.tmpdir), \
                 patch("sys.stdin", io.StringIO(json.dumps({"session_id": "s1"}))), \
                 patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                with open(self.state_path, "w") as f:
                    json.dump(state, f)
                self.mod.main()
                result = json.loads(mock_out.getvalue())
        ctx = result.get("hookSpecificOutput", {}).get("additionalContext", "")
        self.assertIn("MANTRA PROTOCOL", ctx)

    def test_mantra_takes_priority_over_whisper(self):
        """At count=50, mantra fires — not whisper."""
        state = {"session_id": "s1", "tool_count": 49,
                 "last_whisper": 25, "last_mantra": 0}
        result = self._run({"session_id": "s1"}, state_on_disk=state)
        ctx = result.get("hookSpecificOutput", {}).get("additionalContext", "")
        self.assertIn("MANTRA PROTOCOL", ctx)
        self.assertNotIn("SUBCONSCIOUS WHISPER", ctx)

    def test_mantra_updates_last_mantra(self):
        state = {"session_id": "s1", "tool_count": 49,
                 "last_whisper": 25, "last_mantra": 0}
        self._run({"session_id": "s1"}, state_on_disk=state)
        with open(self.state_path) as f:
            saved = json.load(f)
        self.assertEqual(saved["last_mantra"], 50)

    def test_mantra_fires_again_at_100(self):
        state = {"session_id": "s1", "tool_count": 99,
                 "last_whisper": 75, "last_mantra": 50}
        result = self._run({"session_id": "s1"}, state_on_disk=state)
        ctx = result.get("hookSpecificOutput", {}).get("additionalContext", "")
        self.assertIn("MANTRA PROTOCOL", ctx)
        self.assertIn("100", ctx)


# ─────────────────────────────────────────────────────────────────────────────
# context_injector.py
# ─────────────────────────────────────────────────────────────────────────────

class TestContextInjectorEdgeCases(unittest.TestCase):
    def setUp(self):
        self.mod = _load_hook("context_injector.py")

    def _run(self, stdin_text, tmpdir=None):
        patches = []
        if tmpdir:
            patches += [
                patch.object(self.mod, "continuity_dir", tmpdir),
                patch.object(self.mod, "core_dir", tmpdir),
                patch.object(self.mod, "state_file",
                             os.path.join(tmpdir, "injector_state.json")),
            ]
        with patch("sys.stdin", io.StringIO(stdin_text)), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            for p in patches:
                p.start()
            try:
                self.mod.main()
            finally:
                for p in patches:
                    p.stop()
            return json.loads(mock_out.getvalue())

    def test_empty_stdin_returns_empty_dict(self):
        result = self._run("")
        self.assertEqual(result, {})

    def test_invalid_json_returns_empty_dict(self):
        result = self._run("not-json")
        self.assertEqual(result, {})


class TestContextInjectorAlreadyInjected(unittest.TestCase):
    def setUp(self):
        self.mod = _load_hook("context_injector.py")
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = os.path.join(self.tmpdir, "injector_state.json")

    def _run(self, stdin_data, state_on_disk=None):
        if state_on_disk is not None:
            with open(self.state_path, "w") as f:
                json.dump(state_on_disk, f)

        with patch.object(self.mod, "continuity_dir", self.tmpdir), \
             patch.object(self.mod, "core_dir", self.tmpdir), \
             patch.object(self.mod, "state_file", self.state_path), \
             patch("sys.stdin", io.StringIO(json.dumps(stdin_data))), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            self.mod.main()
            return json.loads(mock_out.getvalue())

    def test_already_injected_same_session_returns_empty(self):
        state = {"session_id": "s1", "injected": True}
        result = self._run({"session_id": "s1"}, state_on_disk=state)
        self.assertEqual(result, {})

    def test_different_session_id_re_injects(self):
        # Write state for a different session; no context files → returns {} but marks injected
        state = {"session_id": "OLD", "injected": True}
        result = self._run({"session_id": "NEW"}, state_on_disk=state)
        # No files exist in tmpdir, so injection_parts is empty → returns {}
        self.assertEqual(result, {})
        # But state should be updated to NEW
        with open(self.state_path) as f:
            saved = json.load(f)
        self.assertEqual(saved["session_id"], "NEW")
        self.assertTrue(saved["injected"])

    def test_injected_false_same_session_re_injects(self):
        state = {"session_id": "s1", "injected": False}
        result = self._run({"session_id": "s1"}, state_on_disk=state)
        # No files → empty but state updated
        with open(self.state_path) as f:
            saved = json.load(f)
        self.assertTrue(saved["injected"])


class TestContextInjectorFileInjection(unittest.TestCase):
    def setUp(self):
        self.mod = _load_hook("context_injector.py")
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = os.path.join(self.tmpdir, "injector_state.json")

    def _write(self, filename, content):
        with open(os.path.join(self.tmpdir, filename), "w") as f:
            f.write(content)

    def _run(self, stdin_data):
        with patch.object(self.mod, "continuity_dir", self.tmpdir), \
             patch.object(self.mod, "core_dir", self.tmpdir), \
             patch.object(self.mod, "state_file", self.state_path), \
             patch("sys.stdin", io.StringIO(json.dumps(stdin_data))), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            self.mod.main()
            return json.loads(mock_out.getvalue())

    def test_no_context_files_returns_empty(self):
        result = self._run({"session_id": "s1"})
        self.assertEqual(result, {})

    def test_anchor_file_injected_with_header(self):
        self._write("ANCHOR.md", "ANCHOR CONTENT")
        result = self._run({"session_id": "s1"})
        ctx = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("MEMORY ANCHOR", ctx)
        self.assertIn("ANCHOR CONTENT", ctx)

    def test_core_memory_injected_with_header(self):
        self._write("CORE_MEMORY.md", "MEMORY CONTENT")
        result = self._run({"session_id": "s1"})
        ctx = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("CORE MEMORY", ctx)
        self.assertIn("MEMORY CONTENT", ctx)

    def test_current_pulse_injected_with_header(self):
        self._write("CURRENT_PULSE.md", "PULSE CONTENT")
        result = self._run({"session_id": "s1"})
        ctx = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("PROJECT MOMENTUM", ctx)
        self.assertIn("PULSE CONTENT", ctx)

    def test_fallback_tail_injected_with_header(self):
        self._write("FALLBACK_TAIL.md", "TAIL CONTENT")
        result = self._run({"session_id": "s1"})
        ctx = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("IMMEDIATE CONTEXT", ctx)
        self.assertIn("TAIL CONTENT", ctx)

    def test_issue_tracker_injected_with_header(self):
        self._write("ISSUE_TRACKER.md", "* #61 - Auto-sync issue tracker")
        result = self._run({"session_id": "s1"})
        ctx = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("OPEN TICKETS", ctx)
        self.assertIn("#61", ctx)

    def test_all_five_files_injected(self):
        self._write("ANCHOR.md", "A")
        self._write("CORE_MEMORY.md", "B")
        self._write("CURRENT_PULSE.md", "C")
        self._write("FALLBACK_TAIL.md", "D")
        self._write("ISSUE_TRACKER.md", "E")
        result = self._run({"session_id": "s1"})
        ctx = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("SESSION ONBOARDING", ctx)
        self.assertIn("END ONBOARDING", ctx)
        for marker in ["MEMORY ANCHOR", "CORE MEMORY", "PROJECT MOMENTUM", "IMMEDIATE CONTEXT", "OPEN TICKETS"]:
            self.assertIn(marker, ctx)

    def test_all_four_files_injected(self):
        self._write("ANCHOR.md", "A")
        self._write("CORE_MEMORY.md", "B")
        self._write("CURRENT_PULSE.md", "C")
        self._write("FALLBACK_TAIL.md", "D")
        result = self._run({"session_id": "s1"})
        ctx = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("SESSION ONBOARDING", ctx)
        self.assertIn("END ONBOARDING", ctx)
        for marker in ["MEMORY ANCHOR", "CORE MEMORY", "PROJECT MOMENTUM", "IMMEDIATE CONTEXT"]:
            self.assertIn(marker, ctx)

    def test_partial_files_skipped_gracefully(self):
        """Only ANCHOR.md present — others silently skipped."""
        self._write("ANCHOR.md", "ANCHOR HERE")
        result = self._run({"session_id": "s1"})
        ctx = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("ANCHOR HERE", ctx)
        self.assertNotIn("CORE MEMORY", ctx)

    def test_empty_file_skipped(self):
        """Empty file (whitespace only) should be treated as None."""
        self._write("ANCHOR.md", "   ")
        result = self._run({"session_id": "s1"})
        # No non-empty files → empty result
        self.assertEqual(result, {})

    def test_state_file_marks_injected(self):
        self._write("ANCHOR.md", "content")
        self._run({"session_id": "s1"})
        with open(self.state_path) as f:
            saved = json.load(f)
        self.assertEqual(saved["session_id"], "s1")
        self.assertTrue(saved["injected"])


class TestReadFileSafe(unittest.TestCase):
    def setUp(self):
        self.mod = _load_hook("context_injector.py")
        self.tmpdir = tempfile.mkdtemp()

    def test_returns_none_for_nonexistent_file(self):
        result = self.mod.read_file_safe("/no/such/file.md")
        self.assertIsNone(result)

    def test_returns_none_for_empty_file(self):
        path = os.path.join(self.tmpdir, "empty.md")
        with open(path, "w") as f:
            f.write("  \n  ")
        result = self.mod.read_file_safe(path)
        self.assertIsNone(result)

    def test_returns_content_for_valid_file(self):
        path = os.path.join(self.tmpdir, "valid.md")
        with open(path, "w") as f:
            f.write("hello world")
        result = self.mod.read_file_safe(path)
        self.assertEqual(result, "hello world")

    def test_strips_whitespace(self):
        path = os.path.join(self.tmpdir, "padded.md")
        with open(path, "w") as f:
            f.write("  trimmed  ")
        result = self.mod.read_file_safe(path)
        self.assertEqual(result, "trimmed")


# ─────────────────────────────────────────────────────────────────────────────
# failsafe_context_snapshot.py
# ─────────────────────────────────────────────────────────────────────────────

class TestFailsafeEdgeCases(unittest.TestCase):
    def setUp(self):
        self.mod = _load_hook("failsafe_context_snapshot.py")

    def _run(self, stdin_text, tmpdir=None):
        patches = []
        if tmpdir:
            patches += [
                patch.object(self.mod, "continuity_dir", tmpdir),
                patch.object(self.mod, "backup_path",
                             os.path.join(tmpdir, "INTERIM_BACKUP.jsonl")),
                patch.object(self.mod, "tail_path",
                             os.path.join(tmpdir, "FALLBACK_TAIL.md")),
            ]
        with patch("sys.stdin", io.StringIO(stdin_text)), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            for p in patches:
                p.start()
            try:
                self.mod.main()
            finally:
                for p in patches:
                    p.stop()
            return json.loads(mock_out.getvalue())

    def test_empty_stdin_returns_empty_dict(self):
        result = self._run("")
        self.assertEqual(result, {})

    def test_invalid_json_returns_empty_dict(self):
        result = self._run("not-json")
        self.assertEqual(result, {})

    def test_missing_transcript_path_returns_empty(self):
        tmpdir = tempfile.mkdtemp()
        result = self._run(json.dumps({"session_id": "s1"}), tmpdir=tmpdir)
        self.assertEqual(result, {})

    def test_nonexistent_transcript_returns_empty(self):
        tmpdir = tempfile.mkdtemp()
        data = {"session_id": "s1", "transcript_path": "/no/such/file.jsonl"}
        result = self._run(json.dumps(data), tmpdir=tmpdir)
        self.assertEqual(result, {})
        # No backup file should be created
        self.assertFalse(os.path.exists(os.path.join(tmpdir, "INTERIM_BACKUP.jsonl")))


class TestFailsafeBackup(unittest.TestCase):
    def setUp(self):
        self.mod = _load_hook("failsafe_context_snapshot.py")
        self.tmpdir = tempfile.mkdtemp()
        self.backup = os.path.join(self.tmpdir, "INTERIM_BACKUP.jsonl")
        self.tail = os.path.join(self.tmpdir, "FALLBACK_TAIL.md")

    def _write_transcript(self, messages):
        path = os.path.join(self.tmpdir, "session.jsonl")
        with open(path, "w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")
        return path

    def _run(self, stdin_data):
        with patch.object(self.mod, "continuity_dir", self.tmpdir), \
             patch.object(self.mod, "backup_path", self.backup), \
             patch.object(self.mod, "tail_path", self.tail), \
             patch("sys.stdin", io.StringIO(json.dumps(stdin_data))), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            self.mod.main()
            return json.loads(mock_out.getvalue())

    def test_backup_file_created(self):
        transcript = self._write_transcript([
            {"type": "human", "message": {"role": "user", "content": "hello"}}
        ])
        self._run({"session_id": "s1", "transcript_path": transcript})
        self.assertTrue(os.path.exists(self.backup))

    def test_backup_content_matches_transcript(self):
        original_line = json.dumps({"type": "human", "message": {"role": "user", "content": "hi"}})
        transcript = os.path.join(self.tmpdir, "session.jsonl")
        with open(transcript, "w") as f:
            f.write(original_line + "\n")
        self._run({"session_id": "s1", "transcript_path": transcript})
        with open(self.backup) as f:
            content = f.read()
        self.assertIn("hi", content)

    def test_fallback_tail_created(self):
        transcript = self._write_transcript([
            {"type": "human", "message": {"role": "user", "content": "hello"},
             "timestamp": "2026-03-31T00:00:00Z"},
        ])
        self._run({"session_id": "s1", "transcript_path": transcript})
        self.assertTrue(os.path.exists(self.tail))

    def test_main_always_returns_empty_dict(self):
        transcript = self._write_transcript([
            {"type": "human", "message": {"role": "user", "content": "hello"}}
        ])
        result = self._run({"session_id": "s1", "transcript_path": transcript})
        self.assertEqual(result, {})


class TestReadRecentTurns(unittest.TestCase):
    def setUp(self):
        self.mod = _load_hook("failsafe_context_snapshot.py")
        self.tmpdir = tempfile.mkdtemp()

    def _write_jsonl(self, messages):
        path = os.path.join(self.tmpdir, "turns.jsonl")
        with open(path, "w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")
        return path

    def test_returns_empty_list_for_missing_file(self):
        result = self.mod.read_recent_turns("/no/such/file.jsonl")
        self.assertEqual(result, [])

    def test_returns_last_n_turns(self):
        msgs = [{"type": "human", "id": i} for i in range(20)]
        path = self._write_jsonl(msgs)
        result = self.mod.read_recent_turns(path, n=5)
        self.assertEqual(len(result), 5)
        self.assertEqual(result[0]["id"], 15)

    def test_skips_file_history_snapshot(self):
        msgs = [
            {"type": "file-history-snapshot", "data": "skip me"},
            {"type": "human", "message": {"role": "user", "content": "keep me"}},
        ]
        path = self._write_jsonl(msgs)
        result = self.mod.read_recent_turns(path, n=10)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "human")

    def test_handles_malformed_lines(self):
        path = os.path.join(self.tmpdir, "bad.jsonl")
        with open(path, "w") as f:
            f.write("not-json\n")
            f.write(json.dumps({"type": "human"}) + "\n")
        result = self.mod.read_recent_turns(path, n=10)
        self.assertEqual(len(result), 1)

    def test_handles_empty_lines(self):
        path = os.path.join(self.tmpdir, "empty_lines.jsonl")
        with open(path, "w") as f:
            f.write("\n\n")
            f.write(json.dumps({"type": "human"}) + "\n")
        result = self.mod.read_recent_turns(path, n=10)
        self.assertEqual(len(result), 1)

    def test_returns_all_if_fewer_than_n(self):
        msgs = [{"type": "human", "id": i} for i in range(3)]
        path = self._write_jsonl(msgs)
        result = self.mod.read_recent_turns(path, n=10)
        self.assertEqual(len(result), 3)


class TestBuildTailMarkdown(unittest.TestCase):
    def setUp(self):
        self.mod = _load_hook("failsafe_context_snapshot.py")

    def test_returns_markdown_header(self):
        md = self.mod.build_tail_markdown([])
        self.assertIn("FALLBACK CONTEXT TAIL", md)

    def test_user_turn_string_content(self):
        turns = [{"type": "human",
                  "message": {"role": "user", "content": "hello there"},
                  "timestamp": "T1"}]
        md = self.mod.build_tail_markdown(turns)
        self.assertIn("USER", md)
        self.assertIn("hello there", md)

    def test_user_turn_list_content(self):
        turns = [{"type": "human",
                  "message": {"role": "user",
                               "content": [{"type": "text", "text": "list text"}]},
                  "timestamp": "T1"}]
        md = self.mod.build_tail_markdown(turns)
        self.assertIn("list text", md)

    def test_assistant_text_block(self):
        turns = [{"type": "assistant",
                  "message": {"role": "assistant",
                               "content": [{"type": "text", "text": "I did it"}]},
                  "timestamp": "T2"}]
        md = self.mod.build_tail_markdown(turns)
        self.assertIn("A.I.M.", md)
        self.assertIn("I did it", md)

    def test_assistant_tool_use_block(self):
        turns = [{"type": "assistant",
                  "message": {"role": "assistant",
                               "content": [{"type": "tool_use",
                                            "name": "Bash",
                                            "input": {"command": "ls"}}]},
                  "timestamp": "T2"}]
        md = self.mod.build_tail_markdown(turns)
        self.assertIn("Tool Call", md)
        self.assertIn("Bash", md)
        self.assertIn("ls", md)

    def test_turns_separated_by_hr(self):
        turns = [
            {"type": "human", "message": {"role": "user", "content": "q"},
             "timestamp": "T1"},
            {"type": "assistant",
             "message": {"role": "assistant",
                          "content": [{"type": "text", "text": "a"}]},
             "timestamp": "T2"},
        ]
        md = self.mod.build_tail_markdown(turns)
        self.assertGreater(md.count("---"), 1)

    def test_user_content_truncated_at_500(self):
        long_text = "x" * 1000
        turns = [{"type": "human",
                  "message": {"role": "user", "content": long_text},
                  "timestamp": "T1"}]
        md = self.mod.build_tail_markdown(turns)
        # The raw content is 1000 chars, but only 500 should appear
        self.assertIn("x" * 500, md)
        self.assertNotIn("x" * 501, md)


class TestCheckSignificance(unittest.TestCase):
    def setUp(self):
        self.mod = _load_hook("failsafe_context_snapshot.py")
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = os.path.join(self.tmpdir, "scrivener_state.json")

    def test_high_impact_tool_returns_true(self):
        for tool in ["Edit", "Write", "Bash", "NotebookEdit"]:
            with self.subTest(tool=tool):
                result = self.mod.check_significance(tool, "/any/path", "s1")
                self.assertTrue(result)

    def test_low_impact_tool_no_state_file_returns_false(self):
        with patch.object(self.mod, "state_file", self.state_path):
            result = self.mod.check_significance("Read", "/any/path", "s1")
        self.assertFalse(result)

    def test_five_or_more_new_turns_returns_true(self):
        # Create state with last_count=0 and transcript with 5 lines
        with open(self.state_path, "w") as f:
            json.dump({"s1": 0}, f)
        transcript = os.path.join(self.tmpdir, "t.jsonl")
        with open(transcript, "w") as f:
            for i in range(5):
                f.write(json.dumps({"id": i}) + "\n")
        with patch.object(self.mod, "state_file", self.state_path):
            result = self.mod.check_significance("Read", transcript, "s1")
        self.assertTrue(result)

    def test_fewer_than_five_new_turns_returns_false(self):
        with open(self.state_path, "w") as f:
            json.dump({"s1": 0}, f)
        transcript = os.path.join(self.tmpdir, "t.jsonl")
        with open(transcript, "w") as f:
            for i in range(4):
                f.write(json.dumps({"id": i}) + "\n")
        with patch.object(self.mod, "state_file", self.state_path):
            result = self.mod.check_significance("Read", transcript, "s1")
        self.assertFalse(result)

    def test_dict_state_for_session_uses_last_narrated_turn(self):
        """State value may be a dict with last_narrated_turn key."""
        with open(self.state_path, "w") as f:
            json.dump({"s1": {"last_narrated_turn": 0}}, f)
        transcript = os.path.join(self.tmpdir, "t.jsonl")
        with open(transcript, "w") as f:
            for i in range(5):
                f.write(json.dumps({"id": i}) + "\n")
        with patch.object(self.mod, "state_file", self.state_path):
            result = self.mod.check_significance("Read", transcript, "s1")
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
