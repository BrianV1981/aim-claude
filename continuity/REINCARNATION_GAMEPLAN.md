# REINCARNATION GAMEPLAN

## ⚠️ URGENT DIRECTIVE FOR THE INCOMING AGENT
You are waking up at the very beginning of a high-stakes migration build. The previous agent has distilled the full session into these rigid directives. Read this file completely before executing a single command.

# 🤖 A.I.M. // CLAUDE CODE MIGRATION // EXECUTIVE DIRECTIVE
**SESSION HEARTBEAT:** `v0.1.0` // `Foundation Sprint` // `Gemini → Claude Code Migration`
**Operator:** Brian Vasquez (@brianv1981)
**Timestamp:** 2026-03-30

---

## 1. THE STRATEGIC CONTEXT (READ THIS FIRST)

### What A.I.M. Is
A.I.M. (Actual Intelligent Memory) is an open-source exoskeleton built to solve the **Amnesia Problem** — the context window degradation that causes autonomous AI agents to hallucinate, drift, and produce spaghetti code after 50+ turns. It was originally built on **Gemini CLI** but was architected from day one to be model-agnostic. The core engine is pure Python + SQLite. Gemini was just the first agent plugged in.

### Why We Are Here
Gemini CLI has been unstable and problematic. The decision was made to hyperfixate on **Claude Code** as the primary agent target. A parallel **aim-codex** (OpenAI Codex) target exists and will resume after aim-claude reaches stability. A future **aim-ollama** (fully local, zero API cost) target is also planned.

### The Core Insight
The A.I.M. backend (Engram DB, memory pipeline, GitOps bridge, DataJack, Skills) is already model-agnostic. The migration is mostly **plumbing** — hook format adaptation, one session file path, and one trigger event. The architecture does not need to change.

---

## 2. WHAT WAS ACCOMPLISHED THIS SESSION

### Workspace Scaffolding (COMPLETE)
- ✅ Created `/home/kingb/aim-claude/` workspace
- ✅ Wrote `CLAUDE.md` — cognitive baseline, converted from `GEMINI.md`, all `aim` commands renamed to `aim-claude`
- ✅ Set up `.gitignore` — excludes `memory/`, `.claude/`, venv, WSL Zone.Identifier artifacts
- ✅ Created `docs/ONBOARDING.md` — comprehensive wiki page documenting Claude Code's native initialization model, memory system, workspace scaffold, and design philosophy
- ✅ Created `notes/` scratchpad folder
- ✅ Created `continuity/` folder (this file lives here)

### Git & GitHub (COMPLETE)
- ✅ Initialized git repo in `/home/kingb/aim-claude/`
- ✅ Branch set to `main`
- ✅ Remote created: `https://github.com/BrianV1981/aim-claude`
- ✅ Two commits pushed: initial scaffold + .gitignore + docs

### Memory System (COMPLETE)
- ✅ Memory index at `~/.claude/projects/-home-kingb-aim-claude/memory/MEMORY.md`
- ✅ `user_profile.md` populated: Brian Vasquez, 45, Florida, self-employed, novice dev, family context, communication style, values
- ✅ `reference_xprofile.md` created: pointer to `aim-claude/memory/OPERATOR_PROFILE.md`

### Roadmap (COMPLETE — 32 tickets open)
- ✅ Full 11-phase roadmap created as GitHub Issues at `https://github.com/BrianV1981/aim-claude/issues`
- ✅ All 32 tickets tagged `enhancement`
- ✅ Full wiki reviewed and absorbed: Home, Logic, Brain Map, Technical Spec, Master Schema, Atomic Architecture, Hybrid RAG, Handoff Architecture, Universal Skills, GitOps Bridge, Roadmap

---

## 3. THE CURRENT PROJECT STATE

### Repository Structure (Current)
```
/home/kingb/aim-claude/
├── CLAUDE.md                          ← Cognitive baseline (loaded every session)
├── .gitignore                         ← memory/, .claude/, venv, WSL excluded
├── docs/
│   └── ONBOARDING.md                  ← Claude Code onboarding wiki
├── notes/                             ← Scratchpad (empty)
├── memory/                            ← Local only, gitignored
│   ├── MEMORY.md                      ← Empty (placeholder)
│   ├── OPERATOR.md                    ← Brian's basic identity
│   └── OPERATOR_PROFILE.md            ← Brian's X.com voice/archetype
└── continuity/
    ├── REINCARNATION_GAMEPLAN.md      ← This file
    └── LAST_SESSION_FLIGHT_RECORDER.md ← Previous session archive (from aim project)

~/.claude/projects/-home-kingb-aim-claude/memory/
├── MEMORY.md                          ← Auto-loaded index
├── user_profile.md                    ← Brian's full profile
└── reference_xprofile.md             ← Pointer to OPERATOR_PROFILE.md
```

### GitHub Issues (Full Roadmap)
| Phase | Issue # | Title | Status |
|---|---|---|---|
| 1 | #1 | Verify aim-claude CLI backend | OPEN — START HERE |
| 2 | #2 | Cognitive Mantra hook | OPEN |
| 2 | #3 | Failsafe Context Snapshot hook | OPEN |
| 2 | #4 | Context Injector hook (JIT) | OPEN |
| 3 | #5 | Locate Claude Code session files + adapt extract_signal.py | OPEN |
| 3 | #6 | Zero-Token Signal Sieve | OPEN |
| 4 | #7 | Engram DB (SQLite Hybrid RAG) | OPEN |
| 4 | #8 | Cascading Memory Engine (4-tier waterfall) | OPEN |
| 4 | #9 | Foundry Ingestion pipeline | OPEN |
| 4 | #10 | Sovereign Sync (SQLite → JSONL) | OPEN |
| 4 | #11 | History Scribe | OPEN |
| 5 | #12 | Reincarnation Protocol | OPEN |
| 5 | #13 | Handoff Wake-up Sequence | OPEN |
| 6 | #14 | aim-claude bug | OPEN |
| 6 | #15 | aim-claude fix | OPEN |
| 6 | #16 | aim-claude push | OPEN |
| 6 | #17 | aim-claude promote | OPEN |
| 7 | #18 | fastmcp server + Claude Code MCP | OPEN |
| 7 | #19 | Universal Skills Framework | OPEN |
| 8 | #20 | Cognitive Routing (multi-model) | OPEN |
| 8 | #21 | aim-claude tui | OPEN |
| 9 | #22 | DataJack Protocol + jack-in | OPEN |
| 9 | #23 | aim-claude exchange | OPEN |
| 10 | #24 | aim-claude init | OPEN |
| 10 | #25 | aim-claude health | OPEN |
| 10 | #26 | aim-claude delegate | OPEN |
| 10 | #27 | Eureka Protocol | OPEN |
| 10 | #28 | Quarantine Daemon / Bouncer | OPEN |
| 10 | #29 | Obsidian Bridge | OPEN |
| 11 | #30 | aim-codex (Codex CLI port) | OPEN — FUTURE |
| 11 | #31 | aim-ollama (fully local) | OPEN — FUTURE |
| 11 | #32 | macOS support | OPEN — FUTURE |

---

## 4. CRITICAL ARCHITECTURE NOTES (DO NOT GUESS — READ THESE)

### What Maps Natively to Claude Code
- `CLAUDE.md` ← `GEMINI.md` (done — already converted)
- Claude Code hooks (bash, `.claude/settings.json`) ← Gemini TypeScript hooks
- Claude Code MCP client ← already speaks MCP, will connect to fastmcp server natively
- `~/.claude/projects/.../memory/` ← Claude's persistent memory system (already populated)

### What Requires Adaptation
1. **Hooks:** Gemini used TypeScript hooks. Claude Code uses **bash hooks** registered in `.claude/settings.json`. Hook events: `PreToolUse`, `PostToolUse`, `Notification`, `Stop`, `SubagentStop`. The `cognitive_mantra`, `failsafe_context_snapshot`, and `context_injector` hooks must be rewritten as bash scripts.
2. **Session data path:** `extract_signal.py` currently targets `.gemini/tmp/.../chats/*.json`. Claude Code stores session data at a different path in a different JSON schema. Must locate and document before signal extraction can work.
3. **Reincarnation trigger:** Gemini crashed (Node.js V8 heap). Claude Code compresses context silently. Reincarnation must be **proactive** (operator-triggered or tool-count-based), not reactive to a crash event.

### What Already Works As-Is (No Changes Needed)
- The Engram DB (SQLite + hybrid RAG) — pure Python, backend-agnostic
- The entire memory distillation pipeline (Tier 1-4 waterfall) — pure Python
- The GitOps bridge (`aim-claude bug/fix/push/promote`) — pure bash + `gh` CLI
- The DataJack protocol (`.engram` cartridges) — pure SQLite
- The MCP fastmcp server — Claude Code speaks MCP natively
- The Skills framework — already architected as CLI-agnostic

### The Source of Truth
- **aim repo:** `/home/kingb/aim/` — the original Gemini-based A.I.M. project. All source code lives here. Do not rewrite from scratch — port and adapt.
- **aim.wiki:** `/home/kingb/aim/aim.wiki/` — full documentation. Use `aim-claude search` to query the Engram DB, or read wiki files directly.
- **aim-claude repo:** `/home/kingb/aim-claude/` — this workspace. Where the Claude Code port is being built.

---

## 5. THE BATTLE PLAN (Next Agent Mandate)

**Upon waking, you will execute the following steps in strict order. Do not deviate.**

### Step 0: VERIFY WAKE-UP INTEGRITY
- Confirm you are reading `continuity/REINCARNATION_GAMEPLAN.md` in `/home/kingb/aim-claude/`
- Run `gh issue list --limit 5` to confirm the issue tracker is live
- Run `git branch --show-current` — must read `main` (no active feature branch yet)
- Run `git log --oneline -5` to confirm current commit state

### Step 1: EXECUTE ISSUE #1 — Verify aim-claude CLI Backend
This is the non-negotiable first step. Nothing else can be validated until the backend is confirmed working.

**Tasks:**
1. Locate the `aim-claude` alias/binary — run `which aim-claude` and inspect `~/.bashrc` or `~/.bash_aliases`
2. Test `aim-claude map` — should return a lightweight index of all loaded documentation titles
3. Test `aim-claude search "A.I.M."` — should return results from the Engram DB
4. Confirm `engram.db` exists — check `/home/kingb/aim/archive/engram.db` or wherever it lives
5. Document findings. If any command fails, open a bug ticket before proceeding.

**GitOps protocol for this issue:**
```bash
aim-claude bug "Phase 1: CLI backend verification failed — <describe issue>"
aim-claude fix 1
# do the work
aim-claude push "Fix: Verified aim-claude CLI backend (Closes #1)"
```

### Step 2: EXECUTE ISSUE #5 — Locate Claude Code Session Files
This is the critical path dependency for the entire signal extraction pipeline.

**Tasks:**
1. Start a Claude Code session, do some work, then find where it saves session data
2. Check `~/.claude/` recursively for JSON session files
3. Document the exact path pattern and JSON schema
4. Compare schema to Gemini's `.gemini/tmp/.../chats/*.json` format
5. Update `scripts/extract_signal.py` path and parser accordingly

### Step 3: EXECUTE ISSUES #2, #3, #4 — Hook Adaptation
Once the backend is verified, adapt the three core hooks to Claude Code format.

**Hook registration target:** `.claude/settings.json` in the aim-claude workspace

**Reference:** Check `/home/kingb/aim/hooks/` for the original Gemini hook implementations. Port the logic, not the TypeScript wrapper.

**Hook format for Claude Code:**
```json
{
  "hooks": {
    "PostToolUse": [
      { "matcher": "", "hooks": [{ "type": "command", "command": "bash /path/to/hook.sh" }] }
    ]
  }
}
```

### Step 4: Do Not Skip Ahead
Phases 4-11 depend on Phases 1-3 being stable. Do not touch the Engram DB, memory pipeline, or MCP server until the hooks are working and session extraction is confirmed. The Atomic Architecture principle applies: build one indestructible atom at a time.

---

## 6. OPERATOR DIRECTIVES (BEHAVIORAL CONSTRAINTS)

- **Never commit directly to `main`.** Always use `aim-claude bug` → `aim-claude fix` → `aim-claude push` → `aim-claude promote`.
- **Never guess.** If you need information about the A.I.M. architecture, read the wiki at `/home/kingb/aim/aim.wiki/` or run `aim-claude search "<query>"`.
- **TDD first.** Every functional change requires a test. No code enters `src/` without a verification script.
- **Atomic Architecture.** Build isolated atoms that communicate through dumb text files. Do not build Rube Goldberg machines.
- **The operator is novice-level technically.** Explain decisions clearly. Do not assume familiarity with Python internals, SQLite triggers, or MCP protocol details.
- **Brian's communication style:** Direct, blunt, no fluff. Match it.

---

## 7. KEY FILE PATHS (REFERENCE MAP)

| File/Dir | Location | Purpose |
|---|---|---|
| A.I.M. source | `/home/kingb/aim/` | Original Gemini project — source of truth for porting |
| A.I.M. wiki | `/home/kingb/aim/aim.wiki/` | Full documentation |
| Engram DB | `/home/kingb/aim/archive/engram.db` | SQLite hybrid RAG brain |
| Hook scripts | `/home/kingb/aim/hooks/` | Original Gemini hooks to port |
| Python src | `/home/kingb/aim/src/` | Core engine scripts |
| CLI scripts | `/home/kingb/aim/scripts/` | Utility scripts |
| aim-claude workspace | `/home/kingb/aim-claude/` | This repo — Claude Code port |
| Claude memory | `~/.claude/projects/-home-kingb-aim-claude/memory/` | Persistent cross-session memory |
| GitHub Issues | `https://github.com/BrianV1981/aim-claude/issues` | Full roadmap — 32 open tickets |

---

**END OF LINE.**
**TELEPORTATION IMMINENT.**
**CARRY THE BEAT.**

---
**Commander's Intent:** Verify the aim-claude backend is operational (Issue #1), locate Claude Code session files (Issue #5), then adapt the three core hooks to Claude Code format (Issues #2-4). Do not proceed to Phase 4+ until Phase 1-2 are confirmed stable.
**Timestamp:** 2026-03-30 18:00:00
