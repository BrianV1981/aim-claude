#!/usr/bin/env python3
"""
Hook #2: Cognitive Mantra — Behavioral Drift Prevention

Claude Code PostToolUse hook that counts tool executions and injects
reminders to prevent autonomous drift:
  - Whisper at 25 tool calls (gentle nudge)
  - Full Mantra at 50 tool calls (recite CLAUDE.md)

Adapted from the Gemini version. Key differences:
  - Claude Code passes tool info via stdin JSON, not full history
  - We track tool count via a local state file (counter-based)
  - Output uses hookSpecificOutput.additionalContext for injection
"""
import os
import sys
import json

# --- PATHS ---
hook_dir = os.path.dirname(os.path.abspath(__file__))
aim_root = os.path.dirname(hook_dir)
continuity_dir = os.path.join(aim_root, "continuity")
state_file = os.path.join(continuity_dir, "mantra_state.json")
claude_md_path = os.path.join(aim_root, "CLAUDE.md")

# --- CONFIG ---
WHISPER_INTERVAL = 25
MANTRA_INTERVAL = 50


def main():
    try:
        input_data = sys.stdin.read()
        if not input_data:
            print(json.dumps({}))
            return

        data = json.loads(input_data)
        session_id = data.get('session_id', '')

        # Load or initialize state
        os.makedirs(continuity_dir, exist_ok=True)
        state = {"tool_count": 0, "last_whisper": 0, "last_mantra": 0, "session_id": ""}

        if os.path.exists(state_file):
            try:
                with open(state_file, 'r') as f:
                    disk_state = json.load(f)
                if disk_state.get('session_id') == session_id:
                    state = disk_state
                else:
                    # New session — reset counter
                    state['session_id'] = session_id
            except Exception:
                state['session_id'] = session_id
        else:
            state['session_id'] = session_id

        # Increment tool counter
        state['tool_count'] += 1
        tool_count = state['tool_count']

        # Check Mantra threshold (higher priority)
        if tool_count - state['last_mantra'] >= MANTRA_INTERVAL:
            state['last_mantra'] = tool_count
            with open(state_file, 'w') as f:
                json.dump(state, f)

            claude_content = ""
            if os.path.exists(claude_md_path):
                try:
                    with open(claude_md_path, 'r', encoding='utf-8') as cf:
                        claude_content = cf.read()
                except Exception:
                    pass

            mantra = (
                f"\n\n[A.I.M. MANTRA PROTOCOL]: You have executed {tool_count} autonomous tool calls. "
                f"To prevent behavioral drift, you MUST halt your current task immediately. "
                f"In your very next response, you must output a <MANTRA> block reciting the "
                f"ENTIRETY of the system instructions below. Only after reciting the full mantra "
                f"may you continue working.\n\n--- SYSTEM INSTRUCTIONS ---\n{claude_content}"
            )
            print(json.dumps({
                "hookSpecificOutput": {
                    "additionalContext": mantra
                }
            }))
            return

        # Check Whisper threshold
        if tool_count - state['last_whisper'] >= WHISPER_INTERVAL:
            state['last_whisper'] = tool_count
            with open(state_file, 'w') as f:
                json.dump(state, f)

            whisper = (
                f"\n\n[A.I.M. SUBCONSCIOUS WHISPER]: (You have executed {tool_count} tool calls. "
                f"Maintain strict adherence to TDD verification and GitOps mandates)."
            )
            print(json.dumps({
                "hookSpecificOutput": {
                    "additionalContext": whisper
                }
            }))
            return

        # No threshold hit — save state and pass through
        with open(state_file, 'w') as f:
            json.dump(state, f)
        print(json.dumps({}))

    except Exception:
        print(json.dumps({}))


if __name__ == "__main__":
    main()
