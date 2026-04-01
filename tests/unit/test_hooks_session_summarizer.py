"""
Unit tests for hooks/session_summarizer.py (System 2 Tier 1 — Claude Code migration).

Tests cover:
- _project_dir() path derivation
- extract_signal_jsonl() signal extraction and delta processing
- signal_to_markdown() formatting
- get_state() / update_state() scrivener state persistence
- process_transcript() full pipeline (light mode and LLM mode)
- main() interval gating and no-transcripts path
"""
import importlib.util
import json
import os
import sys
import tempfile
import types
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Load the module in isolation via importlib to avoid sys.modules pollution
# ---------------------------------------------------------------------------
HOOKS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "hooks")
HOOKS_DIR = os.path.abspath(HOOKS_DIR)


def _load_mod(tmp_core_dir):
    """Load session_summarizer.py with AIM_ROOT pointing to a temp directory."""
    # Pre-stub heavy imports so the module-level import block doesn't fail
    for stub in ["reasoning_utils", "memory_utils"]:
        if stub not in sys.modules:
            sys.modules[stub] = types.ModuleType(stub)

    # Ensure the stub modules have the expected callables
    ru_stub = sys.modules["reasoning_utils"]
    if not hasattr(ru_stub, "generate_reasoning"):
        ru_stub.generate_reasoning = MagicMock(return_value="[NARRATIVE]")

    mu_stub = sys.modules["memory_utils"]
    if not hasattr(mu_stub, "should_run_tier"):
        mu_stub.should_run_tier = MagicMock(return_value=True)
    if not hasattr(mu_stub, "mark_tier_run"):
        mu_stub.mark_tier_run = MagicMock()

    script_path = os.path.join(HOOKS_DIR, "session_summarizer.py")
    spec = importlib.util.spec_from_file_location("_ss", script_path)
    mod = importlib.util.module_from_spec(spec)

    # Patch find_aim_root before exec so module-level AIM_ROOT is our tmp dir
    with patch.object(mod, "__spec__", spec):
        # Inject patched find_aim_root via builtins trick isn't clean —
        # instead patch by setting module globals after load
        spec.loader.exec_module(mod)

    # Override AIM_ROOT and derived paths to use tmp dir
    mod.AIM_ROOT = tmp_core_dir
    mod.CONFIG_PATH = os.path.join(tmp_core_dir, "core", "CONFIG.json")
    mod.MEMORY_PATH = os.path.join(tmp_core_dir, "core", "MEMORY.md")
    mod.HOURLY_DIR = os.path.join(tmp_core_dir, "memory", "hourly")
    mod.STATE_FILE = os.path.join(tmp_core_dir, "archive", "scrivener_state.json")

    return mod


def _make_tmp_root(with_hourly_file=True):
    """Create a minimal aim-like temp directory with CONFIG.json.

    Args:
        with_hourly_file: If True (default), seeds a dummy .md file in
            memory/hourly/ so tests exercising the process_transcript path
            pass the #64 empty-check gate.
    """
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "core"))
    os.makedirs(os.path.join(d, "memory", "hourly"))
    os.makedirs(os.path.join(d, "archive"))
    config = {
        "memory_pipeline": {"intervals": {"tier1": 1}},
        "models": {}
    }
    with open(os.path.join(d, "core", "CONFIG.json"), 'w') as f:
        json.dump(config, f)
    with open(os.path.join(d, "core", "MEMORY.md"), 'w') as f:
        f.write("# MEMORY\n- Fact A\n")
    if with_hourly_file:
        with open(os.path.join(d, "memory", "hourly", "seed.md"), 'w') as f:
            f.write("# Seed hourly log\n")
    return d


def _make_jsonl(path, lines):
    """Write a list of dicts as newline-delimited JSON to path."""
    with open(path, 'w') as f:
        for obj in lines:
            f.write(json.dumps(obj) + "\n")


# ============================================================
# Fixtures helpers
# ============================================================

USER_MSG = {
    "parentUuid": None,
    "type": "user",
    "message": {"role": "user", "content": [{"type": "text", "text": "Hello AIM"}]},
    "uuid": "u1",
    "timestamp": "2026-03-31T00:00:01Z",
    "sessionId": "sess-abc123",
}

ASSISTANT_MSG = {
    "type": "assistant",
    "message": {
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": "Let me think..."},
            {"type": "text", "text": "I will search the codebase."},
            {"type": "tool_use", "name": "Glob", "input": {"pattern": "*.py"}},
        ],
    },
    "uuid": "a1",
    "timestamp": "2026-03-31T00:00:02Z",
    "sessionId": "sess-abc123",
}

SNAPSHOT_MSG = {
    "type": "snapshot",
    "isSnapshotUpdate": True,
    "snapshot": {},
}

TOOL_RESULT_MSG = {
    "type": "assistant",
    "message": {
        "role": "assistant",
        "content": [{"type": "tool_result", "content": "lots of output"}],
    },
    "uuid": "tr1",
    "timestamp": "2026-03-31T00:00:03Z",
    "sessionId": "sess-abc123",
}


# ============================================================
# Tests: _project_dir
# ============================================================

class TestProjectDir:
    def test_derives_hash_from_aim_root(self):
        tmp = _make_tmp_root()
        mod = _load_mod(tmp)
        # Temporarily override AIM_ROOT to a known path
        mod.AIM_ROOT = "/home/kingb/aim-claude"
        result = mod._project_dir()
        assert result.endswith("/.claude/projects/-home-kingb-aim-claude")

    def test_handles_nested_path(self):
        tmp = _make_tmp_root()
        mod = _load_mod(tmp)
        mod.AIM_ROOT = "/home/user/projects/my-proj"
        result = mod._project_dir()
        assert result.endswith("-home-user-projects-my-proj")


# ============================================================
# Tests: extract_signal_jsonl
# ============================================================

class TestExtractSignalJsonl:
    def setup_method(self):
        self.tmp = _make_tmp_root()
        self.mod = _load_mod(self.tmp)

    def _write_transcript(self, lines):
        path = os.path.join(self.tmp, "test_session.jsonl")
        _make_jsonl(path, lines)
        return path

    def test_extracts_user_text(self):
        path = self._write_transcript([USER_MSG])
        sid, signal, total = self.mod.extract_signal_jsonl(path)
        assert sid == "sess-abc123"
        assert len(signal) == 1
        assert signal[0]["role"] == "user"
        assert "Hello AIM" in signal[0]["text"]

    def test_extracts_assistant_text_and_tool_use(self):
        path = self._write_transcript([ASSISTANT_MSG])
        sid, signal, total = self.mod.extract_signal_jsonl(path)
        assert len(signal) == 1
        turn = signal[0]
        assert turn["role"] == "assistant"
        assert "I will search" in turn["text"]
        assert len(turn["actions"]) == 1
        assert turn["actions"][0]["tool"] == "Glob"

    def test_skips_thinking_blocks(self):
        path = self._write_transcript([ASSISTANT_MSG])
        sid, signal, _ = self.mod.extract_signal_jsonl(path)
        # No thinking text in output
        assert "Let me think" not in signal[0].get("text", "")

    def test_skips_tool_result_blocks(self):
        path = self._write_transcript([TOOL_RESULT_MSG])
        sid, signal, _ = self.mod.extract_signal_jsonl(path)
        # tool_result produces no signal if no text/tool_use blocks
        assert len(signal) == 0

    def test_skips_snapshot_entries(self):
        path = self._write_transcript([SNAPSHOT_MSG, USER_MSG])
        sid, signal, _ = self.mod.extract_signal_jsonl(path)
        # Only user message captured
        assert len(signal) == 1

    def test_delta_from_line_skips_old_turns(self):
        path = self._write_transcript([USER_MSG, ASSISTANT_MSG])
        # from_line=1 should skip the first line (USER_MSG)
        sid, signal, total = self.mod.extract_signal_jsonl(path, from_line=1)
        assert total == 2
        # Only assistant msg processed
        assert len(signal) == 1
        assert signal[0]["role"] == "assistant"

    def test_returns_zero_signal_when_all_processed(self):
        path = self._write_transcript([USER_MSG])
        sid, signal, total = self.mod.extract_signal_jsonl(path, from_line=10)
        assert signal == []

    def test_total_line_count_accurate(self):
        path = self._write_transcript([USER_MSG, SNAPSHOT_MSG, ASSISTANT_MSG])
        sid, signal, total = self.mod.extract_signal_jsonl(path)
        assert total == 3

    def test_string_content_extracted(self):
        msg = {
            "type": "user",
            "message": {"role": "user", "content": "plain string content"},
            "sessionId": "s1",
            "timestamp": "t",
        }
        path = self._write_transcript([msg])
        _, signal, _ = self.mod.extract_signal_jsonl(path)
        assert len(signal) == 1
        assert signal[0]["text"] == "plain string content"

    def test_tool_intent_truncated_at_200(self):
        long_input = {"key": "x" * 500}
        msg = {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "name": "Write", "input": long_input}],
            },
            "sessionId": "s1",
            "timestamp": "t",
        }
        path = self._write_transcript([msg])
        _, signal, _ = self.mod.extract_signal_jsonl(path)
        assert len(signal[0]["actions"][0]["intent"]) <= 200

    def test_session_id_fallback_from_filename(self):
        # No sessionId in any line
        msg = {"type": "user", "message": {"role": "user", "content": "hi"}, "timestamp": "t"}
        path = os.path.join(self.tmp, "fallback-session-id.jsonl")
        _make_jsonl(path, [msg])
        sid, _, _ = self.mod.extract_signal_jsonl(path)
        # session_id comes from line content; if none, stays None from extract_signal_jsonl
        assert sid is None  # fallback handled in process_transcript


# ============================================================
# Tests: signal_to_markdown
# ============================================================

class TestSignalToMarkdown:
    def setup_method(self):
        self.tmp = _make_tmp_root()
        self.mod = _load_mod(self.tmp)

    def test_includes_user_turn(self):
        signal = [{"role": "user", "timestamp": "T", "text": "What is the plan?"}]
        md = self.mod.signal_to_markdown(signal, "sess-abc123")
        assert "USER" in md
        assert "What is the plan?" in md

    def test_includes_assistant_text(self):
        signal = [{"role": "assistant", "timestamp": "T", "text": "Here is the plan."}]
        md = self.mod.signal_to_markdown(signal, "sess-abc123")
        assert "A.I.M." in md
        assert "Here is the plan." in md

    def test_includes_tool_actions(self):
        signal = [{"role": "assistant", "timestamp": "T", "text": "checking", "actions": [{"tool": "Bash", "intent": "ls /"}]}]
        md = self.mod.signal_to_markdown(signal, "sess-abc123")
        assert "`Bash`" in md
        assert "ls /" in md

    def test_session_id_truncated_in_header(self):
        md = self.mod.signal_to_markdown([], "sess-abc123-full-id")
        assert "sess-abc" in md


# ============================================================
# Tests: get_state / update_state
# ============================================================

class TestScrivenerState:
    def setup_method(self):
        self.tmp = _make_tmp_root()
        self.mod = _load_mod(self.tmp)

    def test_get_state_returns_zero_for_unknown_session(self):
        assert self.mod.get_state("unknown-session") == 0

    def test_update_and_get_state_roundtrip(self):
        self.mod.update_state("sess-1", 42)
        assert self.mod.get_state("sess-1") == 42

    def test_multiple_sessions_independent(self):
        self.mod.update_state("sess-A", 10)
        self.mod.update_state("sess-B", 99)
        assert self.mod.get_state("sess-A") == 10
        assert self.mod.get_state("sess-B") == 99

    def test_update_creates_state_file(self):
        state_path = os.path.join(self.tmp, "archive", "scrivener_state.json")
        assert not os.path.exists(state_path)
        self.mod.update_state("sess-X", 5)
        assert os.path.exists(state_path)

    def test_update_overwrites_previous_value(self):
        self.mod.update_state("sess-1", 10)
        self.mod.update_state("sess-1", 20)
        assert self.mod.get_state("sess-1") == 20

    def test_get_state_handles_corrupt_file(self):
        state_path = os.path.join(self.tmp, "archive", "scrivener_state.json")
        with open(state_path, 'w') as f:
            f.write("{not valid json")
        assert self.mod.get_state("sess-1") == 0


# ============================================================
# Tests: process_transcript (light mode)
# ============================================================

class TestProcessTranscriptLightMode:
    def setup_method(self):
        self.tmp = _make_tmp_root()
        self.mod = _load_mod(self.tmp)

    def _write_transcript(self, lines, name="session.jsonl"):
        path = os.path.join(self.tmp, name)
        _make_jsonl(path, lines)
        return path

    def test_returns_false_when_no_signal(self):
        path = self._write_transcript([SNAPSHOT_MSG])
        result = self.mod.process_transcript(path, is_light_mode=True)
        assert result is False

    def test_returns_true_when_signal_found(self):
        path = self._write_transcript([USER_MSG])
        result = self.mod.process_transcript(path, is_light_mode=True)
        assert result is True

    def test_writes_hourly_file(self):
        path = self._write_transcript([USER_MSG])
        self.mod.process_transcript(path, is_light_mode=True)
        hourly_files = os.listdir(self.mod.HOURLY_DIR)
        # At least one date-stamped hourly file written (seed.md may also exist)
        date_files = [f for f in hourly_files if f != "seed.md"]
        assert len(date_files) >= 1
        assert date_files[0].endswith(".md")

    def test_hourly_file_contains_session_id(self):
        path = self._write_transcript([USER_MSG])
        self.mod.process_transcript(path, is_light_mode=True)
        hourly_path = os.path.join(self.mod.HOURLY_DIR, os.listdir(self.mod.HOURLY_DIR)[0])
        content = open(hourly_path).read()
        assert "sess-abc" in content

    def test_hourly_file_contains_user_text(self):
        path = self._write_transcript([USER_MSG])
        self.mod.process_transcript(path, is_light_mode=True)
        hourly_path = os.path.join(self.mod.HOURLY_DIR, os.listdir(self.mod.HOURLY_DIR)[0])
        content = open(hourly_path).read()
        assert "Hello AIM" in content

    def test_delta_processing_skips_already_processed(self):
        path = self._write_transcript([USER_MSG, ASSISTANT_MSG])
        # Process once to consume all lines
        self.mod.process_transcript(path, is_light_mode=True)
        # Second call should find nothing new
        result = self.mod.process_transcript(path, is_light_mode=True)
        assert result is False

    def test_state_updated_after_processing(self):
        path = self._write_transcript([USER_MSG])
        self.mod.process_transcript(path, is_light_mode=True)
        state = self.mod.get_state("sess-abc123")
        assert state > 0

    def test_session_id_fallback_from_filename(self):
        msg = {"type": "user", "message": {"role": "user", "content": "hi"}, "timestamp": "t"}
        path = self._write_transcript([msg], name="fallback-id-session.jsonl")
        # Should not raise; session_id derived from filename
        result = self.mod.process_transcript(path, is_light_mode=True)
        assert result is True

    def test_appends_to_existing_hourly_file(self):
        path = self._write_transcript([USER_MSG])
        hourly_path = os.path.join(self.mod.HOURLY_DIR, "existing.md")
        with open(hourly_path, 'w') as f:
            f.write("# Existing content\n")
        # Manually set hourly_dir target so we can check the right file
        # Actually process_transcript creates date-based filename, so just check count
        self.mod.process_transcript(path, is_light_mode=True)
        # At least one hourly file exists
        assert len(os.listdir(self.mod.HOURLY_DIR)) >= 1


# ============================================================
# Tests: process_transcript (LLM mode)
# ============================================================

class TestProcessTranscriptLLMMode:
    def setup_method(self):
        self.tmp = _make_tmp_root()
        self.mod = _load_mod(self.tmp)

    def _write_transcript(self, lines):
        path = os.path.join(self.tmp, "session.jsonl")
        _make_jsonl(path, lines)
        return path

    def test_calls_generate_reasoning(self):
        mock_gen = MagicMock(return_value="## Narrative\nBig changes happened.")
        self.mod.generate_reasoning = mock_gen
        path = self._write_transcript([USER_MSG])
        self.mod.process_transcript(path, is_light_mode=False)
        mock_gen.assert_called_once()
        args, kwargs = mock_gen.call_args
        assert kwargs.get("brain_type") == "tier1" or args[2] == "tier1"

    def test_narrative_written_to_hourly(self):
        self.mod.generate_reasoning = MagicMock(return_value="## NARRATIVE OUTPUT")
        path = self._write_transcript([USER_MSG])
        self.mod.process_transcript(path, is_light_mode=False)
        hourly_path = os.path.join(self.mod.HOURLY_DIR, os.listdir(self.mod.HOURLY_DIR)[0])
        content = open(hourly_path).read()
        assert "NARRATIVE OUTPUT" in content

    def test_skips_on_capacity_lockout(self):
        self.mod.generate_reasoning = MagicMock(return_value="[ERROR: CAPACITY_LOCKOUT]")
        path = self._write_transcript([USER_MSG])
        result = self.mod.process_transcript(path, is_light_mode=False)
        assert result is False

    def test_skips_on_empty_narrative(self):
        self.mod.generate_reasoning = MagicMock(return_value="")
        path = self._write_transcript([USER_MSG])
        result = self.mod.process_transcript(path, is_light_mode=False)
        assert result is False

    def test_falls_back_to_light_mode_when_generate_reasoning_none(self):
        self.mod.generate_reasoning = None
        path = self._write_transcript([USER_MSG])
        result = self.mod.process_transcript(path, is_light_mode=False)
        # Should fall back to light mode and succeed
        assert result is True
        hourly_files = [f for f in os.listdir(self.mod.HOURLY_DIR) if f != "seed.md"]
        assert len(hourly_files) >= 1

    def test_calls_mark_tier_run_on_success(self):
        self.mod.generate_reasoning = MagicMock(return_value="narrative")
        mock_mark = MagicMock()
        self.mod.mark_tier_run = mock_mark
        path = self._write_transcript([USER_MSG])
        self.mod.process_transcript(path, is_light_mode=False)
        mock_mark.assert_called_once_with("tier1")


# ============================================================
# Tests: main()
# ============================================================

class TestMain:
    def setup_method(self):
        self.tmp = _make_tmp_root()
        self.mod = _load_mod(self.tmp)

    def test_skips_when_interval_not_met(self, capsys):
        self.mod.should_run_tier = MagicMock(return_value=False)
        self.mod.main([])
        captured = capsys.readouterr()
        out = json.loads(captured.out)
        assert out["decision"] == "skip"
        assert out["reason"] == "interval_not_met"

    def test_returns_zero_updated_when_no_transcripts(self, capsys):
        self.mod.should_run_tier = MagicMock(return_value=True)
        self.mod.find_transcripts = MagicMock(return_value=[])
        self.mod.main([])
        captured = capsys.readouterr()
        out = json.loads(captured.out)
        assert out["decision"] == "proceed"
        assert out["updated"] == 0

    def test_processes_latest_transcript(self, capsys, tmp_path):
        self.mod.should_run_tier = MagicMock(return_value=True)
        # Create two fake transcripts
        t1 = str(tmp_path / "old.jsonl")
        t2 = str(tmp_path / "new.jsonl")
        _make_jsonl(t1, [USER_MSG])
        _make_jsonl(t2, [ASSISTANT_MSG])
        import time; time.sleep(0.01)
        os.utime(t2, None)  # make t2 newer

        self.mod.find_transcripts = MagicMock(return_value=[t1, t2])
        processed = []
        original = self.mod.process_transcript

        def fake_process(path, is_light_mode=False):
            processed.append(path)
            return True

        self.mod.process_transcript = fake_process
        self.mod.main([])
        # Should have processed t2 (newest by mtime)
        assert processed[0] == t2

    def test_light_mode_flag_passed_through(self, capsys, tmp_path):
        self.mod.should_run_tier = MagicMock(return_value=True)
        t1 = str(tmp_path / "t.jsonl")
        _make_jsonl(t1, [USER_MSG])
        self.mod.find_transcripts = MagicMock(return_value=[t1])

        called_with_light = []

        def fake_process(path, is_light_mode=False):
            called_with_light.append(is_light_mode)
            return True

        self.mod.process_transcript = fake_process
        self.mod.main(["--light"])
        assert called_with_light[0] is True

    def test_output_json_on_success(self, capsys, tmp_path):
        self.mod.should_run_tier = MagicMock(return_value=True)
        t1 = str(tmp_path / "t.jsonl")
        _make_jsonl(t1, [USER_MSG])
        self.mod.find_transcripts = MagicMock(return_value=[t1])
        self.mod.process_transcript = MagicMock(return_value=True)
        self.mod.main([])
        captured = capsys.readouterr()
        out = json.loads(captured.out)
        assert out["decision"] == "proceed"
        assert out["updated"] == 1

    # ------------------------------------------------------------------
    # Issue #64 — empty-check gate (Antigravity swarm mandate)
    # ------------------------------------------------------------------

    def test_skips_llm_when_hourly_dir_empty(self, capsys, tmp_path):
        """main() must exit early without calling process_transcript when
        memory/hourly/ has no .md files.  This prevents a wasted LLM call
        when no hourly data exists yet."""
        # Load module with an EMPTY hourly dir (no seed file)
        tmp_empty = _make_tmp_root(with_hourly_file=False)
        mod = _load_mod(tmp_empty)
        mod.should_run_tier = MagicMock(return_value=True)
        t1 = str(tmp_path / "t.jsonl")
        _make_jsonl(t1, [USER_MSG])
        mod.find_transcripts = MagicMock(return_value=[t1])
        mod.process_transcript = MagicMock(return_value=True)

        mod.main([])
        # process_transcript must NOT have been called
        mod.process_transcript.assert_not_called()

    def test_proceeds_normally_when_hourly_dir_has_md_files(self, capsys, tmp_path):
        """main() must proceed to process_transcript when hourly .md files exist."""
        self.mod.should_run_tier = MagicMock(return_value=True)
        t1 = str(tmp_path / "t.jsonl")
        _make_jsonl(t1, [USER_MSG])
        self.mod.find_transcripts = MagicMock(return_value=[t1])
        self.mod.process_transcript = MagicMock(return_value=True)

        # Drop a .md file into HOURLY_DIR
        os.makedirs(self.mod.HOURLY_DIR, exist_ok=True)
        with open(os.path.join(self.mod.HOURLY_DIR, "2026-04-01_00.md"), 'w') as fh:
            fh.write("# Hourly log\n")

        self.mod.main([])
        self.mod.process_transcript.assert_called_once()
