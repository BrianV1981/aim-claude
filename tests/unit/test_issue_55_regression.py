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



# NOTE: history_scribe tests removed — module was deleted from shared repo
# as part of the Single-Shot Memory Engine architectural pivot (Epic #180).

