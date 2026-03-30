#!/usr/bin/env python3
"""
Hook #3: Failsafe Context Snapshot — Rolling Backup & Tail

Claude Code PostToolUse hook that maintains:
  1. A rolling INTERIM_BACKUP of the session JSONL
  2. A FALLBACK_TAIL.md with the last 10 conversational turns (human-readable)
  3. Significance detection — triggers Tier 1 summarizer on high-impact changes

Adapted from the Gemini version. Key differences:
  - Claude Code provides transcript_path pointing to the session JSONL
  - We read the JSONL directly instead of relying on stdin history
  - Tool calls are content blocks with type "tool_use", not separate toolCalls arrays
"""
import os
import sys
import json
import shutil
import subprocess
import re

# --- PATHS ---
hook_dir = os.path.dirname(os.path.abspath(__file__))
aim_root = os.path.dirname(hook_dir)
continuity_dir = os.path.join(aim_root, "continuity")
backup_path = os.path.join(continuity_dir, "INTERIM_BACKUP.jsonl")
tail_path = os.path.join(continuity_dir, "FALLBACK_TAIL.md")
state_file = os.path.join(aim_root, "archive", "scrivener_state.json")

HIGH_IMPACT_TOOLS = ["Edit", "Write", "Bash", "NotebookEdit"]


def read_recent_turns(transcript_path, n=10):
    """Read the last N conversational turns from a Claude Code JSONL transcript."""
    turns = []
    try:
        with open(transcript_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get('type')
                if msg_type in ('file-history-snapshot',):
                    continue
                turns.append(msg)
    except Exception:
        return []
    return turns[-n:]


def build_tail_markdown(turns):
    """Convert recent turns into a human-readable Markdown tail."""
    md = "# A.I.M. FALLBACK CONTEXT TAIL\n\n*Automatic zero-token snapshot of the last 10 turns.*\n\n"

    for msg in turns:
        msg_type = msg.get('type', 'unknown')
        inner = msg.get('message', {})
        role = inner.get('role', msg_type).upper()
        ts = msg.get('timestamp', '')
        content_blocks = inner.get('content', [])

        if role == 'USER':
            md += f"### USER ({ts})\n"
            if isinstance(content_blocks, str):
                text = content_blocks[:500]
            elif isinstance(content_blocks, list):
                texts = [b.get('text', '') for b in content_blocks if isinstance(b, dict) and b.get('type') == 'text']
                text = ' '.join(texts)[:500]
            else:
                text = str(content_blocks)[:500]
            if text:
                md += f"{text}\n\n"

        elif role == 'ASSISTANT':
            md += f"### A.I.M. ({ts})\n"
            if isinstance(content_blocks, list):
                for block in content_blocks:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get('type')
                    if btype == 'text':
                        text = block.get('text', '')[:500]
                        if text:
                            md += f"{text}\n\n"
                    elif btype == 'tool_use':
                        tool = block.get('name', 'unknown')
                        intent = str(block.get('input', {}))[:200]
                        md += f"**Tool Call:** `{tool}`\n```\n{intent}\n```\n\n"

        md += "---\n\n"
    return md


def check_significance(tool_name, transcript_path, session_id):
    """Returns True if the recent activity warrants a Tier 1 summarizer trigger."""
    if tool_name in HIGH_IMPACT_TOOLS:
        return True

    # Check if 5+ new turns since last narration
    if not os.path.exists(state_file):
        return False

    try:
        with open(state_file, 'r') as f:
            state = json.load(f)
        last_count = state.get(session_id, 0)
        if isinstance(last_count, dict):
            last_count = last_count.get('last_narrated_turn', 0)

        # Count current turns
        current_count = 0
        with open(transcript_path, 'r') as f:
            for line in f:
                if line.strip():
                    current_count += 1

        return (current_count - last_count) >= 5
    except Exception:
        return False


def main():
    try:
        input_data = sys.stdin.read()
        if not input_data:
            print(json.dumps({}))
            return

        data = json.loads(input_data)
        transcript_path = data.get('transcript_path', '')
        session_id = data.get('session_id', '')
        tool_name = data.get('tool_name', '')

        os.makedirs(continuity_dir, exist_ok=True)

        # 1. Rolling backup of the session JSONL
        if transcript_path and os.path.exists(transcript_path):
            try:
                shutil.copy2(transcript_path, backup_path)
            except Exception:
                pass

            # 2. Build and write the Fallback Tail
            try:
                turns = read_recent_turns(transcript_path, n=10)
                if turns:
                    tail_md = build_tail_markdown(turns)
                    with open(tail_path, 'w') as f:
                        f.write(tail_md)
            except Exception:
                pass

        # 3. Significance filter — placeholder for Tier 1 summarizer trigger
        # (Tier 1 summarizer will be implemented in Phase 4)
        # if transcript_path and check_significance(tool_name, transcript_path, session_id):
        #     trigger_tier1_summarizer()

        print(json.dumps({}))

    except Exception:
        print(json.dumps({}))


if __name__ == "__main__":
    main()
