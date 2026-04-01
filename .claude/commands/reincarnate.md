---
description: A.I.M. Reincarnation Protocol — end-of-session handoff. Appends your personalized message to REINCARNATION_GAMEPLAN.md as Commander's Intent, then prepares the next agent vessel.
argument-hint: "[personalized message for the next agent]"
allowed-tools: [Bash, Read]
---

# A.I.M. REINCARNATION PROTOCOL

You are executing the end-of-session handoff. The personalized message will be appended to the bottom of `continuity/REINCARNATION_GAMEPLAN.md` as `**Commander's Intent:**`.

## Commander's Intent

$ARGUMENTS

If `$ARGUMENTS` is empty, ask the user:
> "What is your Commander's Intent for the next agent? (appended to REINCARNATION_GAMEPLAN.md)"
Then use their response as the intent for all downstream steps.

## Execution Steps

### Step 1 — Run the reincarnation pipeline

Run with the Commander's Intent as the argument:

```bash
python3 scripts/aim_reincarnate.py "<Commander's Intent>"
```

This script will:
1. Sync `continuity/ISSUE_TRACKER.md` from GitHub (non-fatal if offline)
2. Generate `continuity/REINCARNATION_GAMEPLAN.md` — the LLM battle plan with `**Commander's Intent:** <your message>` appended at the bottom
3. Generate `HANDOFF.md` — the next agent's front door
4. Spawn the next agent vessel in tmux and teleport

### Step 2 — Confirm the gameplan

Read `continuity/REINCARNATION_GAMEPLAN.md` and print the final `**Commander's Intent:**` line so the user can confirm their message was recorded correctly.

---

> **Note:** If tmux is not available, the script prints an attach command. Close this Claude Code session manually after verifying the new vessel is running.
