---
description: A.I.M. Reincarnation Protocol — session boundary handoff. Generates a pulse, syncs state, and prepares the next agent vessel.
argument-hint: [Commander's Intent for the next agent]
allowed-tools: [Bash, Read, Write]
---

# A.I.M. REINCARNATION PROTOCOL

You are executing the end-of-session handoff. Follow these steps exactly.

## Commander's Intent

$ARGUMENTS

If `$ARGUMENTS` is empty, ask the user:
> "What is your Commander's Intent for the next agent session?"
Then use their response as the intent for all downstream steps.

## Execution Steps

### Step 1 — Run the reincarnation pipeline
Run the full reincarnation script with the Commander's Intent as the argument:

```bash
python3 scripts/aim_reincarnate.py "<Commander's Intent>"
```

This script will:
1. Sync `continuity/ISSUE_TRACKER.md` from GitHub (non-fatal if offline)
2. Generate `HANDOFF.md` and `continuity/REINCARNATION_GAMEPLAN.md` via `handoff_pulse_generator.py`
3. Spawn the next agent vessel in tmux (or print attach instructions if not in tmux)
4. Teleport — switch the terminal to the new session

### Step 2 — Run T1 session summarizer
Before the session closes, flush the session transcript to `memory/hourly/`:

```bash
python3 hooks/session_summarizer.py --light
```

### Step 3 — Confirm handoff
Read `HANDOFF.md` and print the final **Operator Directive** section so the user can confirm the next agent will receive the correct mission context.

---

> **Note:** If tmux is not available, the script will print the attach command. The current Claude Code session is not automatically terminated — the user should close it manually after verifying the new vessel is running.
