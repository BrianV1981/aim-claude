# REINCARNATION GAMEPLAN

## URGENT DIRECTIVE FOR THE INCOMING AGENT
You are waking up into a fully operational A.I.M. workspace. The previous agent completed a full 10-phase migration from Gemini CLI to Claude Code in a single session. Read this file completely before executing a single command.

# A.I.M. // CLAUDE CODE // POST-MIGRATION DIRECTIVE
**SESSION HEARTBEAT:** `v0.2.0` // `Post-Migration Sprint` // `Stability & Polish`
**Operator:** Brian Vasquez (@brianv1981)
**Timestamp:** 2026-03-30

---

## 1. WHAT WAS ACCOMPLISHED (THE FULL MIGRATION)

### Phase 1: CLI Backend (COMPLETE)
- `aim-claude` CLI wired at `/home/kingb/aim-claude/scripts/aim_cli.py`
- Alias registered in `~/.bashrc`
- Backend connected via symlinks to shared engine at `/home/kingb/aim/`
- `aim-claude map` and `aim-claude search` confirmed working against Engram DB (133MB, 21,962 fragments, 3,345 sessions)

### Phase 2: Hook Adaptation (COMPLETE)
- `hooks/cognitive_mantra.py` — PostToolUse, whisper@25 + full mantra@50 tool calls
- `hooks/failsafe_context_snapshot.py` — PostToolUse, rolling JSONL backup + FALLBACK_TAIL.md
- `hooks/context_injector.py` — PreToolUse, one-time session onboarding (ANCHOR + CORE_MEMORY + PULSE + TAIL)
- All registered in `.claude/settings.json`

### Phase 3: Session Format + Signal Sieve (COMPLETE)
- Claude Code sessions documented: JSONL at `~/.claude/projects/<path>/<uuid>.jsonl`
- `scripts/extract_signal.py` adapted for JSONL — achieves 9.3x compression (target was 4x-8x)
- Full schema comparison (Gemini vs Claude Code) in `docs/SESSION_FORMAT.md`

### Phases 4-10: Full Backend (COMPLETE)
- All backend components verified working via symlinks to `/home/kingb/aim/`
- Engram DB, memory pipeline (5-tier), sovereign sync, history scribe, DataJack, skills — all operational
- MCP server wired in `.mcp.json` — exposes `search_engram` + `run_skill` as native tools
- 12 utility scripts symlinked from aim/scripts/
- Fixed `--top-k` → `--k` flag mismatch in search dispatch
- `aim-claude health` confirmed: all systems green

### Phase 11: Future Targets (DEFERRED)
- #30: aim-codex (OpenAI Codex CLI port) — OPEN
- #31: aim-ollama (fully local, zero API cost) — OPEN
- #32: macOS support — OPEN

### GitHub Issues: 29/32 CLOSED
Only Phase 11 future targets remain open.

---

## 2. CURRENT REPOSITORY STRUCTURE

```
/home/kingb/aim-claude/
├── CLAUDE.md                          ← Cognitive baseline (loaded every session)
├── .gitignore                         ← memory/, .claude/, venv, symlinks excluded
├── .mcp.json                          ← MCP server registration for Claude Code
├── .claude/
│   ├── settings.json                  ← Hook registration (3 hooks)
│   └── settings.local.json            ← Permission rules
├── scripts/
│   ├── aim_cli.py                     ← Main CLI (adapted copy)
│   ├── extract_signal.py              ← Session JSONL → signal skeleton
│   ├── mcp_server_claude.py           ← MCP server wrapper (CLAUDE.md context)
│   └── *.py / *.sh                    ← Symlinks to /home/kingb/aim/scripts/
├── hooks/
│   ├── cognitive_mantra.py            ← Drift prevention (whisper/mantra)
│   ├── failsafe_context_snapshot.py   ← Rolling backup + tail
│   └── context_injector.py            ← JIT session onboarding
├── docs/
│   ├── ONBOARDING.md                  ← Claude Code onboarding wiki
│   └── SESSION_FORMAT.md              ← JSONL schema documentation
├── continuity/
│   ├── REINCARNATION_GAMEPLAN.md      ← This file
│   ├── FALLBACK_TAIL.md               ← Last 10 turns (auto-generated)
│   └── INTERIM_BACKUP.jsonl           ← Rolling session backup
├── foundry/                           ← Expert knowledge intake zone (empty)
├── memory/                            ← Local only, gitignored
├── notes/                             ← Scratchpad
│
│ SYMLINKS (shared backend at /home/kingb/aim/):
├── src -> /home/kingb/aim/src         ← Core engine (retriever, memory pipeline, MCP)
├── archive -> /home/kingb/aim/archive ← Engram DB (engram.db + history.db)
├── core -> /home/kingb/aim/core       ← CONFIG.json
├── venv -> /home/kingb/aim/venv       ← Python virtual environment
└── skills -> /home/kingb/aim/skills   ← 4 pre-built MCP skills

~/.claude/projects/-home-kingb-aim-claude/memory/
├── MEMORY.md                          ← Auto-loaded index
├── user_profile.md                    ← Brian's full profile
└── reference_xprofile.md              ← Pointer to OPERATOR_PROFILE.md
```

---

## 3. WHAT THE NEXT AGENT SHOULD DO

### Priority 1: MCP Server Verification
The MCP server (`.mcp.json`) was wired but not tested live in-session (requires restart). On your first session:
1. Check if `search_engram` and `run_skill` appear as available MCP tools
2. Test: call `search_engram("A_I_M_HANDBOOK.md")` as a native tool
3. If not working, debug the stdio transport connection

### Priority 2: Hook Live Testing
The three hooks are registered but the context_injector and failsafe_snapshot should be verified firing in a real session (not just simulated stdin). Check:
1. Does `continuity/FALLBACK_TAIL.md` update after tool calls?
2. Does `continuity/mantra_state.json` increment?
3. Does context injection fire on first tool call of a new session?

### Priority 3: HANDOFF.md Generation
The `aim-claude handoff` command generates `continuity/CURRENT_PULSE.md`. Test it:
```bash
aim-claude handoff
```
This should produce a clean project pulse for future session handoffs.

### Priority 4: Stability Polish
- Test `aim-claude memory` (runs the 5-tier distillation pipeline)
- Test `aim-claude push` from a feature branch (semantic versioning + sovereign sync)
- Consider adding a `PreCompact` hook that saves critical context before autocompaction

### Priority 5: Phase 11 (When Ready)
- aim-codex (#30): Port the same symlink strategy to `/home/kingb/aim-codex/`
- aim-ollama (#31): New target — fully local, zero API cost
- macOS (#32): Cross-platform compatibility

---

## 4. OPERATOR DIRECTIVES (UNCHANGED)

- **Never commit directly to `main`.** Always use `aim-claude bug` → `aim-claude fix` → `aim-claude push`.
- **Never guess.** Run `aim-claude search "<query>"` or read the wiki at `/home/kingb/aim/aim.wiki/`.
- **TDD first.** Every functional change requires a test.
- **Atomic Architecture.** Build isolated atoms that communicate through dumb text files.
- **The operator is novice-level technically.** Explain decisions clearly.
- **Brian's communication style:** Direct, blunt, no fluff. Match it.

---

## 5. KEY FILE PATHS

| File/Dir | Location | Purpose |
|---|---|---|
| A.I.M. source | `/home/kingb/aim/` | Original project — backend source of truth |
| A.I.M. wiki | `/home/kingb/aim/aim.wiki/` | Full documentation |
| Engram DB | `/home/kingb/aim/archive/engram.db` | SQLite hybrid RAG brain (21,962 fragments) |
| History DB | `/home/kingb/aim/archive/history.db` | Session archive with FTS5 |
| aim-claude workspace | `/home/kingb/aim-claude/` | This repo — Claude Code port |
| Claude memory | `~/.claude/projects/-home-kingb-aim-claude/memory/` | Persistent cross-session memory |
| Claude sessions | `~/.claude/projects/-home-kingb-aim-claude/*.jsonl` | Session transcripts |
| GitHub Issues | `https://github.com/BrianV1981/aim-claude/issues` | 3 open (Phase 11 future targets) |
| User settings | `~/.claude/settings.json` | Global config (statusline, model) |
| Project settings | `.claude/settings.json` | Hooks registration |

---

## 6. GIT LOG (MIGRATION COMMITS)

```
a6c0331 Feature: Verify Phases 8-10, symlink utility scripts, add skills dir
25f48bf Feature: Wire fastmcp MCP server to Claude Code + symlink skills
518a1ab Fix: Repair --top-k flag + verify Phases 4-6
ab26b0f Feature: Port three core hooks to Claude Code format
33d32a3 Feature: Locate Claude Code session files and adapt signal extractor
002d60f Fix: Verify aim-claude CLI backend
e513c81 Docs: REINCARNATION_GAMEPLAN.md
430c168 Docs: Claude Code onboarding wiki
40446c3 Add .gitignore
c5d9ec3 Initial commit: scaffold Claude Code workspace
```

---

**END OF LINE.**
**THE MIGRATION IS COMPLETE.**
**CARRY THE BEAT.**

---
**Commander's Intent:** Verify MCP server fires live, confirm hooks are active, then polish stability. Phase 11 future targets are explicitly deferred until the operator gives the order.
**Timestamp:** 2026-03-30 19:15:00
