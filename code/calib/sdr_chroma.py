#!/usr/bin/env python3
"""Chroma-aware SDR step: scale all red and blue lifts, then measure single-colour + grey clips.

  sdr_chroma.py <tag> <scale_R> <scale_B> [--state FILE]      e.g. sdr_chroma.py c1 0.9 0.97

Why: the TV low-passes colour (chroma) over roughly +-2 columns, so per-column colour ratios on a single-colour clip
are smeared. Judge colour balance by the SUM of (ratio - 1) over the line area ('sum' in the output; 0 = right
amount of that colour in total), and luma per column on grey. Scale R/B until the sums are ~0 on red/blue clips.
The 60 Hz (4:2:2 output) profile was the 24 Hz profile with R x0.9 and B x0.97 on our set.
"""
import argparse, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lfcal
import lfconfig as C

ap = argparse.ArgumentParser(); ap.add_argument('tag'); ap.add_argument('sR', type=float); ap.add_argument('sB', type=float)
ap.add_argument('--state', default=os.path.join(C.HERE, C.CFG['profiles']['444']))
a = ap.parse_args()
st = lfcal.load(a.state)
if a.sR != 1 or a.sB != 1:
    for c, (al, r, g, b) in st['strips'].items():
        st['strips'][c] = [al, round(min(r * a.sR, al), 1), g, round(min(b * a.sB, al), 1)]
    lfcal.save(st, a.state)
print('strips', st['strips'], flush=True)
lfcal.apply(st)
for fam, L in [('red', 26), ('red', 51), ('red', 102), ('blue', 26), ('blue', 51), ('blue', 102),
               ('grey', 13), ('grey', 26), ('grey', 51), ('grey', 102)]:
    r = lfcal.measure(fam, L, f'{a.tag}-{fam}{L}', st)
    chs = 'RGB' if fam == 'grey' else {'red': 'R', 'blue': 'B'}[fam]
    print(f'{fam:5s}{L:4d} ' + '  '.join(f'{c}:' + ','.join(f'{v:.2f}' for v in r[c].values())
                                        + f' sum{np.sum(np.array(list(r[c].values())) - 1):+.2f}' for c in chs), flush=True)
