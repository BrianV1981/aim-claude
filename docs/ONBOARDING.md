# Claude Code — Onboarding & Workspace Design Guide

A reference for designing projects natively around Claude Code. Based on the initial setup of the `aim-claude` workspace.

---

## Table of Contents
1. [How Claude Initializes](#1-how-claude-initializes)
2. [CLAUDE.md — The Instruction File](#2-claudemd--the-instruction-file)
3. [Memory System](#3-memory-system)
4. [Workspace Scaffold](#4-workspace-scaffold)
5. [Git & GitHub Setup](#5-git--github-setup)
6. [What Goes Where](#6-what-goes-where)
7. [Design Philosophy](#7-design-philosophy)

---

## 1. How Claude Initializes

Every time a new conversation starts in a directory, Claude Code automatically loads:

| File | Location | Purpose |
|---|---|---|
| `CLAUDE.md` | Project root | Instructions, rules, context for this workspace |
| `MEMORY.md` | `~/.claude/projects/<path>/memory/` | Index of persistent memory files |

Claude does **not** scan the whole repo on startup. It reads only what is explicitly pointed to. Everything else is pulled on demand.

---

## 2. CLAUDE.md — The Instruction File

This is the most important file in any Claude workspace. It is loaded on every startup and governs Claude's behavior for that project.

**What belongs in CLAUDE.md:**
- Project identity and purpose
- Behavioral rules and mandates (e.g. GitOps workflow, TDD requirements)
- Conventions and anti-patterns
- Pointers to tools and commands Claude should use

**What does NOT belong in CLAUDE.md:**
- Personal user info (goes in memory)
- Ephemeral task state (use tasks)
- Code documentation (lives with the code)

**Example structure:**
```
# Project Name

## Purpose
What this workspace is for.

## Conventions
How code should be organized and written.

## Mandates
Rules Claude must follow (branch discipline, testing, etc.)

## Things to avoid
Anti-patterns specific to this project.
```

---

## 3. Memory System

Claude has a persistent, file-based memory system stored outside the repo at:

```
~/.claude/projects/-home-<user>-<workspace>/memory/
```

### How it works

- **`MEMORY.md`** — an index file that is auto-loaded every conversation. Claude always sees this.
- **Individual `.md` files** — fetched on demand when the index entry signals relevance.
- Claude does **not** background-poll memory. It is pull-based: see index → judge relevance → fetch file.

### Memory types

| Type | Purpose | Example |
|---|---|---|
| `user` | Who the operator is, how to work with them | Name, background, communication style, family context |
| `feedback` | Corrections and confirmations about Claude's behavior | "Don't summarize at the end", "bundled PRs are right for this repo" |
| `project` | Active goals, decisions, deadlines | Current initiative, why a decision was made, key dates |
| `reference` | Where things live in external systems | X.com profile file path, Linear project name, Grafana dashboard URL |

### What does NOT go in memory
- Code patterns, file paths, architecture — read the code
- Git history — use `git log`
- In-progress task state — use tasks
- Anything already in `CLAUDE.md`

### Memory file format
```markdown
---
name: Memory name
description: One-line description (used to judge relevance from the index)
type: user | feedback | project | reference
---

Content here. For feedback and project types, include:
**Why:** reason behind the rule or fact
**How to apply:** when this guidance kicks in
```

### MEMORY.md index format
```markdown
# Memory Index

- [Title](file.md) — one-line hook under 150 chars
```

---

## 4. Workspace Scaffold

The minimal native Claude workspace:

```
aim-claude/
├── CLAUDE.md              ← Loaded on startup. Governs behavior.
├── .gitignore             ← Excludes memory/, .claude/, venv, WSL artifacts
├── docs/                  ← Reference documentation (this file lives here)
│   └── ONBOARDING.md
└── notes/                 ← Local scratchpad, gitignored or committed as needed

~/.claude/projects/.../memory/   ← Never committed. Claude's persistent memory.
├── MEMORY.md              ← Auto-loaded index
├── user_profile.md        ← Who the operator is
└── reference_*.md         ← Pointers to external resources
```

### .gitignore essentials for Claude workspaces
```gitignore
# Claude Code
.claude/
memory/

# WSL artifacts
*.Zone.Identifier

# Python
__pycache__/
*.py[cod]
.venv/
venv/

# Editor
.vscode/
.idea/

# Env
.env
.env.*
```

---

## 5. Git & GitHub Setup

Claude follows a GitOps mandate: **never commit directly to `main`** for any real work.

### Initial repo setup (done once)
```bash
git init
git branch -m master main
git add CLAUDE.md .gitignore
git commit -m "Initial commit: scaffold Claude workspace"
gh repo create <username>/<repo> --public --source . --remote origin --push
```

### Ongoing workflow
1. Log the issue/task
2. Check out an isolated branch
3. Validate: `git branch --show-current` — if `main`, stop
4. Work and test
5. Push from the branch only

---

## 6. What Goes Where

| Information | Lives in | Why |
|---|---|---|
| Behavioral rules for Claude | `CLAUDE.md` | Loaded every startup |
| Who the operator is | `~/.claude/.../memory/user_profile.md` | Persistent, private, cross-session |
| Active project goals | `~/.claude/.../memory/project_*.md` | Persistent context, not committed |
| Corrections to Claude's behavior | `~/.claude/.../memory/feedback_*.md` | So you don't repeat yourself |
| External resource pointers | `~/.claude/.../memory/reference_*.md` | Pull on demand |
| SOPs and mandates | `CLAUDE.md` | Governs, not remembered |
| Personal/sensitive operator data | `memory/` (local, gitignored) | Never hits GitHub |
| Reference docs for Claude to search | `memory/` or `docs/` | Depends on sensitivity |

---

## 7. Design Philosophy

**Scaffold around Claude, not the other way around.**

Claude natively reads `CLAUDE.md` and its own memory. Everything else — special folder structures, hand-rolled agent frameworks, external tooling — is overhead unless it solves a real problem.

The lightest effective setup:
- `CLAUDE.md` tells Claude how to behave in this project
- Memory tells Claude who it's working with and what matters
- The repo holds the actual work

**SOPs and directives belong in `CLAUDE.md`.** Memory is for knowing the operator — not governing Claude's behavior. The distinction matters: directives load every time, memory loads when relevant.

**Memory decays.** Project memories go stale. When a memory names a specific file, function, or state — verify it before acting on it. `git log` and reading the current code are authoritative over any snapshot in memory.

---

*Last updated: 2026-03-30 — Initial workspace onboarding session with Brian Vasquez.*
