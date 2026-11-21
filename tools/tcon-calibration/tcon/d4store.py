#!/usr/bin/env python3
"""Stored D4 (power-off Vth sensing): headers + bank segments 0/2/4 (R/G/B first half). usage: d4store.py live NAME | file"""
import json, struct, subprocess, sys, pathlib, numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1])); import config as C
from decode import unpack_plane
HERE = pathlib.Path(__file__).parent; M = json.load(open(C.BACKUP/'MANIFEST.json'))   # written by backup_items.py
ext = {e['file'].split('/')[1][:-4]: (int(e['storage'], 16), e['bytes']) for e in M if e['file'].startswith('06_D4/')}
want = ['hdr0', 'hdr1'] + [f'bank{b}_seg{s:02d}' for b in (0, 1) for s in (0, 2, 4)]
def load(mode, name=None):
    if mode == 'file': return {k: (C.BACKUP/'06_D4'/f'{k}.bin').read_bytes() for k in want}
    rng = ','.join(f'st:{ext[k][0]:x}:{ext[k][1]:x}' for k in want)
    subprocess.run([sys.executable, '-B', str(HERE/'tvdump.py'), '--name', name, '--chunk', '4096', '--budget-ms', '90000', '--ranges', rng], check=True, capture_output=True, timeout=400)
    d = (C.CAPTURES/name/'dump.bin').read_bytes(); out = {}; o = 0
    for k in want: out[k] = d[o:o+ext[k][1]]; o += ext[k][1]
    assert o == len(d), (o, len(d)); return out
def gen(h): return struct.unpack_from('<I', h, 8)[0]
def report(D):
    r = {'gen': {'bank0': gen(D['hdr0']), 'bank1': gen(D['hdr1'])}}
    for b in (0, 1):
        for i, s in enumerate((0, 2, 4)):
            P = unpack_plane(D[f'bank{b}_seg{s:02d}'], 1920, 2160, 2880).astype(np.float32); col = np.median(P, axis=0); ref = float(np.median(col[1200:1250]))
            r[f'bank{b}_{"RGB"[i]}'] = dict(ref=round(ref, 1), **{str(x): round(float(col[x]-ref), 1) for x in (1254, 1255, 1256, 1257, 1258, 1259, 1260, 1261, 1278, 1279, 1280, 1281, 1282)})
    return r
if __name__ == '__main__':
    D = load(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None); print(json.dumps(report(D), indent=0))
