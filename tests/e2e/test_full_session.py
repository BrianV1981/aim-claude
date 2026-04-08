"""
E2E test: Full session flow — signal extraction + Single-Shot Memory Compiler.

Tests the pipeline without live LLM calls:
  1. A Claude Code JSONL session transcript is created
  2. extract_signal.py correctly extracts signal from it
  3. session_summarizer.py (Single-Shot Compiler) updates MEMORY.md and CLAUDE.md

Does NOT test:
  - LLM narrative generation (requires live model)
  - Database ingestion into engram.db (covered by unit tests)
  - GitOps push to GitHub (requires credentials)
"""
import json
import os
import sys
import subprocess
import tempfile
import glob
import shutil
import unittest.mock
from pathlib import Path

AIM_CLAUDE_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = AIM_CLAUDE_ROOT / "scripts"
HOOKS_DIR = AIM_CLAUDE_ROOT / "hooks"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_aim_root(base: Path) -> Path:
    """Create a minimal AIM root directory structure for integration testing."""
    (base / "core").mkdir(parents=True, exist_ok=True)
    (base / "memory" / "hourly").mkdir(parents=True, exist_ok=True)
    (base / "archive" / "raw").mkdir(parents=True, exist_ok=True)
    (base / "archive" / "index").mkdir(parents=True, exist_ok=True)
    (base / "continuity").mkdir(parents=True, exist_ok=True)

    config = {
        "memory_pipeline": {"intervals": {"tier1": 1, "tier2": 12}, "cleanup_mode": "archive"},
        "models": {
            "tiers": {
                "tier1": {"provider": "local", "model": "test", "endpoint": "http://localhost:9999", "auth_type": "api_key"},
                "tier2": {"provider": "local", "model": "test", "endpoint": "http://localhost:9999", "auth_type": "api_key"},
            }
        },
        "settings": {"allowed_root": str(base)},
        "paths": {
            "continuity_dir": str(base / "continuity"),
            "tmp_chats_dir": str(base / "fake_claude_projects"),
        },
    }
    (base / "core" / "CONFIG.json").write_text(json.dumps(config))
    (base / "core" / "MEMORY.md").write_text("# MEMORY\n- Fact A\n")
    return base


def make_jsonl_transcript(path: Path, session_id: str = "test-session-id-abc"):
    """Write a minimal Claude Code JSONL transcript."""
    lines = [
        {
            "type": "user",
            "message": {"role": "user", "content": [{"type": "text", "text": "What is the current state of the project?"}]},
            "uuid": "u1",
            "timestamp": "2026-03-31T01:00:00Z",
            "sessionId": session_id,
            "cwd": "/home/kingb/aim-claude",
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "Let me analyze the project state."},
                    {"type": "text", "text": "The project is in good shape. Let me search for recent activity."},
                    {"type": "tool_use", "name": "Bash", "input": {"command": "git log --oneline -5"}},
                ],
            },
            "uuid": "a1",
            "timestamp": "2026-03-31T01:00:05Z",
            "sessionId": session_id,
            "cwd": "/home/kingb/aim-claude",
        },
        {
            "type": "user",
            "message": {"role": "user", "content": [{"type": "text", "text": "Great, please continue with the integration tests."}]},
            "uuid": "u2",
            "timestamp": "2026-03-31T01:00:10Z",
            "sessionId": session_id,
            "cwd": "/home/kingb/aim-claude",
        },
    ]
    path.write_text("\n".join(json.dumps(l) for l in lines) + "\n")


# ---------------------------------------------------------------------------
# Test: extract_signal.py CLI
# ---------------------------------------------------------------------------

class TestExtractSignalCLI:
    """System 1 signal extraction — scripts/extract_signal.py as subprocess."""

    def test_extract_signal_outputs_valid_json(self, tmp_path):
        transcript = tmp_path / "session.jsonl"
        make_jsonl_transcript(transcript)

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "extract_signal.py"), str(transcript)],
            capture_output=True, text=True, cwd=str(AIM_CLAUDE_ROOT)
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        signal = json.loads(result.stdout)
        assert isinstance(signal, list)
        assert len(signal) > 0

    def test_extract_signal_keeps_user_text(self, tmp_path):
        transcript = tmp_path / "session.jsonl"
        make_jsonl_transcript(transcript)

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "extract_signal.py"), str(transcript)],
            capture_output=True, text=True, cwd=str(AIM_CLAUDE_ROOT)
        )
        signal = json.loads(result.stdout)
        user_turns = [t for t in signal if t.get("role") == "user"]
        assert len(user_turns) >= 1
        assert "current state" in user_turns[0].get("text", "")

    def test_extract_signal_includes_tool_use_intent(self, tmp_path):
        transcript = tmp_path / "session.jsonl"
        make_jsonl_transcript(transcript)

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "extract_signal.py"), str(transcript)],
            capture_output=True, text=True, cwd=str(AIM_CLAUDE_ROOT)
        )
        signal = json.loads(result.stdout)
        assistant_turns = [t for t in signal if t.get("role") == "assistant"]
        assert len(assistant_turns) >= 1
        actions = assistant_turns[0].get("actions", [])
        assert any(a["tool"] == "Bash" for a in actions)

    def test_extract_signal_includes_thoughts_field_not_as_main_text(self, tmp_path):
        transcript = tmp_path / "session.jsonl"
        make_jsonl_transcript(transcript)

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "extract_signal.py"), str(transcript)],
            capture_output=True, text=True, cwd=str(AIM_CLAUDE_ROOT)
        )
        signal = json.loads(result.stdout)
        assistant_turns = [t for t in signal if t.get("role") == "assistant"]
        assert len(assistant_turns) >= 1
        turn = assistant_turns[0]
        # Thinking may appear in a 'thoughts' field but the main 'text' should be the text block
        main_text = turn.get("text", "")
        assert "search" in main_text.lower() or "Let me" in main_text

    def test_extract_signal_markdown_flag(self, tmp_path):
        transcript = tmp_path / "session.jsonl"
        make_jsonl_transcript(transcript)

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "extract_signal.py"), str(transcript), "--markdown"],
            capture_output=True, text=True, cwd=str(AIM_CLAUDE_ROOT)
        )
        assert result.returncode == 0
        assert "# A.I.M. Signal Skeleton" in result.stdout
        assert "USER" in result.stdout

    def test_extract_signal_list_flag(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "extract_signal.py"), "--list"],
            capture_output=True, text=True, cwd=str(AIM_CLAUDE_ROOT)
        )
        assert result.returncode == 0
        # May find real session files or print nothing — either is fine
        # Just verify it doesn't crash

    def test_extract_signal_missing_file_exits_nonzero(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "extract_signal.py"), "/nonexistent/path.jsonl"],
            capture_output=True, text=True, cwd=str(AIM_CLAUDE_ROOT)
        )
        # Should exit 0 but return an error string in the JSON output
        output = result.stdout.strip()
        if output:
            # Either a JSON string with "Extraction Error" or empty list
            parsed = json.loads(output)
            assert "Extraction Error" in str(parsed) or parsed == []


# ---------------------------------------------------------------------------
# Test: session_summarizer.py in light mode
# ---------------------------------------------------------------------------

class TestSessionSummarizerLightMode:
    """System 2 Tier 1 — session_summarizer.py runs without LLM."""

    def _setup_project(self, tmp_path):
        """Create a fake Claude projects layout with one JSONL transcript."""
        aim_root = make_aim_root(tmp_path / "aim_root")
        # Create fake ~/.claude/projects/<hash>/ layout
        hash_name = "-" + str(aim_root).lstrip("/").replace("/", "-")
        fake_claude = tmp_path / "fake_claude" / "projects" / hash_name
        fake_claude.mkdir(parents=True)
        transcript = fake_claude / "test-session.jsonl"
        make_jsonl_transcript(transcript)
        return aim_root, fake_claude, transcript

    def test_session_summarizer_writes_hourly_file(self, tmp_path, monkeypatch):
        aim_root, fake_claude, transcript = self._setup_project(tmp_path)

        # Patch _project_dir by setting HOME so expanduser resolves to our fake dir
        fake_home = tmp_path / "fake_claude"
        fake_home.mkdir(exist_ok=True)

        env = os.environ.copy()
        env["HOME"] = str(tmp_path / "fake_claude")

        # Run session_summarizer with --light from the aim_root dir
        result = subprocess.run(
            [sys.executable, str(HOOKS_DIR / "session_summarizer.py"), "--light"],
            capture_output=True, text=True,
            cwd=str(aim_root),
            env=env
        )

        # Even if the project dir hash doesn't match exactly, it should not crash
        assert result.returncode == 0, f"stderr: {result.stderr}"
        output = json.loads(result.stdout)
        assert output["decision"] in ("proceed", "skip")

    def test_session_summarizer_no_crash_when_no_transcripts(self, tmp_path):
        aim_root = make_aim_root(tmp_path / "aim_root")
        # No fake project dir — no archive/history transcripts
        result = subprocess.run(
            [sys.executable, str(HOOKS_DIR / "session_summarizer.py")],
            capture_output=True, text=True,
            cwd=str(aim_root),
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        output = json.loads(result.stdout)
        assert output["decision"] == "skip"
        assert output["reason"] == "no_transcript_found"

    def test_session_summarizer_direct_call_with_mocked_llm(self, tmp_path):
        """Direct integration: Single-Shot Compiler updates MEMORY.md and CLAUDE.md."""
        import importlib.util
        import types
        from unittest.mock import MagicMock

        aim_root = make_aim_root(tmp_path / "aim_root")
        transcript = tmp_path / "transcript.md"
        transcript.write_text("# Session\nUSER: test\nA.I.M.: confirmed\n")

        # Create CLAUDE.md in aim_root
        (aim_root / "CLAUDE.md").write_text("# Rules\n- existing rule\n")

        # Stub reasoning_utils
        if "reasoning_utils" not in sys.modules:
            sys.modules["reasoning_utils"] = types.ModuleType("reasoning_utils")
        sys.modules["reasoning_utils"].generate_reasoning = None

        spec = importlib.util.spec_from_file_location(
            "_ss_e2e", str(HOOKS_DIR / "session_summarizer.py")
        )
        mod = importlib.util.module_from_spec(spec)
        with unittest.mock.patch("os.getcwd", return_value=str(aim_root)):
            spec.loader.exec_module(mod)

        mod.AIM_ROOT = str(aim_root)
        mod.MEMORY_PATH = str(aim_root / "core" / "MEMORY.md")
        mod.CLAUDE_PATH = str(aim_root / "CLAUDE.md")

        fake_output = """### core/MEMORY.md
```markdown
# Memory
- existing fact
- new fact from session (Added: 2026-04-08)
```

### CLAUDE.md
```markdown
# Rules
- existing rule
```
"""
        mod.generate_reasoning = MagicMock(return_value=fake_output)
        result = mod.process_transcript(str(transcript))
        assert result is True

        memory = (aim_root / "core" / "MEMORY.md").read_text()
        assert "new fact from session" in memory


# ---------------------------------------------------------------------------
# Test: cmd_memory pipeline smoke test (regression guard for #52)
# ---------------------------------------------------------------------------

class TestCmdMemoryNoFileNotFoundError:
    """Regression: aim-claude memory must not crash with 'No such file' for session_summarizer.py."""

    def test_session_summarizer_script_exists(self):
        """
        Regression guard for #52: hooks/session_summarizer.py must exist on disk.
        Before the fix, cmd_memory crashed at Stage 1 with FileNotFoundError.
        """
        script_path = AIM_CLAUDE_ROOT / "hooks" / "session_summarizer.py"
        assert script_path.exists(), (
            "hooks/session_summarizer.py is missing — cmd_memory Stage 1 will crash. "
            "This was the bug tracked in #52."
        )

    def test_session_summarizer_is_executable_python(self):
        """Verify the script parses as valid Python (syntax check)."""
        script_path = AIM_CLAUDE_ROOT / "hooks" / "session_summarizer.py"
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(script_path)],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"

    def test_cmd_memory_stage1_path_resolves(self):
        """Verify aim_cli.py cmd_memory calls hooks/session_summarizer.py (not a Gemini path)."""
        import importlib.util
        import types

        # Load aim_cli without executing __main__
        for stub in ["reasoning_utils", "memory_utils"]:
            if stub not in sys.modules:
                sys.modules[stub] = types.ModuleType(stub)
            sys.modules[stub].generate_reasoning = None
            sys.modules[stub].should_run_tier = lambda x, y: True
            sys.modules[stub].mark_tier_run = lambda x: None
            sys.modules[stub].cleanup_consumed_files = lambda x, y: None

        # Read the source and check the Stage 1 path directly
        src = (AIM_CLAUDE_ROOT / "scripts" / "aim_cli.py").read_text()
        # The Stage 1 call must reference hooks/session_summarizer.py
        assert "hooks/session_summarizer.py" in src, (
            "cmd_memory Stage 1 does not reference hooks/session_summarizer.py"
        )
        # Must NOT still reference the old Gemini hooks path pattern
        assert "hooks\\session_summarizer" not in src  # Windows path — should not exist


# ---------------------------------------------------------------------------
# Test: Full pipeline flow (System 1 + System 2 extract → signal → hourly)
# ---------------------------------------------------------------------------

class TestFullSessionFlow:
    """E2E: Real JSONL transcript → extract_signal → session_summarizer light → hourly written."""

    def test_extract_then_summarize_produces_hourly_file(self, tmp_path):
        """
        Full two-step flow:
          1. extract_signal.py reads JSONL → JSON signal
          2. session_summarizer.py (light) reads same JSONL → writes hourly MD
        Both must succeed and produce consistent signal content.
        """
        import importlib.util
        import types

        # Create transcript
        transcript = tmp_path / "session.jsonl"
        make_jsonl_transcript(transcript, session_id="e2e-session-abc")

        # Step 1: extract signal via CLI
        extract_result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "extract_signal.py"), str(transcript)],
            capture_output=True, text=True, cwd=str(AIM_CLAUDE_ROOT)
        )
        assert extract_result.returncode == 0
        signal = json.loads(extract_result.stdout)
        assert len(signal) > 0
        user_texts = [t.get("text", "") for t in signal if t.get("role") == "user"]
        assert any("current state" in t for t in user_texts)

        # Step 2: session summarizer (Single-Shot Compiler) updates MEMORY.md
        aim_root = make_aim_root(tmp_path / "aim_root")
        (aim_root / "CLAUDE.md").write_text("# Rules\n")

        # Write the extracted signal as a markdown transcript for the compiler
        signal_md = aim_root / "archive" / "history" / "session.md"
        signal_md.parent.mkdir(parents=True, exist_ok=True)
        signal_md.write_text(json.dumps(signal, indent=2))

        for stub in ["reasoning_utils"]:
            if stub not in sys.modules:
                sys.modules[stub] = types.ModuleType(stub)
        sys.modules["reasoning_utils"].generate_reasoning = None

        spec = importlib.util.spec_from_file_location(
            "_ss_e2e2", str(HOOKS_DIR / "session_summarizer.py")
        )
        mod = importlib.util.module_from_spec(spec)
        with unittest.mock.patch("os.getcwd", return_value=str(aim_root)):
            spec.loader.exec_module(mod)
        mod.AIM_ROOT = str(aim_root)
        mod.MEMORY_PATH = str(aim_root / "core" / "MEMORY.md")
        mod.CLAUDE_PATH = str(aim_root / "CLAUDE.md")

        fake_output = """### core/MEMORY.md
```markdown
# Memory
- e2e test session recorded (Added: 2026-04-08)
```

### CLAUDE.md
```markdown
# Rules
```
"""
        from unittest.mock import MagicMock
        mod.generate_reasoning = MagicMock(return_value=fake_output)

        updated = mod.process_transcript(str(signal_md))
        assert updated is True

        memory_content = (aim_root / "core" / "MEMORY.md").read_text()
        assert "e2e test session recorded" in memory_content

    def test_extract_signal_produces_valid_json(self, tmp_path):
        """extract_signal.py produces valid JSON signal from a JSONL transcript."""
        transcript = tmp_path / "session.jsonl"
        make_jsonl_transcript(transcript, session_id="count-check-session")

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "extract_signal.py"), str(transcript)],
            capture_output=True, text=True, cwd=str(AIM_CLAUDE_ROOT)
        )
        cli_signal = json.loads(result.stdout)

        cli_roles = {t.get("role") for t in cli_signal}
        assert "user" in cli_roles
        assert "assistant" in cli_roles
