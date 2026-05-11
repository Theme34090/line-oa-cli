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
print(json.load(sys.stdin).get('profile', {}).get('name', ''))
")
if [ "$NAME" = "$EXPECTED_NAME" ]; then
    green "profile.name == '$EXPECTED_NAME'"
    PASS=$((PASS+1))
else
    red "profile.name expected '$EXPECTED_NAME', got '$NAME'"
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
