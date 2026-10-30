#!/usr/bin/env python3
"""Measure a list of clips with a profile applied (or with the layer off).

  verify.py <tag> fam:L [fam:L ...] [--state FILE] [--off]
  e.g.  verify.py v1 grey:13 grey:26 grey:51 grey:102
        verify.py v1 grey:26f60 grey:51f60 --state examples/s95f-sdr-422.json
        verify.py h1 hdr:2 hdr:15 hdr:100 --state examples/s95f-hdr.json
        verify.py before grey:26 hdr:2 --off                     (uncorrected numbers)
Prints the per-column ratios (1.00 = matches the neighbours) and the sum of (ratio - 1) over the reported columns.
"""
import argparse, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lfcal
import lfconfig as C

ap = argparse.ArgumentParser(); ap.add_argument('tag'); ap.add_argument('clips', nargs='+')
ap.add_argument('--state', default=os.path.join(C.HERE, C.CFG['profiles']['444'])); ap.add_argument('--off', action='store_true')
a = ap.parse_args()
st = None
if a.off:
    lfcal.show_original()
else:
    st = lfcal.load(a.state); lfcal.apply(st)
for item in a.clips:
    fam, L = item.split(':'); L = int(L) if L.isdigit() and fam != 'hdr' else L
    r = lfcal.measure(fam, L, f'{a.tag}-{fam}{L}', st)
    chs = {'red': 'R', 'green': 'G', 'blue': 'B'}.get(fam, 'RGB')
    print(f'{fam:5s}{str(L):>6s} ' + '  '.join(f'{c}:' + ','.join(f'{v:.2f}' for v in r[c].values())
                                              + f' sum{np.sum(np.array(list(r[c].values())) - 1):+.2f}' for c in chs), flush=True)
