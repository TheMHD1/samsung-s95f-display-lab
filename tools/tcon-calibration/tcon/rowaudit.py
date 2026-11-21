#!/usr/bin/env python3
"""Row-resolved stored-D4 audit (Claude, CONSULT-18 §1/§5: whole-column medians hid a 74 % split).
blocks(name) -> (3, 8, 3840) column medians of the stored (newest) bank per colour in 8 blocks of 270 rows (rows 0..2159).
usage: python3 -B tcon/rowaudit.py NEW [OLD]   prints per block: blue-red (healthy-centred) on 1253..1262 and, with OLD, the
centred change per colour on 1253..1262 and 1281 (reads capture files only)."""
import pathlib, sys
import numpy as np
TOP = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(TOP))   # bake_eval, decode
NB, BR = 8, 270                                                # 8 blocks x 270 rows = 2160
HEALTHY = slice(1150, 1250)
def blocks(name):
    import bake_eval as E
    from decode import unpack_plane
    blob = memoryview(E.read_capture(name, E.D4_SIZES)); g = E.d4_generations(blob); bank = max(range(2), key=g.__getitem__)
    out = np.empty((3, NB, E.WIDTH))
    for ch in range(3):
        off = 2 * E.HEADER_SIZE + (bank * 3 + ch) * E.PLANE_SIZE
        plane = np.asarray(unpack_plane(blob[off:off + E.PLANE_SIZE], E.WIDTH, E.ROWS, E.PITCH), float)
        for b in range(NB): out[ch, b] = np.median(plane[b * BR:(b + 1) * BR], axis=0)
    return out
def centred(m): return m - np.median(m[..., HEALTHY], axis=-1)[..., None]
def bmr(m):                                                    # (8, W): blue - red, healthy-centred, per block
    return centred(m[2] - m[0])
def change(new, old): return centred(new - old)                # (3, 8, W)
if __name__ == '__main__':
    new = blocks(sys.argv[1]); cols = list(range(1253, 1263))
    print('blue-red per block (rows), cols', cols)
    for b, row in enumerate(bmr(new)): print(f'  {b * BR:4d}..{b * BR + BR - 1:4d}', ' '.join(f'{row[c]:+6.1f}' for c in cols))
    if len(sys.argv) > 2:
        d = change(new, blocks(sys.argv[2]))
        for ch, nm in enumerate('RGB'):
            print(f'{nm} change per block, cols {cols} + 1281')
            for b in range(NB): print(f'  {b * BR:4d}..{b * BR + BR - 1:4d}', ' '.join(f'{d[ch, b, c]:+6.1f}' for c in cols), f'| {d[ch, b, 1281]:+6.1f}')
