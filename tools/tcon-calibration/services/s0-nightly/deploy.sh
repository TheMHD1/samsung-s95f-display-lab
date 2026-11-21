#!/bin/bash
# Deploy the reviewed s0svc (Claude 2026-11-19, v3: any lanes, per-column words 0xHHHHLLLL). usage: deploy.sh LANE=WORD[,LANE=WORD...] REF_D4_CAPTURE
# e.g. deploy.sh 628=0x3055,629=0x3055,630=0x3E96 d4-bake8
#   REF = the D4 capture of the on-demand bake that used exactly these words (seeded as the audit reference).
# Paths from config.py: state in <work>/s0svc (plan.json must exist with pinned helper_sha256: see GUIDE.md), captures in
# <work>/captures. Starts the s0-nightly unit (installed by services/install_unit.sh).
set -euo pipefail
SRC=$(cd "$(dirname "$0")" && pwd); K=$(cd "$SRC/../.." && pwd)
S0=$(python3 -B "$K/config.py" get s0svc); CAP=$(python3 -B "$K/config.py" get captures)
mkdir -p "$S0"; cd "$S0"
WORDS=$1; REF=$2
[ -d "$CAP/$REF" ] || { echo "no capture $REF"; exit 1; }
[ -f plan.json ] || { echo "no $S0/plan.json: copy examples/s0-plan-bake11.json there and pin the helper (tcon/pin_helper.py scan-arm)"; exit 1; }
for u in s95f-arm-keep s95f-arm-bake2 s0-nightly; do systemctl --user stop $u 2>/dev/null || true; done
pgrep -f '^python3 -B [a]rm_wake|[b]ake_now.py' && { echo 'another arm tool is running'; exit 1; } || true
python3 - "$WORDS" "$REF" "$SRC" <<'PY'
import json, sys, pathlib
words, ref, src = sys.argv[1:4]
pairs = [kv.split('=') for kv in words.split(',')]; lanes = dict(pairs)
sys.path.insert(0, src); import s0_nightly as N                       # validate BEFORE writing anything (review v3.1)
def bad(m): print('REFUSED:', m); sys.exit(1)                         # explicit checks, not assert (review v3.3)
try: ints = [int(k) for k, _ in pairs]
except ValueError: bad('lane must be a number')
if len(set(ints)) != len(pairs): bad('a lane is listed twice')
lanes = {str(i): w for i, (_, w) in zip(ints, pairs)}
for L, w in lanes.items():                                            # v3: per-column words 0xHHHHLLLL via N.halves
    try: hi, lo = N.halves(w)
    except ValueError as e: bad(e)
    if not (int(L) in N.LANES_OK and all(N.FLOOR <= h <= N.STOCK for h in (hi, lo))): bad(f'lane {L} word {w} outside bounds')
    if not (hi == lo or 626 <= int(L) <= 632): bad(f'lane {L}: unequal halves only on band lanes 626-632 (stricter than bake_now.py: no 640 rider)')
p = pathlib.Path('plan.json'); d = json.loads(p.read_text()); d['lanes'] = lanes
d['note'] = f'deployed {ref}: words from the on-demand bake series'; p.write_text(json.dumps(d, indent=1))
s = {'ref_d4': ref, 'deploy_ref': ref, 'prev_lanes': sorted(lanes), 'ref_words': lanes, 'soft_fails': 0,
     'last_bake': {'id': ref, 'result': 'ok', 'audit': 'pass', 'note': 'seeded at deploy'}}
pathlib.Path('status.json').write_text(json.dumps(s, indent=1)); print('plan', lanes, 'status ref', ref)
PY
python3 -B -c "import sys; sys.path.insert(0, '$SRC'); import s0_nightly as N; p, pokes = N.load_plan(); print('plan ok:', pokes)"
bash "$K/services/install_unit.sh" s0-nightly
systemctl --user reset-failed s0-nightly.service 2>/dev/null || true
systemctl --user enable --now s0-nightly.service
sleep 20; systemctl --user is-active s0-nightly.service; tail -3 s0_nightly.log
