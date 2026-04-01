"""
Integration tests for Claude Code hook lifecycle.

Tests the three PostToolUse/PreToolUse hooks as real subprocesses:
  - hooks/cognitive_mantra.py  (PostToolUse — drift prevention counter)
  - hooks/context_injector.py  (PreToolUse  — JIT session onboarding)
  - hooks/failsafe_context_snapshot.py (PostToolUse — FALLBACK_TAIL.md writer)

Each test runs the hook via subprocess, feeding crafted stdin JSON,
then asserts on stdout JSON and/or state file mutations.
No LLM calls are made; all hooks operate purely on file I/O.
"""
import json
import os
import sys
import tempfile
import pytest

AIM_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HOOKS_DIR = os.path.join(AIM_ROOT, "hooks")


def run_hook(hook_name, stdin_payload, env_overrides=None):
    """Run a hook as a subprocess, return (returncode, stdout_text, stderr_text)."""
    import subprocess

    hook_path = os.path.join(HOOKS_DIR, hook_name)
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)

    result = subprocess.run(
        [sys.executable, hook_path],
        input=json.dumps(stdin_payload),
        capture_output=True,
        text=True,
        cwd=AIM_ROOT,
        env=env,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Hook 1 — cognitive_mantra.py
# ─────────────────────────────────────────────────────────────────────────────

class TestCognitiveMantraLifecycle:
    """
    cognitive_mantra.py tracks tool_count in continuity/mantra_state.json.
    At count 25 it emits a WHISPER; at count 50 it emits the full MANTRA.
    Integration tests run the hook as a subprocess and verify state file mutations
    and stdout JSON across multiple invocations within the same session.
    """

    HOOK = "cognitive_mantra.py"
    SESSION_ID = "test-session-mantra-001"

    def _payload(self):
        return {
            "tool_name": "Bash",
            "tool_input": {},
            "tool_response": {},
            "session_id": self.SESSION_ID,
        }

    def _read_state(self, continuity_dir):
        state_file = os.path.join(continuity_dir, "mantra_state.json")
        if not os.path.exists(state_file):
            return {}
        with open(state_file) as f:
            return json.load(f)

    def _run_n_times(self, n, continuity_dir):
        """Run the hook n times, patching the continuity dir via a wrapper script."""
        import subprocess, textwrap

        wrapper = textwrap.dedent(f"""
            import sys, os, json
            # Redirect state file to temp dir before importing hook
            hook_dir = {repr(HOOKS_DIR)}
            aim_root = {repr(AIM_ROOT)}
            continuity_dir = {repr(continuity_dir)}
            state_file = os.path.join(continuity_dir, "mantra_state.json")
            claude_md_path = os.path.join(aim_root, "CLAUDE.md")

            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "cognitive_mantra",
                os.path.join(hook_dir, "cognitive_mantra.py")
            )
            mod = importlib.util.module_from_spec(spec)
            # Patch paths BEFORE exec
            mod.__dict__["__name__"] = "cognitive_mantra"
            spec.loader.exec_module(mod)
            # Override module-level path variables
            mod.continuity_dir = continuity_dir
            mod.state_file = state_file
            mod.claude_md_path = claude_md_path
            os.makedirs(continuity_dir, exist_ok=True)
            mod.main()
        """)

        outputs = []
        for _ in range(n):
            result = subprocess.run(
                [sys.executable, "-c", wrapper],
                input=json.dumps(self._payload()),
                capture_output=True,
                text=True,
                cwd=AIM_ROOT,
            )
            try:
                out = json.loads(result.stdout.strip())
            except Exception:
                out = {}
            outputs.append(out)
        return outputs

    def test_call_count_increments(self, tmp_path):
        """After N calls the state file records tool_count == N."""
        continuity_dir = str(tmp_path / "continuity")
        os.makedirs(continuity_dir)
        self._run_n_times(5, continuity_dir)
        state = self._read_state(continuity_dir)
        assert state.get("tool_count") == 5

    def test_no_threshold_returns_empty_dict(self, tmp_path):
        """First 24 calls should each return {}."""
        continuity_dir = str(tmp_path / "continuity")
        os.makedirs(continuity_dir)
        outputs = self._run_n_times(24, continuity_dir)
        for out in outputs:
            assert out == {}, f"Expected {{}} but got {out}"

    def test_whisper_fires_at_call_25(self, tmp_path):
        """Call 25 triggers the SUBCONSCIOUS WHISPER."""
        continuity_dir = str(tmp_path / "continuity")
        os.makedirs(continuity_dir)
        outputs = self._run_n_times(25, continuity_dir)
        last = outputs[-1]
        context = last.get("hookSpecificOutput", {}).get("additionalContext", "")
        assert "SUBCONSCIOUS WHISPER" in context, f"Expected WHISPER in call 25, got: {last}"
        assert "25 tool calls" in context

    def test_mantra_fires_at_call_50(self, tmp_path):
        """Call 50 triggers the full MANTRA PROTOCOL."""
        continuity_dir = str(tmp_path / "continuity")
        os.makedirs(continuity_dir)
        outputs = self._run_n_times(50, continuity_dir)
        last = outputs[-1]
        context = last.get("hookSpecificOutput", {}).get("additionalContext", "")
        assert "MANTRA PROTOCOL" in context, f"Expected MANTRA in call 50, got: {last}"
        assert "50 autonomous tool calls" in context

    def test_new_session_resets_counter(self, tmp_path):
        """A new session_id resets tool_count to 1 even if old state exists."""
        import subprocess, textwrap, json

        continuity_dir = str(tmp_path / "continuity")
        os.makedirs(continuity_dir)

        # Pre-seed a state file from a different session at count 24
        state_file = os.path.join(continuity_dir, "mantra_state.json")
        with open(state_file, "w") as f:
            json.dump({"tool_count": 24, "last_whisper": 0, "last_mantra": 0,
                       "session_id": "old-session-999"}, f)

        # Now run once with a fresh session id
        wrapper = textwrap.dedent(f"""
            import sys, os, json, importlib.util
            continuity_dir = {repr(continuity_dir)}
            state_file = os.path.join(continuity_dir, "mantra_state.json")
            spec = importlib.util.spec_from_file_location(
                "cognitive_mantra",
                os.path.join({repr(HOOKS_DIR)}, "cognitive_mantra.py")
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.continuity_dir = continuity_dir
            mod.state_file = state_file
            mod.claude_md_path = os.path.join({repr(AIM_ROOT)}, "CLAUDE.md")
            mod.main()
        """)
        payload = {
            "tool_name": "Bash",
            "tool_input": {},
            "tool_response": {},
            "session_id": "brand-new-session-xyz",
        }
        result = subprocess.run(
            [sys.executable, "-c", wrapper],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=AIM_ROOT,
        )
        state = self._read_state(continuity_dir)
        assert state.get("tool_count") == 1, f"Expected reset to 1, got {state}"
        assert state.get("session_id") == "brand-new-session-xyz"


# ─────────────────────────────────────────────────────────────────────────────
# Hook 2 — context_injector.py
# ─────────────────────────────────────────────────────────────────────────────

class TestContextInjectorLifecycle:
    """
    context_injector.py reads continuity/ and core/ files and injects them
    as additionalContext on the FIRST tool call of a session.
    Subsequent calls within the same session return {}.

    Integration tests run the hook as a subprocess using a patched module
    that points file paths at a temp directory.
    """

    HOOK = "context_injector.py"
    SESSION_ID = "test-session-injector-001"

    def _run_injector(self, session_id, continuity_dir, core_dir):
        import subprocess, textwrap

        wrapper = textwrap.dedent(f"""
            import sys, os, json, importlib.util
            continuity_dir = {repr(continuity_dir)}
            core_dir = {repr(core_dir)}
            state_file = os.path.join(continuity_dir, "injector_state.json")
            spec = importlib.util.spec_from_file_location(
                "context_injector",
                os.path.join({repr(HOOKS_DIR)}, "context_injector.py")
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.continuity_dir = continuity_dir
            mod.core_dir = core_dir
            mod.state_file = state_file
            os.makedirs(continuity_dir, exist_ok=True)
            mod.main()
        """)
        payload = {
            "tool_name": "Read",
            "tool_input": {},
            "tool_response": {},
            "session_id": session_id,
        }
        result = subprocess.run(
            [sys.executable, "-c", wrapper],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=AIM_ROOT,
        )
        try:
            return json.loads(result.stdout.strip())
        except Exception:
            return {}

    def test_first_call_injects_context(self, tmp_path):
        """First call for a new session returns additionalContext when files exist."""
        continuity_dir = str(tmp_path / "continuity")
        core_dir = str(tmp_path / "core")
        os.makedirs(continuity_dir)
        os.makedirs(core_dir)

        # Plant a context file
        with open(os.path.join(core_dir, "ANCHOR.md"), "w") as f:
            f.write("# THE ANCHOR\nThis is the immutable truth.\n")

        result = self._run_injector(self.SESSION_ID, continuity_dir, core_dir)
        context = result.get("hookSpecificOutput", {}).get("additionalContext", "")
        assert "SESSION ONBOARDING" in context, f"Expected onboarding block, got: {result}"
        assert "ANCHOR" in context or "immutable truth" in context

    def test_second_call_same_session_returns_empty(self, tmp_path):
        """Second call within the same session returns {} (already injected)."""
        continuity_dir = str(tmp_path / "continuity")
        core_dir = str(tmp_path / "core")
        os.makedirs(continuity_dir)
        os.makedirs(core_dir)

        with open(os.path.join(core_dir, "ANCHOR.md"), "w") as f:
            f.write("# THE ANCHOR\nContent here.\n")

        self._run_injector(self.SESSION_ID, continuity_dir, core_dir)
        second = self._run_injector(self.SESSION_ID, continuity_dir, core_dir)
        assert second == {}, f"Expected {{}} on second call, got: {second}"

    def test_no_context_files_returns_empty(self, tmp_path):
        """If no context files exist, hook returns {} even on first call."""
        continuity_dir = str(tmp_path / "continuity")
        core_dir = str(tmp_path / "core")
        os.makedirs(continuity_dir)
        os.makedirs(core_dir)

        result = self._run_injector(self.SESSION_ID, continuity_dir, core_dir)
        assert result == {}, f"Expected {{}} when no context files, got: {result}"

    def test_all_context_files_injected(self, tmp_path):
        """All four context files (ANCHOR, CORE_MEMORY, CURRENT_PULSE, FALLBACK_TAIL) are injected."""
        continuity_dir = str(tmp_path / "continuity")
        core_dir = str(tmp_path / "core")
        os.makedirs(continuity_dir)
        os.makedirs(core_dir)

        with open(os.path.join(core_dir, "ANCHOR.md"), "w") as f:
            f.write("Anchor content")
        with open(os.path.join(continuity_dir, "CORE_MEMORY.md"), "w") as f:
            f.write("Core memory content")
        with open(os.path.join(continuity_dir, "CURRENT_PULSE.md"), "w") as f:
            f.write("Pulse content")
        with open(os.path.join(continuity_dir, "FALLBACK_TAIL.md"), "w") as f:
            f.write("Tail content")

        result = self._run_injector(self.SESSION_ID, continuity_dir, core_dir)
        context = result.get("hookSpecificOutput", {}).get("additionalContext", "")
        assert "MEMORY ANCHOR" in context
        assert "CORE MEMORY" in context
        assert "PROJECT MOMENTUM" in context
        assert "IMMEDIATE CONTEXT" in context

    def test_new_session_injects_again(self, tmp_path):
        """A different session_id triggers injection even if another session was already injected."""
        continuity_dir = str(tmp_path / "continuity")
        core_dir = str(tmp_path / "core")
        os.makedirs(continuity_dir)
        os.makedirs(core_dir)

        with open(os.path.join(core_dir, "ANCHOR.md"), "w") as f:
            f.write("Anchor for second session")

        self._run_injector("session-A", continuity_dir, core_dir)
        result_b = self._run_injector("session-B", continuity_dir, core_dir)
        context = result_b.get("hookSpecificOutput", {}).get("additionalContext", "")
        assert "SESSION ONBOARDING" in context, f"Expected injection for session-B, got: {result_b}"


# ─────────────────────────────────────────────────────────────────────────────
# Hook 3 — failsafe_context_snapshot.py
# ─────────────────────────────────────────────────────────────────────────────

class TestFailsafeContextSnapshotLifecycle:
    """
    failsafe_context_snapshot.py reads a Claude Code JSONL transcript and writes:
      - continuity/FALLBACK_TAIL.md  (last 10 turns, human-readable Markdown)
      - continuity/INTERIM_BACKUP.jsonl  (rolling copy of the transcript)

    Integration tests create a minimal JSONL transcript in a temp directory
    and run the hook as a subprocess, asserting that FALLBACK_TAIL.md is written
    with the expected structure.
    """

    HOOK = "failsafe_context_snapshot.py"
    SESSION_ID = "test-session-snapshot-001"

    def _make_minimal_jsonl(self, path, num_turns=3):
        """Write a minimal Claude Code JSONL transcript."""
        lines = []
        import time

        for i in range(num_turns):
            # User turn
            lines.append(json.dumps({
                "type": "human",
                "sessionId": self.SESSION_ID,
                "timestamp": f"2026-01-01T00:0{i}:00Z",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": f"User message {i}"}],
                },
            }))
            # Assistant turn
            lines.append(json.dumps({
                "type": "assistant",
                "sessionId": self.SESSION_ID,
                "timestamp": f"2026-01-01T00:0{i}:05Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": f"Assistant response {i}"},
                        {"type": "tool_use", "name": "Bash", "input": {"command": f"echo {i}"}},
                    ],
                },
            }))
        with open(path, "w") as f:
            f.write("\n".join(lines) + "\n")

    def _run_snapshot(self, transcript_path, continuity_dir):
        import subprocess, textwrap

        wrapper = textwrap.dedent(f"""
            import sys, os, json, importlib.util
            continuity_dir = {repr(continuity_dir)}
            backup_path = os.path.join(continuity_dir, "INTERIM_BACKUP.jsonl")
            tail_path = os.path.join(continuity_dir, "FALLBACK_TAIL.md")
            state_file = os.path.join({repr(AIM_ROOT)}, "archive", "scrivener_state.json")
            spec = importlib.util.spec_from_file_location(
                "failsafe_context_snapshot",
                os.path.join({repr(HOOKS_DIR)}, "failsafe_context_snapshot.py")
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.continuity_dir = continuity_dir
            mod.backup_path = backup_path
            mod.tail_path = tail_path
            mod.state_file = state_file
            os.makedirs(continuity_dir, exist_ok=True)
            mod.main()
        """)
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo test"},
            "tool_response": {"output": "test"},
            "session_id": self.SESSION_ID,
            "transcript_path": transcript_path,
        }
        result = subprocess.run(
            [sys.executable, "-c", wrapper],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=AIM_ROOT,
        )
        return result

    def test_fallback_tail_is_written(self, tmp_path):
        """Hook writes FALLBACK_TAIL.md when given a valid transcript_path."""
        transcript_path = str(tmp_path / "session.jsonl")
        continuity_dir = str(tmp_path / "continuity")
        os.makedirs(continuity_dir)
        self._make_minimal_jsonl(transcript_path, num_turns=3)

        result = self._run_snapshot(transcript_path, continuity_dir)
        assert result.returncode == 0, f"Hook exited non-zero: {result.stderr}"

        tail_path = os.path.join(continuity_dir, "FALLBACK_TAIL.md")
        assert os.path.exists(tail_path), "FALLBACK_TAIL.md was not created"

        with open(tail_path) as f:
            content = f.read()
        assert "A.I.M. FALLBACK CONTEXT TAIL" in content
        assert "USER" in content or "A.I.M." in content

    def test_interim_backup_is_written(self, tmp_path):
        """Hook copies the transcript to INTERIM_BACKUP.jsonl."""
        transcript_path = str(tmp_path / "session.jsonl")
        continuity_dir = str(tmp_path / "continuity")
        os.makedirs(continuity_dir)
        self._make_minimal_jsonl(transcript_path, num_turns=2)

        self._run_snapshot(transcript_path, continuity_dir)

        backup_path = os.path.join(continuity_dir, "INTERIM_BACKUP.jsonl")
        assert os.path.exists(backup_path), "INTERIM_BACKUP.jsonl was not created"

        with open(backup_path) as f:
            backup_content = f.read()
        with open(transcript_path) as f:
            original_content = f.read()
        assert backup_content == original_content, "Backup content does not match original"

    def test_hook_returns_empty_dict_on_stdout(self, tmp_path):
        """Hook always outputs {} on stdout (pass-through to Claude Code)."""
        transcript_path = str(tmp_path / "session.jsonl")
        continuity_dir = str(tmp_path / "continuity")
        os.makedirs(continuity_dir)
        self._make_minimal_jsonl(transcript_path)

        result = self._run_snapshot(transcript_path, continuity_dir)
        assert result.returncode == 0
        out = json.loads(result.stdout.strip())
        assert out == {}, f"Expected {{}} on stdout, got: {out}"

    def test_missing_transcript_path_runs_cleanly(self, tmp_path):
        """Hook handles missing transcript_path gracefully — still exits 0."""
        continuity_dir = str(tmp_path / "continuity")
        os.makedirs(continuity_dir)
        import subprocess

        payload = {
            "tool_name": "Bash",
            "tool_input": {},
            "tool_response": {},
            "session_id": self.SESSION_ID,
            "transcript_path": "",
        }
        hook_path = os.path.join(HOOKS_DIR, self.HOOK)
        result = subprocess.run(
            [sys.executable, hook_path],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=AIM_ROOT,
        )
        assert result.returncode == 0, f"Hook crashed on empty transcript_path: {result.stderr}"
        out = json.loads(result.stdout.strip())
        assert out == {}

    def test_tail_contains_tool_calls(self, tmp_path):
        """FALLBACK_TAIL.md captures assistant tool_use blocks."""
        transcript_path = str(tmp_path / "session.jsonl")
        continuity_dir = str(tmp_path / "continuity")
        os.makedirs(continuity_dir)
        self._make_minimal_jsonl(transcript_path, num_turns=2)

        self._run_snapshot(transcript_path, continuity_dir)

        tail_path = os.path.join(continuity_dir, "FALLBACK_TAIL.md")
        with open(tail_path) as f:
            content = f.read()
        # The hook formats tool_use blocks as "**Tool Call:** `<name>`"
        assert "Tool Call" in content or "Bash" in content, \
            f"Expected tool call in tail, got:\n{content}"
