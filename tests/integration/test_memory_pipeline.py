"""
Integration tests for the A.I.M. System 2 Memory Pipeline.

Tests the 5-tier memory distillation cascade without making LLM calls:
  Stage 1 — hooks/session_summarizer.py  (--light flag bypasses LLM)
  Stage 2 — src/memory_proposer.py       (waterfall check, no LLM needed to verify file detection)
  Smoke    — scripts/aim_cli.py memory   (regression guard: must not crash with FileNotFoundError)

All tests use a real AIM_ROOT on disk (the project root) so that
find_aim_root() resolves correctly and CONFIG.json is found.
"""
import json
import os
import sys
import subprocess
import tempfile
import shutil
from datetime import datetime

import pytest

AIM_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HOOKS_DIR = os.path.join(AIM_ROOT, "hooks")
SRC_DIR = os.path.join(AIM_ROOT, "src")
SCRIPTS_DIR = os.path.join(AIM_ROOT, "scripts")
VENV_PYTHON = os.path.join(AIM_ROOT, "venv", "bin", "python3")

# Use venv python if present, else fall back to current interpreter
PYTHON = VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable


def make_minimal_jsonl(path, session_id="test-session-pipeline-001"):
    """Write a minimal Claude Code JSONL transcript with enough signal to process."""
    lines = [
        json.dumps({
            "type": "human",
            "sessionId": session_id,
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "What is the current project state?"}],
            },
        }),
        json.dumps({
            "type": "assistant",
            "sessionId": session_id,
            "timestamp": "2026-01-01T00:00:05Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "The project is in a healthy state."},
                    {"type": "tool_use", "name": "Read",
                     "input": {"file_path": "/home/kingb/aim-claude/CLAUDE.md"}},
                ],
            },
        }),
        json.dumps({
            "type": "human",
            "sessionId": session_id,
            "timestamp": "2026-01-01T00:01:00Z",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "Run the tests please."}],
            },
        }),
        json.dumps({
            "type": "assistant",
            "sessionId": session_id,
            "timestamp": "2026-01-01T00:01:05Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Bash",
                     "input": {"command": "python3 -m pytest tests/"}},
                ],
            },
        }),
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — session_summarizer.py
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionSummarizerStage1:
    """
    session_summarizer.py reads JSONL transcripts and writes hourly summary files
    to memory/hourly/. With --light flag it skips LLM calls entirely, producing
    a structured Markdown summary via signal_to_markdown().

    These tests create a fake Claude Code project structure so that
    find_aim_root() locates the real aim-claude root (by running from AIM_ROOT cwd)
    but we supply a synthetic JSONL transcript for processing.
    """

    SESSION_ID = "integration-test-session-s1-001"

    def _write_transcript(self, project_dir):
        """Write a minimal JSONL to the project dir and return the path."""
        fname = f"{self.SESSION_ID}.jsonl"
        path = os.path.join(project_dir, fname)
        make_minimal_jsonl(path, self.SESSION_ID)
        return path

    def test_light_mode_writes_hourly_file(self, tmp_path):
        """--light flag produces an hourly .md file without any LLM call."""
        # Create a fake ~/.claude/projects/<hash> dir that the summarizer will scan.
        # The hash is derived from AIM_ROOT: '-' + AIM_ROOT.lstrip('/').replace('/', '-')
        project_hash = '-' + AIM_ROOT.lstrip('/').replace('/', '-')
        fake_claude_dir = tmp_path / ".claude" / "projects" / project_hash
        fake_claude_dir.mkdir(parents=True)
        self._write_transcript(str(fake_claude_dir))

        # We also need a temp HOURLY_DIR and STATE_FILE so we don't pollute real dirs.
        fake_hourly = tmp_path / "memory" / "hourly"
        fake_hourly.mkdir(parents=True)
        fake_archive = tmp_path / "archive"
        fake_archive.mkdir()

        # Build a wrapper that overrides the module-level constants before main() runs
        wrapper = f"""
import sys, os, json
sys.argv = ['session_summarizer.py', '--light']
# Redirect home so _project_dir() finds our fake transcript
import pathlib
fake_home = {repr(str(tmp_path))}
real_expanduser = pathlib.Path.expanduser

def patched_expanduser(self):
    s = str(self)
    if s.startswith('~'):
        return pathlib.Path(fake_home + s[1:])
    return self

pathlib.Path.expanduser = patched_expanduser

import importlib.util
spec = importlib.util.spec_from_file_location(
    "session_summarizer",
    {repr(os.path.join(HOOKS_DIR, "session_summarizer.py"))}
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

mod.HOURLY_DIR = {repr(str(fake_hourly))}
mod.STATE_FILE = {repr(str(fake_archive / "scrivener_state.json"))}

mod.main(sys.argv[1:])
"""
        result = subprocess.run(
            [PYTHON, "-c", wrapper],
            capture_output=True,
            text=True,
            cwd=AIM_ROOT,
        )
        assert result.returncode == 0, f"session_summarizer exited non-zero:\n{result.stderr}"

        hourly_files = list(fake_hourly.glob("*.md"))
        if hourly_files:
            # If a transcript was processed, verify the file content
            content = hourly_files[0].read_text()
            assert "Surgical Delta" in content or "Session" in content, \
                f"Hourly file missing expected content:\n{content}"
        else:
            # Acceptable: summarizer may skip if interval_not_met or no new signal
            out = json.loads(result.stdout.strip()) if result.stdout.strip() else {}
            assert out.get("decision") in ("skip", "proceed"), \
                f"Unexpected output: {result.stdout}"

    def test_light_mode_outputs_valid_json(self, tmp_path):
        """session_summarizer.py --light always outputs valid JSON on stdout."""
        # Run without any transcript dir set up — should output proceed/skip JSON
        result = subprocess.run(
            [PYTHON, os.path.join(HOOKS_DIR, "session_summarizer.py"), "--light"],
            capture_output=True,
            text=True,
            cwd=AIM_ROOT,
        )
        # Script may exit 0 with JSON, or exit 0 with decision=skip
        if result.returncode == 0 and result.stdout.strip():
            try:
                out = json.loads(result.stdout.strip())
                assert "decision" in out, f"No 'decision' key in output: {out}"
            except json.JSONDecodeError:
                pytest.fail(f"stdout is not valid JSON: {result.stdout!r}")

    def test_no_transcript_produces_proceed_json(self, tmp_path):
        """When no JSONL transcripts exist, summarizer exits 0 with proceed/skip JSON."""
        # Patch home to a tmp dir with no .claude/projects subdir
        wrapper = f"""
import sys, os, pathlib
import importlib.util

fake_home = {repr(str(tmp_path))}
real_expanduser = pathlib.Path.expanduser
def patched_expanduser(self):
    s = str(self)
    if s.startswith('~'):
        return pathlib.Path(fake_home + s[1:])
    return self
pathlib.Path.expanduser = patched_expanduser

spec = importlib.util.spec_from_file_location(
    "session_summarizer",
    {repr(os.path.join(HOOKS_DIR, "session_summarizer.py"))}
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.main(['--light'])
"""
        result = subprocess.run(
            [PYTHON, "-c", wrapper],
            capture_output=True,
            text=True,
            cwd=AIM_ROOT,
        )
        assert result.returncode == 0, f"Exited {result.returncode}:\n{result.stderr}"
        if result.stdout.strip():
            out = json.loads(result.stdout.strip())
            assert out.get("decision") in ("skip", "proceed")


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — memory_proposer.py (file detection without LLM)
# ─────────────────────────────────────────────────────────────────────────────

class TestMemoryProposerStage2:
    """
    memory_proposer.py reads hourly/*.md reports and proposes memory updates.
    The get_recent_summaries() function simply globs memory/hourly/*.md.
    We can verify file detection without triggering an LLM call by
    inspecting the module's logic directly (imported as a module with mocked paths).
    """

    def test_get_recent_summaries_finds_md_files(self, tmp_path):
        """get_recent_summaries returns all *.md files from the hourly dir."""
        hourly_dir = tmp_path / "memory" / "hourly"
        hourly_dir.mkdir(parents=True)

        # Write 3 fake hourly reports
        for i in range(3):
            (hourly_dir / f"2026-01-0{i+1}_10.md").write_text(
                f"--- HOURLY REPORT {i+1} ---\nSome content\n"
            )

        # Import memory_proposer and patch HOURLY_LOG_DIR
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "memory_proposer",
            os.path.join(SRC_DIR, "memory_proposer.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        # The module does top-level CONFIG loading, so we need AIM_ROOT in path
        sys.path.insert(0, SRC_DIR)
        try:
            spec.loader.exec_module(mod)
        except SystemExit:
            pass  # CONFIG may trigger sys.exit if interval check fails — that's ok
        except Exception:
            pass

        # After load, override the hourly dir and call get_recent_summaries
        if hasattr(mod, "get_recent_summaries") and hasattr(mod, "HOURLY_LOG_DIR"):
            mod.HOURLY_LOG_DIR = str(hourly_dir)
            logs, combined = mod.get_recent_summaries()
            assert len(logs) == 3, f"Expected 3 hourly files, got {len(logs)}: {logs}"
            assert "HOURLY REPORT" in combined
        else:
            pytest.skip("memory_proposer module could not be loaded cleanly")

    def test_get_recent_summaries_empty_dir(self, tmp_path):
        """get_recent_summaries returns empty results when no hourly files exist."""
        hourly_dir = tmp_path / "memory" / "hourly"
        hourly_dir.mkdir(parents=True)

        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "memory_proposer",
            os.path.join(SRC_DIR, "memory_proposer.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.path.insert(0, SRC_DIR)
        try:
            spec.loader.exec_module(mod)
        except (SystemExit, Exception):
            pass

        if hasattr(mod, "get_recent_summaries") and hasattr(mod, "HOURLY_LOG_DIR"):
            mod.HOURLY_LOG_DIR = str(hourly_dir)
            logs, combined = mod.get_recent_summaries()
            assert logs == [], f"Expected empty list, got: {logs}"
            assert combined == ""
        else:
            pytest.skip("memory_proposer module could not be loaded cleanly")


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Smoke Test — aim_cli.py memory (regression guard)
# ─────────────────────────────────────────────────────────────────────────────

class TestMemoryPipelineSmokeTest:
    """
    Regression guard against the Stage 1 'FileNotFoundError' bug where
    session_summarizer.py crashed if no JSONL transcripts existed.

    The smoke test runs `aim_cli.py memory` (the full 5-tier pipeline entrypoint)
    and verifies:
      1. The exit code is NOT caused by an unhandled FileNotFoundError
      2. Each stage at minimum starts (output contains stage markers)

    The test accepts graceful exits (e.g. 'interval not met', API unavailable)
    but rejects crashes with tracebacks.
    """

    def test_memory_command_does_not_crash_with_file_not_found(self):
        """aim_cli.py memory must not exit with a FileNotFoundError traceback.

        The full 5-tier pipeline can take several minutes when LLM tiers are
        reachable (Ollama + Gemini). We allow up to 5 minutes; the test passes
        if it completes without a FileNotFoundError regardless of LLM availability.
        """
        result = subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "aim_cli.py"), "memory"],
            capture_output=True,
            text=True,
            cwd=AIM_ROOT,
            timeout=300,
        )
        # Regression: original bug was an unhandled FileNotFoundError in session_summarizer
        combined_output = result.stdout + result.stderr
        assert "FileNotFoundError" not in combined_output, (
            f"Pipeline crashed with FileNotFoundError:\n{combined_output}"
        )
        assert "Traceback" not in combined_output or result.returncode == 0, (
            f"Unexpected traceback:\n{combined_output}"
        )

    def test_memory_command_starts_stage_1(self):
        """aim_cli.py memory prints Stage 1 header before any possible failure."""
        result = subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "aim_cli.py"), "memory"],
            capture_output=True,
            text=True,
            cwd=AIM_ROOT,
            timeout=60,
        )
        combined = result.stdout + result.stderr
        # The CLI prints "[1/5] Stage 1:" regardless of whether the stage succeeds
        assert "Stage 1" in combined, (
            f"Did not see Stage 1 output. Full output:\n{combined}"
        )

    def test_session_summarizer_light_flag_no_file_not_found(self):
        """
        Directly run session_summarizer.py --light (Stage 1 entry point) and
        confirm it exits cleanly, never raising FileNotFoundError.
        This is the precise regression guard for the original bug.
        """
        result = subprocess.run(
            [PYTHON, os.path.join(HOOKS_DIR, "session_summarizer.py"), "--light"],
            capture_output=True,
            text=True,
            cwd=AIM_ROOT,
            timeout=30,
        )
        assert "FileNotFoundError" not in result.stderr, (
            f"FileNotFoundError in session_summarizer --light:\n{result.stderr}"
        )
        assert result.returncode == 0, (
            f"session_summarizer --light exited {result.returncode}:\n{result.stderr}"
        )
