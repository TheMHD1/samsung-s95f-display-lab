#!/usr/bin/env python3
"""Line-fix keeper (optional supervisor, runs on your computer; can also run as a service).

The box-side relay already switches profiles, enforces the Kodi properties and self-heals after HDMI resets. The keeper
covers what the box cannot do for itself, checking every few seconds:
  - box reachable, Kodi JSON-RPC answering, native 4K GUI still on (a CoreELEC update/reset can turn it off),
  - the skin dialog file still present (a SKIN UPDATE deletes it) -> re-install skin + profiles + ReloadSkin,
  - the installed profiles.json/strips match the local profile files -> re-install if not,
  - a stale calibration lock (profile.lock) while no calibration is running -> re-install (removes the lock),
  - the 'on' flag exists (unless paused),
  - the relay's 'resets' counter (HDMI re-plug / mode change) -> re-check everything immediately,
  - the HDR shader mount status (reported in the log; re-patching after an update is a manual install_box.py run).
Pause: create the file keeper.pause next to this script (the layer is switched off while paused).
Hold: the calibration scripts create keeper.hold while they run (keeper changes nothing) and remove it on exit.
Transport hiccups (box asleep, Wi-Fi) are NOT treated as 'not ready': nothing is changed until the box answers again.
Log: keeper.log (rotated at 5 MB). Exit with Ctrl-C.
"""
import hashlib, json, os, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lfconfig as C
import linefix_skin as S

PAUSE = os.path.join(C.HERE, 'keeper.pause')
HOLD = os.path.join(C.HERE, 'keeper.hold')
LOG = os.path.join(C.HERE, 'keeper.log')
ST = {'last': None, 'resets': None, 'checked_t': 0.0, 'n': 0}


def log(m):
    with open(LOG, 'a') as f:
        f.write(time.strftime('%Y-%m-%dT%H:%M:%S ') + m + '\n')
    if os.path.getsize(LOG) > 5e6:
        os.replace(LOG, LOG + '.1')


def relay_state():
    try:
        url = f"http://{C.CFG['box']['host']}:{C.CFG['relay'].get('port', 8790)}/p"
        with urllib.request.urlopen(url, timeout=1.5) as r:
            return json.loads(r.read())
    except Exception:
        return None


def wanted():
    profs = S.load_profiles()
    B = next((int(s['B']) for s in profs.values() if not s.get('hdr')), 0)
    paths = {k: S.strip_name(S.strip_bytes(st, B)) for k, st in profs.items()}
    return profs, paths, hashlib.md5(S.skin_xml(B).encode()).hexdigest()


def check(acts):
    profs, paths, xml_md5 = wanted()
    out = C.ssh(f'grep -c "disableguiscaling\\">true" /storage/.kodi/userdata/guisettings.xml; '
                f'echo SKIN=$(md5sum {S.skin_file()} 2>/dev/null | cut -c1-32); '
                f'echo PROF=$(cat {C.D}/profiles.json 2>/dev/null); '
                f'for f in {" ".join(paths.values())}; do test -f $f && echo HAVE; done; '
                f'test -f {C.D}/profile.lock && echo LOCKED; test -f {C.D}/on && echo ONFLAG; '
                f'echo MOUNT=$(cat {C.D}/shader-mount.status 2>/dev/null)', timeout=20)
    if not out:
        return 'unreachable'
    lines = out.splitlines()
    if lines[0].strip() != '1':
        acts.append('4K GUI is OFF (coreelec.amlogic.disableguiscaling) - layer cannot be pixel-exact; run install_box.py install')
    have = {}
    for l in lines:
        if l.startswith('PROF='):
            try:
                have = json.loads(l[5:] or '{}')
            except ValueError:
                have = {}
    if (f'SKIN={xml_md5}' not in out or have != paths or out.count('HAVE') != len(paths)
            or ('LOCKED' in out and not os.path.exists(PAUSE))):
        S.install_profiles(profs)
        acts.append('re-installed skin + profiles' + (' (stale calibration lock removed)' if 'LOCKED' in out else ''))
    if 'ONFLAG' not in out:
        S.layer_on(); acts.append('layer on')
    m = next((l[6:] for l in lines if l.startswith('MOUNT=')), '')
    if profs.get('hdr') and not m.startswith(('mounted', 'already')):
        acts.append(f'HDR shader not active: {m or "no status"}')
    return 'ok'


def step():
    acts = []
    if os.path.exists(HOLD) and time.time() - os.path.getmtime(HOLD) < 4 * 3600:   # a crashed calibration can't block forever
        return 'hold (calibration running)', acts
    if os.path.exists(PAUSE):
        C.ssh(f'test -f {C.D}/on && {{ rm -f {C.D}/on; kodi-send --action="ClearProperty(linefix_on,Home)" >/dev/null; echo OFF; }}',
              timeout=15) and acts.append('paused -> layer off')
        return 'paused', acts
    rp = relay_state()
    if rp is None:
        return 'box unreachable (no change)', acts
    if ST['resets'] is not None and rp.get('resets') != ST['resets']:
        ST['checked_t'] = 0; acts.append(f"box display reset #{rp.get('resets')} -> re-checking")
    ST['resets'] = rp.get('resets')
    if rp.get('err'):
        acts.append('relay error: ' + rp['err'])
    if time.time() - ST['checked_t'] > 30:
        ST['checked_t'] = time.time()
        r = check(acts)
        if r != 'ok':
            return r, acts
    return f"{rp.get('profile')} ({rp.get('mode')}, x={rp.get('x')})", acts


def main():
    log('keeper start')
    errs = 0
    while True:
        delay = 2
        try:
            mode, acts = step(); errs = 0
            msg = f'[{mode}] ' + (', '.join(acts) if acts else 'ok')
        except Exception as e:
            errs += 1; delay = min(60, 2 ** min(errs, 6))
            msg = f'error: {type(e).__name__}: {str(e)[:200]}'
        ST['n'] += 1
        if msg != ST['last'] or ST['n'] % 900 == 0:
            log(msg); print(msg, flush=True); ST['last'] = msg
        time.sleep(delay)


if __name__ == '__main__':
    main()
