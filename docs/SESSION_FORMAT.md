# Claude Code Session File Format

## Location
```
~/.claude/projects/<project-path>/<session-id>.jsonl
```

Example:
```
~/.claude/projects/-home-kingb-aim-claude/35aca61e-d51d-4ade-a323-a355f7344305.jsonl
```

## Index Files
Session metadata (lightweight):
```
~/.claude/sessions/<pid>.json
```
Schema: `{ pid, sessionId, cwd, startedAt, kind, entrypoint }`

## Global History
Prompt history (user messages only):
```
~/.claude/history.jsonl
```
Schema: `{ display, pastedContents, timestamp, project, sessionId }`

## Session JSONL Schema
One JSON object per line. Each line has:

| Field | Type | Description |
|---|---|---|
| `type` | string | `"user"`, `"assistant"`, `"tool_result"`, `"file-history-snapshot"` |
| `message.role` | string | `"user"` or `"assistant"` |
| `message.content` | array | Content blocks (see below) |
| `timestamp` | string | ISO 8601 |
| `sessionId` | string | UUID |
| `uuid` | string | Per-message UUID |
| `parentUuid` | string | Links to parent message (conversation tree) |
| `cwd` | string | Working directory at time of message |
| `version` | string | Claude Code version (e.g., `"2.1.85"`) |
| `gitBranch` | string | Active git branch |

## Content Block Types (assistant messages)

| Block Type | Fields | Description |
|---|---|---|
| `text` | `text` | Plain text response |
| `thinking` | `thinking`, `signature` | Internal reasoning (extended thinking) |
| `tool_use` | `name`, `input`, `id` | Tool invocation with arguments |

## Comparison to Gemini Format

| Aspect | Gemini | Claude Code |
|---|---|---|
| Format | Single JSON file | JSONL (one object per line) |
| Location | `~/.gemini/tmp/<project>/chats/session-*.json` | `~/.claude/projects/<path>/<uuid>.jsonl` |
| Messages | `data.messages[]` array | One line per message |
| Model role | `"gemini"` / `"model"` | `"assistant"` |
| Thinking | `msg.thoughts[]` | Content block with `type: "thinking"` |
| Tool calls | `msg.toolCalls[]` | Content block with `type: "tool_use"` |
| Tool results | Inline in messages | Separate `type: "tool_result"` lines |
