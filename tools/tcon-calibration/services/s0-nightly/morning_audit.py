#!/usr/bin/env python3
"""Morning audit after an S0 bake (Claude, v2; replaces the Codex draft). Offline: reads saved captures only.
PASS requires all of:
  1 generation: the new stored D4 generation is newer than the reference capture's.
  2 untrimmed columns (outside 1248-1268 and +/-3 columns around every lane trimmed in this or the previous bake):
    per channel, new - ref minus the channel's median shift is within max(15 counts, 5 * MAD) at every column.
  3 trimmed columns: new D4 median >= local healthy reference - floor (plan floor_below_ref, default 150 counts), i.e.
    no column gets much more compensation drive than healthy (over-trim = bright line / near-black glow).
  4 C1: live C1 row 0 (DDR capture) == new D4 row 0 - 2047 at every checked column 1250-1290 (the stock rebuild ran).
  5 band (v3, CONSULT-12: the stock vertical-line repair can flip 1255 or leave 1261 unrepaired), columns 1254-1262:
    a with --band-delta: |new - ref - channel shift| <= 10 counts R/G, 15 B (ref = last passed scan, same words);
    b always: R/G excess (new - local healthy reference) >= --band-min (default -30; below = bright line).
Any exception = FAIL. Usage: morning_audit.py --ref D4NAME --new D4NAME --c1 C1NAME --lanes 628,629 [--prev-lanes 640]
[--floor 150] [--band-delta] [--band-min -30] [--json OUT].
Exit 0 = PASS, 3 = only band checks failed (soft: may be a one-scan repair flip), 1 = any other FAIL (2 = argparse usage)."""
import argparse, json, sys
from pathlib import Path
import numpy as np
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tcon'))   # bake_eval.py
import bake_eval as BE

SKIP = (1248, 1268)
BAND = range(1254, 1263)
BAND_TOL = (10.0, 10.0, 15.0)                              # R, G, B

def lane_cols(lanes, pad=0):
    s = set()
    for L in lanes:
        s.update(range(2 * L - pad, 2 * L + 2 + pad))
    return s

def audit(ref, new, c1row0, lanes, prev_lanes, floor, band_delta=False, band_min=-30.0):
    out = dict(ref=ref.info(), new=new.info(), lanes=lanes, prev_lanes=prev_lanes, floor_below_ref=floor, fails=[], band_fails=[])
    g_ref, g_new = ref.generations[ref.bank], new.generations[new.bank]
    out['generation'] = [g_ref, g_new]
    if not g_new > g_ref: out['fails'].append(f'generation not newer ({g_ref} -> {g_new})')
    # 2 untrimmed drift
    mask = np.ones(BE.WIDTH, bool); mask[SKIP[0]:SKIP[1] + 1] = False
    for c in lane_cols(lanes + prev_lanes, pad=3):
        if 0 <= c < BE.WIDTH: mask[c] = False
    drift = {}
    for k, col in enumerate(BE.COLOURS):
        d = new.medians[k] - ref.medians[k]; shift = float(np.median(d[mask])); r = d - shift
        mad = float(np.median(np.abs(r[mask]))); tol = max(15.0, 5 * mad)
        bad = np.flatnonzero(mask & (np.abs(r) > tol))
        drift[col] = dict(shift=round(shift, 2), mad=round(mad, 2), tol=round(tol, 1), bad=bad.tolist()[:20], n_bad=int(bad.size))
        if bad.size: out['fails'].append(f'{col}: {bad.size} untrimmed columns drifted > {tol:.0f} counts (e.g. {bad.tolist()[:5]})')
    out['drift'] = drift
    # 3 trimmed floor
    nref = BE.local_reference(new.medians); trimmed = {}
    for c in sorted(lane_cols(lanes)):
        row = {}
        for k, col in enumerate(BE.COLOURS):
            below = float(nref[k, c] - new.medians[k, c]); row[col] = dict(d4=round(float(new.medians[k, c]), 1),
                                                                          excess=round(-below, 1))
            if below > floor: out['fails'].append(f'over-trim col {c} {col}: {below:.0f} counts below healthy (> {floor})')
        trimmed[c] = row
    out['trimmed'] = trimmed
    # 4 C1 rebuilt from the new D4
    expect = new.row0[:, BE.C1_COLUMNS] - BE.D4_TO_C1
    mism = int(np.sum(c1row0 != expect)); out['c1_mismatches'] = mism
    if mism: out['fails'].append(f'C1 != D4 - 2047 at {mism} of {expect.size} checked values')
    # 5 band columns
    band = {}; cols = sorted(set(BAND) | {c for c in lane_cols(lanes, pad=2) if 0 <= c < BE.WIDTH})   # every trimmed lane too
    out['band_columns'] = cols
    for k, col in enumerate(BE.COLOURS):
        for c in cols:
            ex = float(new.medians[k, c] - nref[k, c]); row = band.setdefault(c, {}); row[col] = dict(excess=round(ex, 1))
            if band_delta:
                dd = float(new.medians[k, c] - ref.medians[k, c]) - drift[col]['shift']; row[col]['delta'] = round(dd, 1)
                if abs(dd) > BAND_TOL[k]: out['band_fails'].append(f'band col {c} {col}: moved {dd:+.0f} vs ref (> {BAND_TOL[k]:.0f})')
            if col != 'B' and ex < band_min: out['band_fails'].append(f'band col {c} {col}: excess {ex:.0f} < {band_min:.0f} (bright line)')
    out['band'] = band
    out['verdict'] = 'PASS' if not out['fails'] and not out['band_fails'] else ('BAND' if not out['fails'] else 'FAIL')
    return out

def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument('--ref', required=True, type=BE.capture_name); a.add_argument('--new', required=True, type=BE.capture_name)
    a.add_argument('--c1', required=True, type=BE.capture_name); a.add_argument('--lanes', required=True)
    a.add_argument('--prev-lanes', default=''); a.add_argument('--floor', type=float, default=150.0); a.add_argument('--json')
    a.add_argument('--band-delta', action='store_true'); a.add_argument('--band-min', type=float, default=-30.0)
    x = a.parse_args()
    try:
        lanes = [int(v) for v in x.lanes.split(',') if v]; prev = [int(v) for v in x.prev_lanes.split(',') if v]
        res = audit(BE.read_d4(x.ref), BE.read_d4(x.new), BE.read_c1(x.c1), lanes, prev, x.floor, x.band_delta, x.band_min)
    except Exception as e:
        res = dict(verdict='FAIL', fails=[f'audit error {type(e).__name__}: {e}'])
    txt = json.dumps(res, indent=1)
    if x.json: Path(x.json).write_text(txt)
    print(json.dumps(dict(verdict=res['verdict'], fails=res['fails'], band_fails=res.get('band_fails', [])[:8], generation=res.get('generation'))))
    return {'PASS': 0, 'BAND': 3}.get(res['verdict'], 1)

if __name__ == '__main__':
    sys.exit(main())
