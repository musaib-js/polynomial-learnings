#!/usr/bin/env bash
# End-to-end smoke test: signup -> agent -> API key -> persist -> retrieve ->
# isolation -> revoke.
#
# Prerequisites: Postgres up, `alembic upgrade head` run, API serving on $API.
#
#   ./scripts/smoke.sh
#
# Exits non-zero on the first unexpected result.

set -euo pipefail

API="${API:-http://127.0.0.1:8000}"
PY="${PY:-.venv/bin/python}"
EMAIL="smoke-$(date +%s)@example.com"
PASSWORD="smoke-password-123"

checks_run=0

pass() { printf '  \033[32mok\033[0m   %s\n' "$1"; checks_run=$((checks_run + 1)); }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; exit 1; }

# expect <description> <actual> <wanted>
# Each caller computes <actual> into a variable first — inlining a command
# substitution here is what broke an earlier version of this script.
expect() {
  local description="$1" actual="$2" wanted="$3"
  if [ "$actual" = "$wanted" ]; then
    pass "$description ($actual)"
  else
    fail "$description: got '$actual', wanted '$wanted'"
  fi
}

# Reads one field out of a JSON body on stdin, e.g. jfield "d['access_token']".
jfield() { "$PY" -c "import sys,json;d=json.load(sys.stdin);print($1)"; }

post_json() { # post_json <url> <body> [auth-header-value] -> body on stdout
  local url="$1" body="$2" auth="${3:-}"
  if [ -n "$auth" ]; then
    curl -s -X POST "$url" -H 'Content-Type: application/json' \
         -H "Authorization: Bearer $auth" -d "$body"
  else
    curl -s -X POST "$url" -H 'Content-Type: application/json' -d "$body"
  fi
}

post_code() { # post_code <url> <body> [auth-header-value] -> status on stdout
  local url="$1" body="$2" auth="${3:-}"
  if [ -n "$auth" ]; then
    curl -s -o /dev/null -w '%{http_code}' -X POST "$url" \
         -H 'Content-Type: application/json' -H "Authorization: Bearer $auth" -d "$body"
  else
    curl -s -o /dev/null -w '%{http_code}' -X POST "$url" \
         -H 'Content-Type: application/json' -d "$body"
  fi
}

echo "API: $API"
echo

# Reachability first, with its own message: without this the script would die
# on curl's exit code alone and say nothing useful about why.
if ! curl -s -o /dev/null --max-time 5 "$API/health"; then
  echo "  Cannot reach $API"
  echo "  Start it with:"
  echo "    set -a; . ./.env; set +a"
  echo "    PYTHONPATH=src .venv/bin/python -m uvicorn learnings.api.app:app --port 8000"
  exit 1
fi

echo "1. health"
status=$(curl -s -o /dev/null -w '%{http_code}' "$API/health")
expect "GET /health" "$status" 200

echo
echo "2. account"
signup_body="{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\",\"name\":\"Smoke\"}"
signup_json=$(post_json "$API/v1/auth/signup" "$signup_body")
jwt=$(printf '%s' "$signup_json" | jfield "d['access_token']")
pass "signed up $EMAIL"

good_login="{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}"
status=$(post_code "$API/v1/auth/login" "$good_login")
expect "login, correct password" "$status" 200

bad_login="{\"email\":\"$EMAIL\",\"password\":\"definitely-wrong\"}"
status=$(post_code "$API/v1/auth/login" "$bad_login")
expect "login, wrong password" "$status" 401

echo
echo "3. agent + key"
# The server mints agent_id; the caller only supplies a display name.
agent_json=$(post_json "$API/v1/dashboard/agents" '{"display_name":"Smoke Agent"}' "$jwt")
agent_id=$(printf '%s' "$agent_json" | jfield "d['agent_id']")
pass "agent $agent_id"

key_json=$(post_json "$API/v1/dashboard/api-keys" '{"name":"smoke key"}' "$jwt")
raw_key=$(printf '%s' "$key_json" | jfield "d.get('raw_key') or d.get('key') or d['api_key']")
key_id=$(printf '%s' "$key_json" | jfield "d.get('id') or d['key_id']")
pass "key ${raw_key:0:16}... (returned once, never stored)"

echo
echo "4. authentication"
probe='{"messages":[{"role":"user","content":"x"}]}'
status=$(post_code "$API/v1/agents/$agent_id/retrieve" "$probe")
expect "no key" "$status" 401
status=$(post_code "$API/v1/agents/$agent_id/retrieve" "$probe" "sk_live_made_up_key")
expect "bogus key" "$status" 401
status=$(post_code "$API/v1/agents/$agent_id/retrieve" "$probe" "$raw_key")
expect "valid key, own agent" "$status" 200

echo
echo "5. isolation"
# 404 rather than 403 on purpose: a 403 would confirm the agent exists.
status=$(post_code "$API/v1/agents/agt_not_yours_00000000/retrieve" "$probe" "$raw_key")
expect "another org's agent" "$status" 404

echo
echo "6. hot path"
lesson='{"messages":[{"role":"user","content":"Always reply in British English, never American spelling."}],"entity_id":"acme"}'
persist_json=$(post_json "$API/v1/agents/$agent_id/persist" "$lesson" "$raw_key")
decision=$(printf '%s' "$persist_json" | jfield "d.get('decision','<none>')")
expect "persist" "$decision" persisted

# Deliberately different wording, so this exercises semantic retrieval.
query='{"messages":[{"role":"user","content":"which spelling convention?"}],"entity_id":"acme","limit":5}'
found_json=$(post_json "$API/v1/agents/$agent_id/retrieve" "$query" "$raw_key")
found=$(printf '%s' "$found_json" | jfield "len(d)")
if [ "$found" -ge 1 ]; then
  pass "retrieve returned $found learning(s) for a differently-worded query"
else
  fail "retrieve returned nothing"
fi

echo
echo "7. revocation"
revoke_status=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
  "$API/v1/dashboard/api-keys/$key_id/revoke" -H "Authorization: Bearer $jwt")
expect "revoke" "$revoke_status" 200
status=$(post_code "$API/v1/agents/$agent_id/retrieve" "$probe" "$raw_key")
expect "same key after revoke" "$status" 401

echo
printf '\033[32mAll %d checks passed.\033[0m Agent used: %s\n' "$checks_run" "$agent_id"
