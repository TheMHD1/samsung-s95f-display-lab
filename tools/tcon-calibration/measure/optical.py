#!/usr/bin/env python3
"""Player clip stimulus + per-column camera measurement (adapted from the S95F kit: the camera analysis now runs here,
in colratio.py, instead of on a separate camera host). Player = Kodi with JSON-RPC (TCP port player.jsonrpc_port on the
player), reached through config player.shell; clips are the narrow 320-column bars (1100..1419) from mkclip.py, black
elsewhere, copied to player.clip_dir. Camera = config camera.capture (one photo per call). Only one caller at a time."""
import fcntl, json, os, pathlib, shlex, subprocess, sys, time
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
import config as C, colratio
C.ensure_dirs(); OUT = str(C.CAPTURES / 'optical'); os.makedirs(OUT, exist_ok=True)
LOCK = str(C.CAMERA_LOCK)

def ug(cmd, t=20):
    return C.player_shell(cmd, t)
def rpc(method, params=None):
    b = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, **({'params': params} if params else {})})
    return ug(f"printf '%s' {shlex.quote(b)} | nc -w 3 localhost {C.JSONRPC_PORT}")
def screensaver_on():
    return '"System.ScreenSaverActive":true' in rpc('XBMC.GetInfoBooleans', {'booleans': ['System.ScreenSaverActive']})
def wake():
    """Wake Kodi's black screensaver (Claude): since the line-fix helpers stopped sending Kodi actions (3-min idle
    fix), nothing else wakes it, and a test clip would play UNDER the black screensaver. JSON-RPC Input.ExecuteAction wakes
    it (the first action is consumed by the wake). -> True when the screensaver is off."""
    for k in range(4):
        if not screensaver_on(): return True
        rpc('Input.ExecuteAction', {'action': 'noop'}); time.sleep(1.0)
    return not screensaver_on()
def play(clip, settle=2.5):
    if not wake(): raise RuntimeError('Kodi screensaver still active after wake')
    it = ''
    for attempt in range(3):
        r = rpc('Player.Open', {'item': {'file': f'{C.CLIP_DIR}/{clip}.mp4'}, 'options': {'repeat': 'one', 'resume': False}})
        if '"OK"' not in r: time.sleep(1.5); continue
        for k in range(8):
            time.sleep(settle if k == 0 else 0.6)
            it = rpc('Player.GetItem', {'playerid': 1, 'properties': ['file']})
            if f'/{clip}.mp4' in it:
                if not wake(): raise RuntimeError(f'{clip} playing but the Kodi screensaver is still on')
                return
        time.sleep(1.0)
    raise RuntimeError(f'not playing {clip}: {it[:200]}')
def stop():
    """Stop playback and blank the player at once (black screen whenever not measuring: OLED, no static pictures)."""
    for p in (0, 1, 2): rpc('Player.Stop', {'playerid': p})
    for k in range(4):
        try:
            time.sleep(1.5)
            ug('kodi-send --action="ActivateScreensaver" >/dev/null 2>&1', 15); time.sleep(1.0)
            if '"System.ScreenSaverActive":true' in rpc('XBMC.GetInfoBooleans', {'booleans': ['System.ScreenSaverActive']}): return True
        except Exception: pass
    return False
def set_raw():
    return C.camera_mode('raw')
def set_jpeg():
    return C.camera_mode('jpeg')
def _shutter_s(path):
    """Exposure time from the photo's EXIF as '1/50' style text, or None (RAW files: Pillow cannot read them)."""
    try:
        from PIL import Image
        e = Image.open(path).getexif().get_ifd(0x8769).get(0x829A)
        if e: return f'1/{round(1 / float(e))}' if float(e) < 1 else f'{float(e):g}'
    except Exception: pass
    return None
def shot(label, shutter=None):
    """One photo; returns dict with per-column arrays (colratio.analyse). The photo is deleted after the analysis unless
    camera.keep_photos is true. Refuses unless the TV is really showing the player picture (screencheck.ok)."""
    import screencheck
    good, info = screencheck.ok()
    if not good: raise RuntimeError(f'screen check failed, not shooting: {info}')
    lk = open(LOCK, 'w'); fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        photo, used = C.camera_capture(pathlib.Path(OUT) / f'{label}-{int(time.time())}', shutter)
    finally:
        fcntl.flock(lk, fcntl.LOCK_UN); lk.close()
    try:
        A = C.ANALYSIS
        f = colratio.analyse(photo, A['first_column'], A['bar_columns'], tuple(A['rows']), A.get('unmix'))
        sh = used or _shutter_s(photo) or shutter
    finally:
        if not C.KEEP_PHOTOS: photo.unlink(missing_ok=True)
    r = dict(label=label, shutter=sh, t=time.time(), line=int(f['line_col_idx']), period=f['period'], sat=f['sat'], peak=f['peak'],
             phase_off=f['phase_off'], centres=np.array(f['centres'], float), **{c: np.array(f['cols'][c], float) for c in 'RGB'})
    np.savez_compressed(os.path.join(OUT, label + '.npz'), **{k: v for k, v in r.items() if isinstance(v, np.ndarray)},
                        meta=json.dumps({k: v for k, v in r.items() if not isinstance(v, np.ndarray)}))
    return r
def table(r, half=12, ref=(14, 45)):
    """value / median healthy neighbours, per channel, around the darkest 6-column window of that channel."""
    out = {}
    for c in 'RGB':
        v = r[c]; L = r['line']; a = max(0, L - 12)
        w = [v[i:i + 6].sum() for i in range(a, L + 8)]; s = a + int(np.argmin(w))
        idx = np.r_[s - ref[1]:s - ref[0], s + 6 + ref[0]:s + 6 + ref[1]]; h = np.median(v[idx])
        out[c] = dict(start=s, healthy=float(h), core=[round(float(x / h), 3) for x in v[s - 3:s + 9]])
    return out
if __name__ == '__main__':                                     # usage: optical.py CLIP auto|SHUTTER [LABEL]
    print(set_raw())
    clip, sh = sys.argv[1], (None if sys.argv[2] == 'auto' else sys.argv[2])
    try:
        play('grey13', 1.0); play(clip)
        r = shot(sys.argv[3] if len(sys.argv) > 3 else f'probe-{clip}-{int(time.time())}', sh)
        print(json.dumps(dict(shutter=r['shutter'], period=round(r['period'], 3), line=r['line'], n=len(r['G']), peak=r['peak'], sat=r['sat'], table=table(r))))
    finally:
        print('blank', stop())                                 # public kit: never leave the bar on the OLED
