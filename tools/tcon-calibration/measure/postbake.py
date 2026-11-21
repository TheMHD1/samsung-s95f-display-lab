#!/usr/bin/env python3
"""Post-bake camera batch (Claude 2026-11-19). Same clips, column indices and normalisation as the post200 set, so
results compare 1:1. Usage: python3 -B postbake.py LABEL [--ref post200] [--skip-grey] [--skip-black] [--split32]
Each batch runs under screencheck.hold (TV must show the player; short static time) and blanks the player afterwards.
The core is located per photo (darkest 6-column G window start s): core = s-3..s+6, lane 640 = s+23/24,
healthy = s-37..s-10, s+13..s+20, s+28..s+62 (2026-11-19: fixed indices broke when the camera was moved)."""
import argparse, json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import optical as O, screencheck
OUT = O.OUT                                                    # <work>/captures/optical
GREY = ['grey128', 'grey77', 'grey204', 'xred153', 'xgreen153', 'xblue153']
BLACK = ['grey4', 'grey8', 'grey13']

# CONSULT-21 §5: a set once photographed the dark screen (shutter 32/10 s) and logged "photos ok". Per clip now: Kodi must
# show full-screen video with no modal dialog, and the auto shutter must stay near its normal value (normal: grey clips
# and split32 <= 1/50, black-grey13 <= 1/40, black-grey8 <= 1/13; black-grey4 is up to 32/10 even when fine -> unchecked).
MAX_SH = dict({c: 0.1 for c in GREY}, **{'black-grey13': 0.2, 'black-grey8': 0.5, 'black-split32': 0.1})
ALLOW_UNKNOWN_EXPOSURE = False
def sh_s(sh):
    a, _, b = str(sh).partition('/'); return float(a) / float(b or 1)
def check_shot(clip, r):
    lim = MAX_SH.get(clip)
    if r['shutter'] is None:
        if ALLOW_UNKNOWN_EXPOSURE:
            print(f'   {clip}: exposure time unknown: dark-screen check SKIPPED (--allow-unknown-exposure)', flush=True); return
        raise RuntimeError(f'abort: {clip} exposure time unknown, so a dark screen cannot be ruled out (make camera.capture print '
                           'SHUTTER=..., or pass --allow-unknown-exposure and check every photo by eye)')
    if lim is not None and sh_s(r['shutter']) > lim:
        raise RuntimeError(f'abort: {clip} shutter {r["shutter"]} > {lim} s - the screen looks dark, photos not valid')
def check_kodi():
    st = O.rpc('XBMC.GetInfoLabels', {'labels': ['System.CurrentWindow']}) + O.rpc('XBMC.GetInfoBooleans', {'booleans': ['System.HasModalDialog']})
    if '"System.CurrentWindow":"Fullscreen video"' not in st or '"System.HasModalDialog":false' not in st:
        raise RuntimeError(f'abort: something is on top of the test video ({st[:200]})')

def locate(r):
    """Start of the darkest 6-column window in G (the damaged core); the camera framing can move between sessions."""
    G = np.asarray(r['G'], float); n = len(G); w = [G[i:i + 6].sum() for i in range(60, n - 70)]
    return 60 + int(np.argmin(w))

def healthy(v, s):
    n = len(v); return np.median(np.r_[v[s - 37:s - 9], v[s + 13:s + 21], v[s + 28:min(n, s + 63)]])

def metrics(r):
    s = locate(r); j = dict(core_start=s)
    for k in 'RGB':
        v = np.asarray(r[k], float); h = healthy(v, s)
        core = v[s - 3:s + 7] / h
        j[k] = [round(float(x), 3) for x in core]
        j[k + '_L640'] = round(float(np.mean(v[s + 23:s + 25]) / h), 3)
        j[k + '_deficit'] = round(float(np.sum(1 - np.minimum(core, 1))), 3)   # summed missing light, 10 columns
    return j

def ref_rows(ref):
    p = os.path.join(OUT, ref + '.jsonl'); rows = {}
    if os.path.exists(p):
        for line in open(p):
            d = json.loads(line); rows[d['clip']] = d
    return rows

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('label'); ap.add_argument('--ref', default='post200')
    ap.add_argument('--skip-grey', action='store_true'); ap.add_argument('--skip-black', action='store_true')
    ap.add_argument('--allow-unknown-exposure', action='store_true', help='skip the dark-screen shutter check when the camera reports no exposure time')
    ap.add_argument('--split32', action='store_true', help='also shoot the split32 clip (not made by mkclip.py; S95F set only)')
    a = ap.parse_args()
    global ALLOW_UNKNOWN_EXPOSURE; ALLOW_UNKNOWN_EXPOSURE = a.allow_unknown_exposure
    refs = ref_rows(a.ref); out = open(os.path.join(OUT, a.label + '.jsonl'), 'a'); O.set_raw()
    if not a.skip_grey:
        with screencheck.hold(480):
            try:
                for c in GREY:
                    O.play('grey4', 1.0); O.play(c, 3.0); check_kodi(); r = O.shot(f'{a.label}-{c}'); check_shot(c, r)
                    j = dict(clip=c, sh=r['shutter'], **metrics(r)); out.write(json.dumps(j) + '\n'); out.flush()
                    rf = refs.get(c, {})
                    if rf and 'R_deficit' not in rf:
                        for k in 'RGB': rf[k + '_deficit'] = round(float(np.sum(1 - np.minimum(np.array(rf[k]), 1))), 3)
                    print(c.ljust(10), r['shutter'], ' | '.join(
                        f"{k} deficit {j[k+'_deficit']:.2f}" + (f" (ref {rf[k+'_deficit']:.2f})" if rf else '') +
                        f" L640 {j[k+'_L640']:.2f}" + (f" (ref {rf[k+'_L640']:.2f})" if rf else '') for k in 'RGB'), flush=True)
                    print('   core', ' '.join(f'{x:.2f}' for x in j['G']), flush=True)
            finally:
                print('blank', O.stop(), flush=True)
    if not a.skip_black:
        with screencheck.hold(300):
            rows = []                                      # review: written only after every checked clip passed (grey4 is unchecked)
            try:
                for c in BLACK:
                    O.play(c, 3.0); check_kodi(); r = O.shot(f'{a.label}-black-{c}'); check_shot('black-' + c, r); o = {}
                    s0 = locate(r)
                    for k in 'RGB':
                        v = np.asarray(r[k], float); h = healthy(v, s0)
                        o[k] = dict(ratio640=round(float(np.mean(v[s0 + 23:s0 + 25]) / h), 2), core=[round(float(x / h), 2) for x in v[s0 - 1:s0 + 7]])
                    rows.append(dict(clip='black-' + c, sh=r['shutter'], **o))
                    print('black', c, r['shutter'], json.dumps(o), flush=True)
                if a.split32: O.play('split32', 3.0); check_kodi(); r = O.shot(f'{a.label}-black-split32'); check_shot('black-split32', r)
                o = {}
                for k in ('RGB' if a.split32 else ''):
                    v = r[k]; lit = np.median(v[20:110]); blk = np.median(np.r_[v[150:158], v[164:200]])
                    o[k] = dict(lit=round(float(lit)), black_bg=round(float(blk), 1), idx158_163=[round(float(x), 1) for x in v[158:164]],
                                core133_142=[round(float(x), 1) for x in v[133:143]])
                if a.split32: rows.append(dict(clip='black-split32', sh=r['shutter'], **o)); print('split32', r['shutter'], json.dumps(o), flush=True)
                for d in rows: out.write(json.dumps(d) + '\n')
                out.flush()
            finally:
                print('blank', O.stop(), flush=True)

if __name__ == '__main__':
    main()
