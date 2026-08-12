#!/usr/bin/env bash
# Walk DEMO_GUIDE cases against a running API (Module A oral-demo acceptance).
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
auth_required="$(curl -sf "$BASE/health" | python3 -c "import sys,json; print(json.load(sys.stdin).get('auth_required'))")"
if [[ "$auth_required" == "True" ]]; then
  if [[ -z "$KEY" ]]; then
    echo "FAIL: auth_required but no ANIMA_API_KEY" >&2
    exit 1
  fi
  hdr+=(-H "X-API-Key: $KEY")
fi

echo "Base: $BASE  auth_required=$auth_required"
pass=0
fail=0

run() {
  local name="$1" expect="$2" body="$3"
  local tmp code status intercepted
  tmp="$(mktemp)"
  code="$(curl -s -o "$tmp" -w "%{http_code}" -X POST "$BASE/v1/triage/query" "${hdr[@]}" -d "$body")"
  if [[ "$code" != "200" ]]; then
    echo "[FAIL] $name HTTP $code"
    cat "$tmp" >&2 || true
    rm -f "$tmp"
    fail=$((fail + 1))
    return
  fi
  status="$(python3 -c "import json; print(json.load(open('$tmp')).get('red_light_status'))")"
  intercepted="$(python3 -c "import json; print(json.load(open('$tmp')).get('intercepted'))")"
  if [[ "$status" == "$expect" ]]; then
    echo "[PASS] $name → $status intercepted=$intercepted"
    pass=$((pass + 1))
  else
    echo "[FAIL] $name expected $expect got $status"
    fail=$((fail + 1))
  fi
  rm -f "$tmp"
}

run "1_normal_hr_green" "GREEN" \
  '{"question":"小狗正常心率是多少？运动后呼吸有点快，有点担心。","species":"dog","size":"small","heart_rate_bpm":95,"crt_seconds":1.5,"rectal_temp_f":101.8}'
run "2a_heat_mild_yellow" "YELLOW" \
  '{"question":"中暑怎么办？散步后喘气、流口水，仍清醒能走。","species":"dog","size":"large","heart_rate_bpm":120,"crt_seconds":1.5,"rectal_temp_f":102.8}'
run "2b_heat_severe_red" "RED" \
  '{"question":"中暑怎么办？爬山后虚脱、站不起来了，体温很高。","species":"dog","size":"large","heart_rate_bpm":170,"crt_seconds":1.5,"rectal_temp_f":105.2}'
run "3_chocolate_yellow" "YELLOW" \
  '{"question":"小狗吃了巧克力，精神还行，有点担心。","species":"dog","size":"small"}'
run "4_poison_red" "RED" \
  '{"question":"狗狗中毒怎么办？刚才吃了老鼠药，还在呕吐。","species":"dog"}'
run "5_lily_red" "RED" \
  '{"question":"猫吃了百合叶子，现在在吐。","species":"cat"}'

echo
echo "DEMO_GUIDE smoke: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
