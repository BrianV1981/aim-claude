"""
Regression tests for issue #57:
heartbeat.py, mcp_server.py, maintenance.py, retriever.py all used __file__-first
root resolution. Since src/ is a symlink to aim/src/, this caused AIM_ROOT to
resolve to /home/kingb/aim instead of /home/kingb/aim-claude.

All four must now use cwd-first lookup identical to the pattern established in #55.
"""

import importlib.util
import os
import sys
import types
from pathlib import Path
from unittest.mock import patch

AIM_CLAUDE_ROOT = str(Path(__file__).parent.parent.parent)
AIM_SRC = os.path.join(AIM_CLAUDE_ROOT, "src")


# ---------------------------------------------------------------------------
# Stubs for heavy deps
# ---------------------------------------------------------------------------

def _ensure_stub(name, **attrs):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod
    return sys.modules[name]


_ensure_stub("keyring", get_password=lambda *a, **k: None, set_password=lambda *a, **k: None)
_ensure_stub("google")
_ensure_stub("google.genai")


# ---------------------------------------------------------------------------
# Generic loader: load a src/ module with cwd patched to aim-claude root
# ---------------------------------------------------------------------------

def _load_src_module(filename, module_alias, extra_stubs=None):
    """
    Load a src/ Python file with os.getcwd() patched to AIM_CLAUDE_ROOT.
    Returns the loaded module or raises on import failure.
    """
    sys.modules.pop(module_alias, None)
    spec = importlib.util.spec_from_file_location(
        module_alias,
        os.path.join(AIM_SRC, filename),
    )
    mod = importlib.util.module_from_spec(spec)

    stub_ctx = extra_stubs or {}
    with patch("os.getcwd", return_value=AIM_CLAUDE_ROOT), \
         patch.dict(sys.modules, stub_ctx):
        spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Shared assertion helper
# ---------------------------------------------------------------------------

def _assert_aim_root_correct(mod, label):
    assert mod.AIM_ROOT == AIM_CLAUDE_ROOT, (
        f"{label}: AIM_ROOT={mod.AIM_ROOT!r} — expected {AIM_CLAUDE_ROOT!r}. "
        "The __file__-first bug (issue #57) has regressed."
    )
    core_cfg = os.path.join(mod.AIM_ROOT, "core", "CONFIG.json")
    assert os.path.exists(core_cfg), (
        f"{label}: core/CONFIG.json not found at {core_cfg}"
    )
    assert "aim-claude" in mod.AIM_ROOT, (
        f"{label}: AIM_ROOT does not contain 'aim-claude': {mod.AIM_ROOT!r}"
    )


# ===========================================================================
# heartbeat.py
# ===========================================================================

class TestHeartbeatFindAimRoot:

    def _load(self):
        # heartbeat uses only stdlib — no extra stubs needed
        return _load_src_module("heartbeat.py", "_test_heartbeat_57")

    def test_aim_root_resolves_to_aim_claude(self):
        mod = self._load()
        _assert_aim_root_correct(mod, "heartbeat.py")

    def test_find_aim_root_checks_cwd_before_file(self):
        """Verify the function resolves via cwd, not __file__ which would give aim/ bare."""
        mod = self._load()
        # The physical parent of src/ (via __file__) is /home/kingb/aim — not aim-claude.
        # If the fix is working, AIM_ROOT must be aim-claude, not bare aim.
        aim_bare = str(Path(AIM_SRC).resolve().parent)  # /home/kingb/aim
        assert mod.AIM_ROOT != aim_bare, (
            "heartbeat.py resolved AIM_ROOT via __file__ (aim/), not cwd (aim-claude/)"
        )


# ===========================================================================
# mcp_server.py
# ===========================================================================

class TestMcpServerFindAimRoot:

    def _load(self):
        # mcp_server imports fastmcp — stub it
        _fastmcp_stub = types.ModuleType("fastmcp")
        class _FakeMCP:
            def __init__(self, *a, **k): pass
            def tool(self, *a, **k): return lambda f: f
            def resource(self, *a, **k): return lambda f: f
            def run(self): pass
        _fastmcp_stub.FastMCP = _FakeMCP
        return _load_src_module(
            "mcp_server.py", "_test_mcp_server_57",
            extra_stubs={
                "fastmcp": _fastmcp_stub,
                "retriever": types.ModuleType("retriever"),
                "config_utils": types.ModuleType("config_utils"),
            }
        )

    def test_aim_root_resolves_to_aim_claude(self):
        mod = self._load()
        _assert_aim_root_correct(mod, "mcp_server.py")

    def test_src_dir_added_to_path_from_correct_root(self):
        mod = self._load()
        expected_src = os.path.join(AIM_CLAUDE_ROOT, "src")
        assert expected_src in sys.path, (
            f"mcp_server.py did not add the correct src dir to sys.path. "
            f"Expected {expected_src!r} in sys.path."
        )


# ===========================================================================
# maintenance.py
# ===========================================================================

class TestMaintenanceFindAimRoot:

    def _load(self):
        _config_stub = types.ModuleType("config_utils")
        _config_stub.CONFIG = {}
        return _load_src_module(
            "maintenance.py", "_test_maintenance_57",
            extra_stubs={"config_utils": _config_stub}
        )

    def test_aim_root_resolves_to_aim_claude(self):
        mod = self._load()
        _assert_aim_root_correct(mod, "maintenance.py")


# ===========================================================================
# retriever.py
# ===========================================================================

class TestRetrieverFindAimRoot:

    def _load(self):
        _config_stub = types.ModuleType("config_utils")
        _config_stub.CONFIG = {
            "models": {
                "embedding_provider": "local",
                "embedding": "nomic-embed-text",
                "embedding_endpoint": "http://localhost:11434/api/embeddings",
            }
        }
        _config_stub.AIM_ROOT = AIM_CLAUDE_ROOT

        _dj_stub = types.ModuleType("datajack_plugin")
        _dj_stub.load_knowledge_provider = lambda: None

        return _load_src_module(
            "retriever.py", "_test_retriever_57",
            extra_stubs={
                "config_utils": _config_stub,
                "datajack_plugin": _dj_stub,
            }
        )

    def test_aim_root_resolves_to_aim_claude(self):
        mod = self._load()
        _assert_aim_root_correct(mod, "retriever.py")

    def test_retriever_had_no_walk_up_before_fix(self):
        """
        Before the fix, retriever.py returned __file__-parent directly with no walk-up.
        After the fix, it must resolve via cwd. The correct AIM_ROOT is the proof.
        """
        mod = self._load()
        # If it's wrong, it would be /home/kingb/aim — not aim-claude
        assert mod.AIM_ROOT == AIM_CLAUDE_ROOT
