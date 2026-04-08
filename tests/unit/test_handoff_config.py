"""
Tests for Configurable Multi-Agent Handoff (#74).

Validates:
1. resolve_target_agent() follows CLI → CONFIG → fallback resolution
2. get_agent_config() returns agent-specific cmd, manifest, wake_up
3. Unknown agent falls back to default with warning
4. DEFAULT_AGENTS registry has claude, gemini, codex entries
"""
import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest

AIM_CLAUDE_ROOT = str(Path(__file__).parent.parent.parent)


def _load_module():
    mod_name = "_test_handoff_74"
    sys.modules.pop(mod_name, None)
    spec = importlib.util.spec_from_file_location(
        mod_name,
        os.path.join(AIM_CLAUDE_ROOT, "src", "handoff_config.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestDefaultAgents:

    def test_has_claude_agent(self):
        mod = _load_module()
        assert "claude" in mod.DEFAULT_AGENTS

    def test_has_gemini_agent(self):
        mod = _load_module()
        assert "gemini" in mod.DEFAULT_AGENTS

    def test_has_codex_agent(self):
        mod = _load_module()
        assert "codex" in mod.DEFAULT_AGENTS

    def test_agent_has_required_keys(self):
        mod = _load_module()
        for name, cfg in mod.DEFAULT_AGENTS.items():
            assert "cmd" in cfg, f"{name} missing 'cmd'"
            assert "manifest" in cfg, f"{name} missing 'manifest'"
            assert "wake_up" in cfg, f"{name} missing 'wake_up'"


class TestResolveTargetAgent:

    def test_cli_arg_takes_priority(self):
        mod = _load_module()
        result = mod.resolve_target_agent(cli_agent="gemini", config_agent="claude")
        assert result == "gemini"

    def test_config_fallback(self):
        mod = _load_module()
        result = mod.resolve_target_agent(cli_agent=None, config_agent="codex")
        assert result == "codex"

    def test_hardcoded_fallback(self):
        mod = _load_module()
        result = mod.resolve_target_agent(cli_agent=None, config_agent=None)
        assert result == "claude"

    def test_empty_string_cli_uses_config(self):
        mod = _load_module()
        result = mod.resolve_target_agent(cli_agent="", config_agent="gemini")
        assert result == "gemini"


class TestGetAgentConfig:

    def test_known_agent_returns_config(self):
        mod = _load_module()
        cfg = mod.get_agent_config("claude")
        assert cfg["cmd"] == "claude"
        assert "CLAUDE.md" in cfg["manifest"]

    def test_unknown_agent_returns_fallback(self):
        mod = _load_module()
        cfg = mod.get_agent_config("nonexistent-agent")
        # Should return claude (default) config
        assert cfg["cmd"] == "claude"

    def test_custom_agents_override(self):
        mod = _load_module()
        custom = {"custom-bot": {"cmd": "mybot", "manifest": "BOT.md", "wake_up": "hello"}}
        cfg = mod.get_agent_config("custom-bot", custom_agents=custom)
        assert cfg["cmd"] == "mybot"
