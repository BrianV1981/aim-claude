"""
Integration tests for the A.I.M. System 3 Reincarnation Pipeline.

System 3 consists of two producers and one consumer:
  Producer 1 — hooks/failsafe_context_snapshot.py
    Writes continuity/FALLBACK_TAIL.md from a Claude Code JSONL transcript.

  Producer 2 — src/handoff_pulse_generator.py
    Reads Gemini raw transcripts OR archive/raw/ JSON files,
    extracts signal, writes:
      - continuity/LAST_SESSION_FLIGHT_RECORDER.md
      - continuity/CURRENT_PULSE.md
      - continuity/REINCARNATION_GAMEPLAN.md  (requires LLM — mocked here)

Tests verify:
  1. failsafe_context_snapshot writes FALLBACK_TAIL.md with correct structure
     when supplied a JSONL transcript with realistic turn data.
  2. FALLBACK_TAIL.md header, USER blocks, and tool-call blocks are present.
  3. The continuity files written by handoff_pulse_generator can be reproduced
     by calling atomic_write() directly (mocking the LLM call), verifying
     file creation and atomic-write correctness without a real LLM.
  4. The reincarnation pipeline directory structure exists and is writable.
"""
import json
import os
import sys
import subprocess
import textwrap

import pytest

AIM_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HOOKS_DIR = os.path.join(AIM_ROOT, "hooks")
SRC_DIR = os.path.join(AIM_ROOT, "src")
CONTINUITY_DIR = os.path.join(AIM_ROOT, "continuity")
VENV_PYTHON = os.path.join(AIM_ROOT, "venv", "bin", "python3")
PYTHON = VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable

SESSION_ID = "integration-test-reincarnation-001"


def make_jsonl_transcript(path, session_id=SESSION_ID, num_turns=4):
    """Write a Claude Code JSONL transcript with realistic turn data."""
    lines = []
    for i in range(num_turns):
        lines.append(json.dumps({
            "type": "human",
            "sessionId": session_id,
            "timestamp": f"2026-01-01T00:0{i}:00Z",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": f"User turn {i}: please do something."}],
            },
        }))
        lines.append(json.dumps({
            "type": "assistant",
            "sessionId": session_id,
            "timestamp": f"2026-01-01T00:0{i}:10Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": f"Assistant response {i}."},
                    {"type": "tool_use", "name": "Bash",
                     "input": {"command": f"echo turn-{i}"}},
                ],
            },
        }))
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def make_gemini_json_transcript(path, session_id=SESSION_ID, num_turns=20):
    """
    Write a Gemini-style JSON transcript (list of dicts with 'role'/'parts').
    handoff_pulse_generator reads these from archive/raw/ as a fallback.
    """
    turns = []
    for i in range(num_turns):
        turns.append({
            "role": "user",
            "parts": [{"text": f"User message {i}"}],
        })
        turns.append({
            "role": "model",
            "parts": [{"text": f"Model response {i}"}],
        })
    with open(path, "w") as f:
        json.dump(turns, f)


# ─────────────────────────────────────────────────────────────────────────────
# Part 1 — failsafe_context_snapshot.py as FALLBACK_TAIL.md producer
# ─────────────────────────────────────────────────────────────────────────────

class TestFailsafeSnapshotProducer:
    """
    Verify that failsafe_context_snapshot.py correctly produces
    continuity/FALLBACK_TAIL.md when given a Claude Code JSONL transcript.
    """

    def _run_snapshot_hook(self, transcript_path, continuity_dir):
        """Run the hook with patched continuity_dir; return (returncode, stdout_json)."""
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
            "tool_name": "Edit",
            "tool_input": {"file_path": "/fake/file.py"},
            "tool_response": {},
            "session_id": SESSION_ID,
            "transcript_path": transcript_path,
        }
        result = subprocess.run(
            [PYTHON, "-c", wrapper],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=AIM_ROOT,
        )
        try:
            out = json.loads(result.stdout.strip())
        except Exception:
            out = {}
        return result.returncode, out

    def test_fallback_tail_has_correct_header(self, tmp_path):
        """FALLBACK_TAIL.md starts with the expected A.I.M. header."""
        transcript_path = str(tmp_path / "session.jsonl")
        continuity_dir = str(tmp_path / "continuity")
        os.makedirs(continuity_dir)
        make_jsonl_transcript(transcript_path)

        rc, out = self._run_snapshot_hook(transcript_path, continuity_dir)
        assert rc == 0, f"Hook exited {rc}"
        assert out == {}, f"Expected empty dict on stdout, got: {out}"

        tail_path = os.path.join(continuity_dir, "FALLBACK_TAIL.md")
        assert os.path.exists(tail_path), "FALLBACK_TAIL.md not created"
        content = open(tail_path).read()
        assert "A.I.M. FALLBACK CONTEXT TAIL" in content

    def test_fallback_tail_contains_user_blocks(self, tmp_path):
        """FALLBACK_TAIL.md contains ### USER sections from the transcript."""
        transcript_path = str(tmp_path / "session.jsonl")
        continuity_dir = str(tmp_path / "continuity")
        os.makedirs(continuity_dir)
        make_jsonl_transcript(transcript_path, num_turns=3)

        self._run_snapshot_hook(transcript_path, continuity_dir)

        tail_path = os.path.join(continuity_dir, "FALLBACK_TAIL.md")
        content = open(tail_path).read()
        assert "### USER" in content, f"No USER block found:\n{content}"

    def test_fallback_tail_contains_assistant_tool_calls(self, tmp_path):
        """FALLBACK_TAIL.md captures tool_use blocks as **Tool Call:** entries."""
        transcript_path = str(tmp_path / "session.jsonl")
        continuity_dir = str(tmp_path / "continuity")
        os.makedirs(continuity_dir)
        make_jsonl_transcript(transcript_path, num_turns=2)

        self._run_snapshot_hook(transcript_path, continuity_dir)

        tail_path = os.path.join(continuity_dir, "FALLBACK_TAIL.md")
        content = open(tail_path).read()
        assert "Tool Call" in content or "Bash" in content, \
            f"Expected tool call entry:\n{content}"

    def test_fallback_tail_respects_10_turn_limit(self, tmp_path):
        """With 20 JSONL turns, FALLBACK_TAIL.md captures only the last 10."""
        transcript_path = str(tmp_path / "session.jsonl")
        continuity_dir = str(tmp_path / "continuity")
        os.makedirs(continuity_dir)
        # 20 turns = 40 JSONL lines; hook reads last 10 turns
        make_jsonl_transcript(transcript_path, num_turns=20)

        self._run_snapshot_hook(transcript_path, continuity_dir)

        tail_path = os.path.join(continuity_dir, "FALLBACK_TAIL.md")
        content = open(tail_path).read()
        # The last 10 turns means messages from turn 10-19; turn 0 text should not appear
        # (turn 0 = "User turn 0")
        assert "turn 19" in content or "turn 18" in content or "User turn 1" in content, \
            "Expected recent turns in tail"
        # The very first turn should not be in the tail
        assert "User turn 0: please do something" not in content, \
            "First turn (beyond 10-turn window) should be truncated"

    def test_no_transcript_path_exits_cleanly(self, tmp_path):
        """Hook handles empty transcript_path without crashing."""
        continuity_dir = str(tmp_path / "continuity")
        os.makedirs(continuity_dir)

        payload = {
            "tool_name": "Bash",
            "tool_input": {},
            "tool_response": {},
            "session_id": SESSION_ID,
            "transcript_path": "",
        }
        result = subprocess.run(
            [PYTHON, os.path.join(HOOKS_DIR, "failsafe_context_snapshot.py")],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=AIM_ROOT,
        )
        assert result.returncode == 0, f"Crashed on empty transcript_path:\n{result.stderr}"
        out = json.loads(result.stdout.strip())
        assert out == {}

    def test_nonexistent_transcript_path_exits_cleanly(self, tmp_path):
        """Hook handles a nonexistent transcript_path without crashing."""
        continuity_dir = str(tmp_path / "continuity")
        os.makedirs(continuity_dir)

        payload = {
            "tool_name": "Bash",
            "tool_input": {},
            "tool_response": {},
            "session_id": SESSION_ID,
            "transcript_path": "/nonexistent/path/session.jsonl",
        }
        result = subprocess.run(
            [PYTHON, os.path.join(HOOKS_DIR, "failsafe_context_snapshot.py")],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=AIM_ROOT,
        )
        assert result.returncode == 0
        out = json.loads(result.stdout.strip())
        assert out == {}


# ─────────────────────────────────────────────────────────────────────────────
# Part 2 — handoff_pulse_generator.py file-write contract (LLM mocked)
# ─────────────────────────────────────────────────────────────────────────────

class TestHandoffPulseGeneratorFileWrites:
    """
    handoff_pulse_generator.py writes three continuity files.
    generate_reincarnation_gameplan() and generate_handoff_pulse() both
    require an LLM — we mock generate_reasoning() with a stub that returns
    a fixed string, then verify the file-write contract.

    We also test atomic_write() directly to verify the temp-file + os.replace
    pattern leaves no .tmp artifacts.
    """

    def test_atomic_write_creates_file(self, tmp_path):
        """atomic_write() creates the target file with correct content."""
        wrapper = textwrap.dedent(f"""
            import sys, os
            sys.path.insert(0, {repr(SRC_DIR)})
            from handoff_pulse_generator import atomic_write
            target = {repr(str(tmp_path / "output.md"))}
            atomic_write(target, "# Test Content\\nHello world.\\n")
        """)
        result = subprocess.run(
            [PYTHON, "-c", wrapper],
            capture_output=True,
            text=True,
            cwd=AIM_ROOT,
        )
        assert result.returncode == 0, f"atomic_write failed:\n{result.stderr}"
        output_path = tmp_path / "output.md"
        assert output_path.exists(), "atomic_write did not create the file"
        assert output_path.read_text() == "# Test Content\nHello world.\n"

    def test_atomic_write_leaves_no_tmp_artifact(self, tmp_path):
        """atomic_write() removes the .tmp file after the atomic swap."""
        wrapper = textwrap.dedent(f"""
            import sys, os
            sys.path.insert(0, {repr(SRC_DIR)})
            from handoff_pulse_generator import atomic_write
            target = {repr(str(tmp_path / "output.md"))}
            atomic_write(target, "content")
            tmp_path = target + ".tmp"
            exists = os.path.exists(tmp_path)
            print("tmp_exists:" + str(exists))
        """)
        result = subprocess.run(
            [PYTHON, "-c", wrapper],
            capture_output=True,
            text=True,
            cwd=AIM_ROOT,
        )
        assert result.returncode == 0, f"Script failed:\n{result.stderr}"
        assert "tmp_exists:False" in result.stdout, \
            f".tmp artifact was not cleaned up. Output: {result.stdout}"

    # NOTE: test_reincarnation_gameplan_written_with_mocked_llm removed.
    # The live agent now writes REINCARNATION_GAMEPLAN.md directly via
    # /reincarnation command (PR #80). generate_reincarnation_gameplan()
    # no longer exists in the pipeline.

    def test_flight_recorder_written_with_mocked_llm(self, tmp_path):
        """
        generate_handoff_pulse() writes LAST_SESSION_FLIGHT_RECORDER.md
        when pointed at a fake archive/raw/ transcript.
        No LLM call needed — the function writes a markdown artifact from
        the signal skeleton (extract_signal + skeleton_to_markdown).
        """
        continuity_dir = str(tmp_path / "continuity")
        archive_raw_dir = str(tmp_path / "archive" / "raw")
        os.makedirs(continuity_dir)
        os.makedirs(archive_raw_dir)

        # Write a fake Gemini transcript with enough turns (>= 15)
        transcript_path = os.path.join(archive_raw_dir, "test_session.json")
        make_gemini_json_transcript(transcript_path, num_turns=20)

        wrapper = textwrap.dedent(f"""
            import sys, os, json
            sys.path.insert(0, {repr(SRC_DIR)})

            # Mock generate_reasoning to prevent LLM calls
            import reasoning_utils
            reasoning_utils.generate_reasoning = lambda *a, **kw: "Mocked pulse content."

            import handoff_pulse_generator as hpg
            hpg.CONTINUITY_DIR = {repr(continuity_dir)}
            hpg.ARCHIVE_RAW_DIR = {repr(archive_raw_dir)}

            hpg.generate_handoff_pulse()
        """)
        result = subprocess.run(
            [PYTHON, "-c", wrapper],
            capture_output=True,
            text=True,
            cwd=AIM_ROOT,
        )
        assert result.returncode == 0, f"Script failed:\n{result.stderr}"

        flight_recorder = os.path.join(continuity_dir, "LAST_SESSION_FLIGHT_RECORDER.md")
        assert os.path.exists(flight_recorder), (
            f"LAST_SESSION_FLIGHT_RECORDER.md not written. "
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        content = open(flight_recorder).read()
        assert "Flight Recorder" in content or "Session" in content


# ─────────────────────────────────────────────────────────────────────────────
# Part 3 — Continuity directory structure integrity
# ─────────────────────────────────────────────────────────────────────────────

class TestContinuityDirectoryIntegrity:
    """
    Verify the real continuity/ directory exists and has the expected structure
    after the reincarnation system has run at least once.
    These are lightweight existence checks — no subprocess needed.
    """

    def test_continuity_directory_exists(self):
        """continuity/ directory exists at AIM_ROOT."""
        assert os.path.isdir(CONTINUITY_DIR), \
            f"continuity/ directory missing at {CONTINUITY_DIR}"

    def test_fallback_tail_exists_or_can_be_created(self, tmp_path):
        """FALLBACK_TAIL.md path is writable — it exists or can be created."""
        tail_path = os.path.join(CONTINUITY_DIR, "FALLBACK_TAIL.md")
        # Either it already exists (from a previous reincarnation run)
        # or the directory is writable so the hook can create it
        if os.path.exists(tail_path):
            assert os.path.isfile(tail_path)
        else:
            # Verify the continuity dir itself is writable
            test_file = os.path.join(CONTINUITY_DIR, ".write_test")
            try:
                with open(test_file, "w") as f:
                    f.write("test")
                os.remove(test_file)
            except OSError as e:
                pytest.fail(f"continuity/ directory is not writable: {e}")

    def test_injector_state_schema_when_present(self):
        """If injector_state.json exists, it has the expected keys."""
        state_path = os.path.join(CONTINUITY_DIR, "injector_state.json")
        if not os.path.exists(state_path):
            pytest.skip("injector_state.json does not exist yet")
        with open(state_path) as f:
            state = json.load(f)
        assert "session_id" in state, f"Missing 'session_id' in injector state: {state}"
        assert "injected" in state, f"Missing 'injected' in injector state: {state}"

    def test_mantra_state_schema_when_present(self):
        """If mantra_state.json exists, it has the expected counter keys."""
        state_path = os.path.join(CONTINUITY_DIR, "mantra_state.json")
        if not os.path.exists(state_path):
            pytest.skip("mantra_state.json does not exist yet")
        with open(state_path) as f:
            state = json.load(f)
        for key in ("tool_count", "last_whisper", "last_mantra", "session_id"):
            assert key in state, f"Missing '{key}' in mantra state: {state}"
        assert isinstance(state["tool_count"], int)
        assert state["tool_count"] >= 0
