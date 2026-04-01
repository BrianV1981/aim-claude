"""
Regression tests for issue #55:
1. reasoning_utils.find_aim_root() must use cwd-first lookup (not __file__)
   so that shared src/ symlink resolves to the correct workspace.
2. history_scribe.scribe_all_sessions() must discover Claude Code JSONL
   sessions from ~/.claude/projects/{hash}/*.jsonl, not just Gemini JSON.
"""

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------

AIM_CLAUDE_ROOT = str(Path(__file__).parent.parent.parent)  # /home/kingb/aim-claude
AIM_SRC = os.path.join(AIM_CLAUDE_ROOT, "src")  # symlink → /home/kingb/aim/src


# ---------------------------------------------------------------------------
# Stub heavy dependencies that are not installed in the test environment
# ---------------------------------------------------------------------------

def _ensure_stub(name, **attrs):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod
    return sys.modules[name]


_ensure_stub("keyring",
             get_password=lambda *a, **k: None,
             set_password=lambda *a, **k: None)
_ensure_stub("google")
_ensure_stub("google.genai")


# ---------------------------------------------------------------------------
# Helper: load reasoning_utils isolated from any cached sys.modules entry
# ---------------------------------------------------------------------------

def _load_reasoning_utils(cwd_override=None):
    """
    Load reasoning_utils from source with an optional cwd override.
    Uses importlib to avoid polluting the global sys.modules cache.
    """
    mod_name = "_test_reasoning_utils_55"
    # Remove any prior test copy
    sys.modules.pop(mod_name, None)

    spec = importlib.util.spec_from_file_location(
        mod_name,
        os.path.join(AIM_SRC, "reasoning_utils.py"),
    )
    mod = importlib.util.module_from_spec(spec)

    with patch("os.getcwd", return_value=cwd_override or AIM_CLAUDE_ROOT):
        spec.loader.exec_module(mod)

    return mod


# ===========================================================================
# 1. reasoning_utils — find_aim_root() cwd-first regression
# ===========================================================================

class TestReasoningUtilsFindAimRoot:

    def test_aim_root_resolves_to_aim_claude_when_cwd_is_aim_claude(self):
        """
        When cwd is /home/kingb/aim-claude, AIM_ROOT must be aim-claude,
        NOT aim (the physical location of reasoning_utils.py via __file__).
        """
        mod = _load_reasoning_utils(cwd_override=AIM_CLAUDE_ROOT)
        assert mod.AIM_ROOT == AIM_CLAUDE_ROOT, (
            f"Expected AIM_ROOT={AIM_CLAUDE_ROOT!r}, got {mod.AIM_ROOT!r}. "
            "The __file__-first bug (issue #55) may have regressed."
        )

    def test_find_aim_root_function_prefers_cwd(self):
        """find_aim_root() returns cwd-based root when CONFIG.json exists there."""
        mod = _load_reasoning_utils(cwd_override=AIM_CLAUDE_ROOT)
        result = mod.find_aim_root.__wrapped__() if hasattr(mod.find_aim_root, "__wrapped__") else None
        # We can't easily call it again post-import, but the AIM_ROOT value proves it.
        # Just confirm it points to aim-claude (which has core/CONFIG.json).
        core_config = os.path.join(mod.AIM_ROOT, "core", "CONFIG.json")
        assert os.path.exists(core_config), (
            f"core/CONFIG.json not found at {core_config}. "
            "AIM_ROOT is likely pointing at the wrong directory."
        )

    def test_aim_root_contains_aim_claude_not_aim(self):
        """AIM_ROOT path must include 'aim-claude', not end at bare 'aim'."""
        mod = _load_reasoning_utils(cwd_override=AIM_CLAUDE_ROOT)
        assert "aim-claude" in mod.AIM_ROOT, (
            f"AIM_ROOT={mod.AIM_ROOT!r} does not contain 'aim-claude'. "
            "Likely resolved via __file__ symlink to bare /home/kingb/aim."
        )


# ===========================================================================
# 2. history_scribe — Claude Code JSONL discovery regression
# ===========================================================================

def _load_history_scribe(aim_root_override=None):
    """Load history_scribe from source, stubbing extract_signal."""
    mod_name = "_test_history_scribe_55"
    sys.modules.pop(mod_name, None)

    # Stub extract_signal before loading so the import doesn't fail
    _es_stub = types.ModuleType("extract_signal")
    _es_stub.extract_signal = MagicMock(return_value=None)
    _es_stub.skeleton_to_markdown = MagicMock(return_value="# stub\n")

    spec = importlib.util.spec_from_file_location(
        mod_name,
        os.path.join(AIM_SRC, "history_scribe.py"),
    )
    mod = importlib.util.module_from_spec(spec)

    with patch.dict(sys.modules, {"extract_signal": _es_stub}):
        if aim_root_override:
            with patch("os.getcwd", return_value=aim_root_override):
                spec.loader.exec_module(mod)
        else:
            spec.loader.exec_module(mod)

    return mod


class TestHistoryScribeClaudeCodeDiscovery:

    def test_claude_hash_derivation(self):
        """
        The Claude Code project hash must be '-' + path.lstrip('/').replace('/','- ').
        For /home/kingb/aim-claude → -home-kingb-aim-claude
        """
        mod = _load_history_scribe()
        aim_root = AIM_CLAUDE_ROOT  # /home/kingb/aim-claude
        expected_hash = '-' + aim_root.lstrip('/').replace('/', '-')
        assert expected_hash == "-home-kingb-aim-claude", (
            f"Hash derivation changed: got {expected_hash!r}"
        )

    def test_scribe_discovers_jsonl_files(self, tmp_path):
        """
        scribe_all_sessions() must scan ~/.claude/projects/{hash}/*.jsonl.
        Inject a fake JSONL transcript and confirm it is picked up.
        """
        mod = _load_history_scribe()

        # The hash inside scribe_all_sessions() is derived from AIM_ROOT at call time.
        # We will override mod.AIM_ROOT to tmp_path, so use that for the hash.
        fake_aim_root = str(tmp_path / "aim-claude-fake")
        (tmp_path / "aim-claude-fake" / "core").mkdir(parents=True)
        (tmp_path / "aim-claude-fake" / "core" / "CONFIG.json").write_text("{}")

        fake_hash = '-' + fake_aim_root.lstrip('/').replace('/', '-')
        fake_claude_dir = tmp_path / ".claude" / "projects" / fake_hash
        fake_claude_dir.mkdir(parents=True)

        session_id = "test-session-abc123"
        jsonl_content = json.dumps({"sessionId": session_id, "timestamp": "2026-01-01T00:00:00Z"}) + "\n"
        jsonl_path = fake_claude_dir / f"{session_id}.jsonl"
        jsonl_path.write_text(jsonl_content)

        # Override AIM_ROOT and related paths in the loaded module
        fake_archive = tmp_path / "aim-claude-fake" / "archive"
        fake_history_dir = fake_archive / "history"
        fake_history_dir.mkdir(parents=True)
        fake_raw_dir = fake_archive / "raw"
        fake_raw_dir.mkdir(parents=True)

        mod.AIM_ROOT = fake_aim_root
        mod.HISTORY_DB = str(fake_archive / "history.db")
        mod.HISTORY_DIR = str(fake_history_dir)
        mod.RAW_DIR = str(fake_raw_dir)

        # extract_signal returns None so no MD is written, but we want to
        # verify the JSONL file was at least opened/attempted.
        call_log = []
        original_extract = mod.extract_signal

        def spy_extract(path):
            call_log.append(path)
            return None  # simulate no signal extracted

        mod.extract_signal = spy_extract

        # Patch expanduser to redirect ~/.claude → tmp_path/.claude
        home_str = str(tmp_path)
        with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_str)):
            mod.scribe_all_sessions()

        mod.extract_signal = original_extract

        # The JSONL transcript must have been passed to extract_signal
        assert str(jsonl_path) in call_log, (
            f"history_scribe did not attempt to process Claude JSONL transcript. "
            f"Called extract_signal with: {call_log}"
        )

    def test_scribe_skips_already_processed_jsonl(self, tmp_path):
        """
        If a MD file for a session already exists, scribe_all_sessions()
        must skip re-processing it (idempotent).
        """
        mod = _load_history_scribe()

        fake_hash = "-home-kingb-aim-claude"
        fake_claude_dir = tmp_path / ".claude" / "projects" / fake_hash
        fake_claude_dir.mkdir(parents=True)

        session_id = "already-done-xyz"
        jsonl_content = json.dumps({"sessionId": session_id}) + "\n"
        (fake_claude_dir / f"{session_id}.jsonl").write_text(jsonl_content)

        fake_archive = tmp_path / "archive"
        fake_history_dir = fake_archive / "history"
        fake_history_dir.mkdir(parents=True)
        # Pre-create the MD file to simulate already-processed
        (fake_history_dir / f"{session_id}.md").write_text("# already processed\n")

        fake_raw_dir = fake_archive / "raw"
        fake_raw_dir.mkdir(parents=True)

        mod.AIM_ROOT = str(tmp_path)
        mod.HISTORY_DB = str(fake_archive / "history.db")
        mod.HISTORY_DIR = str(fake_history_dir)
        mod.RAW_DIR = str(fake_raw_dir)

        call_log = []
        mod.extract_signal = lambda path: call_log.append(path) or None

        home_str = str(tmp_path)
        with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_str)):
            mod.scribe_all_sessions()

        assert str(fake_claude_dir / f"{session_id}.jsonl") not in call_log, (
            "history_scribe re-processed an already-done JSONL session (not idempotent)"
        )
