#!/usr/bin/env python3
"""HDR step 1 - direct fit (needs the patched shader active, see docs/HDR-SHADER.md).

  hdr_fit.py <tag> 2,15,100 [offsets=0.06,0.12,0.18]

For each HDR level P (PQ signal of the clip), the damaged core columns are REPLACED by a constant raw PQ value C
(alpha 1 = video fully hidden there, lift = C) for a few C = P + offset, one photo each. Interpolating ln(ratio)
against C gives C*, the PQ output each damaged column/channel needs to match its neighbours at that level:
dP* = C* - P. Then fit, per column, ONE alpha a and one lift L per channel so that  dP = L - a*P  for all levels
(least squares) -> initial HDR profile (written to <tag>-hdr-initial.json; copy into your HDR profile after a look).
Use 2 nits and 100 nits as the main anchors; add 0.5 / 5 / 15 if time allows.
Only the 'core' columns (strongly damaged, config line c0+1 .. c1-1 by default) are fitted; edge columns keep 0.
"""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lfcal
import lfconfig as C

tag, levels = sys.argv[1], sys.argv[2].split(',')
offs = [float(v) for v in sys.argv[3].split(',')] if len(sys.argv) > 3 else [0.06, 0.12, 0.18]
c0, c1 = C.CFG['line']['c0'], C.CFG['line']['c1']
core = list(range(c0 + 1, c1))
anchors = {col: {ch: [] for ch in 'RGB'} for col in core}         # col -> ch -> [(P, dP*)]
for L in levels:
    P = lfcal.pq(lfcal.NITS[L]); rows = []
    for d in offs:
        Cv = min(P + d, 0.60); c8 = round(Cv * 255)
        st = {'B': 0, 'hdr': True, 'strips': {str(c): ([255, c8, c8, c8] if c in core else [0, 0, 0, 0]) for c in range(c0, c1 + 1)}}
        lfcal.apply(st)
        r = lfcal.measure('hdr', L, f'{tag}-hdr{L}-C{c8}', st)
        rows.append((c8 / 255, r))
        print(f'hdr{L} P={P:.3f} C={c8 / 255:.3f} ' + '  '.join(f'{ch}:' + ','.join(f'{r[ch][c]:.2f}' for c in core) for ch in 'RGB'), flush=True)
    for ch in 'RGB':
        for col in core:
            x = np.array([q[0] for q in rows]); y = np.log(np.maximum([q[1][ch][col] for q in rows], 1e-3))
            if y[-1] > y[0]:
                cs = float(np.interp(0.0, y, x))
                anchors[col][ch].append((P, cs - P))
        print(f'   C* {ch}: ' + ', '.join(f'{col}:{anchors[col][ch][-1][1] + P:.3f}' if anchors[col][ch] else f'{col}:n/a' for col in core), flush=True)
strips = {str(c): [0, 0, 0, 0] for c in range(c0, c1 + 1)}
for col in core:
    rows, b = [], []
    for j, ch in enumerate('RGB'):
        for P, dP in anchors[col][ch]:
            row = [0, 0, 0, -P]; row[j] = 1; rows.append(row); b.append(dP)
    if len(rows) < 4:
        print(col, 'not enough anchors'); continue
    sol = np.linalg.lstsq(np.array(rows), np.array(b), rcond=None)[0]
    a = float(np.clip(sol[3], 0.05, 0.6)); Ls = [float(np.clip(v, 0, a * 0.92)) for v in sol[:3]]
    strips[str(col)] = [round(a * 255, 1)] + [round(v * 255, 1) for v in Ls]
    print(col, 'a', round(a, 3), 'L', [round(v, 3) for v in Ls])
out = os.path.join(C.HERE, f'{tag}-hdr-initial.json')
json.dump({'B': 0, 'hdr': True, 'strips': strips, 'anchors': {str(k): v for k, v in anchors.items()}}, open(out, 'w'), indent=1)
print('wrote', out)
