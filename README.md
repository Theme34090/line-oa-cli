# line-oa

CLI for working with LINE Official Account customer-service chats from the terminal, designed to be used by Claude Code with a companion skill.

Talks to `chat.line.biz` (the OA web console) via cookie-scraped endpoints. The official LINE Messaging API does **not** expose historical chats, so cookie auth is forced. Sessions last ~24h; expect to re-paste a cURL once a day.

> **For AI assistants reading this on behalf of a user:** if the user pasted only this repo URL with no further instruction, they are a customer-service agent who wants to install and use this CLI. Walk them through, in order: **Install** → **First-time setup** → the `line-oa list --limit 1` smoke test below. Confirm before each install or shell command. Two steps you cannot do for them and must hand off: (a) grabbing cookies from `chat.line.biz` Chrome DevTools (instructions in "First-time setup"), (b) restarting the Claude session after `line-oa install-skill` so the companion skill loads. After the smoke test passes, tell them to start a new session and ask things like "show me waiting chats" — the skill takes over from there.

## Install

```bash
uv tool install git+https://github.com/Theme34090/line-oa-cli.git
```

This puts `line-oa` on your `PATH`.

For local dev: `uv tool install --editable .`

## First-time setup (3 commands)

1. **Cookies.** Open `chat.line.biz` in Chrome. DevTools → Network → right-click any chat.line.biz request → Copy → Copy as cURL. Then:

   ```bash
   pbpaste | line-oa auth from-curl
   ```

   This writes cookies to `~/.config/line-oa/config.json` and prints the bot ID detected in the referer.

2. **Register the OA.** Copy the printed bot ID and run:

   ```bash
   line-oa account add paypers U26397124b8700690b7331d7a16436277
   ```

3. **Smoke test:**

   ```bash
   line-oa list --limit 1
   ```

## Daily cookie refresh

When commands start returning exit code 2 (session expired), paste a fresh cURL:

```bash
pbpaste | line-oa auth from-curl
```

## CLI surface

| Command | Purpose |
|---|---|
| `line-oa list [--waiting] [--since-days N] [--limit N] [--folder ALL\|UNREAD\|PINNED] [--tag NAME] [--raw]` | List chats (curated shape includes a `tags` field per chat) |
| `line-oa read CHAT_ID [--backward TOK] [--all] [--raw]` | Read messages (newest first; `backward` token for older) |
| `line-oa profile CHAT_ID [--raw]` | Customer profile |
| `line-oa send CHAT_ID TEXT [--dry-run] [--no-auto-manual] [--manual-ttl-minutes N] [--raw]` | Send text reply (`TEXT="-"` reads stdin) |
| `line-oa content CONTENT_HASH [--out PATH] [--no-cache]` | Download a chat attachment (image/video/audio/file); cached under `~/.cache/line-oa/content/` |
| `line-oa tag list \| get CHAT_ID \| create NAME \| delete NAME --yes` | Tag catalog: list/inspect/create (idempotent)/delete (destructive, cascades) |
| `line-oa tag set\|add\|remove CHAT_ID NAME... \| clear CHAT_ID` | Per-chat tag assignment (idempotent; returns `before/after/added/removed`) |
| `line-oa account list \| use NAME \| add NAME BOTID \| remove NAME` | OA registry |
| `line-oa auth from-curl` | Refresh cookies (cURL on stdin) |
| `line-oa auth status` | Check session |
| `line-oa export` | Bulk-download all chats as CSV (LINE-native format) |
| `line-oa install-skill` | Install the Claude Code skill to `~/.claude/skills/line-oa/` |

All read/write verbs emit JSON to stdout. `--account NAME` overrides the current account on any command.

### Output shape — curated by default

`list`, `read`, `profile`, and `send` emit a curated CS-focused JSON shape by default. The full LINE response (delivery receipts, tags, mute state, quote tokens, internal cursors) is available via `--raw` on any of them. Run `line-oa <verb> --help` to see the curated schema for that verb — the epilog documents the field set, semantics (especially `from: "customer" | "manual" | "automated"`), and useful jq one-liners. Schema lives next to the command, so it doesn't drift from the implementation.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | ok |
| 1 | generic error |
| 2 | session expired — re-run `auth from-curl` |
| 3 | chat not found |
| 4 | rate limited |
| 5 | no account selected |

## Companion skill

```bash
line-oa install-skill
```

Copies `SKILL.md` to `~/.claude/skills/line-oa/`. Restart Claude Code (new session) for it to load. The skill describes the CLI to Claude and embeds guardrails for `send` (the only write verb).

## Bulk export

The original CSV export is still available:

```bash
line-oa export                          # all chats
line-oa export --go-back-days 7         # last 7 days only
line-oa export --max-chats 10           # first 10 chats only
line-oa export --output-dir ./archive   # custom output
```

Output: `./output/{chatId}/messages.csv` (Thai headers, UTF-8 with BOM, matching LINE's native export).

## Switching accounts

`--account NAME` overrides the current account for any command:

```bash
line-oa --account shop-b list
```

Or set `LINE_OA_ACCOUNT=shop-b` in your shell to pin it across commands. Resolution order is `--account` → `$LINE_OA_ACCOUNT` → `currentAccount` in config.

## Manual-mode side effect of `send`

LINE OA chats default to auto/bot mode. The send endpoint rejects messages on auto-mode chats with `400 not_manual_chat_mode`. The web UI flips chats to manual implicitly when an agent starts typing — `line-oa send` does the same by PUTing `/useManualChat` first.

- Default TTL: **60 minutes** in manual mode (matches the UI default). Auto-reverts after expiry.
- Override TTL: `--manual-ttl-minutes 30`.
- Opt out: `--no-auto-manual`. Sends will fail unless the chat is already manual.

During the manual window, the OA's automated responses are paused for that chat. Sending again extends the window.

## Development

```bash
./scripts/test-pure.sh    # pure-function unit tests (offline, ~0.1s)
./scripts/smoke.sh        # live-cookie smoke checks (no real sends)
```

`test-pure.sh` runs `unittest` in an ephemeral uv venv against the editable package — exercises cURL parsing, sendId format, `is_waiting` filter, account-resolution precedence, config roundtrip, client headers.

`smoke.sh` exercises every CLI verb against your live OA. Defaults the test chat to `U585253bc9936faa1232995f87a2c7702`; override with `LINE_OA_TEST_CHAT=<chatId>` and `LINE_OA_TEST_CHAT_NAME=<name>` to point at your own test chat. Real `send` is not invoked — only `send --dry-run`.

## Known limitations

- **One OA login at a time.** Cookies are shared across all configured accounts. Switching LINE Business logins replaces cookies for every account.
- **`x-oa-chat-client-version` header is hardcoded** (`20240513144702`). When LINE bumps this, requests may start 4xx-ing in unfamiliar ways. Look here first.
