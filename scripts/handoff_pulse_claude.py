#!/usr/bin/env python3
"""
handoff_pulse_claude.py — Claude Code-specific handoff pulse generator (Issue #78)

Replaces the Gemini-specific handoff_pulse_generator.py for aim-claude.

Responsibilities:
  1. Find the current session JSONL from ~/.claude/projects/<hash>/
  2. Extract the last 5 user+assistant turns (no LLM — pure mechanical extraction)
  3. Write CURRENT_PULSE.md
  4. Refresh HANDOFF.md from a static template (timestamp only changes)

Anti-cannibalization: if the newest JSONL has < 15 lines (e.g. a fresh wake-up
session), use the previous one so we don't overwrite a full history with a stub.
"""
import glob
import json
import os
import sys
from datetime import datetime

# ---------------------------------------------------------------------------
# Root discovery
# ---------------------------------------------------------------------------

def _find_aim_root():
    for start in [os.path.abspath(os.getcwd()),
                  os.path.dirname(os.path.abspath(__file__))]:
        current = start
        while current != "/":
            if os.path.exists(os.path.join(current, "core", "CONFIG.json")):
                return current
            current = os.path.dirname(current)
    return os.path.dirname(os.path.abspath(__file__))


AIM_ROOT = _find_aim_root()
CONTINUITY_DIR = os.path.join(AIM_ROOT, "continuity")
HANDOFF_PATH = os.path.join(AIM_ROOT, "HANDOFF.md")

# ---------------------------------------------------------------------------
# Static HANDOFF.md template — only the timestamp varies
# ---------------------------------------------------------------------------

HANDOFF_TEMPLATE = """\
# A.I.M. Continuity Handoff

## ⚠️ CRITICAL INSTRUCTION FOR INCOMING AGENT ⚠️
You are waking up in the middle of a continuous operational loop.
To prevent hallucination, you must establish **Epistemic Certainty** regarding
the previous agent's actions before you write any code.

### The Continuity Protocol (The Reincarnation Gameplan)
1. Read `continuity/REINCARNATION_GAMEPLAN.md` — the soul/battle plan written by the previous agent.
2. Read `continuity/CURRENT_PULSE.md` — the last 5 turns of the session (raw, no LLM).
3. Read `continuity/ISSUE_TRACKER.md` — all open and closed tickets.
4. (Optional) Read `continuity/LAST_SESSION_FLIGHT_RECORDER.md` ONLY IF the Gameplan explicitly requires historical context extraction.
5. Do not blindly assume success. Verify state via file reads or tests.

---
**Timestamp:** {timestamp}
"""

# ---------------------------------------------------------------------------
# JSONL discovery
# ---------------------------------------------------------------------------

def find_transcripts():
    """Return all JSONL session transcripts for this project, sorted by mtime ascending."""
    project_hash = "-" + AIM_ROOT.lstrip("/").replace("/", "-")
    proj_dir = os.path.expanduser(f"~/.claude/projects/{project_hash}")
    if not os.path.isdir(proj_dir):
        return []
    files = glob.glob(os.path.join(proj_dir, "*.jsonl"))
    files.sort(key=os.path.getmtime)
    return files


def select_transcript(transcripts):
    """Apply anti-cannibalization check: if newest JSONL has < 15 lines and a
    previous session exists, return the previous one instead."""
    if not transcripts:
        return None
    newest = transcripts[-1]
    if len(transcripts) > 1:
        try:
            with open(newest, "r") as f:
                line_count = sum(1 for _ in f)
            if line_count < 15:
                return transcripts[-2]
        except Exception:
            pass
    return newest

# ---------------------------------------------------------------------------
# Turn extraction
# ---------------------------------------------------------------------------

def extract_last_turns(jsonl_path, n=5):
    """Extract the last n user+assistant turns from a JSONL file.

    Skips: snapshot entries, tool_result blocks, thinking blocks.
    Returns a list of dicts: {role, text, timestamp}
    """
    turns = []
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if obj.get("type") == "snapshot" or obj.get("isSnapshotUpdate"):
                    continue

                msg = obj.get("message", {})
                role = msg.get("role", "")
                if role not in ("user", "assistant"):
                    continue

                content = msg.get("content", "")
                ts = obj.get("timestamp", "")

                text = ""
                if isinstance(content, str):
                    text = content.strip()
                elif isinstance(content, list):
                    parts = []
                    for item in content:
                        if not isinstance(item, dict):
                            continue
                        itype = item.get("type", "")
                        if itype == "text":
                            t = item.get("text", "").strip()
                            if t:
                                parts.append(t)
                        # skip: tool_result, thinking, tool_use, image
                    text = " ".join(parts)

                if text:
                    turns.append({"role": role, "text": text, "timestamp": ts})

    except Exception:
        pass

    return turns[-n:] if len(turns) > n else turns

# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def _atomic_write(path, content):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def write_current_pulse(turns):
    """Write CURRENT_PULSE.md from extracted turns — no LLM."""
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")

    lines = [
        f"---",
        f"date: {date_str}",
        f'time: "{time_str}"',
        f"type: handoff",
        f"---",
        f"",
        f"# A.I.M. Context Pulse: {date_str} {time_str}",
        f"",
        f"## Last {len(turns)} Turn(s)",
        f"",
    ]

    for turn in turns:
        role_label = "USER" if turn["role"] == "user" else "A.I.M."
        ts = turn.get("timestamp", "")
        lines.append(f"### {role_label} ({ts})")
        lines.append(turn["text"])
        lines.append("")
        lines.append("---")
        lines.append("")

    if not turns:
        lines.append("*(No session turns found)*")
        lines.append("")

    lines.append('"I believe I\'ve made my point." — **A.I.M. (Auto-Pulse)**')

    os.makedirs(CONTINUITY_DIR, exist_ok=True)
    _atomic_write(os.path.join(CONTINUITY_DIR, "CURRENT_PULSE.md"), "\n".join(lines))


def write_handoff():
    """Refresh HANDOFF.md from the static template with a current timestamp."""
    content = HANDOFF_TEMPLATE.format(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    _atomic_write(HANDOFF_PATH, content)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    transcripts = find_transcripts()
    transcript = select_transcript(transcripts)

    if transcript:
        turns = extract_last_turns(transcript, n=5)
    else:
        turns = []
        print("[handoff_pulse_claude] No JSONL transcripts found — writing empty pulse.")

    write_current_pulse(turns)
    write_handoff()
    print("[handoff_pulse_claude] CURRENT_PULSE.md and HANDOFF.md refreshed.")


if __name__ == "__main__":
    main()
