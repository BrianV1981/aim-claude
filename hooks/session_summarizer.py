#!/usr/bin/env python3
"""
Session Summarizer — A.I.M. System 2 Tier 1 (Claude Code Migration)

Reads Claude Code JSONL session transcripts, extracts architectural signal,
and uses an LLM to produce hourly narrative reports in memory/hourly/.
These reports feed the System 2 Memory Refinement Cascade (Tier 2+).

System context:
  System 1 (session history): history_scribe.py + extract_signal.py → archive/history/
  System 2 (refinement cascade): THIS SCRIPT → memory_proposer.py → daily_refiner.py → ...
  System 3 (reincarnate black box): handoff_pulse_generator.py + failsafe_context_snapshot.py
"""
import sys
import json
import os
import glob
import subprocess
from datetime import datetime

# --- DYNAMIC ROOT DISCOVERY ---
def find_aim_root():
    current = os.path.abspath(os.getcwd())
    while current != '/':
        if os.path.exists(os.path.join(current, "core", "CONFIG.json")):
            return current
        current = os.path.dirname(current)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

AIM_ROOT = find_aim_root()
sys.path.append(os.path.join(AIM_ROOT, "src"))

try:
    from reasoning_utils import generate_reasoning
except ImportError:
    generate_reasoning = None

try:
    from memory_utils import should_run_tier, mark_tier_run
except ImportError:
    should_run_tier = lambda x, y: True
    mark_tier_run = lambda x: None

CONFIG_PATH = os.path.join(AIM_ROOT, "core/CONFIG.json")
MEMORY_PATH = os.path.join(AIM_ROOT, "core/MEMORY.md")

if not os.path.exists(CONFIG_PATH):
    sys.exit(0)

with open(CONFIG_PATH, 'r') as f:
    CONFIG = json.load(f)

HOURLY_DIR = os.path.join(AIM_ROOT, "memory/hourly")
STATE_FILE = os.path.join(AIM_ROOT, "archive/scrivener_state.json")

# --- NARRATOR PROMPT ---
NARRATOR_SYSTEM = """You are a Memory Proposer (System 2, Tier 1). Analyze a delta of project activity and propose updates for Durable Memory (MEMORY.md).

### INPUTS
1. **Signal Skeleton:** A noise-reduced transcript of recent activity (tool results and thinking blocks excluded).
2. **Current Memory:** The existing state of durable memory.

### CONSTRAINTS
- Output a structured report identifying what to ADD, REMOVE, or CONTRADICT.
- Prioritize DELETION of stale facts over simple concatenation.
- Identify contradictory instructions or logic shifts.

### OUTPUT SCHEMA
1. **Rationale:** Brief summary of the activity delta.
2. **Proposed Adds:** New facts, milestones, or rules to record.
3. **Proposed Removes:** Outdated or redundant facts to purge.
4. **Contradictions:** Existing rules in MEMORY.md that were violated or superseded.
"""


def _project_dir():
    """Derive the Claude Code project directory from AIM_ROOT.

    Claude Code uses the convention: ~/.claude/projects/<hash>
    where <hash> is '-' + AIM_ROOT with leading '/' stripped and all '/' replaced by '-'.
    e.g. /home/kingb/aim-claude → -home-kingb-aim-claude
    """
    project_hash = '-' + AIM_ROOT.lstrip('/').replace('/', '-')
    return os.path.expanduser(f"~/.claude/projects/{project_hash}")


def find_transcripts():
    """Return all JSONL session transcripts for this project, sorted by mtime ascending."""
    proj_dir = _project_dir()
    if not os.path.isdir(proj_dir):
        return []
    files = glob.glob(os.path.join(proj_dir, "*.jsonl"))
    files.sort(key=os.path.getmtime)
    return files


def get_state(session_id):
    """Return last processed line index for this session (0 if none)."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
            val = state.get(session_id, {})
            if isinstance(val, dict):
                return val.get('last_line_processed', 0)
        except Exception:
            pass
    return 0


def update_state(session_id, last_line):
    """Persist last processed line index for this session."""
    state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
        except Exception:
            pass
    current = state.get(session_id, {})
    current['last_line_processed'] = last_line
    state[session_id] = current
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def extract_signal_jsonl(jsonl_path, from_line=0):
    """Extract architectural signal from a Claude Code JSONL transcript.

    Args:
        jsonl_path: Path to the .jsonl session file.
        from_line: Line index to start reading from (for delta processing).

    Returns:
        Tuple of (session_id, signal_list, total_line_count).
        signal_list contains dicts with 'role', 'timestamp', 'text', 'actions'.
        Skips: tool_result blocks, thinking blocks, snapshot entries.
    """
    signal = []
    session_id = None
    line_count = 0

    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for raw_line in f:
            raw_line = raw_line.strip()
            if not raw_line:
                line_count += 1
                continue
            try:
                obj = json.loads(raw_line)
            except json.JSONDecodeError:
                line_count += 1
                continue

            # Skip snapshot/metadata entries
            if obj.get('type') == 'snapshot' or obj.get('isSnapshotUpdate'):
                line_count += 1
                continue

            # Extract session_id from any message that carries it
            if not session_id and 'sessionId' in obj:
                session_id = obj['sessionId']

            # Only process lines at or after from_line
            if line_count >= from_line and 'message' in obj:
                msg = obj['message']
                role = msg.get('role', '')
                content = msg.get('content', '')
                ts = obj.get('timestamp', '')

                fragment = {'role': role, 'timestamp': ts}

                if isinstance(content, str):
                    if content.strip():
                        fragment['text'] = content.strip()
                        signal.append(fragment)
                elif isinstance(content, list):
                    texts = []
                    actions = []
                    for item in content:
                        if not isinstance(item, dict):
                            continue
                        itype = item.get('type', '')
                        if itype == 'text':
                            t = item.get('text', '').strip()
                            if t:
                                texts.append(t)
                        elif itype == 'tool_use':
                            name = item.get('name', 'unknown')
                            intent = str(item.get('input', {}))[:200]
                            actions.append({'tool': name, 'intent': intent})
                        # Skip: tool_result, thinking, image

                    if texts:
                        fragment['text'] = ' '.join(texts)
                    if actions:
                        fragment['actions'] = actions
                    if texts or actions:
                        signal.append(fragment)

            line_count += 1

    return session_id, signal, line_count


def signal_to_markdown(signal, session_id):
    """Convert signal list to structured markdown (no LLM — zero cost)."""
    sid_short = session_id[:8] if session_id else 'unknown'
    lines = [f"## Session: `{sid_short}`\n"]
    for turn in signal:
        role = turn.get('role', 'unknown').upper()
        ts = turn.get('timestamp', '')
        text = turn.get('text', '')
        actions = turn.get('actions', [])

        if role == 'USER':
            lines.append(f"### USER ({ts})")
            if text:
                lines.append(text)
        elif role == 'ASSISTANT':
            lines.append(f"### A.I.M. ({ts})")
            if text:
                lines.append(text)
            if actions:
                lines.append("**Tools:**")
                for a in actions:
                    lines.append(f"- `{a['tool']}`: {a['intent']}")
        lines.append("---")
    return "\n".join(lines)


def process_transcript(jsonl_path, is_light_mode=False):
    """Process a JSONL transcript and append to today's hourly summary.

    Returns True if the hourly file was updated, False otherwise.
    """
    try:
        # Read session_id from first matching line
        session_id = None
        with open(jsonl_path, 'r', encoding='utf-8') as f:
            for raw_line in f:
                try:
                    obj = json.loads(raw_line.strip())
                    if 'sessionId' in obj:
                        session_id = obj['sessionId']
                        break
                except Exception:
                    continue

        if not session_id:
            session_id = os.path.splitext(os.path.basename(jsonl_path))[0]

        last_line = get_state(session_id)
        _, signal, total_lines = extract_signal_jsonl(jsonl_path, from_line=last_line)

        if not signal:
            return False

        now = datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
        hourly_file = os.path.join(HOURLY_DIR, now.strftime("%Y-%m-%d_%H") + ".md")
        os.makedirs(HOURLY_DIR, exist_ok=True)

        if is_light_mode or not generate_reasoning:
            if not is_light_mode:
                sys.stderr.write("[WARN] generate_reasoning unavailable — using light mode\n")
            md = signal_to_markdown(signal, session_id)
            with open(hourly_file, 'a', encoding='utf-8') as f:
                f.write(f"\n\n## Surgical Delta (Light): {timestamp_str}\n")
                f.write(f"Session: `{session_id[:8]}` | New turns: {len(signal)}\n\n")
                f.write(md)
                f.write("\n---\n")
            update_state(session_id, total_lines)
            return True

        # LLM narrative mode
        memory_content = ""
        if os.path.exists(MEMORY_PATH):
            try:
                with open(MEMORY_PATH, 'r') as f:
                    memory_content = f.read()
            except Exception:
                pass

        skeleton_str = json.dumps(signal, indent=2)
        prompt = (
            f"### SIGNAL SKELETON\n{skeleton_str}\n\n"
            f"### CURRENT MEMORY\n{memory_content}"
        )

        narrative = generate_reasoning(prompt, system_instruction=NARRATOR_SYSTEM, brain_type="tier1")

        if not narrative or "[ERROR: CAPACITY_LOCKOUT]" in narrative:
            return False

        with open(hourly_file, 'a', encoding='utf-8') as f:
            f.write(f"\n\n## Surgical Delta: {timestamp_str}\n")
            f.write(f"Session: `{session_id[:8]}` | New turns: `{len(signal)}`\n\n")
            f.write(narrative)
            f.write("\n---\n")

        update_state(session_id, total_lines)
        mark_tier_run("tier1")
        return True

    except Exception as e:
        sys.stderr.write(f"[SESSION_SUMMARIZER FATAL] {e}\n")
        return False


def main(args):
    is_light_mode = "--light" in args

    interval = CONFIG.get('memory_pipeline', {}).get('intervals', {}).get('tier1', 1)
    if not should_run_tier("tier1", interval):
        print(json.dumps({"decision": "skip", "reason": "interval_not_met"}))
        return

    transcripts = find_transcripts()
    if not transcripts:
        print(json.dumps({"decision": "proceed", "updated": 0, "reason": "no_transcripts"}))
        return

    # Process only the most recently modified transcript (incremental delta)
    latest = max(transcripts, key=os.path.getmtime)
    updated = 1 if process_transcript(latest, is_light_mode) else 0

    # Trigger history_scribe (System 1) for full session mirroring
    try:
        subprocess.run(
            [sys.executable, os.path.join(AIM_ROOT, "src", "history_scribe.py")],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30
        )
    except Exception:
        pass

    print(json.dumps({"decision": "proceed", "updated": updated}))


if __name__ == "__main__":
    main(sys.argv[1:])
