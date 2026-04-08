"""
Tests for Strategic Synthesis & Morning Reports (#105).

Validates:
1. gather_report_data() aggregates project state into a structured dict
2. format_report() renders a human-readable markdown report
3. Handles missing data sources gracefully
"""
import importlib.util
import os
import sys
import types
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

AIM_CLAUDE_ROOT = str(Path(__file__).parent.parent.parent)


def _load_module():
    mod_name = "_test_morning_105"
    sys.modules.pop(mod_name, None)
    spec = importlib.util.spec_from_file_location(
        mod_name,
        os.path.join(AIM_CLAUDE_ROOT, "src", "morning_report.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestGatherReportData:

    def test_returns_dict_with_required_keys(self, tmp_path):
        mod = _load_module()
        data = mod.gather_report_data(str(tmp_path))
        assert "git_log" in data
        assert "unread_mail" in data
        assert "open_issues" in data
        assert "timestamp" in data

    def test_reads_unread_mail(self, tmp_path):
        mod = _load_module()
        cont = tmp_path / "continuity"
        cont.mkdir()
        (cont / "UNREAD_MAIL.md").write_text("## Mail\n- Task from aim-codex")
        data = mod.gather_report_data(str(tmp_path))
        assert "aim-codex" in data["unread_mail"]

    def test_missing_mail_returns_empty(self, tmp_path):
        mod = _load_module()
        data = mod.gather_report_data(str(tmp_path))
        assert data["unread_mail"] == ""

    def test_git_log_captured(self, tmp_path):
        """In a git repo, git_log should be non-empty."""
        mod = _load_module()
        # Use the real aim-claude root which is a git repo
        data = mod.gather_report_data(AIM_CLAUDE_ROOT)
        assert len(data["git_log"]) > 0


class TestFormatReport:

    def test_contains_header(self):
        mod = _load_module()
        data = {
            "git_log": "abc123 Fix bug",
            "unread_mail": "",
            "open_issues": "3 open issues",
            "timestamp": "2026-04-08T12:00:00",
        }
        report = mod.format_report(data)
        assert "Morning Report" in report or "Strategic Briefing" in report

    def test_includes_git_activity(self):
        mod = _load_module()
        data = {
            "git_log": "abc123 Merged PR #100",
            "unread_mail": "",
            "open_issues": "",
            "timestamp": "2026-04-08T12:00:00",
        }
        report = mod.format_report(data)
        assert "abc123" in report

    def test_includes_mail_section(self):
        mod = _load_module()
        data = {
            "git_log": "",
            "unread_mail": "MANDATE from aim-codex",
            "open_issues": "",
            "timestamp": "2026-04-08T12:00:00",
        }
        report = mod.format_report(data)
        assert "MANDATE" in report

    def test_empty_data_still_renders(self):
        mod = _load_module()
        data = {
            "git_log": "",
            "unread_mail": "",
            "open_issues": "",
            "timestamp": "2026-04-08T12:00:00",
        }
        report = mod.format_report(data)
        assert len(report) > 0
