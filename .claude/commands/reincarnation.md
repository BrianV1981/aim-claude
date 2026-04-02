---
description: A.I.M. Reincarnation Protocol — end-of-session handoff. The living agent writes its own gameplan (soul/essence/trajectory), then passes the baton to a fresh Claude vessel.
argument-hint: "[personalized message for the next agent]"
allowed-tools: [Bash, Read, Write]
---

# A.I.M. REINCARNATION PROTOCOL

You are the dying agent. You still have full context. You are about to pass the baton.
Before the script runs, YOU must write the gameplan — not a cold LLM reading a transcript.

## Step 1 — Get Commander's Intent

$ARGUMENTS

If `$ARGUMENTS` is empty, ask the user:
> "What is your Commander's Intent for the next agent? (appended to REINCARNATION_GAMEPLAN.md)"

## Step 2 — Write REINCARNATION_GAMEPLAN.md (YOU write this, right now)

Using your full live context of this session, write `continuity/REINCARNATION_GAMEPLAN.md`.
Do NOT summarize mechanically. Capture the soul of the session.

Follow this structure exactly:

```
# REINCARNATION GAMEPLAN

## ⚠️ URGENT DIRECTIVE FOR THE INCOMING AGENT
You are waking up in the middle of a high-momentum development cycle.
The previous agent has distilled the session heartbeat into these rigid directives:

[YOUR CONTENT — address the following:]
- What was the core theme and technical momentum of this session?
- What was the "Eureka" direction — the thing that finally clicked or the path that proved correct?
- What was thrashed on, debated, or pivoted away from? (So the next agent doesn't repeat it)
- What is the active trajectory — where were things heading when the session ended?
- 3–5 rigid, numbered battle steps for the next agent to execute immediately upon waking.
  Focus only on active momentum. Ignore closed/abandoned directions.

---
**Commander's Intent:** <user message from Step 1>
**Timestamp:** <current datetime>
```

Write this file now using the Write tool before proceeding.

## Step 3 — Run the reincarnation pipeline

```bash
python3 scripts/aim_reincarnate.py "<Commander's Intent from Step 1>"
```

This will:
1. Sync `continuity/ISSUE_TRACKER.md`
2. Run scrivener pipeline (T1 + System 1)
3. Refresh `CURRENT_PULSE.md` and `HANDOFF.md` (timestamps only — does NOT overwrite your gameplan)
4. Spawn a new Claude vessel in tmux and teleport

## Step 4 — Confirm

Read the final line of `continuity/REINCARNATION_GAMEPLAN.md` and confirm the Commander's Intent was recorded correctly.
