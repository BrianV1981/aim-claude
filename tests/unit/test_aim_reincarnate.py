"""
Unit tests for scripts/aim_reincarnate.py

Covers:
- Issue #61: sync_issue_tracker.py is invoked as step 0 before handoff pulse
- Sync failure is non-fatal (WARN, not abort)
- venv_python resolution
"""

import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

AIM_CLAUDE_ROOT = str(Path(__file__).parent.parent.parent)
REINCARNATE_PATH = os.path.join(AIM_CLAUDE_ROOT, "scripts", "aim_reincarnate.py")


def _load_reincarnate():
    sys.modules.pop("aim_reincarnate", None)
    spec = importlib.util.spec_from_file_location("aim_reincarnate", REINCARNATE_PATH)
    mod = importlib.util.module_from_spec(spec)
    with patch("os.getcwd", return_value=AIM_CLAUDE_ROOT):
        spec.loader.exec_module(mod)
    return mod


class TestReincarnateIssueTrackerSync(unittest.TestCase):
    """Issue #61: sync_issue_tracker.py must be called as step 0 of reincarnation."""

    def setUp(self):
        self.mod = _load_reincarnate()

    def _run_main_mocked(self, sync_side_effect=None):
        """Run main() with all interactive and external calls stubbed."""
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if sync_side_effect and "sync_issue_tracker" in str(cmd):
                raise sync_side_effect
            result = MagicMock()
            result.stdout = ""
            result.returncode = 0
            return result

        with patch("builtins.input", return_value="test intent"), \
             patch.object(self.mod.subprocess, "run", side_effect=fake_run), \
             patch.object(self.mod.time, "sleep"), \
             patch.object(self.mod.os, "environ", {"TMUX": ""}), \
             patch.object(self.mod.os, "getppid", return_value=1), \
             patch.object(self.mod.os, "kill"):
            try:
                self.mod.main()
            except (SystemExit, Exception):
                pass
        return calls

    def test_sync_issue_tracker_called_before_pulse(self):
        """sync_issue_tracker.py must appear in subprocess calls before handoff_pulse_generator.py."""
        calls = self._run_main_mocked()
        flat = [str(c) for c in calls]
        sync_idx = next((i for i, c in enumerate(flat) if "sync_issue_tracker" in c), None)
        pulse_idx = next((i for i, c in enumerate(flat) if "handoff_pulse_generator" in c), None)
        self.assertIsNotNone(sync_idx, "sync_issue_tracker.py was never called during reincarnation")
        self.assertIsNotNone(pulse_idx, "handoff_pulse_generator.py was never called during reincarnation")
        self.assertLess(sync_idx, pulse_idx,
                        "sync_issue_tracker must be called BEFORE handoff_pulse_generator")

    def test_sync_failure_is_non_fatal(self):
        """If sync_issue_tracker fails, reincarnation should continue (not abort)."""
        import subprocess
        calls = self._run_main_mocked(
            sync_side_effect=subprocess.CalledProcessError(1, "sync_issue_tracker.py")
        )
        flat = [str(c) for c in calls]
        # Pulse should still have been called despite sync failure
        pulse_called = any("handoff_pulse_generator" in c for c in flat)
        self.assertTrue(pulse_called,
                        "Reincarnation aborted after sync failure — sync must be non-fatal")

    def test_sync_timeout_is_non_fatal(self):
        """If sync_issue_tracker times out, reincarnation should continue."""
        import subprocess
        calls = self._run_main_mocked(
            sync_side_effect=subprocess.TimeoutExpired("sync_issue_tracker.py", 15)
        )
        flat = [str(c) for c in calls]
        pulse_called = any("handoff_pulse_generator" in c for c in flat)
        self.assertTrue(pulse_called,
                        "Reincarnation aborted after sync timeout — must be non-fatal")

    def test_sync_uses_scripts_dir(self):
        """sync_issue_tracker.py must be resolved from AIM_ROOT/scripts/, not hardcoded."""
        calls = self._run_main_mocked()
        flat = [str(c) for c in calls]
        sync_call = next((c for c in flat if "sync_issue_tracker" in c), None)
        self.assertIsNotNone(sync_call)
        self.assertIn("scripts", sync_call,
                      "sync_issue_tracker.py path must include 'scripts/' directory")


class TestReincarnateCliArg(unittest.TestCase):
    """Issue #68: intent can be passed as a CLI arg to bypass interactive input()."""

    def setUp(self):
        self.mod = _load_reincarnate()

    def _run_main_with_argv(self, argv):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            result = MagicMock()
            result.stdout = ""
            result.returncode = 0
            return result

        with patch.object(sys, "argv", ["aim_reincarnate.py"] + argv), \
             patch.object(self.mod.subprocess, "run", side_effect=fake_run), \
             patch.object(self.mod.time, "sleep"), \
             patch.object(self.mod.os, "environ", {"TMUX": ""}), \
             patch.object(self.mod.os, "getppid", return_value=1), \
             patch.object(self.mod.os, "kill"), \
             patch("builtins.input") as mock_input:
            try:
                self.mod.main()
            except (SystemExit, Exception):
                pass
            return calls, mock_input

    def test_cli_arg_bypasses_input(self):
        """When intent is supplied as argv, input() must not be called."""
        _, mock_input = self._run_main_with_argv(["Continue the roadmap"])
        mock_input.assert_not_called()

    def test_cli_arg_multi_word(self):
        """Multi-word intent passed as argv is joined and used."""
        calls, mock_input = self._run_main_with_argv(["Fix", "issue", "42"])
        mock_input.assert_not_called()
        flat = [str(c) for c in calls]
        pulse_called = any("handoff_pulse_generator" in c for c in flat)
        self.assertTrue(pulse_called)

    def test_no_argv_falls_back_to_input(self):
        """When no argv is supplied, input() is called for Commander's Intent."""
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            result = MagicMock()
            result.stdout = ""
            result.returncode = 0
            return result

        with patch.object(sys, "argv", ["aim_reincarnate.py"]), \
             patch.object(self.mod.subprocess, "run", side_effect=fake_run), \
             patch.object(self.mod.time, "sleep"), \
             patch.object(self.mod.os, "environ", {"TMUX": ""}), \
             patch.object(self.mod.os, "getppid", return_value=1), \
             patch.object(self.mod.os, "kill"), \
             patch("builtins.input", return_value="manual intent") as mock_input:
            try:
                self.mod.main()
            except (SystemExit, Exception):
                pass
        mock_input.assert_called_once()


class TestReincarnateScrivenerPipeline(unittest.TestCase):
    """Issue #72: session_summarizer.py must be wired into aim_reincarnate.py
    as step 0.5 — before the pulse, after the issue tracker sync."""

    def setUp(self):
        self.mod = _load_reincarnate()

    def _run_main_mocked(self, summarizer_side_effect=None):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if summarizer_side_effect and "session_summarizer" in str(cmd):
                raise summarizer_side_effect
            result = MagicMock()
            result.stdout = ""
            result.returncode = 0
            return result

        with patch("builtins.input", return_value="test intent"), \
             patch.object(self.mod.subprocess, "run", side_effect=fake_run), \
             patch.object(self.mod.time, "sleep"), \
             patch.object(self.mod.os, "environ", {"TMUX": ""}), \
             patch.object(self.mod.os, "getppid", return_value=1), \
             patch.object(self.mod.os, "kill"):
            try:
                self.mod.main()
            except (SystemExit, Exception):
                pass
        return calls

    def test_session_summarizer_called(self):
        """session_summarizer.py must be invoked during reincarnation."""
        calls = self._run_main_mocked()
        flat = [str(c) for c in calls]
        self.assertTrue(
            any("session_summarizer" in c for c in flat),
            "session_summarizer.py was never called during reincarnation"
        )

    def test_summarizer_called_before_pulse(self):
        """session_summarizer must run before handoff_pulse_generator (step 0.5 < step 1)."""
        calls = self._run_main_mocked()
        flat = [str(c) for c in calls]
        summ_idx = next((i for i, c in enumerate(flat) if "session_summarizer" in c), None)
        pulse_idx = next((i for i, c in enumerate(flat) if "handoff_pulse_generator" in c), None)
        self.assertIsNotNone(summ_idx, "session_summarizer.py never called")
        self.assertIsNotNone(pulse_idx, "handoff_pulse_generator.py never called")
        self.assertLess(summ_idx, pulse_idx,
                        "session_summarizer must run BEFORE handoff_pulse_generator")

    def test_summarizer_called_after_sync(self):
        """session_summarizer must run after sync_issue_tracker (step 0 < step 0.5)."""
        calls = self._run_main_mocked()
        flat = [str(c) for c in calls]
        sync_idx = next((i for i, c in enumerate(flat) if "sync_issue_tracker" in c), None)
        summ_idx = next((i for i, c in enumerate(flat) if "session_summarizer" in c), None)
        self.assertIsNotNone(sync_idx, "sync_issue_tracker.py never called")
        self.assertIsNotNone(summ_idx, "session_summarizer.py never called")
        self.assertLess(sync_idx, summ_idx,
                        "sync_issue_tracker must run BEFORE session_summarizer")

    def test_summarizer_failure_is_non_fatal(self):
        """If session_summarizer fails, reincarnation must continue to pulse."""
        import subprocess
        calls = self._run_main_mocked(
            summarizer_side_effect=subprocess.CalledProcessError(1, "session_summarizer.py")
        )
        flat = [str(c) for c in calls]
        self.assertTrue(
            any("handoff_pulse_generator" in c for c in flat),
            "Reincarnation aborted after summarizer failure — must be non-fatal"
        )

    def test_summarizer_uses_hooks_dir(self):
        """session_summarizer.py must be resolved from AIM_ROOT/hooks/."""
        calls = self._run_main_mocked()
        flat = [str(c) for c in calls]
        summ_call = next((c for c in flat if "session_summarizer" in c), None)
        self.assertIsNotNone(summ_call)
        self.assertIn("hooks", summ_call,
                      "session_summarizer.py path must include 'hooks/' directory")

    def test_summarizer_called_with_light_flag(self):
        """session_summarizer must be called with --light for fast non-LLM mode."""
        calls = self._run_main_mocked()
        summ_call = next((c for c in calls if "session_summarizer" in str(c)), None)
        self.assertIsNotNone(summ_call)
        self.assertIn("--light", summ_call,
                      "session_summarizer must be invoked with --light flag")


if __name__ == "__main__":
    unittest.main()
