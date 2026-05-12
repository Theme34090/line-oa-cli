#!/usr/bin/env bash
# Live-cookie smoke test for the line-oa CLI.
#
# Run after changes that could affect API surface. Requires:
#   - line-oa on PATH (uv tool install --editable . or release install)
#   - a configured account with live cookies
#       line-oa auth status   -> alive
#   - a test chat designated via $LINE_OA_TEST_CHAT (default: Theme's chat)
#
# Skips REAL sends. Tests `send --dry-run` only. To do a real send,
# run it by hand and inspect.
set -uo pipefail

TEST_CHAT="${LINE_OA_TEST_CHAT:-U585253bc9936faa1232995f87a2c7702}"
EXPECTED_NAME="${LINE_OA_TEST_CHAT_NAME:-Theme}"

PASS=0
FAIL=0
SKIP=0

green()   { printf '\033[32mPASS\033[0m %s\n' "$*"; }
red()     { printf '\033[31mFAIL\033[0m %s\n' "$*"; }
yellow()  { printf '\033[33mSKIP\033[0m %s\n' "$*"; }
heading() { printf '\n=== %s ===\n' "$*"; }

# check LABEL EXPECTED_EXIT CMD...
check() {
    local label="$1"; shift
    local expected="$1"; shift
    "$@" > /tmp/line-oa-smoke.out 2> /tmp/line-oa-smoke.err
    local got=$?
    if [ "$got" -eq "$expected" ]; then
        green "$label (exit=$got)"
        PASS=$((PASS+1))
    else
        red "$label (expected exit=$expected, got=$got)"
        sed 's/^/    /' /tmp/line-oa-smoke.err
        FAIL=$((FAIL+1))
    fi
}

heading "Preflight"
if ! command -v line-oa >/dev/null 2>&1; then
    red "line-oa not on PATH; install with: uv tool install --editable ."
    exit 1
fi
green "line-oa on PATH ($(command -v line-oa))"

if ! line-oa auth status > /tmp/line-oa-smoke.out 2>&1; then
    red "auth status not alive — refresh cookies first:"
    red "  pbpaste | line-oa auth from-curl"
    exit 1
fi
green "session alive"

heading "Account"
check "account list" 0 line-oa account list

heading "List"
check "list --limit 3" 0 line-oa list --limit 3
check "list --waiting --limit 3" 0 line-oa list --waiting --limit 3
check "list --since-days 7 --limit 5" 0 line-oa list --since-days 7 --limit 5

heading "Read"
check "read first page" 0 line-oa read "$TEST_CHAT"
check "read --all" 0 line-oa read "$TEST_CHAT" --all

heading "Profile"
check "profile" 0 line-oa profile "$TEST_CHAT"

NAME=$(line-oa profile "$TEST_CHAT" 2>/dev/null | python3 -c "
import json, sys
print(json.load(sys.stdin).get('name', ''))
")
if [ "$NAME" = "$EXPECTED_NAME" ]; then
    green "profile.name (curated) == '$EXPECTED_NAME'"
    PASS=$((PASS+1))
else
    red "profile.name (curated) expected '$EXPECTED_NAME', got '$NAME'"
    FAIL=$((FAIL+1))
fi

check "profile --raw" 0 line-oa profile "$TEST_CHAT" --raw
RAW_NAME=$(line-oa profile "$TEST_CHAT" --raw 2>/dev/null | python3 -c "
import json, sys
print(json.load(sys.stdin).get('profile', {}).get('name', ''))
")
if [ "$RAW_NAME" = "$EXPECTED_NAME" ]; then
    green "profile.profile.name (--raw) == '$EXPECTED_NAME'"
    PASS=$((PASS+1))
else
    red "profile.profile.name (--raw) expected '$EXPECTED_NAME', got '$RAW_NAME'"
    FAIL=$((FAIL+1))
fi

heading "Curated shape asserts"
CURATED_KEYS=$(line-oa list --limit 1 2>/dev/null | python3 -c "
import json, sys
chats = json.load(sys.stdin).get('chats', [])
print(','.join(sorted(chats[0].keys())) if chats else '')
")
EXPECTED_CURATED="chatId,done,followedUp,lastReceivedAt,latest,name,unread"
if [ "$CURATED_KEYS" = "$EXPECTED_CURATED" ]; then
    green "list curated chat keys exactly: $EXPECTED_CURATED"
    PASS=$((PASS+1))
else
    red "list curated keys drifted. expected '$EXPECTED_CURATED', got '$CURATED_KEYS'"
    FAIL=$((FAIL+1))
fi

FROM_VALUES=$(line-oa list --limit 25 2>/dev/null | python3 -c "
import json, sys
chats = json.load(sys.stdin).get('chats', [])
froms = {c.get('latest', {}).get('from') for c in chats if c.get('latest')}
print(','.join(sorted(f for f in froms if f)))
")
case ",$FROM_VALUES," in
    *",customer,"*|*",manual,"*|*",automated,"*)
        green "list latest.from contains expected categories: $FROM_VALUES"
        PASS=$((PASS+1))
        ;;
    *)
        red "list latest.from missing all expected categories. got: $FROM_VALUES"
        FAIL=$((FAIL+1))
        ;;
esac

heading "Content fetch"
HASH=$(line-oa list --limit 30 2>/dev/null | python3 -c "
import json, subprocess, sys
chats = json.load(sys.stdin).get('chats', [])
for c in chats:
    if (c.get('latest') or {}).get('type') == 'image':
        out = subprocess.run(['line-oa', 'read', c['chatId']],
                             capture_output=True, text=True)
        if out.returncode != 0:
            continue
        for m in json.loads(out.stdout).get('messages', []):
            if m.get('type') == 'image' and m.get('contentHash'):
                print(m['contentHash']); sys.exit(0)
")
if [ -n "$HASH" ]; then
    if line-oa content "$HASH" > /tmp/line-oa-smoke.out 2> /tmp/line-oa-smoke.err; then
        PATH_VAL=$(python3 -c "import json,sys; print(json.load(open('/tmp/line-oa-smoke.out')).get('path',''))")
        BYTES=$(python3 -c "import json,sys; print(json.load(open('/tmp/line-oa-smoke.out')).get('bytes',0))")
        if [ -f "$PATH_VAL" ] && [ "$BYTES" -gt 0 ]; then
            green "content fetch wrote $BYTES bytes to $PATH_VAL"
            PASS=$((PASS+1))
        else
            red "content fetch: missing file or zero bytes (path=$PATH_VAL bytes=$BYTES)"
            FAIL=$((FAIL+1))
        fi
        # second call should report cached=true
        CACHED=$(line-oa content "$HASH" 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('cached'))")
        if [ "$CACHED" = "True" ]; then
            green "content fetch second call cached=True"
            PASS=$((PASS+1))
        else
            red "content fetch second call expected cached=True, got '$CACHED'"
            FAIL=$((FAIL+1))
        fi
    else
        red "content fetch errored"
        sed 's/^/    /' /tmp/line-oa-smoke.err
        FAIL=$((FAIL+1))
    fi
else
    yellow "no image in latest 30 chats — skipping content fetch check"
    SKIP=$((SKIP+1))
fi

heading "Search"
check "search --type profile 'Theme'" 0 line-oa search "$EXPECTED_NAME" --type profile --limit 5
PROFILE_HIT_NAMES=$(line-oa search "$EXPECTED_NAME" --type profile --limit 5 2>/dev/null | python3 -c "
import json, sys
hits = json.load(sys.stdin).get('hits', [])
print(','.join(h.get('name','') for h in hits))
")
case ",$PROFILE_HIT_NAMES," in
    *",$EXPECTED_NAME,"*)
        green "profile search returns '$EXPECTED_NAME' in hits"
        PASS=$((PASS+1))
        ;;
    *)
        red "profile search missing '$EXPECTED_NAME'. got: $PROFILE_HIT_NAMES"
        FAIL=$((FAIL+1))
        ;;
esac

MSG_QUERY="smoke test from line-oa CLI"
check "search --type message '$MSG_QUERY'" 0 line-oa search "$MSG_QUERY" --type message --limit 5
MSG_HIT_NAMES=$(line-oa search "$MSG_QUERY" --type message --limit 5 2>/dev/null | python3 -c "
import json, sys
hits = json.load(sys.stdin).get('hits', [])
print(','.join(h.get('name','') for h in hits))
")
case ",$MSG_HIT_NAMES," in
    *",$EXPECTED_NAME,"*)
        green "message search returns '$EXPECTED_NAME' in hits"
        PASS=$((PASS+1))
        ;;
    *)
        red "message search missing '$EXPECTED_NAME'. got: $MSG_HIT_NAMES"
        FAIL=$((FAIL+1))
        ;;
esac

SEARCH_KEYS=$(line-oa search "$EXPECTED_NAME" --type profile --limit 1 2>/dev/null | python3 -c "
import json, sys
hits = json.load(sys.stdin).get('hits', [])
print(','.join(sorted(hits[0].keys())) if hits else '')
")
EXPECTED_SEARCH_KEYS="chatId,done,followedUp,foundMessagesCount,lastReceivedAt,latest,name,unread"
if [ "$SEARCH_KEYS" = "$EXPECTED_SEARCH_KEYS" ]; then
    green "search curated hit keys exactly: $EXPECTED_SEARCH_KEYS"
    PASS=$((PASS+1))
else
    red "search curated keys drifted. expected '$EXPECTED_SEARCH_KEYS', got '$SEARCH_KEYS'"
    FAIL=$((FAIL+1))
fi

heading "Send (dry-run only — real sends not tested here)"
check "send --dry-run (auto-manual)" 0 line-oa send "$TEST_CHAT" "smoke" --dry-run
check "send --dry-run --no-auto-manual" 0 line-oa send "$TEST_CHAT" "smoke" --dry-run --no-auto-manual

heading "Error paths"
TMP_EMPTY=$(mktemp)
trap 'rm -f "$TMP_EMPTY" "$TMP_BAD"' EXIT
echo '{}' > "$TMP_EMPTY"
check "empty config => exit 5" 5 line-oa --config "$TMP_EMPTY" list

TMP_BAD=$(mktemp)
python3 - "$TMP_BAD" <<'PY'
import json, os, pathlib, sys
src = pathlib.Path(os.path.expanduser("~/.config/line-oa/config.json"))
cfg = json.loads(src.read_text())
cfg["cookies"] = dict(cfg["cookies"])
cfg["cookies"]["__Host-chat-ses"] = "BROKEN"
pathlib.Path(sys.argv[1]).write_text(json.dumps(cfg))
PY
check "broken cookies => exit 2" 2 line-oa --config "$TMP_BAD" auth status

heading "Summary"
TOTAL=$((PASS + FAIL + SKIP))
printf "%d/%d passed" "$PASS" "$TOTAL"
[ "$SKIP" -gt 0 ] && printf " (%d skipped)" "$SKIP"
[ "$FAIL" -gt 0 ] && printf " (%d failed)" "$FAIL"
printf "\n"
[ "$FAIL" -eq 0 ]
