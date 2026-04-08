#!/usr/bin/env python3
"""
Configurable multi-agent handoff system.
Resolves which agent to target during /reincarnation based on
CLI args, CONFIG.json, or hardcoded defaults.
"""

DEFAULT_FALLBACK_AGENT = "claude"

DEFAULT_AGENTS = {
    "claude": {
        "cmd": "claude",
        "manifest": "CLAUDE.md",
        "wake_up": "Wake up. MANDATE: 1. Read CLAUDE.md and acknowledge your core constraints. 2. Read HANDOFF.md. 3. You must read continuity/REINCARNATION_GAMEPLAN.md, continuity/CURRENT_PULSE.md, and ISSUE_TRACKER.md before taking any action or responding.",
    },
    "gemini": {
        "cmd": "gemini",
        "manifest": "GEMINI.md",
        "wake_up": "Wake up. MANDATE: 1. Read GEMINI.md and acknowledge your core constraints. 2. Read HANDOFF.md. 3. You must read continuity/REINCARNATION_GAMEPLAN.md, continuity/CURRENT_PULSE.md, and ISSUE_TRACKER.md before taking any action or responding.",
    },
    "codex": {
        "cmd": "codex",
        "manifest": "CODEX.md",
        "wake_up": "Wake up. MANDATE: 1. Read CODEX.md and acknowledge your core constraints. 2. Read HANDOFF.md. 3. You must read continuity/REINCARNATION_GAMEPLAN.md, continuity/CURRENT_PULSE.md, and ISSUE_TRACKER.md before taking any action or responding.",
    },
}


def resolve_target_agent(cli_agent=None, config_agent=None):
    """Resolve target agent: CLI arg → CONFIG → hardcoded fallback."""
    if cli_agent:
        return cli_agent
    if config_agent:
        return config_agent
    return DEFAULT_FALLBACK_AGENT


def get_agent_config(agent_name, custom_agents=None):
    """Return config dict for a named agent. Falls back to default if unknown."""
    agents = custom_agents or DEFAULT_AGENTS
    if agent_name in agents:
        return agents[agent_name]
    return DEFAULT_AGENTS.get(DEFAULT_FALLBACK_AGENT, DEFAULT_AGENTS["claude"])
