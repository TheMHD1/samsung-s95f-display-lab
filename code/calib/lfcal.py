"""Calibration library: apply a profile, play a test clip, shoot it, return per-column ratios.

Used by sdr_round.py, sdr_chroma.py, hdr_fit.py, hdr_round.py, verify.py, reference.py.
Rules learned the hard way (see docs/kodi/CALIBRATION.md):
  - a pattern is on screen ONLY for the photo: playback is stopped right after every shot;
  - clips are small windows around the line on black, never bright full-screen fields;
  - wait until the clip really plays at the expected refresh rate, then ~5 s more (Kodi shows a 'now playing'
    pop-up for a few seconds; the TV needs time after an HDMI mode switch);
  - after the shot check the clip is STILL playing (otherwise the photo shows the menu);
  - a frame much brighter than expected -> stop the whole run; a few saturated pixels -> shorter shutter and re-shoot;
  - every script pauses the keeper (keeper.hold) and on ANY exit (also crashes/Ctrl-C) stops playback, removes the
    calibration lock and restores the layer flag.
"""
import atexit, json, os, sys, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, 'camera'))
import lfconfig as C
import linefix_skin as S
import camctl

DATA = os.path.join(HERE, 'calib-data.jsonl')
HOLD = os.path.join(HERE, 'keeper.hold')
NITS = {'0p5': 0.5, '2': 2, '5': 5, '15': 15, '50': 50, '100': 100, '200': 200}
LADDER = ['30', '25', '20', '15', '13', '10', '8', '6', '5', '4', '32/10', '25/10', '2', '16/10', '13/10', '1', '8/10',
          '6/10', '5/10', '4/10', '1/3', '1/4', '1/5', '1/6', '1/8', '1/10', '1/13', '1/15', '1/20', '1/25', '1/30',
          '1/40', '1/50', '1/60', '1/80', '1/100', '1/125', '1/160', '1/200', '1/250']


def pq(nits):
    """SMPTE ST 2084 inverse EOTF: absolute luminance (cd/m2) -> PQ signal 0..1."""
    m1, m2, c1, c2, c3 = 0.1593017578125, 78.84375, 0.8359375, 18.8515625, 18.6875
    y = (nits / 1e4) ** m1
    return ((c1 + c2 * y) / (1 + c3 * y)) ** m2


_started = False


def start():
    """Call once at the start of a calibration script."""
    global _started
    if _started:
        return
    _started = True
    open(HOLD, 'w').write(time.strftime('%F %T'))
    atexit.register(_restore)


def _restore():
    try:
        C.stop()
        C.ssh(f'rm -f {C.D}/profile.lock; touch {C.D}/on', timeout=15)
    finally:
        if os.path.exists(HOLD):
            os.remove(HOLD)


def apply(st):
    """Show one profile state (SDR or HDR) on the box; sets the calibration lock so the relay does not switch."""
    start()
    S.install(st)
    S.layer_on()
    time.sleep(1.0)


def show_original():
    """Layer off (for 'uncorrected' reference shots)."""
    start()
    C.ssh(f'touch {C.D}/profile.lock; rm -f {C.D}/on; kodi-send --action="ClearProperty(linefix_on,Home)" >/dev/null')
    time.sleep(1.0)


def shutter_for(fam, L):
    cam = C.CFG['camera']
    if fam == 'hdr':
        return cam['shutter_hdr'][str(L)]
    Ls = str(L)[:-3] if str(L).endswith('f60') else str(L)
    return cam['shutter_sdr'][Ls] if fam == 'grey' else cam['shutter_colour'][f'{fam}{Ls}']


def measure(fam, L, label, st=None):
    """Play clip <fam><L>, shoot, stop. Returns camctl.ratios() dict. L: 13 / '26f60' (60 Hz clip) / HDR '2'."""
    start()
    clip = f'{fam}{L}'
    want = '2160p60' if str(L).endswith('f60') else '2160p24'
    C.play(clip)
    for n in range(30):
        time.sleep(1.0)
        if C.output_mode().startswith(want) and C.playing(clip):
            break
        if n in (8, 18):
            C.play(clip)                                  # e.g. Kodi was still starting: ask again
    else:
        raise RuntimeError(f'{clip}: not playing at {want} (refresh-rate switching on? 2160p{want[5:]} whitelisted?)')
    time.sleep(5.0)
    sh = shutter_for(fam, L)
    for attempt in range(3):
        fr = camctl.measure(label, 1, sh)[0]
        still = C.playing(clip)
        C.stop()                                          # pattern on screen only for the photo
        if not still:
            print(f'  ({label}: clip left the screen during the shot - replaying)', flush=True)
        elif max(fr['sat'].values()) < 1e-4 and max(fr['peak'].values()) < 0.9:
            break
        else:
            if max(fr['peak'].values()) >= 0.9:
                raise RuntimeError(f'{label}: frame much brighter than expected - stopped, not re-shooting')
            print(f'  ({label}: a few saturated pixels - shorter shutter)', flush=True)
            if sh in LADDER and LADDER.index(sh) + 3 < len(LADDER):
                sh = LADDER[LADDER.index(sh) + 3]         # ~1 stop shorter
        C.play(clip); time.sleep(8)
    else:
        raise RuntimeError(f'{label}: no clean frame after 3 attempts')
    r = camctl.ratios(fr)
    with open(DATA, 'a') as f:
        f.write(json.dumps({'t': time.strftime('%F %T'), 'label': label, 'fam': fam, 'L': L, 'state': st,
                            'r': {k: v for k, v in r.items()}, 'peak': fr['peak'], 'sat': fr['sat']}) + '\n')
    return r


def show(fam, L, r):
    chs = 'RGB' if fam in ('grey', 'hdr') else {'red': 'R', 'green': 'G', 'blue': 'B'}[fam]
    print(f'{fam:5s}{str(L):>6s} ' + camctl.fmt(r, chs), flush=True)


def load(path):
    return json.load(open(path))


def save(st, path):
    if os.path.exists(path):
        os.replace(path, path + '.prev')                  # one-step undo
    json.dump(st, open(path, 'w'), indent=1)
