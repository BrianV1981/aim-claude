#!/usr/bin/env python3
"""
Hook #4: Context Injector — JIT Session Onboarding

Claude Code PreToolUse hook that fires on the FIRST tool call of a session
and injects continuity context:
  - ANCHOR.md (immutable truths)
  - CORE_MEMORY.md (writable RAM)
  - CURRENT_PULSE.md (project momentum)
  - FALLBACK_TAIL.md (last 10 turns from previous session)

Adapted from the Gemini version. Key differences:
  - Claude Code uses PreToolUse (fires before the first tool executes)
  - We track "already injected" via a state file keyed by session_id
  - Output uses hookSpecificOutput.additionalContext
"""
import os
import sys
import json

# --- PATHS ---
hook_dir = os.path.dirname(os.path.abspath(__file__))
aim_root = os.path.dirname(hook_dir)
continuity_dir = os.path.join(aim_root, "continuity")
core_dir = os.path.join(aim_root, "core")
state_file = os.path.join(continuity_dir, "injector_state.json")


def read_file_safe(path):
    """Read a file, returning None if it doesn't exist or fails."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        return content if content else None
    except Exception:
        return None


def main():
    try:
        input_data = sys.stdin.read()
        if not input_data:
            print(json.dumps({}))
            return

        data = json.loads(input_data)
        session_id = data.get('session_id', '')

        os.makedirs(continuity_dir, exist_ok=True)

        # Check if we've already injected for this session
        state = {}
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r') as f:
                    state = json.load(f)
            except Exception:
                pass

        if state.get('session_id') == session_id and state.get('injected', False):
            # Already injected this session — pass through
            print(json.dumps({}))
            return

        # Mark as injected
        state = {'session_id': session_id, 'injected': True}
        with open(state_file, 'w') as f:
            json.dump(state, f)

        # Gather context fragments
        injection_parts = []

        anchor = read_file_safe(os.path.join(core_dir, "ANCHOR.md"))
        if anchor:
            injection_parts.append(f"## THE MEMORY ANCHOR (IMMUTABLE TRUTHS)\n{anchor}")

        core_mem = read_file_safe(os.path.join(continuity_dir, "CORE_MEMORY.md"))
        if core_mem:
            injection_parts.append(f"## CORE MEMORY (WRITABLE RAM)\n{core_mem}")

        pulse = read_file_safe(os.path.join(continuity_dir, "CURRENT_PULSE.md"))
        if pulse:
            injection_parts.append(f"## PROJECT MOMENTUM (LATEST PULSE)\n{pulse}")

        tail = read_file_safe(os.path.join(continuity_dir, "FALLBACK_TAIL.md"))
        if tail:
            injection_parts.append(f"## IMMEDIATE CONTEXT (LAST 10 TURNS)\n{tail}")

        if not injection_parts:
            print(json.dumps({}))
            return

        final_injection = "\n--- [A.I.M. SESSION ONBOARDING] ---\n"
        final_injection += "\n\n---\n\n".join(injection_parts)
        final_injection += "\n\n--- [END ONBOARDING] ---\n"

        print(json.dumps({
            "hookSpecificOutput": {
                "additionalContext": final_injection
            }
        }))

    except Exception:
        print(json.dumps({}))


if __name__ == "__main__":
    main()
