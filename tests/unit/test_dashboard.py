"""
Tests for Sovereignty Dashboard (#102).

Validates:
1. gather_dashboard_data() collects system metrics
2. format_dashboard() renders a readable terminal output
3. Handles missing data sources gracefully
"""
import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

AIM_CLAUDE_ROOT = str(Path(__file__).parent.parent.parent)


def _load_module():
    mod_name = "_test_dashboard_102"
    sys.modules.pop(mod_name, None)
    spec = importlib.util.spec_from_file_location(
        mod_name,
        os.path.join(AIM_CLAUDE_ROOT, "src", "dashboard.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestGatherDashboardData:

    def test_returns_required_keys(self, tmp_path):
        mod = _load_module()
        data = mod.gather_dashboard_data(str(tmp_path))
        assert "engram_stats" in data
        assert "mail_count" in data
        assert "git_summary" in data
        assert "continuity_files" in data

    def test_counts_continuity_files(self, tmp_path):
        mod = _load_module()
        cont = tmp_path / "continuity"
        cont.mkdir()
        (cont / "HANDOFF.md").write_text("test")
        (cont / "PULSE.md").write_text("test")
        data = mod.gather_dashboard_data(str(tmp_path))
        assert data["continuity_files"] == 2

    def test_counts_unread_mail(self, tmp_path):
        mod = _load_module()
        cont = tmp_path / "continuity"
        cont.mkdir()
        (cont / "UNREAD_MAIL.md").write_text("## Mail\n- msg1\n- msg2\n- msg3")
        data = mod.gather_dashboard_data(str(tmp_path))
        assert data["mail_count"] == 3

    def test_missing_dirs_returns_zeros(self, tmp_path):
        mod = _load_module()
        data = mod.gather_dashboard_data(str(tmp_path))
        assert data["mail_count"] == 0
        assert data["continuity_files"] == 0


class TestFormatDashboard:

    def test_contains_header(self):
        mod = _load_module()
        data = {
            "engram_stats": {"databases": 0, "total_size_mb": 0},
            "mail_count": 0,
            "git_summary": "abc123 Latest commit",
            "continuity_files": 3,
        }
        output = mod.format_dashboard(data)
        assert "Dashboard" in output or "STATUS" in output

    def test_includes_git_info(self):
        mod = _load_module()
        data = {
            "engram_stats": {"databases": 0, "total_size_mb": 0},
            "mail_count": 2,
            "git_summary": "def456 Merged PR",
            "continuity_files": 1,
        }
        output = mod.format_dashboard(data)
        assert "def456" in output

    def test_shows_mail_count(self):
        mod = _load_module()
        data = {
            "engram_stats": {"databases": 0, "total_size_mb": 0},
            "mail_count": 5,
            "git_summary": "",
            "continuity_files": 0,
        }
        output = mod.format_dashboard(data)
        assert "5" in output
