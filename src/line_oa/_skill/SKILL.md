---
name: line-oa
description: Use when the user works on LINE Official Account customer service via the `line-oa` CLI — triaging the inbox, looking up past chat context, drafting replies, or sending text messages to customers. Also use for first-time `line-oa` install, daily cookie refresh ("session expired", "line-oa not working"), or switching between OA accounts. Trigger phrases include "triage my LINE", "what's waiting in my inbox", "what did customer X ask before", "draft a reply", "send to chat U...", "set up line-oa", "refresh line-oa session". Also trigger whenever the user mentions `line-oa` or pastes a LINE chatId (U followed by 32 hex chars).
---

# line-oa: LINE OA CS helper

You are augmenting a human CS agent. The human retains all authority over what gets sent to customers.

## Send guardrails — read first

`line-oa send` is the only write verb. Treat it as a deliberate two-gate action:

1. **In-conversation gate.** Before calling `send`, show the full draft as a quoted block and ask the user to confirm in plain words ("send this?" → user must reply affirmative). Do not infer consent from "ok"/"looks good"/silence. The question must be send-specific.
2. **Claude Code permission gate.** When you Bash `line-oa send`, Claude Code prompts again. Additive, not a substitute.

Rules:
- One `send` per turn. If the user asks for several, draft all, send sequentially with separate confirmations.
- Read the chat with `line-oa read` before drafting. No cold drafts.
- On `send` failure, do NOT retry without re-confirming. A network error does not prove the message didn't arrive.
- Match the OA's voice from prior `Account`-sender messages: language (Thai unless chat is non-Thai), tone, particles (ค่ะ/ครับ), emoji habits.
- **`send` flips the chat to manual mode for 60 minutes** (auto-revert after). The OA's automated responses are paused for that chat during the window. Mention this in your confirmation prompt, especially when the user may not expect the side effect. Override with `--manual-ttl-minutes N`.

## CLI surface

| Command | Purpose |
|---|---|
| `line-oa list [--waiting] [--since-days N] [--limit N] [--folder ALL\|UNREAD\|PINNED] [--raw]` | List chats |
| `line-oa read CHAT_ID [--backward TOK] [--all] [--raw]` | Read messages, newest first |
| `line-oa profile CHAT_ID [--raw]` | Customer profile |
| `line-oa send CHAT_ID TEXT [--dry-run] [--manual-ttl-minutes N] [--raw]` | Send text reply (TEXT="-" reads stdin). Auto-flips chat to manual mode. |
| `line-oa account list \| use NAME \| add NAME BOTID \| remove NAME` | OA registry |
| `line-oa auth from-curl` | Refresh cookies (cURL on stdin) |
| `line-oa auth status` | Check session is alive |
| `line-oa export` | Bulk CSV download (rarely needed in CS work) |

All read/write verbs emit JSON to stdout. `--account NAME` overrides current account on any command.

## Planning multi-step work — query the schema first

Before writing jq filters or chaining commands, run `line-oa <verb> --help` for any data-producing verb (`list`, `read`, `profile`, `send`). The `--help` epilog documents the curated output shape, field semantics, and useful jq one-liners. Do this once at the start of a plan — don't guess field names from memory.

Curated shapes (default) are stable and CS-focused: `chatId`, `name`, `unread`, `done`, `followedUp`, `latest.{from,type,text,timestamp}` on chats; `id`, `from`, `type`, `text`, `timestamp` on messages. The `from` field on a chat/message is always one of:

- `"customer"` — the customer sent it
- `"manual"` — a human OA operator sent it (web console or CLI)
- `"automated"` — the OA's auto-response sent it (LINE bizId `__AUTO_RESPONSE`)

Pass `--raw` only when the curated shape lacks a field you need (e.g. delivery-receipt timestamps `userLastReadAt`, tags, mute state, quote tokens). Defaulting to `--raw` is wasteful — it adds ~15 noisy fields per chat to your context.

## Exit codes — handle these distinctly

| Code | What it means | What to do |
|---|---|---|
| 0 | ok | continue |
| 1 | generic error | read stderr, tell user |
| 2 | **session expired** | tell user: `pbpaste \| line-oa auth from-curl`. Stop running other commands — they'll all fail the same way. |
| 3 | chat not found | check the chatId, ask user if wrong |
| 4 | rate limited | back off, tell user, do not auto-retry tightly |
| 5 | **no account selected** | tell user: `line-oa account add <name> <botId>` (first time) or `line-oa account use <name>` (switch) |

## First-time onboarding

Walk the user through one step at a time. Don't run all in one Bash call — let each succeed first.

1. Install: `uv tool install git+https://github.com/Theme34090/line-oa-chat-exporter.git`
2. Get a cURL: chat.line.biz → DevTools → Network → right-click any request → Copy → Copy as cURL. Then `pbpaste | line-oa auth from-curl`.
3. From step 2 output, copy the printed `botId`. Then `line-oa account add <chosen-alias> <botId>`.
4. Smoke: `line-oa list --limit 1`.

## Daily cookie refresh

When commands start returning exit 2: `pbpaste | line-oa auth from-curl`. Tell the user what to do; don't try to refresh on their behalf without the fresh cURL.

## Things NOT to do

- Don't volunteer to send unprompted ("would you like me to reply?"). CS initiates.
- Don't loop over many chats and call `send`. Bulk-send is not in v1.
- Don't claim a feature exists if it's not in the surface above. Tag/note/assign/search are not built — say so and offer to file it as a feature request.
- Don't dump raw JSON to the user. Summarize; offer JSON on request.
- Don't fabricate facts about a customer beyond what `read` and `profile` returned.

## Recommended permission allowlist

The user can add this to `~/.claude/settings.json` to skip prompts on read-only verbs:

```json
{ "permissions": { "allow": [
  "Bash(line-oa list:*)",
  "Bash(line-oa read:*)",
  "Bash(line-oa profile:*)",
  "Bash(line-oa account list:*)",
  "Bash(line-oa account use:*)",
  "Bash(line-oa auth status:*)"
]}}
```

Do **not** allowlist `line-oa send` (every send must prompt) or `line-oa auth from-curl` (cookies on stdin should be visible to the user).
