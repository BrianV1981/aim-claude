#!/usr/bin/env python3
"""
Single-Shot Memory Compiler — A.I.M. (Claude Code Edition)

Replaces the deprecated 5-Tier Waterfall Memory Pipeline.
Reads a session transcript (Claude Code JSONL or pre-cleaned MD),
feeds it alongside MEMORY.md and CLAUDE.md to an LLM, and
surgically rewrites both files in a single pass.

Triggered by the /reincarnate pipeline (aim_reincarnate.py).

Architecture origin: aim #241 (Epic Phase 1: Single-Shot Compiler).
"""
import sys
import json
import os
import glob
import re
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

CONFIG_PATH = os.path.join(AIM_ROOT, "core/CONFIG.json")
MEMORY_PATH = os.path.join(AIM_ROOT, "core/MEMORY.md")
CLAUDE_PATH = os.path.join(AIM_ROOT, "CLAUDE.md")

if not os.path.exists(CONFIG_PATH):
    sys.exit(0)

with open(CONFIG_PATH, 'r') as f:
    CONFIG = json.load(f)

# --- SINGLE-SHOT COMPILER PROMPT ---
COMPILER_SYSTEM = """You are the Sovereign Memory Compiler. Your goal is to analyze a session transcript and immediately update the project's permanent memory and rule files.

### INPUTS
1. **Session Transcript:** A noise-reduced record of recent activity.
2. **Current `core/MEMORY.md`:** The existing state of durable memory.
3. **Current `CLAUDE.md`:** The existing absolute rules and agentic guardrails.

### CONSTRAINTS
- **Recency Bias Guard:** Do NOT add temporary debugging steps or rabbit-holes. ONLY update `core/MEMORY.md` if a permanent architectural state changed.
- **Rule of Law Guard:** ONLY update `CLAUDE.md` if a catastrophic workflow failure occurred that requires a new absolute physical constraint. Do NOT add stylistic preferences.
- **Compression:** If you add a new fact, attempt to consolidate or remove an outdated one.
- **Timestamping:** Any NEW architectural facts or rules you add MUST include a timestamp in the format `(Added: YYYY-MM-DD)` at the end of the bullet point or sentence.

### OUTPUT SCHEMA
You MUST output the entirety of both files. Do NOT use omission placeholders like "..." or "rest of code". Rewriting the entire file is required so that new information is woven elegantly into the correct existing sections (rather than just appended to the bottom).
Your final output MUST follow this exact structure:

### core/MEMORY.md
```markdown
[FULL UPDATED CONTENT OF core/MEMORY.md]
```

### CLAUDE.md
```markdown
[FULL UPDATED CONTENT OF CLAUDE.md]
```
"""

def extract_file_content(full_text, filename):
    """Extracts the markdown block following a specific filename header."""
    pattern = rf"### {re.escape(filename)}\s*```(?:markdown|md)?\n(.*?)```"
    match = re.search(pattern, full_text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None

def atomic_write(file_path, content):
    temp_path = f"{file_path}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(content + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, file_path)
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise e

def process_transcript(md_path):
    """Feed a transcript + current MEMORY.md + CLAUDE.md to the LLM compiler.

    The LLM returns updated versions of both files, which are atomically written.
    Returns True on success, False on failure.
    """
    if not generate_reasoning:
        print("[ERROR] reasoning_utils not available.")
        return False

    try:
        with open(md_path, 'r', encoding='utf-8') as f:
            transcript = f.read()

        memory_content = ""
        if os.path.exists(MEMORY_PATH):
            with open(MEMORY_PATH, 'r', encoding='utf-8') as f:
                memory_content = f.read()

        claude_content = ""
        if os.path.exists(CLAUDE_PATH):
            with open(CLAUDE_PATH, 'r', encoding='utf-8') as f:
                claude_content = f.read()

        combined_input = (
            f"### SESSION TRANSCRIPT\n{transcript}\n\n"
            f"### CURRENT core/MEMORY.md\n{memory_content}\n\n"
            f"### CURRENT CLAUDE.md\n{claude_content}"
        )

        print(f"[COMPILER] Distilling Single-Shot Memory from: {os.path.basename(md_path)}")
        compiled_output = generate_reasoning(
            combined_input,
            system_instruction=COMPILER_SYSTEM,
            brain_type="tier1",
        )

        if not compiled_output or compiled_output.startswith("Error:") or " API Error:" in compiled_output or "Ollama Error" in compiled_output:
            print(f"[ERROR] LLM generation failed: {compiled_output}")
            return False

        new_memory = extract_file_content(compiled_output, "core/MEMORY.md")
        new_claude = extract_file_content(compiled_output, "CLAUDE.md")

        if not new_memory and not new_claude:
            print("[ERROR] LLM failed to format the output correctly. No Markdown blocks extracted.")
            return False

        if new_memory and len(new_memory) > 50:
            atomic_write(MEMORY_PATH, new_memory)
            print("[SUCCESS] MEMORY.md securely updated.")

        if new_claude and len(new_claude) > 50:
            atomic_write(CLAUDE_PATH, new_claude)
            print("[SUCCESS] CLAUDE.md securely updated.")

        return True

    except Exception as e:
        print(f"[FATAL] Single-Shot Compiler Error: {e}")
        return False

def main(args):
    is_light_mode = "--light" in args

    if is_light_mode:
        print(json.dumps({"decision": "skip", "reason": "light_mode_active"}))
        return

    # Check cognitive mode for offloading
    cognitive_mode = CONFIG.get('settings', {}).get('cognitive_mode', 'monolithic')
    if cognitive_mode == 'frontline':
        print(json.dumps({"decision": "skip", "reason": "frontline_mode_offloads_compute"}))
        return

    # Accept direct MD path or find the latest in archive/history
    md_path = None
    for arg in args:
        if not arg.startswith("--") and arg.endswith('.md') and os.path.exists(arg):
            md_path = arg
            break

    if not md_path:
        history_dir = os.path.join(AIM_ROOT, "archive/history")
        if os.path.exists(history_dir):
            transcripts = glob.glob(os.path.join(history_dir, "*.md"))
            if transcripts:
                md_path = max(transcripts, key=os.path.getmtime)

    if not md_path:
        print(json.dumps({"decision": "skip", "reason": "no_transcript_found"}))
        return

    updated = 1 if process_transcript(md_path) else 0
    print(json.dumps({"decision": "proceed", "updated": updated}))

if __name__ == "__main__":
    main(sys.argv[1:])
