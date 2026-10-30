#!/usr/bin/env python3
"""One SDR calibration round (24p clips -> 4:4:4 output): measure grey 13/26/51/102, then update every column.

  sdr_round.py <tag> [damp=0.6] [--state examples/my-sdr-444.json]

Model per column (8-bit GUI code domain, see docs/kodi/METHOD.md): out = lift + k * video, k = 1 - alpha/255.
  - lift per channel from the DARK levels 13 and 26: the panel's light ~ code^GAM, so a light ratio r means the
    code is off by a factor r^(-1/GAM); the needed code change is (lift + k*L) * (r^(-1/GAM) - 1), averaged, damped.
  - k (one per column, all channels) from the BRIGHT level 102 (geometric mean of the three channels).
  - blue is judged on a 3-column average (blue light spreads into the neighbours on the panel/camera).
Constraints: 0 <= alpha <= 150, 0 <= lift <= alpha (premultiplied; a lift above alpha cannot be encoded). If the
dark levels need more lift than the bright-level alpha allows, alpha is raised (dark scenes are where the line shows).
Start state: copy examples/s95f-sdr-444.json and zero the strips, or start from those numbers. Typically 3 rounds.
With B = 0 (no global dim) the line can only be made brighter by lift, not by gain: k <= 1. That is enough when the
defect is a threshold (offset) - see docs/kodi/METHOD.md - but highlights in the line may stay slightly dim.
"""
import argparse, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lfcal
import lfconfig as C

GAM = 2.0
ap = argparse.ArgumentParser(); ap.add_argument('tag'); ap.add_argument('damp', nargs='?', type=float, default=0.6)
ap.add_argument('--state', default=os.path.join(C.HERE, C.CFG['profiles']['444']))
a = ap.parse_args()
st = lfcal.load(a.state); lfcal.apply(st)
last = {}
for L in (13, 26, 51, 102):
    last[L] = lfcal.measure('grey', L, f'{a.tag}-g{L}', st); lfcal.show('grey', L, last[L])
c0, c1 = C.CFG['line']['c0'], C.CFG['line']['c1']
new = {}
for col in range(c0, c1 + 1):
    al, cr, cg, cb = st['strips'].get(str(col), [st['B'], 0, 0, 0]); c = [cr, cg, cb]; k = 1 - al / 255
    for ch in range(3):
        def ratio(L):
            v = last[L]['RGB'[ch]]
            return float(np.mean([v[col - 1], v[col], v[col + 1]])) if ch == 2 else v[col]
        d = [(c[ch] + k * L) * (ratio(L) ** (-1 / GAM) - 1) for L in (13, 26)]
        c[ch] += a.damp * float(np.mean(d))
    g = float(np.exp(np.mean([np.log(last[102]['RGB'[ch]][col] ** (-1 / GAM)) for ch in range(3)])))
    k *= 1 + a.damp * (g - 1)
    al = max(0.0, min(150.0, 255 * (1 - k)))
    al = min(150.0, max(al, max(c)))      # lift needs alpha >= lift: dark levels win over the bright-level gain
    new[str(col)] = [round(al, 1)] + [round(float(min(max(v, 0), al)), 1) for v in c]
    print(col, st['strips'].get(str(col)), '->', new[str(col)])
st['strips'] = new
lfcal.save(st, a.state)
print('saved', a.state, '(previous state kept as .prev)')
