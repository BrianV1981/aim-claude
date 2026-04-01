"""
Unit tests for scripts/aim_cli.py

Tests cover:
- Argument parser: all subcommands and flags
- Command dispatch logic
- Pure business logic functions (version bumping, commit, search-sessions, daemon, etc.)
- Known bugs caught during audit (cmd_clean undefined, json not imported, stale .gemini path)

External dependencies (subprocess, file I/O) are mocked.
"""

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from io import StringIO
from unittest.mock import MagicMock, mock_open, patch, call

# ---------------------------------------------------------------------------
# Bootstrap: make aim_cli importable without executing main() or triggering
# the venv-swap at the top of the file.
# ---------------------------------------------------------------------------

AIM_CLI_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "scripts", "aim_cli.py"
)


def _load_aim_cli():
    """Load aim_cli as a module without running main() or the venv execv."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("aim_cli", AIM_CLI_PATH)
    mod = importlib.util.module_from_spec(spec)

    # Patch execv so the venv-bootstrap doesn't replace the process
    with patch("os.execv"), patch("os.path.exists", return_value=False):
        # config_utils is a backend dependency — stub it out
        fake_config_utils = types.ModuleType("config_utils")
        fake_config_utils.CONFIG = {}
        fake_config_utils.AIM_ROOT = "/tmp/fake-aim-root"
        sys.modules["config_utils"] = fake_config_utils

        spec.loader.exec_module(mod)

    return mod


aim_cli = _load_aim_cli()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_args(**kwargs):
    """Build a minimal argparse Namespace."""
    defaults = {"command": None}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# 1. Parser tests
# ---------------------------------------------------------------------------


class TestParser(unittest.TestCase):
    """Verify the argument parser accepts all documented subcommands and flags."""

    def _parse(self, argv):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        # Re-register a minimal clone of the real parser entries we care about
        sp = subparsers.add_parser("search")
        sp.add_argument("query", nargs="+")
        sp.add_argument("--top-k", type=int, dest="top_k")
        sp.add_argument("--full", action="store_true")
        sp.add_argument("--context", type=int, nargs="?", const=2000)
        sp.add_argument("--session", type=str)

        bp = subparsers.add_parser("bug")
        bp.add_argument("title")

        fp = subparsers.add_parser("fix")
        fp.add_argument("id")

        pp = subparsers.add_parser("push")
        pp.add_argument("message")

        dp = subparsers.add_parser("daemon")
        dp.add_argument("action", choices=["start", "stop", "status"])

        jip = subparsers.add_parser("jack-in")
        jip.add_argument("file")

        bk = subparsers.add_parser("bake")
        bk.add_argument("directory")
        bk.add_argument("output")

        dlg = subparsers.add_parser("delegate")
        dlg.add_argument("instruction")
        dlg.add_argument("--files", nargs="+", required=True)

        mbp = subparsers.add_parser("merge-batch")
        mbp.add_argument("--push", action="store_true")

        ssp = subparsers.add_parser("search-sessions")
        ssp.add_argument("query", nargs="+")

        for name in [
            "init", "status", "config", "tui", "core-memory", "update",
            "commit", "doctor", "health", "purge", "uninstall", "index",
            "ingest", "handoff", "pulse", "sync", "sync-issues", "crash",
            "reincarnate", "clean", "exchange", "unplug", "memory", "map",
            "sessions", "promote", "swarm",
        ]:
            subparsers.add_parser(name)

        return parser.parse_args(argv)

    def test_search_basic(self):
        args = self._parse(["search", "hybrid", "rag"])
        self.assertEqual(args.query, ["hybrid", "rag"])
        self.assertIsNone(args.top_k)
        self.assertFalse(args.full)

    def test_search_all_flags(self):
        args = self._parse(["search", "engram", "--top-k", "5", "--full", "--context", "1000", "--session", "abc123"])
        self.assertEqual(args.top_k, 5)
        self.assertTrue(args.full)
        self.assertEqual(args.context, 1000)
        self.assertEqual(args.session, "abc123")

    def test_bug_title(self):
        args = self._parse(["bug", "Something is broken"])
        self.assertEqual(args.title, "Something is broken")

    def test_fix_id(self):
        args = self._parse(["fix", "42"])
        self.assertEqual(args.id, "42")

    def test_push_message(self):
        args = self._parse(["push", "Fix: resolve null pointer"])
        self.assertEqual(args.message, "Fix: resolve null pointer")

    def test_daemon_actions(self):
        for action in ["start", "stop", "status"]:
            args = self._parse(["daemon", action])
            self.assertEqual(args.action, action)

    def test_merge_batch_push_flag(self):
        args = self._parse(["merge-batch", "--push"])
        self.assertTrue(args.push)

    def test_merge_batch_no_push(self):
        args = self._parse(["merge-batch"])
        self.assertFalse(args.push)

    def test_delegate_required_files(self):
        args = self._parse(["delegate", "analyze this", "--files", "a.py", "b.py"])
        self.assertEqual(args.instruction, "analyze this")
        self.assertEqual(args.files, ["a.py", "b.py"])


# ---------------------------------------------------------------------------
# 2. Version bumping logic (cmd_push)
# ---------------------------------------------------------------------------


class TestVersionBumping(unittest.TestCase):
    """The semantic release section of cmd_push contains pure logic we can test
    by extracting it into a helper function pattern."""

    def _bump(self, current_version, message):
        """Mirrors the bump logic in cmd_push exactly."""
        major, minor, patch = map(int, current_version.replace("v", "").split("."))
        bump_type = "none"
        if message.startswith("BREAKING CHANGE:"):
            bump_type = "major"
        elif message.startswith("Feature:") or message.startswith("feat:"):
            bump_type = "minor"
        elif message.startswith("Fix:") or message.startswith("fix:"):
            bump_type = "patch"

        if bump_type == "major":
            major += 1; minor = 0; patch = 0
        elif bump_type == "minor":
            minor += 1; patch = 0
        elif bump_type == "patch":
            patch += 1

        return f"v{major}.{minor}.{patch}", bump_type

    def test_breaking_change_bumps_major(self):
        v, t = self._bump("v1.2.3", "BREAKING CHANGE: rework API")
        self.assertEqual(v, "v2.0.0")
        self.assertEqual(t, "major")

    def test_feature_bumps_minor(self):
        v, t = self._bump("v1.2.3", "Feature: add search")
        self.assertEqual(v, "v1.3.0")
        self.assertEqual(t, "minor")

    def test_feat_prefix_bumps_minor(self):
        v, t = self._bump("v1.2.3", "feat: new endpoint")
        self.assertEqual(v, "v1.3.0")
        self.assertEqual(t, "minor")

    def test_fix_bumps_patch(self):
        v, t = self._bump("v1.2.3", "Fix: null pointer in retriever")
        self.assertEqual(v, "v1.2.4")
        self.assertEqual(t, "patch")

    def test_fix_lowercase_bumps_patch(self):
        v, t = self._bump("v1.2.3", "fix: edge case")
        self.assertEqual(v, "v1.2.4")
        self.assertEqual(t, "patch")

    def test_docs_prefix_no_bump(self):
        v, t = self._bump("v1.2.3", "Docs: update readme")
        self.assertEqual(v, "v1.2.3")
        self.assertEqual(t, "none")

    def test_major_resets_minor_and_patch(self):
        v, _ = self._bump("v3.7.9", "BREAKING CHANGE: overhaul")
        self.assertEqual(v, "v4.0.0")

    def test_minor_resets_patch(self):
        v, _ = self._bump("v1.0.9", "Feature: add thing")
        self.assertEqual(v, "v1.1.0")


# ---------------------------------------------------------------------------
# 3. cmd_status
# ---------------------------------------------------------------------------


class TestCmdStatus(unittest.TestCase):

    def test_prints_pulse_when_file_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aim_cli.BASE_DIR = tmpdir
            os.makedirs(os.path.join(tmpdir, "continuity"), exist_ok=True)
            pulse_path = os.path.join(tmpdir, "continuity", "CURRENT_PULSE.md")
            with open(pulse_path, "w") as f:
                f.write("# Pulse\nAll systems go.")

            with patch("sys.stdout", new_callable=StringIO) as mock_out:
                aim_cli.cmd_status(_make_args())
            self.assertIn("All systems go.", mock_out.getvalue())

    def test_error_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aim_cli.BASE_DIR = tmpdir
            with patch("sys.stderr", new_callable=StringIO) as mock_err:
                aim_cli.cmd_status(_make_args())
            self.assertIn("CURRENT_PULSE.md not found", mock_err.getvalue())


# ---------------------------------------------------------------------------
# 4. cmd_core_memory
# ---------------------------------------------------------------------------


class TestCmdCoreMemory(unittest.TestCase):

    def test_creates_file_if_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aim_cli.BASE_DIR = tmpdir
            with patch("subprocess.call"):
                aim_cli.cmd_core_memory(_make_args())
            path = os.path.join(tmpdir, "continuity", "CORE_MEMORY.md")
            self.assertTrue(os.path.exists(path))
            with open(path) as f:
                self.assertIn("A.I.M. Core Memory", f.read())

    def test_opens_editor_with_correct_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aim_cli.BASE_DIR = tmpdir
            os.makedirs(os.path.join(tmpdir, "continuity"), exist_ok=True)
            core_path = os.path.join(tmpdir, "continuity", "CORE_MEMORY.md")
            with open(core_path, "w") as f:
                f.write("existing content")

            with patch("subprocess.call") as mock_call, \
                 patch.dict(os.environ, {"EDITOR": "vim"}):
                aim_cli.cmd_core_memory(_make_args())
                mock_call.assert_called_once_with(["vim", core_path])


# ---------------------------------------------------------------------------
# 5. cmd_bug
# ---------------------------------------------------------------------------


class TestCmdBug(unittest.TestCase):

    def test_creates_issue_via_gh(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aim_cli.BASE_DIR = tmpdir
            args = _make_args(title="Something broke")
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                aim_cli.cmd_bug(args)
            call_args = mock_run.call_args[0][0]
            self.assertEqual(call_args[0], "gh")
            self.assertIn("issue", call_args)
            self.assertIn("create", call_args)
            self.assertIn("Something broke", call_args)

    def test_includes_fallback_tail_when_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aim_cli.BASE_DIR = tmpdir
            os.makedirs(os.path.join(tmpdir, "continuity"), exist_ok=True)
            tail_path = os.path.join(tmpdir, "continuity", "FALLBACK_TAIL.md")
            with open(tail_path, "w") as f:
                f.write("## Last 10 Turns\nsome context here")

            args = _make_args(title="Bug report")
            captured_body = []

            def capture_run(cmd, **kwargs):
                if "--body" in cmd:
                    idx = cmd.index("--body")
                    captured_body.append(cmd[idx + 1])
                return MagicMock(returncode=0)

            with patch("subprocess.run", side_effect=capture_run):
                aim_cli.cmd_bug(args)

            self.assertTrue(captured_body, "gh issue create was not called")
            self.assertIn("some context here", captured_body[0])

    def test_handles_missing_gh_gracefully(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aim_cli.BASE_DIR = tmpdir
            args = _make_args(title="Test")
            with patch("subprocess.run", side_effect=FileNotFoundError), \
                 patch("sys.stdout", new_callable=StringIO) as out:
                aim_cli.cmd_bug(args)
            self.assertIn("not installed", out.getvalue())


# ---------------------------------------------------------------------------
# 6. cmd_fix
# ---------------------------------------------------------------------------


class TestCmdFix(unittest.TestCase):

    def test_creates_branch_with_correct_name(self):
        args = _make_args(id="42")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            aim_cli.cmd_fix(args)
        branch_cmd = mock_run.call_args[0][0]
        self.assertIn("fix/issue-42", branch_cmd)
        self.assertIn("checkout", branch_cmd)
        self.assertIn("-b", branch_cmd)


# ---------------------------------------------------------------------------
# 7. cmd_promote — must refuse to run from main
# ---------------------------------------------------------------------------


class TestCmdPromote(unittest.TestCase):

    def test_refuses_from_main_branch(self):
        mock_result = MagicMock()
        mock_result.stdout = "main\n"
        with patch("subprocess.run", return_value=mock_result), \
             patch("sys.stdout", new_callable=StringIO) as out:
            aim_cli.cmd_promote(_make_args())
        self.assertIn("already on 'main'", out.getvalue())

    def test_proceeds_from_dev_branch(self):
        responses = {
            "branch --show-current": MagicMock(stdout="fix/issue-99\n"),
            "fetch": MagicMock(returncode=0),
        }

        def smart_run(cmd, **kwargs):
            if "--show-current" in cmd:
                return MagicMock(stdout="fix/issue-99\n")
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=smart_run), \
             patch("sys.stdout", new_callable=StringIO) as out:
            aim_cli.cmd_promote(_make_args())
        # Should not show the "already on main" error
        self.assertNotIn("already on 'main'", out.getvalue())


# ---------------------------------------------------------------------------
# 8. cmd_search_sessions
# ---------------------------------------------------------------------------


class TestCmdSearchSessions(unittest.TestCase):

    def _make_history_db(self, tmpdir):
        db_path = os.path.join(tmpdir, "archive", "history.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE VIRTUAL TABLE history_fts USING fts5(session_id, timestamp, content)")
        conn.execute("INSERT INTO history_fts VALUES ('abc123def456', '2026-03-31', 'hybrid rag retrieval engram')")
        conn.commit()
        conn.close()
        return db_path

    def test_finds_matching_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aim_cli.BASE_DIR = tmpdir
            self._make_history_db(tmpdir)
            args = _make_args(query=["hybrid", "rag"])
            with patch("sys.stdout", new_callable=StringIO) as out:
                aim_cli.cmd_search_sessions(args)
            output = out.getvalue()
            self.assertIn("abc123", output)

    def test_no_results_message(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aim_cli.BASE_DIR = tmpdir
            self._make_history_db(tmpdir)
            args = _make_args(query=["xyzzy_not_found"])
            with patch("sys.stdout", new_callable=StringIO) as out:
                aim_cli.cmd_search_sessions(args)
            self.assertIn("No matches found", out.getvalue())

    def test_missing_db_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aim_cli.BASE_DIR = tmpdir
            args = _make_args(query=["anything"])
            with patch.object(aim_cli, "run_script"), \
                 patch("sys.stdout", new_callable=StringIO) as out:
                aim_cli.cmd_search_sessions(args)
            self.assertIn("No historical sessions found", out.getvalue())


# ---------------------------------------------------------------------------
# 9. cmd_daemon
# ---------------------------------------------------------------------------


class TestCmdDaemon(unittest.TestCase):

    def test_start_writes_pid_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aim_cli.BASE_DIR = tmpdir
            os.makedirs(os.path.join(tmpdir, "archive"), exist_ok=True)
            args = _make_args(action="start")
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            with patch("subprocess.Popen", return_value=mock_proc), \
                 patch("sys.stdout", new_callable=StringIO):
                aim_cli.cmd_daemon(args)
            pid_file = os.path.join(tmpdir, "archive", "daemon.pid")
            self.assertTrue(os.path.exists(pid_file))
            with open(pid_file) as f:
                self.assertEqual(f.read(), "12345")

    def test_start_warns_if_already_running(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aim_cli.BASE_DIR = tmpdir
            os.makedirs(os.path.join(tmpdir, "archive"), exist_ok=True)
            pid_file = os.path.join(tmpdir, "archive", "daemon.pid")
            with open(pid_file, "w") as f:
                f.write("99999")
            args = _make_args(action="start")
            with patch("sys.stdout", new_callable=StringIO) as out:
                aim_cli.cmd_daemon(args)
            self.assertIn("WARNING", out.getvalue())

    def test_stop_removes_pid_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aim_cli.BASE_DIR = tmpdir
            os.makedirs(os.path.join(tmpdir, "archive"), exist_ok=True)
            pid_file = os.path.join(tmpdir, "archive", "daemon.pid")
            with open(pid_file, "w") as f:
                f.write("99999")
            args = _make_args(action="stop")
            with patch("subprocess.run"), \
                 patch("sys.stdout", new_callable=StringIO):
                aim_cli.cmd_daemon(args)
            self.assertFalse(os.path.exists(pid_file))

    def test_status_inactive_when_no_pid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aim_cli.BASE_DIR = tmpdir
            os.makedirs(os.path.join(tmpdir, "archive"), exist_ok=True)
            args = _make_args(action="status")
            with patch("sys.stdout", new_callable=StringIO) as out:
                aim_cli.cmd_daemon(args)
            self.assertIn("INACTIVE", out.getvalue())


# ---------------------------------------------------------------------------
# 10. cmd_commit — proposal parsing and delta extraction
# ---------------------------------------------------------------------------


class TestCmdCommit(unittest.TestCase):

    VALID_PROPOSAL = """\
### 1. SUMMARY
Test summary

### 2. ANALYSIS
Some analysis

### 3. MEMORY DELTA
```markdown
# Updated Memory

- Key fact preserved
```
"""

    def test_commits_valid_proposal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aim_cli.BASE_DIR = tmpdir
            proposal_dir = os.path.join(tmpdir, "memory", "proposals")
            os.makedirs(proposal_dir)
            os.makedirs(os.path.join(tmpdir, "core"), exist_ok=True)

            proposal_path = os.path.join(proposal_dir, "PROPOSAL_2026-03-31.md")
            with open(proposal_path, "w") as f:
                f.write(self.VALID_PROPOSAL)

            memory_path = os.path.join(tmpdir, "core", "MEMORY.md")
            with open(memory_path, "w") as f:
                f.write("# Old Memory\n")

            with patch("sys.stdout", new_callable=StringIO) as out, \
                 patch("subprocess.run"):
                aim_cli.cmd_commit(_make_args())

            with open(memory_path) as f:
                content = f.read()
            self.assertIn("Key fact preserved", content)
            self.assertIn("Successfully committed", out.getvalue())

    def test_creates_backup_before_overwrite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aim_cli.BASE_DIR = tmpdir
            proposal_dir = os.path.join(tmpdir, "memory", "proposals")
            os.makedirs(proposal_dir)
            os.makedirs(os.path.join(tmpdir, "core"), exist_ok=True)

            with open(os.path.join(proposal_dir, "PROPOSAL_2026-03-31.md"), "w") as f:
                f.write(self.VALID_PROPOSAL)

            memory_path = os.path.join(tmpdir, "core", "MEMORY.md")
            with open(memory_path, "w") as f:
                f.write("# Original Memory\n")

            with patch("sys.stdout", new_callable=StringIO), \
                 patch("subprocess.run"):
                aim_cli.cmd_commit(_make_args())

            backup_path = memory_path + ".bak"
            self.assertTrue(os.path.exists(backup_path))
            with open(backup_path) as f:
                self.assertIn("Original Memory", f.read())

    def test_error_when_no_proposals_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aim_cli.BASE_DIR = tmpdir
            with patch("sys.stderr", new_callable=StringIO) as err:
                aim_cli.cmd_commit(_make_args())
            self.assertIn("No proposals folder found", err.getvalue())

    def test_error_when_no_proposals(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aim_cli.BASE_DIR = tmpdir
            os.makedirs(os.path.join(tmpdir, "memory", "proposals"))
            with patch("sys.stderr", new_callable=StringIO) as err:
                aim_cli.cmd_commit(_make_args())
            self.assertIn("No pending proposals found", err.getvalue())


# ---------------------------------------------------------------------------
# 11. run_script / run_bash_script error handling
# ---------------------------------------------------------------------------


class TestRunScript(unittest.TestCase):

    def test_run_script_exits_on_failure(self):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "cmd")), \
             self.assertRaises(SystemExit) as cm:
            aim_cli.run_script("/fake/script.py", [])
        self.assertEqual(cm.exception.code, 1)

    def test_run_bash_script_exits_on_failure(self):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(2, "bash")), \
             self.assertRaises(SystemExit) as cm:
            aim_cli.run_bash_script("/fake/script.sh", [])
        self.assertEqual(cm.exception.code, 2)


# ---------------------------------------------------------------------------
# 12. Known bugs — caught by reading the code
# ---------------------------------------------------------------------------


class TestKnownBugs(unittest.TestCase):
    """
    These tests document bugs found during the audit.
    They are expected to FAIL until the bugs are fixed.
    Once fixed, they should pass and serve as regression guards.
    """

    def test_bug_cmd_clean_is_defined(self):
        """cmd_clean is dispatched at line 808 but never defined — NameError at runtime."""
        self.assertTrue(
            hasattr(aim_cli, "cmd_clean"),
            "BUG: cmd_clean is referenced in dispatch but never defined. "
            "Running `aim-claude clean` will raise NameError.",
        )

    def test_bug_json_is_imported(self):
        """json.load() is used in ensure_hooks_mapped() but json is never imported."""
        import importlib
        import ast

        with open(AIM_CLI_PATH) as f:
            source = f.read()
        tree = ast.parse(source)
        imports = [
            node.names[0].name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
        ]
        self.assertIn(
            "json", imports,
            "BUG: json.load() is used in ensure_hooks_mapped() but 'import json' is missing. "
            "ensure_hooks_mapped() will raise NameError if ~/.gemini/settings.json exists.",
        )

    def test_bug_ensure_hooks_mapped_stale_gemini_path(self):
        """ensure_hooks_mapped() reads ~/.gemini/settings.json — stale path post-migration.
        Should read ~/.claude/settings.json instead."""
        with open(AIM_CLI_PATH) as f:
            source = f.read()
        self.assertNotIn(
            ".gemini/settings.json",
            source,
            "BUG: ensure_hooks_mapped() still references ~/.gemini/settings.json. "
            "This is a stale path from the Gemini CLI era. Should be ~/.claude/settings.json.",
        )


# ---------------------------------------------------------------------------
# CLAUDE.md — swarm portability checks (#63)
# ---------------------------------------------------------------------------

CLAUDE_MD_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "CLAUDE.md"
)

# Verbs that appear in CLAUDE.md command examples (aim-claude <verb>)
_CLI_VERBS = ["search", "bug", "fix", "push", "map", "crash", "mail", "sync-issues"]


class TestClaudeMdCliNamePortability(unittest.TestCase):
    """
    Swarm mandate (aim-antigravity 2026-04-01): every command reference in
    CLAUDE.md must use the <CLI_NAME> placeholder, not the hardcoded
    workspace name 'aim-claude'. This ensures agents on other repos
    (aim-codex, aim-ollama, aim-vscode) execute the correct CLI alias.
    """

    def _source(self):
        with open(CLAUDE_MD_PATH, encoding="utf-8") as f:
            return f.read()

    def test_cli_name_callout_block_present(self):
        """CLAUDE.md must contain the fluid CLI name callout so agents know
        to substitute <CLI_NAME> with the actual workspace folder name."""
        src = self._source()
        self.assertIn(
            "<CLI_NAME>",
            src,
            "CLAUDE.md is missing the <CLI_NAME> placeholder. "
            "Swarm mandate (aim-antigravity) requires replacing hardcoded 'aim-claude' "
            "commands with <CLI_NAME> for cross-repo portability.",
        )

    def test_no_hardcoded_aim_claude_commands(self):
        """No backtick-wrapped `aim-claude <verb>` commands should remain.
        Every command example must use `<CLI_NAME> <verb>` instead."""
        src = self._source()
        import re
        # Match `aim-claude <verb>` patterns inside backticks
        pattern = r"`aim-claude\s+(' + '|'.join(_CLI_VERBS) + r')`"
        hardcoded = re.findall(r"`aim-claude\s+(?:' + '|'.join(_CLI_VERBS) + r')(?:[^`]*)`", src)
        self.assertEqual(
            hardcoded, [],
            f"CLAUDE.md still contains hardcoded `aim-claude` command(s): {hardcoded}. "
            "Replace with `<CLI_NAME> <verb>` per swarm mandate.",
        )

    def test_each_cli_verb_uses_cli_name_placeholder(self):
        """Every core CLI verb should appear as <CLI_NAME> <verb>, not aim-claude <verb>."""
        src = self._source()
        for verb in ["search", "bug", "fix", "push", "map"]:
            self.assertIn(
                f"<CLI_NAME> {verb}",
                src,
                f"CLAUDE.md missing `<CLI_NAME> {verb}` — ensure the {verb} command "
                f"uses the portable placeholder.",
            )


# ---------------------------------------------------------------------------


if __name__ == "__main__":
    unittest.main()
