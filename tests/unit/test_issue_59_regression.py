"""
Regression tests for issue #59:
Skills in aim/skills/ (symlinked as aim-claude/skills/) used Path(__file__).parent.parent
to derive aim_root. Since skills/ is a symlink, __file__ resolves to the physical
path aim/skills/, making aim_root = /home/kingb/aim (wrong).

Fix: each skill now uses a cwd-first walk-up (_find_aim_root()) with __file__ as fallback.
Since the MCP server passes cwd=AIM_ROOT (aim-claude) to skill subprocesses, the
cwd-first walk finds aim-claude correctly.
"""

import importlib.util
import os
import sys
import types
from pathlib import Path
from unittest.mock import patch

AIM_CLAUDE_ROOT = str(Path(__file__).parent.parent.parent)
AIM_SKILLS = os.path.join(AIM_CLAUDE_ROOT, "skills")  # local directory (decoupled from shared aim/)


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

def _ensure_stub(name, **attrs):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod
    return sys.modules[name]


# ---------------------------------------------------------------------------
# Generic skill loader with cwd patched
# ---------------------------------------------------------------------------

def _load_skill(filename, alias, extra_stubs=None):
    """
    Load a skill module with os.getcwd() patched to AIM_CLAUDE_ROOT so the
    cwd-first _find_aim_root() resolves to aim-claude, not aim.
    """
    sys.modules.pop(alias, None)
    spec = importlib.util.spec_from_file_location(
        alias,
        os.path.join(AIM_SKILLS, filename),
    )
    mod = importlib.util.module_from_spec(spec)

    stub_ctx = extra_stubs or {}
    with patch("os.getcwd", return_value=AIM_CLAUDE_ROOT), \
         patch.dict(sys.modules, stub_ctx):
        try:
            spec.loader.exec_module(mod)
        except SystemExit:
            pass  # some skills call sys.exit on missing DB
    return mod


# ---------------------------------------------------------------------------
# Shared assertion
# ---------------------------------------------------------------------------

def _assert_aim_root_correct(mod, label):
    find_fn = getattr(mod, "_find_aim_root", None)
    assert find_fn is not None, f"{label}: missing _find_aim_root() function"
    with patch("os.getcwd", return_value=AIM_CLAUDE_ROOT):
        result = find_fn()
    assert result == AIM_CLAUDE_ROOT, (
        f"{label}: _find_aim_root() returned {result!r}, expected {AIM_CLAUDE_ROOT!r}. "
        "The __file__-parent bug may have regressed."
    )
    # Verify it's NOT the bare aim/ repo (the shared swarm repo)
    aim_bare = "/home/kingb/aim"
    assert result != aim_bare, (
        f"{label}: resolved to bare aim/ repo instead of aim-claude/"
    )


# ===========================================================================
# list_recent_sessions.py
# ===========================================================================

class TestListRecentSessionsAimRoot:

    def _load(self):
        return _load_skill("list_recent_sessions.py", "_test_lrs_59")

    def test_find_aim_root_function_exists(self):
        mod = self._load()
        assert hasattr(mod, "_find_aim_root"), (
            "list_recent_sessions.py missing _find_aim_root() — fix not applied"
        )

    def test_find_aim_root_resolves_to_aim_claude(self):
        mod = self._load()
        _assert_aim_root_correct(mod, "list_recent_sessions.py")


# ===========================================================================
# propose_memory_commit.py
# ===========================================================================

class TestProposeMemoryCommitAimRoot:

    def _load(self):
        # Stub subprocess so the skill body doesn't actually run aim_cli
        _sp_stub = types.ModuleType("subprocess")
        _sp_stub.run = lambda *a, **k: types.SimpleNamespace(stdout="", stderr="", returncode=0)
        # Skill imports json, sys, os, subprocess, Path — only subprocess needs stubbing
        return _load_skill(
            "propose_memory_commit.py", "_test_pmc_59",
            extra_stubs={"subprocess": _sp_stub},
        )

    def test_find_aim_root_function_exists(self):
        mod = self._load()
        assert hasattr(mod, "_find_aim_root"), (
            "propose_memory_commit.py missing _find_aim_root() — fix not applied"
        )

    def test_find_aim_root_resolves_to_aim_claude(self):
        mod = self._load()
        _assert_aim_root_correct(mod, "propose_memory_commit.py")

    def test_aim_cli_path_points_into_aim_claude(self):
        mod = self._load()
        with patch("os.getcwd", return_value=AIM_CLAUDE_ROOT):
            root = mod._find_aim_root()
        expected_cli = os.path.join(root, "scripts", "aim_cli.py")
        # The script should not be pointing into bare aim/
        aim_bare = "/home/kingb/aim"
        assert not expected_cli.startswith(aim_bare + "/scripts"), (
            f"aim_cli path resolves into bare aim/ repo: {expected_cli!r}"
        )


# ===========================================================================
# export_datajack_cartridge.py
# ===========================================================================

class TestExportDatajackCartridgeAimRoot:

    def _load(self):
        _sp_stub = types.ModuleType("subprocess")
        _sp_stub.run = lambda *a, **k: types.SimpleNamespace(stdout="", stderr="", returncode=0)
        return _load_skill(
            "export_datajack_cartridge.py", "_test_edc_59",
            extra_stubs={"subprocess": _sp_stub},
        )

    def test_find_aim_root_function_exists(self):
        mod = self._load()
        assert hasattr(mod, "_find_aim_root"), (
            "export_datajack_cartridge.py missing _find_aim_root() — fix not applied"
        )

    def test_find_aim_root_resolves_to_aim_claude(self):
        mod = self._load()
        _assert_aim_root_correct(mod, "export_datajack_cartridge.py")


# ===========================================================================
# advanced_memory_search.py
# ===========================================================================

class TestAdvancedMemorySearchAimRoot:

    def _load(self):
        # Stub the forensic_utils import so the skill can load
        _plugins = types.ModuleType("plugins")
        _dj = types.ModuleType("plugins.datajack")
        _fu = types.ModuleType("plugins.datajack.forensic_utils")
        _fu.ForensicDB = lambda *a, **k: types.SimpleNamespace(
            search_fragments=lambda *a, **k: [],
            search_lexical=lambda *a, **k: [],
            close=lambda: None,
        )
        _fu.get_embedding = lambda *a, **k: None
        _plugins.datajack = _dj
        _dj.forensic_utils = _fu
        return _load_skill(
            "advanced_memory_search.py", "_test_ams_59",
            extra_stubs={
                "plugins": _plugins,
                "plugins.datajack": _dj,
                "plugins.datajack.forensic_utils": _fu,
            },
        )

    def test_find_aim_root_function_exists(self):
        mod = self._load()
        assert hasattr(mod, "_find_aim_root"), (
            "advanced_memory_search.py missing _find_aim_root() — fix not applied"
        )

    def test_find_aim_root_resolves_to_aim_claude(self):
        mod = self._load()
        _assert_aim_root_correct(mod, "advanced_memory_search.py")

    def test_src_path_appended_correctly(self):
        mod = self._load()
        with patch("os.getcwd", return_value=AIM_CLAUDE_ROOT):
            root = mod._find_aim_root()
        expected_src = os.path.join(root, "src")
        assert expected_src in sys.path, (
            f"advanced_memory_search.py did not append correct src to sys.path. "
            f"Expected {expected_src!r} in sys.path."
        )
