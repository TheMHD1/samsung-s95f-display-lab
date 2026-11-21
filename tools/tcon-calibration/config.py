#!/usr/bin/env python3
"""Single configuration module of the TCON calibration kit. Every machine-specific item lives here; the tools import it.

Settings come from config.json next to this file (or the file named by $TCON_KIT_CONFIG); copy config.example.json and
edit it. A few environment variables override single keys: TCON_KIT_WORK (work_dir), TCON_KIT_TV_SHELL (tv.shell, as a
shell-quoted string). Nothing here contacts any device at import time.

Command templates are argv lists (or one shell-quoted string). Placeholders are replaced literally, never via str.format:
  tv.shell        {cmd}  the POSIX sh command to run as root on the TV. Without {cmd} the command is sent on stdin.
                         Must return the command's stdout and its exit status (ssh does).
  tv.forward      {port} optional: forward local TCP {port} to the TV's loopback {port} (faster dump fetch).
  tv.key_cmd      {key}  optional: send a remote-control key (only used to dismiss the TV screensaver before photos).
  player.shell    {cmd}  run a shell command on the media player (Kodi JSON-RPC calls go through this).
  camera.capture  {out} {shutter}  take ONE photo; {out} is a path without extension; print the written file's path.

usage: python3 config.py show            -> print the effective settings (no device contact)
       python3 config.py get KEY         -> print one value (work_dir, captures, watcher_dir, watcher_enabled, ...)
"""
import datetime, json, os, pathlib, re, shlex, subprocess, sys

KIT = pathlib.Path(__file__).resolve().parent
TCON, MEASURE, SERVICES, OFFLINE = KIT / 'tcon', KIT / 'measure', KIT / 'services', KIT / 'offline'
HELPERS = TCON / 'helpers'                       # helpers/<read-poke|scan-arm|runtime>/bin = docker build output
CONFIG_FILE = pathlib.Path(os.environ.get('TCON_KIT_CONFIG', KIT / 'config.json')).expanduser()

DEFAULTS = {
    'work_dir': None,                            # default: <kit>/work
    'tv': {'shell': None, 'forward': None, 'forward_remove': None, 'timezone': None,
           'bake_window': ['10:30', '01:15'], 'key_cmd': None, 'player_input': 'SOURCE_TYPE_HDMI3'},
    'watcher': {'enabled': False, 'dir': None},
    'player': {'shell': None, 'clip_dir': '/storage/linefix/clips', 'jsonrpc_port': 9090},
    'camera': {'capture': None, 'raw_cmd': None, 'jpeg_cmd': None, 'keep_photos': False,
               'analysis': {'bar_columns': 320, 'first_column': 1100, 'rows': [0.40, 0.60]}},
    'alert': {'url': None, 'token_file': None},
}

def _merge(a, b):
    out = dict(a)
    for k, v in (b or {}).items():
        out[k] = _merge(a[k], v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
    return out

def _load():
    try: user = json.loads(CONFIG_FILE.read_text())
    except FileNotFoundError: user = {}
    return _merge(DEFAULTS, user)

CFG = _load()
if os.environ.get('TCON_KIT_TV_SHELL'): CFG['tv']['shell'] = shlex.split(os.environ['TCON_KIT_TV_SHELL'])
if os.environ.get('TCON_KIT_WORK'): CFG['work_dir'] = os.environ['TCON_KIT_WORK']

# ---- paths (work data: captures, backups, logs, service state) ----------------------------------------------------------
WORK = pathlib.Path(CFG['work_dir']).expanduser() if CFG['work_dir'] else KIT / 'work'
CAPTURES, BACKUP = WORK / 'captures', WORK / 'backup'
S0SVC, RTSVC, BAKE11 = WORK / 's0svc', WORK / 'rtsvc', WORK / 'bake11'     # state of the three services
CAMERA_LOCK = WORK / 'camera.lock'
WATCHER_ENABLED = bool(CFG['watcher']['enabled'])
WATCHER_DIR = pathlib.Path(CFG['watcher']['dir']).expanduser() if CFG['watcher']['dir'] else WORK / 'watcher'

def ensure_dirs():
    for d in (WORK, CAPTURES, CAPTURES / 'optical', BACKUP, S0SVC, RTSVC, BAKE11, WATCHER_DIR):
        d.mkdir(parents=True, exist_ok=True)

# ---- command templates ------------------------------------------------------------------------------------------------
def _argv(template, **subs):
    """-> (argv, stdin). Placeholders are replaced literally; {cmd} missing -> the command goes to stdin."""
    t = shlex.split(template) if isinstance(template, str) else list(template)
    stdin = None
    if 'cmd' in subs and not any('{cmd}' in x for x in t): stdin = subs['cmd']
    out = []
    for x in t:
        for k, v in subs.items(): x = x.replace('{' + k + '}', str(v))
        out.append(x)
    return out, stdin

def tv_root(cmd, timeout=30):
    """Run CMD as root on the TV through tv.shell -> stdout. Raises RuntimeError on a non-zero exit (same contract as the
    root channel the tools were built on: stdout back, exit code checked)."""
    if not CFG['tv']['shell']: raise RuntimeError('tv.shell is not configured (config.json); no TV access')
    argv, stdin = _argv(CFG['tv']['shell'], cmd=cmd)
    p = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=timeout + 60)
    if p.returncode != 0: raise RuntimeError(f'remote rc={p.returncode} {p.stderr[-300:]} {p.stdout[-300:]}')
    return p.stdout

def tv_forward(port, remove=False):
    """Optional TCP forward for the dump fetch. -> True if configured (and run), False if not configured."""
    t = CFG['tv']['forward_remove' if remove else 'forward']
    if not t: return False
    argv, _ = _argv(t, port=port); subprocess.run(argv, capture_output=True, text=True, timeout=20); return True

def tv_key(key):
    if not CFG['tv']['key_cmd']: return 'tv.key_cmd not configured'
    argv, _ = _argv(CFG['tv']['key_cmd'], key=key)
    return subprocess.run(argv, capture_output=True, text=True, timeout=60).stdout[-200:]

def player_shell(cmd, timeout=20):
    """Run CMD on the media player -> stdout ('' on a non-zero exit, like the original helper)."""
    if not CFG['player']['shell']: raise RuntimeError('player.shell is not configured (config.json)')
    argv, stdin = _argv(CFG['player']['shell'], cmd=cmd)
    return subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=timeout).stdout

def camera_capture(out_base, shutter=None, timeout=150):
    """Take one photo with camera.capture -> (pathlib.Path of the file written, exposure text or None). The hook may print a
    line SHUTTER=1/50 (exposure actually used); the last stdout line naming an existing file is the photo."""
    if not CFG['camera']['capture']: raise RuntimeError('camera.capture is not configured (config.json)')
    out_base = pathlib.Path(out_base); out_base.parent.mkdir(parents=True, exist_ok=True)
    argv, _ = _argv(CFG['camera']['capture'], out=out_base, shutter=shutter or 'auto')
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    lines = p.stdout.strip().splitlines()
    sh = next((l.strip()[8:] for l in reversed(lines) if l.strip().startswith('SHUTTER=')), None)
    for line in reversed(lines):
        f = pathlib.Path(line.strip()).expanduser()
        if line.strip() and f.is_file(): return f, sh
    hits = sorted(out_base.parent.glob(out_base.name + '.*'))
    if hits: return hits[-1], sh
    raise RuntimeError(f'camera.capture wrote no file (rc {p.returncode}): {p.stdout[-200:]} {p.stderr[-200:]}')

def camera_mode(mode):
    """Optional camera.raw_cmd / camera.jpeg_cmd (e.g. a gphoto2 --set-config call). -> short status text."""
    t = CFG['camera'][f'{mode}_cmd']
    if not t: return f'camera {mode} command not configured (set the format on the camera)'
    argv, _ = _argv(t); return subprocess.run(argv, capture_output=True, text=True, timeout=60).stdout.strip()[-200:]

ANALYSIS = CFG['camera']['analysis']; KEEP_PHOTOS = bool(CFG['camera']['keep_photos'])
CLIP_DIR, JSONRPC_PORT = CFG['player']['clip_dir'], int(CFG['player']['jsonrpc_port'])
PLAYER_INPUT = CFG['tv']['player_input']

# ---- alerts (optional) ------------------------------------------------------------------------------------------------
ALERT_URL = CFG['alert']['url']
ALERT_TOKEN_FILE = pathlib.Path(CFG['alert']['token_file']).expanduser() if CFG['alert']['token_file'] else WORK / 'alert-token'

# ---- TV local time and the on-demand bake window ------------------------------------------------------------------------
TV_TZ = CFG['tv']['timezone']                    # IANA zone name, a fixed offset such as "+02:00", or null = this host's zone
BAKE_WINDOW = tuple(CFG['tv']['bake_window'])

def _tz(spec):
    if not spec: return None
    m = re.fullmatch(r'([+-])(\d\d):?(\d\d)', spec)
    if m:
        d = datetime.timedelta(hours=int(m[2]), minutes=int(m[3])); return datetime.timezone(-d if m[1] == '-' else d)
    import zoneinfo; return zoneinfo.ZoneInfo(spec)

def tv_local(now=None):
    t = datetime.datetime.fromtimestamp(now if now is not None else __import__('time').time(), datetime.timezone.utc)
    z = _tz(TV_TZ); return t.astimezone(z) if z else t.astimezone()

def _mins(hhmm):
    h, m = hhmm.split(':'); return int(h) * 60 + int(m)

def in_bake_window(now=None):
    """True inside BAKE_WINDOW (TV local; the window may wrap past midnight)."""
    t = tv_local(now); m = t.hour * 60 + t.minute; a, b = (_mins(x) for x in BAKE_WINDOW)
    return a <= m <= b if a <= b else (m >= a or m <= b)

def window_text(): return f'{BAKE_WINDOW[0]}-{BAKE_WINDOW[1]} TV local'

if __name__ == '__main__':
    vals = dict(kit=KIT, config_file=CONFIG_FILE, work_dir=WORK, captures=CAPTURES, backup=BACKUP, s0svc=S0SVC, rtsvc=RTSVC,
                bake11=BAKE11, watcher_dir=WATCHER_DIR, watcher_enabled=int(WATCHER_ENABLED), tcon=TCON, measure=MEASURE,
                services=SERVICES, helpers=HELPERS, tv_shell_configured=int(bool(CFG['tv']['shell'])),
                bake_window=window_text(), tv_timezone=TV_TZ or 'host local')
    if sys.argv[1:2] == ['get'] and len(sys.argv) == 3: print(vals[sys.argv[2]]); sys.exit(0)
    if sys.argv[1:2] == ['show']:
        for k, v in vals.items(): print(f'{k:22s} {v}')
        sys.exit(0)
    print(__doc__); sys.exit(2)
