#!/bin/bash
# After an on-demand bake (Claude 2026-11-19): wait for watcher MASKED after the TV is back on (only if a blackout watcher is
# configured), read stored D4 + live C1, evaluate against the previous bake, photograph vs the previous photo set, blank the
# player. Paths come from config.py (work_dir); the previous tag needs captures d4-PREV, c1-ddr-PREV and optical/post-PREV
# (make them with the baseline step in GUIDE.md before the first bake).
# usage: after_now.sh TAG PREV_TAG   e.g. after_now.sh bake3 bake2
set -u
K=$(cd "$(dirname "$0")" && pwd)                       # tcon/
cd "$K"
WORK=$(python3 -B ../config.py get work_dir); CAP=$(python3 -B ../config.py get captures)
WD=$(python3 -B ../config.py get watcher_dir); WEN=$(python3 -B ../config.py get watcher_enabled)
T=$1; P=$2; L=$WORK/after_$T.log; W=$WD/watcher-v3.log
say() { echo "$(date -u +%FT%TZ) $*" | tee -a "$L"; }
start=$(date -u +%s); last='watcher not configured'
if [ "$WEN" = 1 ]; then
  for i in $(seq 1 90); do
    last=$(grep -- '-> MASKED' "$W" | tail -1)
    ts=$(date -u -d "${last:0:19}" +%s 2>/dev/null || echo 0)
    [ "$ts" -ge $((start - 300)) ] && [ ! -e "$WD/watcher.pause" ] && break
    sleep 10
  done
fi
say "watcher: $last"
sleep 30
say "d4store"; python3 -B d4store.py live d4-$T > "$CAP/d4-$T.json" 2>> "$L"; say "d4store rc=$?"
R=$(python3 -c "print(','.join(f'{0x755b8000+n*0x388400:x}:fe000' for n in range(12)))")
rm -rf "$CAP/c1-ddr-$T"
say "c1 read"; python3 -B tvdump.py --name c1-ddr-$T --chunk 4096 --budget-ms 15000 --ranges $R > /dev/null 2>> "$L"; say "c1 rc=$?"
python3 -B bake_eval.py --old d4-$P --new d4-$T --c1-old c1-ddr-$P --c1-new c1-ddr-$T > "$CAP/eval-$T.txt" 2>> "$L"; say "eval rc=$?"
for k in 1 2; do
  python3 -B ../measure/postbake.py post-$T --ref post-$P >> "$L" 2>&1 && { say "photos ok"; break; }
  say "photos failed (attempt $k); switching TV to the player and retrying"
  python3 -B -c 'import sys; sys.path.insert(0, "../measure"); import optical; print(optical.ug("kodi-send --action=\"CECActivateSource\""))' >> "$L" 2>&1; sleep 25
done
python3 -B -c 'import sys; sys.path.insert(0, "../measure"); import optical; print("blank", optical.stop())' >> "$L" 2>&1
say "after_now done"
