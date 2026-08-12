#!/usr/bin/env bash
# Server-side smoke for the iOS App contract (RED / YELLOW / GREEN + auth).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BASE="${ANIMA_BASE_URL:-http://127.0.0.1:8000}"
KEY="${ANIMA_API_KEY:-}"
if [[ -z "$KEY" && -f .env ]]; then
  KEY="$(python3 -c "from pathlib import Path
for line in Path('.env').read_text().splitlines():
  if line.startswith('ANIMA_API_KEY='):
    print(line.split('=',1)[1].strip()); break")"
fi

hdr=(-H "Content-Type: application/json")
if [[ -n "$KEY" ]]; then
  hdr+=(-H "X-API-Key: $KEY")
fi

echo "Base: $BASE"
health="$(curl -sf "$BASE/health")"
python3 -c "import json,sys; d=json.loads(sys.argv[1]); print('health', d.get('status'), 'auth_required=', d.get('auth_required'))" "$health"

auth_required="$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('auth_required'))" "$health")"
if [[ "$auth_required" == "True" && -z "$KEY" ]]; then
  echo "FAIL: auth_required but ANIMA_API_KEY empty" >&2
  exit 1
fi

if [[ "$auth_required" == "True" ]]; then
  code="$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/v1/triage/query" \
    -H "Content-Type: application/json" \
    -d '{"question":"ping","species":"dog"}')"
  if [[ "$code" != "401" ]]; then
    echo "FAIL: expected 401 without key, got $code" >&2
    exit 1
  fi
  echo "auth: 401 without key OK"
fi

run_case() {
  local name="$1" expect="$2" body="$3"
  local tmp
  tmp="$(mktemp)"
  code="$(curl -s -o "$tmp" -w "%{http_code}" -X POST "$BASE/v1/triage/query" "${hdr[@]}" -d "$body")"
  if [[ "$code" != "200" ]]; then
    echo "FAIL: $name HTTP $code" >&2
    cat "$tmp" >&2
    rm -f "$tmp"
    exit 1
  fi
  python3 - "$tmp" "$name" "$expect" <<'PY'
import json, sys
path, name, expect = sys.argv[1], sys.argv[2], sys.argv[3]
d = json.load(open(path))
status = d.get("red_light_status")
intercepted = d.get("intercepted")
chips = d.get("extracted_symptoms") or []
ok = status == expect
if expect == "RED" and not intercepted:
    ok = False
if expect != "RED" and intercepted:
    ok = False
print(f"[{'PASS' if ok else 'FAIL'}] {name}: status={status} intercepted={intercepted} chips={chips[:6]}")
if not ok:
    sys.exit(1)
PY
  rm -f "$tmp"
}

run_case "yellow_chocolate" "YELLOW" \
  '{"question":"小狗吃了巧克力，精神还行，有点担心。","species":"dog","size":"small"}'
run_case "red_poison" "RED" \
  '{"question":"狗狗中毒怎么办？刚才吃了老鼠药，还在呕吐。","species":"dog"}'
run_case "green_hr" "GREEN" \
  '{"question":"小狗正常心率是多少？运动后呼吸有点快，有点担心。","species":"dog","size":"small","heart_rate_bpm":95,"crt_seconds":1.5,"rectal_temp_f":101.8}'

echo "iOS API smoke: 3/3 OK"
