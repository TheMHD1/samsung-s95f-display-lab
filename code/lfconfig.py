"""Shared helpers: configuration, SSH/SCP to the CoreELEC box, Kodi JSON-RPC and playback control.

Everything that talks to the box goes through ssh/scp as root (CoreELEC's normal SSH login; enable SSH in the
CoreELEC settings and install your public key on the box). Nothing here touches the TV.
"""
import json, os, shlex, subprocess, time

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get('LINEFIX_CONFIG', os.path.join(HERE, 'config.json'))
STAGE = os.path.join(HERE, '.stage')          # local staging dir for generated files (not /tmp: survives reboots)


def load_config(path=CONFIG_PATH):
    if not os.path.exists(path):
        raise SystemExit(f'config not found: {path}  (copy config.example.json to config.json and edit it)')
    cfg = json.load(open(path))
    ln = cfg['line']
    ln.setdefault('ref_col', (ln['c0'] + ln['c1']) // 2)
    ln.setdefault('report_cols', [ln['c0'] - 2, ln['c1'] + 2])
    ln.setdefault('bg_left', [ln['c0'] - 38, ln['c0'] - 8])
    ln.setdefault('bg_right', [ln['c1'] + 7, ln['c1'] + 37])
    return cfg


CFG = load_config()                            # exits with a hint if config.json is missing
D = CFG['box'].get('linefix_dir', '/storage/linefix')


def target():
    return CFG['box']['host']


def _opts():
    """SSH options incl. the login user (passed as -o User=..., works for ssh and scp)."""
    return ['-o', f"User={CFG['box'].get('user', 'root')}", *CFG['box'].get('ssh_options', [])]


def ssh(cmd, timeout=40, check=False):
    """Run a shell command on the box, return stdout."""
    p = subprocess.run(['ssh', *_opts(), target(), cmd],
                       capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f'box command failed ({p.returncode}): {cmd[:120]}\n{p.stderr[-400:]}')
    return p.stdout


def scp(local_files, remote_path, timeout=60):
    if isinstance(local_files, str):
        local_files = [local_files]
    subprocess.run(['scp', '-q', *_opts(), *local_files, f'{target()}:{remote_path}'],
                   check=True, timeout=timeout)


def put_atomic(local_file, remote_path):
    """Upload then rename, so Kodi never reads a half-written file."""
    scp(local_file, remote_path + '.tmp')
    ssh(f'mv {shlex.quote(remote_path)}.tmp {shlex.quote(remote_path)}', check=True)


def kodi_send(action):
    """Send a built-in action through kodi-send (EventServer) on the box."""
    return ssh(f'kodi-send --action={shlex.quote(action)} >/dev/null')


def rpc(method, params=None, timeout=20):
    """Kodi JSON-RPC over the raw TCP port 9090 on the box (enable 'Allow remote control' in Kodi).
    Returns the raw reply text."""
    body = json.dumps({'jsonrpc': '2.0', 'method': method, 'id': 1, **({'params': params} if params else {})})
    return ssh(f"printf '%s' {shlex.quote(body)} | nc -w 3 127.0.0.1 9090", timeout=timeout)


def rpc_json(method, params=None):
    out = rpc(method, params)
    try:
        return json.loads(out.strip().splitlines()[-1]).get('result')
    except Exception:
        return None


# ---------- test clip playback (calibration) ----------
def play(clip):
    """Play a calibration clip in a loop. Player.Open's own 'repeat' option is ignored by Kodi, so SetRepeat is sent too."""
    path = f"{CFG['clips']['box_dir']}/{clip}.mp4"
    rpc('Player.Open', {'item': {'file': path}, 'options': {'repeat': 'one'}})
    time.sleep(1.0)
    rpc('Player.SetRepeat', {'playerid': 1, 'repeat': 'one'})


def playing(clip):
    it = rpc('Player.GetItem', {'playerid': 1, 'properties': ['file']})
    return f'/{clip}.mp4' in it


def stop():
    for pid in (0, 1, 2):
        rpc('Player.Stop', {'playerid': pid})


def output_mode():
    return ssh('cat /sys/class/display/mode').strip()
