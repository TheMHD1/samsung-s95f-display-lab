#!/usr/bin/env python3
"""Pre-shot screen check for player camera tests (Claude, after a night of shooting the Samsung Apps page).

ok() -> (True, info) only when: TV source is config tv.player_input (S95F test setup: HDMI3), the TV screensaver app is not running, and the TV's own graphics
(OSD) plane is essentially empty (enlightenment_info -dump_screen captures OSD only; HDMI video is not in it, so any
visible pixel there = Home/Apps/screensaver/menu covering the player picture).
hold(sec): context manager for a short batch: raises the window-manager screensaver timer (RAM-only, max 600 s),
dismisses the screensaver with one Return key if it is up, verifies ok(), and always restores the timer to 120 s.
Owner rule: no static picture longer than ~20 min; batches must stay short.
"""
import base64, contextlib, io, json, pathlib, re, subprocess, sys, time
HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE.parent)); import config as C
_td = C.TCON / 'tvdump.py'; _src = _td.read_text().rsplit('main()', 1)[0]
_g = {'__file__': str(_td)}; _argv = sys.argv; sys.argv = _argv[:1]
try: exec(compile(_src, str(_td), 'exec'), _g)
finally: sys.argv = _argv
root = _g['root']
ENV = 'export XDG_RUNTIME_DIR=/run; '

def key(k):
    return C.tv_key(k)                                         # config tv.key_cmd (optional)

def ok():
    out = root(ENV + 'echo SRC=$(buxton2ctl get memory memory/eden/source/current_source 2>/dev/null | tail -1 | grep -o "SOURCE_TYPE_[A-Z0-9_]*"); '
               'echo SS=$(ps -eo args | grep "[s]potlight-ss/bin" | wc -l); rm -rf /tmp/cshot; mkdir -p /tmp/cshot; '
               'enlightenment_info -dump_screen -p /tmp/cshot/ -n s.png >/dev/null 2>&1; echo B64; base64 /tmp/cshot/s.png', 60)
    src = (re.search(r'SRC=(\S*)', out) or [None, '?'])[1]; ss = (re.search(r'SS=(\d+)', out) or [None, '?'])[1]
    cover = None
    try:
        from PIL import Image
        import numpy as np
        b = base64.b64decode(''.join(re.findall(r'^[A-Za-z0-9+/=]+$', out.split('B64', 1)[1], re.M)))
        a = np.asarray(Image.open(io.BytesIO(b)).convert('RGBA'))
        m = a[..., 3] > 16; W = m.shape[1]
        cover = float(m.mean())
        bar = float(m[:, int(W * 500 / 1920):int(W * 760 / 1920)].mean())   # test bars = panel cols 1100-1419 (+ margin)
    except Exception as e:
        cover = bar = None
    info = dict(src=src, screensaver=ss, osd_cover=None if cover is None else round(cover, 4),
                osd_bar=None if bar is None else round(bar, 4))
    good = (src == C.PLAYER_INPUT and ss == '0' and cover is not None and cover < 0.05 and bar < 0.002)
    return good, info

def _restore_timer():
    import signal
    old = [signal.signal(x, signal.SIG_IGN) for x in (signal.SIGTERM, signal.SIGINT)]
    try:
        for k in range(6):
            try:
                out = root(ENV + 'enlightenment_info -scrsaver timeout 120 >/dev/null; enlightenment_info -scrsaver info', 30)
                if 'Timeout period: 120.0' in out: return True
            except Exception:
                pass
            time.sleep(2 * (k + 1))
        print('WARNING: could not verify TV screensaver timer restore to 120 s', file=sys.stderr, flush=True)
        return False
    finally:
        signal.signal(signal.SIGTERM, old[0]); signal.signal(signal.SIGINT, old[1])

@contextlib.contextmanager
def hold(sec=480):
    if not 0 < sec <= 600: raise ValueError('hold must be 1..600 s')
    try:
        root(ENV + f'enlightenment_info -scrsaver timeout {int(sec)} >/dev/null', 30)
        good, info = ok()
        if not good and info['screensaver'] not in ('0', '?'):
            key('KEY_RETURN'); time.sleep(4); good, info = ok()
        if not good:
            raise RuntimeError(f'screen not showing the player picture: {json.dumps(info)}')
        yield info
    finally:
        _restore_timer()

if __name__ == '__main__':
    print(json.dumps(ok()))
