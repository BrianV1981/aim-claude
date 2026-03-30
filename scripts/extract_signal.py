#!/usr/bin/env python3
"""
extract_signal.py — Claude Code Session Signal Extractor

Adapted from the Gemini version for Claude Code's JSONL session format.

Gemini stored sessions as single JSON files with a messages[] array.
Claude Code stores sessions as JSONL files (one JSON object per line)
at: ~/.claude/projects/<project-path>/<session-id>.jsonl

Each line is a message object with fields:
  - type: "user" | "assistant" | "tool_result" | "file-history-snapshot"
  - message.role: "user" | "assistant"
  - message.content: list of content blocks (text, thinking, tool_use, tool_result)
  - timestamp: ISO 8601 string
  - sessionId: UUID
  - uuid: per-message UUID
"""
import json
import sys
import os
import glob


def find_session_files(project_path=None):
    """
    Discovers all Claude Code session JSONL files.
    Default search path: ~/.claude/projects/
    """
    if project_path:
        pattern = os.path.join(project_path, "*.jsonl")
    else:
        base = os.path.expanduser("~/.claude/projects")
        pattern = os.path.join(base, "**", "*.jsonl")
    return sorted(glob.glob(pattern, recursive=True))


def extract_signal(jsonl_path):
    """
    Surgically extracts architectural signal from a Claude Code session JSONL.
    Removes raw tool outputs while keeping Intent, Thoughts, and Actions.
    """
    try:
        signal = []

        with open(jsonl_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get('type')
                timestamp = msg.get('timestamp', 'Unknown')
                inner = msg.get('message', {})
                role = inner.get('role', msg_type)
                content_blocks = inner.get('content', [])

                # Skip non-conversation entries
                if msg_type in ('file-history-snapshot', 'tool_result'):
                    continue

                fragment = {"role": role, "timestamp": timestamp}

                if role == 'user':
                    # User content can be a string or list of content blocks
                    if isinstance(content_blocks, str):
                        fragment['text'] = content_blocks
                    elif isinstance(content_blocks, list):
                        texts = []
                        for block in content_blocks:
                            if isinstance(block, dict) and block.get('type') == 'text':
                                texts.append(block.get('text', ''))
                            elif isinstance(block, str):
                                texts.append(block)
                        fragment['text'] = ' '.join(texts)
                    else:
                        fragment['text'] = str(content_blocks)
                    signal.append(fragment)

                elif role == 'assistant':
                    if not isinstance(content_blocks, list):
                        continue

                    texts = []
                    thoughts = []
                    actions = []

                    for block in content_blocks:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get('type')

                        if btype == 'text':
                            texts.append(block.get('text', ''))
                        elif btype == 'thinking':
                            thought = block.get('thinking', '')
                            if thought:
                                thoughts.append(thought[:500])
                        elif btype == 'tool_use':
                            tool_name = block.get('name', 'unknown')
                            tool_input = block.get('input', {})
                            # Capture intent, not full output
                            intent = str(tool_input)[:200]
                            actions.append({"tool": tool_name, "intent": intent})

                    if texts or thoughts or actions:
                        fragment['text'] = ' '.join(texts)
                        if thoughts:
                            fragment['thoughts'] = thoughts
                        if actions:
                            fragment['actions'] = actions
                        signal.append(fragment)

        return signal
    except Exception as e:
        return f"Extraction Error: {e}"


def skeleton_to_markdown(skeleton, session_id):
    """
    Converts a JSON signal skeleton into Obsidian-native Markdown.
    Zero API cost.
    """
    md = f"---\nSession: {session_id}\nType: Raw Backup\n---\n\n# A.I.M. Signal Skeleton\n\n"
    for turn in skeleton:
        role = turn.get('role', 'unknown').upper()
        text = turn.get('text', '').strip()
        ts = turn.get('timestamp', '')

        if role == 'USER':
            md += f"## USER ({ts})\n"
            if text:
                md += f"{text}\n\n"
        elif role == 'ASSISTANT':
            md += f"## A.I.M. ({ts})\n"
            thoughts = turn.get('thoughts', [])
            if thoughts:
                md += "> **Internal Monologue:**\n"
                for thought in thoughts:
                    if isinstance(thought, str):
                        md += f"> * {thought[:200]}\n"
                md += "\n"

            if text:
                md += f"{text}\n\n"

            actions = turn.get('actions', [])
            if actions:
                md += "**Tools Executed:**\n"
                for action in actions:
                    tool = action.get('tool', 'unknown')
                    intent = action.get('intent', '')
                    md += f"- `{tool}`: {intent}\n"
                md += "\n"

        md += "---\n\n"
    return md


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 extract_signal.py <path_to_jsonl> [--markdown]")
        print("\nExamples:")
        print("  python3 extract_signal.py ~/.claude/projects/-home-kingb-aim-claude/<session>.jsonl")
        print("  python3 extract_signal.py --list  # List all discovered session files")
        sys.exit(1)

    if sys.argv[1] == '--list':
        files = find_session_files()
        for f in files:
            size = os.path.getsize(f)
            print(f"  {f}  ({size:,} bytes)")
        sys.exit(0)

    result = extract_signal(sys.argv[1])

    if '--markdown' in sys.argv:
        session_id = os.path.basename(sys.argv[1]).replace('.jsonl', '')
        print(skeleton_to_markdown(result, session_id))
    else:
        print(json.dumps(result, indent=2))
