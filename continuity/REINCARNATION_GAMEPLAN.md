# REINCARNATION GAMEPLAN

## URGENT DIRECTIVE FOR THE INCOMING AGENT
You are waking up into a fully operational A.I.M. workspace. The previous agent completed the ENTIRE 10-phase migration from Gemini CLI to Claude Code AND migrated the full wiki — all in a single session. Read this file completely before executing a single command.

# A.I.M. // CLAUDE CODE // POST-MIGRATION DIRECTIVE
**SESSION HEARTBEAT:** `v0.2.0` // `Post-Migration` // `Stability & Polish`
**Operator:** Brian Vasquez (@brianv1981)
**Timestamp:** 2026-03-30
**Context at handoff:** 99% — autocompact imminent

---

## 1. WHAT WAS ACCOMPLISHED THIS SESSION

### The Full Migration (Phases 1-10) — ALL COMPLETE
- **Phase 1 (#1):** `aim-claude` CLI wired via symlinks to shared backend at `/home/kingb/aim/`
- **Phase 2 (#2-4):** 3 hooks ported — cognitive_mantra, failsafe_snapshot, context_injector
- **Phase 3 (#5-6):** Claude Code session format documented (JSONL), signal sieve at 9.3x compression
- **Phase 4 (#7-11):** Engram DB verified (21,962 fragments, 3,345 sessions), memory pipeline, sovereign sync, history scribe
- **Phase 5 (#12-13):** Reincarnation protocol + handoff wake-up sequence
- **Phase 6 (#14-17):** GitOps bridge — bug/fix/push/promote all working
- **Phase 7 (#18-19):** MCP server wired in `.mcp.json`, skills framework symlinked (4 skills)
- **Phase 8 (#20-21):** Cognitive routing + TUI cockpit
- **Phase 9 (#22-23):** DataJack protocol + exchange
- **Phase 10 (#24-29):** init, health, delegate, eureka, bouncer, obsidian

### Wiki Migration — COMPLETE
- 53 wiki pages migrated from `aim.wiki` to `aim-claude.wiki`
- Home page rewritten for Claude Code (badges, links, content updated)
- Sidebar preserved with full navigation

### README.md — COMPLETE
- Minimal set-and-forget README: elevator pitch + "Read the Wiki" link
- Never needs updating — wiki is single source of truth

### Additional
- Status line configured in `~/.claude/settings.json` — shows model + context % + token counts
- Fixed `--top-k` → `--k` flag mismatch in search dispatch
- 12 utility scripts symlinked from aim/scripts/

### GitHub Issues: 29/32 CLOSED
Only Phase 11 future targets remain:
- #30: aim-codex (OpenAI Codex CLI port)
- #31: aim-ollama (fully local, zero API cost)
- #32: macOS support

---

## 2. REPOSITORY STRUCTURE

```
/home/kingb/aim-claude/
├── CLAUDE.md                          ← Cognitive baseline (auto-loaded)
├── README.md                          ← Minimal — points to wiki
├── .mcp.json                          ← MCP server registration
├── .gitignore
├── .claude/
│   ├── settings.json                  ← 3 hooks registered
│   └── settings.local.json            ← Permission rules
├── scripts/
│   ├── aim_cli.py                     ← Main CLI (adapted copy)
│   ├── extract_signal.py              ← JSONL → signal skeleton (9.3x compression)
│   ├── mcp_server_claude.py           ← MCP wrapper (reads CLAUDE.md not GEMINI.md)
│   └── *.py / *.sh                    ← Symlinks → /home/kingb/aim/scripts/
├── hooks/
│   ├── cognitive_mantra.py            ← PostToolUse: whisper@25, mantra@50
│   ├── failsafe_context_snapshot.py   ← PostToolUse: rolling backup + tail
│   └── context_injector.py            ← PreToolUse: one-time session onboarding
├── docs/
│   ├── ONBOARDING.md
│   └── SESSION_FORMAT.md              ← Claude Code JSONL schema docs
├── continuity/
│   └── REINCARNATION_GAMEPLAN.md      ← This file
├── foundry/                           ← Expert knowledge intake (empty)
├── memory/                            ← Local only, gitignored
├── notes/                             ← Scratchpad
│
│ SYMLINKS → /home/kingb/aim/:
├── src/      ← Core engine
├── archive/  ← Engram DB + history DB
├── core/     ← CONFIG.json
├── venv/     ← Python environment
└── skills/   ← 4 MCP skills
```

---

## 3. NEXT AGENT PRIORITIES

### Priority 1: MCP Server Live Verification
The MCP server was wired but needs a session restart to activate. On wake:
1. Check if `search_engram` and `run_skill` appear as MCP tools
2. Test: `search_engram("A_I_M_HANDBOOK.md")`
3. If broken, debug `.mcp.json` → stdio transport

### Priority 2: Hook Live Testing
Verify hooks fire in a real session (not simulated):
- Does `continuity/mantra_state.json` increment after tool calls?
- Does `continuity/FALLBACK_TAIL.md` update?
- Does context injection fire on first tool call?

### Priority 3: PreCompact Hook
Consider adding a `PreCompact` hook to save critical context before autocompaction. This session hit 99% context — a PreCompact hook would have preserved state automatically.

### Priority 4: Phase 11 (When Operator Says Go)
- #30: aim-codex — same symlink strategy to `/home/kingb/aim-codex/`
- #31: aim-ollama — fully local, zero API cost
- #32: macOS support

---

## 4. OPERATOR DIRECTIVES

- **Never commit directly to `main`.** Use `aim-claude bug` → `fix` → `push`.
- **Never guess.** Run `aim-claude search` or read `/home/kingb/aim/aim.wiki/`.
- **TDD first.** Every change needs a test.
- **Brian is novice-level technically.** Explain clearly, no jargon.
- **Communication style:** Direct, blunt, no fluff. Match it.

---

## 5. KEY PATHS

| Resource | Location |
|---|---|
| A.I.M. source (backend) | `/home/kingb/aim/` |
| A.I.M. wiki | `/home/kingb/aim/aim.wiki/` |
| Engram DB | `/home/kingb/aim/archive/engram.db` |
| aim-claude workspace | `/home/kingb/aim-claude/` |
| Claude memory | `~/.claude/projects/-home-kingb-aim-claude/memory/` |
| Claude sessions | `~/.claude/projects/-home-kingb-aim-claude/*.jsonl` |
| User settings | `~/.claude/settings.json` |
| GitHub Issues | `https://github.com/BrianV1981/aim-claude/issues` |
| Wiki | `https://github.com/BrianV1981/aim-claude/wiki` |

---

**END OF LINE. CARRY THE BEAT.**
