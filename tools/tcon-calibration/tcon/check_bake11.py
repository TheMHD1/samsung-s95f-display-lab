#!/usr/bin/env python3
"""Bake-11 guard check (Claude, CONSULT-16 sec 1/sec 6 step 3). Local files only, no TV contact.
Reads the stored D4 of bake 10 and bake 11 (bake_eval.read_d4) and prints per-column centred deltas (new - old - per-colour
median shift, as bake_eval's footprint) and stored excess (column median - median of columns 1200..1249, as CONSULT-16).
Verdict (exit code):
  0 PASS        every column 1255..1260 inside the CONSULT-16 window, 1261/1262 within +-3
  0 PASS-FLIP   1255 flipped (stores ~R +4 / G -5.5 / B +45; accepted by CONSULT-16), 1256..1259 allowed +3 higher
  3 HOLD        outside the window but no re-bake signature: keep the bake, get an independent review before any S1 change
  4 REBAKE      re-bake signature: re-bake with the bake-10 words
  5 NOBAKE      D4 generation did not advance (no new bake stored)
  6 ERROR       a D4 capture is missing or invalid
--same: re-bake of the SAME words (fallback to bake 10): expected change 0 everywhere, window +-8 (night-to-night drift),
        no flip allowance; signatures as above.
--after NAME: NEW must also be a newer generation than capture NAME (the D4 stored before this bake), else NOBAKE.
usage: check_bake11.py [--same] [--after NAME] [OLD NEW]   (default d4-bake10 d4-bake11)"""
import sys, pathlib
import numpy as np
HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE)); import bake_eval as E
av = sys.argv[1:]; AFTER = None
if '--after' in av: i = av.index('--after'); AFTER = av[i + 1]; del av[i:i + 2]
SAME = '--same' in av; av = [a for a in av if a != '--same']
old_n, new_n = (av[0:2] if len(av) >= 2 else ('d4-bake10', 'd4-bake11'))
COLS = list(range(1254, 1263))
EXP = {'R': dict(zip(range(1255, 1263), (6, 8, 11, 13, 9, 7, 0, 0))),          # CONSULT-16 sec 1 "Change" row
       'G': dict(zip(range(1255, 1263), (6, 8, 11, 13, 8, 5, 0, 0))),
       'B': dict(zip(range(1255, 1263), (6, 8, 12, 13, 8, 8, 0, 0)))}
TOL = {'R': 4, 'G': 4, 'B': 6}
if SAME: EXP = {k: {c: 0 for c in v} for k, v in EXP.items()}; TOL = {'R': 8, 'G': 8, 'B': 8}
FLIP = {'R': 12.5, 'G': -1.5, 'B': 19.0}; FTOL = {'R': 4, 'G': 4, 'B': 6}   # 1255 flip: -8.5/-4/+26 -> +4/-5.5/+45 stored
try: old, new = E.read_d4(old_n), E.read_d4(new_n); aft = E.read_d4(AFTER) if AFTER else None
except (OSError, ValueError) as e: print(f'ERROR: cannot read the D4 captures ({e})'); sys.exit(6)
if aft is not None and max(new.generations) <= max(aft.generations):
    print(f'NOBAKE: {new_n} generations {new.generations} not newer than {AFTER} {aft.generations}'); sys.exit(5)
print(f'{old_n}: generations {old.generations} bank {old.bank} | {new_n}: generations {new.generations} bank {new.bank}')
if max(new.generations) <= max(old.generations):
    print('NOBAKE: the stored D4 generation did not advance'); sys.exit(5)
delta = new.medians - old.medians; cen = delta - np.median(delta, axis=1)[:, None]
ref = np.median(new.medians[:, 1200:1250], axis=1)[:, None]; stored = new.medians - ref
ref0 = np.median(old.medians[:, 1200:1250], axis=1)[:, None]; stored0 = old.medians - ref0
K = {k: i for i, k in enumerate('RGB')}
print(f'col   centred delta R/G/B (expected)            stored {old_n} R/G/B     stored {new_n} R/G/B')
for c in COLS:
    e = '/'.join(f'{EXP[k].get(c, 0):+d}' for k in 'RGB')
    print(f'{c}  {cen[0, c]:+6.1f}/{cen[1, c]:+6.1f}/{cen[2, c]:+6.1f} ({e:>11})   '
          f'{stored0[0, c]:+7.1f}/{stored0[1, c]:+7.1f}/{stored0[2, c]:+7.1f}   {stored[0, c]:+7.1f}/{stored[1, c]:+7.1f}/{stored[2, c]:+7.1f}')
sig = [f'{c} stores R {stored[0, c]:+.1f} < -100 (repair did not run)' for c in (1256, 1258, 1260) if stored[0, c] < -100]
sig += [f'{c} stores B {stored[2, c]:+.1f} >= +110 (own value)' for c in (1257, 1259) if stored[2, c] >= 110]
sig += [f'1261 {k} moved {cen[K[k], 1261]:+.1f} (> 6)' for k in 'RGB' if abs(cen[K[k], 1261]) > 6]
if sig:
    print('REBAKE:', '; '.join(sig)); sys.exit(4)
flip = not SAME and all(abs(cen[K[k], 1255] - FLIP[k]) <= FTOL[k] for k in 'RGB')   # CONSULT-16 sec 1 flip values
bad = []
for c in range(1255, 1263):
    if flip and c == 1255: continue
    for k in 'RGB':
        e, v = EXP[k][c], cen[K[k], c]
        lo, hi = (e - TOL[k], e + TOL[k]) if c <= 1260 else (-3, 3)
        if flip and 1256 <= c <= 1259: hi += 3
        if not lo <= v <= hi: bad.append(f'{c} {k} {v:+.1f} outside [{lo:+d}, {hi:+d}]')
if bad:
    print('HOLD (keep the bake, consult before any S1 change):', '; '.join(bad)); sys.exit(3)
print('PASS-FLIP (1255 flipped, accepted per CONSULT-16)' if flip else 'PASS'); sys.exit(0)
