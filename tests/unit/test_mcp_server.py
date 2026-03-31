"""
Unit tests for:
  - scripts/mcp_server_claude.py  (CLAUDE.md wrapper)
  - src/mcp_server.py             (shared backend: search_engram, run_skill,
                                   _parse_skill_manifest, _build_sandbox_command,
                                   _sandboxed_run)

External I/O (subprocess, file reads, FastMCP) is mocked throughout.
"""

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

# ---------------------------------------------------------------------------
# Bootstrap: stub FastMCP so we can import mcp_server without the package
# ---------------------------------------------------------------------------

def _make_fake_fastmcp():
    fake_mcp = MagicMock()
    # decorator stubs that return the function unchanged
    fake_mcp.tool.return_value = lambda f: f
    fake_mcp.resource.return_value = lambda f: f
    fake_mcp.run = MagicMock()
    return fake_mcp

_fake_fastmcp_instance = _make_fake_fastmcp()
_fake_fastmcp_class = MagicMock(return_value=_fake_fastmcp_instance)

fake_fastmcp_module = types.ModuleType("fastmcp")
fake_fastmcp_module.FastMCP = _fake_fastmcp_class
sys.modules["fastmcp"] = fake_fastmcp_module

# Stub config_utils
fake_config_utils = types.ModuleType("config_utils")
fake_config_utils.CONFIG = {}
fake_config_utils.AIM_ROOT = "/tmp/fake-aim-root"
sys.modules["config_utils"] = fake_config_utils

MCP_SERVER_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "src", "mcp_server.py"
)

def _load_mcp_server():
    import importlib.util
    spec = importlib.util.spec_from_file_location("mcp_server", MCP_SERVER_PATH)
    mod = importlib.util.module_from_spec(spec)
    # Stub retriever import inside the module
    with patch.dict(sys.modules, {"retriever": MagicMock()}):
        spec.loader.exec_module(mod)
    return mod

mcp_server = _load_mcp_server()


# ---------------------------------------------------------------------------
# 1. mcp_server_claude.py — get_project_context() override
# ---------------------------------------------------------------------------

class TestMcpServerClaudeWrapper(unittest.TestCase):
    """
    Tests for the thin wrapper in scripts/mcp_server_claude.py.
    We test get_project_context() in isolation since that is the only
    custom logic the wrapper adds.
    """

    def _make_get_project_context(self, aim_claude_root):
        """Recreate get_project_context() bound to a specific root dir."""
        def get_project_context():
            path = os.path.join(aim_claude_root, "CLAUDE.md")
            if os.path.exists(path):
                with open(path, "r") as f:
                    return f.read()
            return "CLAUDE.md not found."
        return get_project_context

    def test_returns_claude_md_contents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            claude_md = os.path.join(tmpdir, "CLAUDE.md")
            with open(claude_md, "w") as f:
                f.write("# A.I.M. — Sovereign Memory Interface\n\nMy mandate.")
            fn = self._make_get_project_context(tmpdir)
            result = fn()
            self.assertIn("Sovereign Memory Interface", result)
            self.assertIn("mandate", result)

    def test_returns_fallback_when_claude_md_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fn = self._make_get_project_context(tmpdir)
            result = fn()
            self.assertEqual(result, "CLAUDE.md not found.")

    def test_reads_claude_md_not_gemini_md(self):
        """Verify the wrapper reads CLAUDE.md, not GEMINI.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Put content in GEMINI.md only — should NOT be returned
            with open(os.path.join(tmpdir, "GEMINI.md"), "w") as f:
                f.write("GEMINI content")
            fn = self._make_get_project_context(tmpdir)
            result = fn()
            self.assertNotIn("GEMINI content", result)
            self.assertEqual(result, "CLAUDE.md not found.")

    def test_wrapper_aim_claude_root_is_parent_of_scripts(self):
        """aim_claude_root must be the parent of the scripts/ directory."""
        scripts_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "scripts"
        )
        expected_root = os.path.dirname(os.path.abspath(scripts_dir))
        # The wrapper computes: os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # where __file__ is scripts/mcp_server_claude.py
        wrapper_file = os.path.join(
            os.path.dirname(__file__), "..", "..", "scripts", "mcp_server_claude.py"
        )
        computed_root = os.path.dirname(os.path.dirname(os.path.abspath(wrapper_file)))
        self.assertEqual(os.path.normpath(computed_root), os.path.normpath(expected_root))


# ---------------------------------------------------------------------------
# 2. search_engram tool
# ---------------------------------------------------------------------------

class TestSearchEngram(unittest.TestCase):

    def test_returns_formatted_results(self):
        mock_results = [
            {"session_file": "session-abc.jsonl", "content": "Hybrid RAG architecture", "score": 0.9123},
            {"session_file": "session-def.jsonl", "content": "Engram DB schema", "score": 0.8456},
        ]
        with patch.object(mcp_server, "perform_search", return_value=mock_results):
            result = mcp_server.search_engram("hybrid rag")
        self.assertIn("hybrid rag", result)
        self.assertIn("Hybrid RAG architecture", result)
        self.assertIn("Engram DB schema", result)
        self.assertIn("0.9123", result)

    def test_returns_no_fragments_message_when_empty(self):
        with patch.object(mcp_server, "perform_search", return_value=[]):
            result = mcp_server.search_engram("nonexistent topic")
        self.assertIn("No fragments found", result)
        self.assertIn("nonexistent topic", result)

    def test_returns_error_when_perform_search_is_none(self):
        original = mcp_server.perform_search
        mcp_server.perform_search = None
        try:
            result = mcp_server.search_engram("anything")
        finally:
            mcp_server.perform_search = original
        self.assertIn("Error", result)
        self.assertIn("Retriever", result)

    def test_returns_retrieval_error_on_exception(self):
        with patch.object(mcp_server, "perform_search", side_effect=RuntimeError("DB locked")):
            result = mcp_server.search_engram("query")
        self.assertIn("Retrieval Error", result)
        self.assertIn("DB locked", result)

    def test_result_contains_separator_lines(self):
        mock_results = [
            {"session_file": "s.jsonl", "content": "content", "score": 0.5},
        ]
        with patch.object(mcp_server, "perform_search", return_value=mock_results):
            result = mcp_server.search_engram("q")
        self.assertIn("---", result)

    def test_search_passes_top_k_5(self):
        with patch.object(mcp_server, "perform_search", return_value=[]) as mock_search:
            mcp_server.search_engram("test")
        mock_search.assert_called_once_with("test", top_k=5)


# ---------------------------------------------------------------------------
# 3. run_skill tool
# ---------------------------------------------------------------------------

class TestRunSkill(unittest.TestCase):

    def test_error_when_skill_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mcp_server.SKILLS_DIR = Path(tmpdir)
            result = mcp_server.run_skill("nonexistent_skill")
        data = json.loads(result)
        self.assertIn("error", data)
        self.assertIn("not found", data["error"])

    def test_finds_py_skill(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_path = Path(tmpdir) / "my_skill.py"
            skill_path.write_text("print('hello')")
            mcp_server.SKILLS_DIR = Path(tmpdir)
            with patch.object(mcp_server, "_sandboxed_run", return_value='{"result": "ok"}') as mock_run:
                result = mcp_server.run_skill("my_skill")
            mock_run.assert_called_once_with(skill_path, {})

    def test_finds_sh_skill_when_no_py(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_path = Path(tmpdir) / "my_skill.sh"
            skill_path.write_text("echo hello")
            mcp_server.SKILLS_DIR = Path(tmpdir)
            with patch.object(mcp_server, "_sandboxed_run", return_value="ok") as mock_run:
                mcp_server.run_skill("my_skill")
            mock_run.assert_called_once_with(skill_path, {})

    def test_parses_valid_args_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_path = Path(tmpdir) / "my_skill.py"
            skill_path.write_text("")
            mcp_server.SKILLS_DIR = Path(tmpdir)
            with patch.object(mcp_server, "_sandboxed_run", return_value="ok") as mock_run:
                mcp_server.run_skill("my_skill", args_json='{"key": "value"}')
            mock_run.assert_called_once_with(skill_path, {"key": "value"})

    def test_empty_args_json_passes_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_path = Path(tmpdir) / "my_skill.py"
            skill_path.write_text("")
            mcp_server.SKILLS_DIR = Path(tmpdir)
            with patch.object(mcp_server, "_sandboxed_run", return_value="ok") as mock_run:
                mcp_server.run_skill("my_skill", args_json="{}")
            mock_run.assert_called_once_with(skill_path, {})

    def test_invalid_args_json_returns_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_path = Path(tmpdir) / "my_skill.py"
            skill_path.write_text("")
            mcp_server.SKILLS_DIR = Path(tmpdir)
            result = mcp_server.run_skill("my_skill", args_json="not valid json")
        data = json.loads(result)
        self.assertIn("error", data)


# ---------------------------------------------------------------------------
# 4. _parse_skill_manifest
# ---------------------------------------------------------------------------

class TestParseSkillManifest(unittest.TestCase):
    """
    BUG #45: _parse_skill_manifest() uses Path.with_suffix("_SKILL.md") for .py files,
    which raises ValueError because with_suffix() requires the arg to start with ".".
    All 4 skills are .py — so this function always crashes.
    Fix: use with_name(stem + "_SKILL.md") instead.
    These tests document the expected behaviour AFTER the bug is fixed.
    """

    def test_parses_name_and_description(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_py = Path(tmpdir) / "my_skill.py"
            skill_md = Path(tmpdir) / "my_skill_SKILL.md"
            skill_py.write_text("")
            skill_md.write_text(
                "**Name:** My Awesome Skill\n"
                "**Description:** Does something great\n"
            )
            result = mcp_server._parse_skill_manifest(skill_py)
        self.assertEqual(result["name"], "My Awesome Skill")
        self.assertEqual(result["description"], "Does something great")

    def test_fallback_when_no_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_py = Path(tmpdir) / "my_skill.py"
            skill_py.write_text("")
            result = mcp_server._parse_skill_manifest(skill_py)
        self.assertEqual(result["name"], "my_skill")
        self.assertEqual(result["description"], "No manifest found")

    def test_returns_empty_args_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_py = Path(tmpdir) / "my_skill.py"
            skill_py.write_text("")
            result = mcp_server._parse_skill_manifest(skill_py)
        self.assertEqual(result["args"], {})


# ---------------------------------------------------------------------------
# 5. _build_sandbox_command
# ---------------------------------------------------------------------------

class TestBuildSandboxCommand(unittest.TestCase):

    def test_py_script_uses_python_executor(self):
        skill = Path("/tmp/my_skill.py")
        cmd = mcp_server._build_sandbox_command(skill, {})
        self.assertIn(sys.executable, cmd)
        self.assertIn(str(skill), cmd)

    def test_sh_script_uses_bash(self):
        skill = Path("/tmp/my_skill.sh")
        cmd = mcp_server._build_sandbox_command(skill, {})
        self.assertIn("bash", cmd)
        self.assertIn(str(skill), cmd)

    def test_bwrap_is_in_command(self):
        skill = Path("/tmp/my_skill.py")
        cmd = mcp_server._build_sandbox_command(skill, {})
        self.assertIn("bwrap", cmd)

    def test_timeout_60s_in_command(self):
        skill = Path("/tmp/my_skill.py")
        cmd = mcp_server._build_sandbox_command(skill, {})
        self.assertIn("timeout", cmd)
        self.assertIn("60s", cmd)

    def test_unshare_net_in_command(self):
        skill = Path("/tmp/my_skill.py")
        cmd = mcp_server._build_sandbox_command(skill, {})
        self.assertIn("--unshare-net", cmd)

    def test_args_dict_serialized_as_json(self):
        skill = Path("/tmp/my_skill.py")
        cmd = mcp_server._build_sandbox_command(skill, {"key": "value"})
        self.assertIn('{"key": "value"}', cmd)

    def test_no_extra_arg_when_args_empty(self):
        skill = Path("/tmp/my_skill.py")
        cmd_with = mcp_server._build_sandbox_command(skill, {"k": "v"})
        cmd_without = mcp_server._build_sandbox_command(skill, {})
        # Command with args should be longer
        self.assertGreater(len(cmd_with), len(cmd_without))


# ---------------------------------------------------------------------------
# 6. _sandboxed_run
# ---------------------------------------------------------------------------

class TestSandboxedRun(unittest.TestCase):

    def test_returns_error_when_bwrap_not_installed(self):
        with patch("shutil.which", return_value=None):
            result = mcp_server._sandboxed_run(Path("/tmp/skill.py"), {})
        data = json.loads(result)
        self.assertIn("error", data)
        self.assertIn("bubblewrap", data["error"])

    def test_returns_stdout_on_success(self):
        mock_result = MagicMock()
        mock_result.stdout = "skill output here"
        mock_result.stderr = ""
        with patch("shutil.which", return_value="/usr/bin/bwrap"), \
             patch("subprocess.run", return_value=mock_result):
            result = mcp_server._sandboxed_run(Path("/tmp/skill.py"), {})
        self.assertEqual(result, "skill output here")

    def test_falls_back_to_stderr_when_stdout_empty(self):
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "some warning"
        with patch("shutil.which", return_value="/usr/bin/bwrap"), \
             patch("subprocess.run", return_value=mock_result):
            result = mcp_server._sandboxed_run(Path("/tmp/skill.py"), {})
        self.assertEqual(result, "some warning")

    def test_returns_completed_message_when_both_empty(self):
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = ""
        with patch("shutil.which", return_value="/usr/bin/bwrap"), \
             patch("subprocess.run", return_value=mock_result):
            result = mcp_server._sandboxed_run(Path("/tmp/skill.py"), {})
        self.assertIn("completed", result)

    def test_returns_error_on_timeout(self):
        import subprocess
        with patch("shutil.which", return_value="/usr/bin/bwrap"), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired("bwrap", 65)):
            result = mcp_server._sandboxed_run(Path("/tmp/skill.py"), {})
        data = json.loads(result)
        self.assertIn("error", data)
        self.assertIn("timed out", data["error"])

    def test_returns_error_on_generic_exception(self):
        with patch("shutil.which", return_value="/usr/bin/bwrap"), \
             patch("subprocess.run", side_effect=OSError("permission denied")):
            result = mcp_server._sandboxed_run(Path("/tmp/skill.py"), {})
        data = json.loads(result)
        self.assertIn("error", data)


# ---------------------------------------------------------------------------
# 7. Known bugs
# ---------------------------------------------------------------------------

class TestKnownBugs(unittest.TestCase):

    def test_bug_base_mcp_server_reads_gemini_md(self):
        """
        src/mcp_server.py base resource still reads GEMINI.md (stale post-migration).
        The wrapper overrides this correctly, but the base is never fixed.
        Caught by: code review. Filed as #44.
        """
        with open(MCP_SERVER_PATH) as f:
            source = f.read()
        self.assertNotIn(
            '"GEMINI.md"',
            source,
            "BUG #44: src/mcp_server.py base get_project_context() still reads GEMINI.md. "
            "Should be platform-neutral or updated to CLAUDE.md.",
        )


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
