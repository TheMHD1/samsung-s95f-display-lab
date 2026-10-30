#!/usr/bin/env python3
"""HDR step 2 - refinement rounds on the real profile (patched shader active).

  hdr_round.py <tag> <damp> 0p5,2,15,100 [--state FILE]                    measure + refit
  hdr_round.py <tag> <damp> 0p5,2,15,100 --refit OLDTAG [--weights 2,1,1,1] refit from LOGGED data (no photos)

Each measured ratio error is turned into a PQ correction through the damaged columns' sensitivity
S(P) = d lnY / dP (light change per PQ step at level P, measured during hdr_fit; table below from our panel):
    dP_new = (L - a*P) - damp * ln(ratio) / S(P)
then alpha and the three lifts are refitted per column by (weighted) least squares over all levels:
    dP = L_ch - a*P.
Constraints: 0.05 <= a <= 0.6, 0 <= L <= 0.92*a. Blue uses a 3-column average (blue spreads sideways).
Our final profile was the MIDPOINT of a plain refit and a refit weighted towards 0.5 nits (--weights 2,1,1,1).
"""
import argparse, json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lfcal
import lfconfig as C

# measured sensitivity of the damaged columns (PQ signal -> d ln(light) / dP); re-measure for your panel if possible
S_P = [0.12, 0.188, 0.248, 0.333, 0.508, 0.58]
S_V = [30, 25, 21, 15, 12, 11]
S = lambda P: float(np.interp(P, S_P, S_V))

ap = argparse.ArgumentParser(); ap.add_argument('tag'); ap.add_argument('damp', type=float); ap.add_argument('levels')
ap.add_argument('--state', default=os.path.join(C.HERE, C.CFG['profiles']['hdr']))
ap.add_argument('--refit', default=None, help='use logged measurements of this earlier tag instead of new photos')
ap.add_argument('--weights', default=None)
a = ap.parse_args()
levels = a.levels.split(',')
W = dict(zip(levels, [float(w) for w in a.weights.split(',')])) if a.weights else {L: 1.0 for L in levels}
st = lfcal.load(a.state)
meas = {}
if a.refit:
    for line in open(lfcal.DATA):
        r = json.loads(line)
        if r.get('label', '').startswith(f'{a.refit}-hdr') and r['label'][len(a.refit) + 4:] in levels:
            meas[r['label'][len(a.refit) + 4:]] = {ch: {int(k): v for k, v in r['r'][ch].items()} for ch in 'RGB'}
else:
    lfcal.apply(st)
    for L in levels:
        try:
            meas[L] = lfcal.measure('hdr', L, f'{a.tag}-hdr{L}', st); lfcal.show('hdr', L, meas[L])
        except RuntimeError as e:
            print('  skipped', L, e, flush=True)
c0, c1 = C.CFG['line']['c0'], C.CFG['line']['c1']
new = dict(st['strips'])
for col in range(c0 + 1, c1):
    al, *lift = st['strips'][str(col)]; al /= 255; lift = [v / 255 for v in lift]
    rows, b = [], []
    for L, out in meas.items():
        P = lfcal.pq(lfcal.NITS[L]); w = W.get(L, 1.0)
        for j, ch in enumerate('RGB'):
            v = out[ch]
            r = np.mean([v[col - 1], v[col], v[col + 1]]) if ch == 'B' else v[col]
            d_new = (lift[j] - al * P) - a.damp * np.log(max(r, 0.05)) / S(P)
            row = [0, 0, 0, -P]; row[j] = 1; rows.append([w * x for x in row]); b.append(w * d_new)
    if len(rows) < 4:
        continue
    sol = np.linalg.lstsq(np.array(rows), np.array(b), rcond=None)[0]
    a2 = float(np.clip(sol[3], 0.05, 0.6)); L2 = [float(np.clip(x, 0, a2 * 0.92)) for x in sol[:3]]
    new[str(col)] = [round(a2 * 255, 1)] + [round(x * 255, 1) for x in L2]
    print(col, st['strips'][str(col)], '->', new[str(col)], flush=True)
st['strips'] = new
lfcal.save(st, a.state)
print('saved', a.state, '(previous state kept as .prev)')
