#!/usr/bin/env python3
"""Run the read-only TconDump helper with the watcher paused and the shared TV lock held. Always resumes the watcher."""
import argparse, base64, hashlib, json, os, pathlib, secrets, subprocess, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1])); import config as C   # all machine-specific settings
HERE = C.TCON; W = C.WATCHER_DIR; C.ensure_dirs(); sys.path.insert(0, str(C.TCON))
import tvlock as mw                                        # lock_script / unlock_script (TV-side lock shared by all tools)
BIN = C.HELPERS/'read-poke'/'bin'; OWNER = 'claude-tcon-dump'
PAUSE = W/'watcher.pause'; STATE = W/'watcher-v3-state.json'
def root(cmd, timeout=30):
    """Run CMD as root on the TV (config tv.shell) -> stdout; raises on a non-zero exit. Touches watcher.busy first, as
    the original root channel did (an optional blackout watcher yields the TV while that file is fresh)."""
    (W/'watcher.busy').touch()
    return C.tv_root(cmd, timeout)
def phase():
    d = json.load(open(STATE)); return d.get('phase'), d.get('heartbeat_t', 0)
def wait_phase(want, since, limit):
    if not C.WATCHER_ENABLED: return next(iter(want))     # no blackout watcher configured: nothing to wait for
    end = time.time()+limit
    while time.time() < end:
        try:
            ph, hb = phase()
            if ph in want and hb >= since: return ph
        except Exception: pass
        time.sleep(1)
    return None
def main():
    a = argparse.ArgumentParser(); a.add_argument('--ranges', required=True); a.add_argument('--name', required=True); a.add_argument('--chunk', type=int, default=512); a.add_argument('--budget-ms', type=int, default=60000); a.add_argument('--fetch', action='store_true', default=True); x = a.parse_args()
    out = C.CAPTURES/x.name; out.mkdir(parents=True, exist_ok=False)
    start = time.time(); PAUSE.touch(); locked = False; stage = f'/tmp/claude-tcon-{secrets.token_hex(8)}'; res = {}
    try:
        if not wait_phase({'PAUSED'}, start, 45): raise RuntimeError('watcher did not reach PAUSED')
        o = root(mw.lock_script('/tmp/s95f-watcher.lock', OWNER, 120), 15)
        if 'LOCK=ACQUIRED' not in o: raise RuntimeError('TV lock '+o[-100:])
        locked = True
        info = root('cat /proc/sys/kernel/random/boot_id; cat /sys/bus/usb/devices/7-1/devnum').split(); boot, dev = info[0], int(info[1])
        root(f'umask 077; mkdir {stage}')
        for f in ('TconDump.dll', 'TconDump.runtimeconfig.json', 'TconDump.deps.json'):
            b = base64.b64encode((BIN/f).read_bytes()).decode()
            for i in range(0, len(b), 4500): root(f"printf %s '{b[i:i+4500]}' >> {stage}/{f}.b64")
            root(f'base64 -d {stage}/{f}.b64 > {stage}/{f}; rm {stage}/{f}.b64; sha256sum {stage}/{f}')
        t = min(110, x.budget_ms//1000+25)
        cmd = f'cd {stage}; DOTNET_gcServer=0 /usr/bin/dotnet TconDump.dll --boot {boot} --device {dev} --out {stage}/dump.bin --chunk {x.chunk} --budget-ms {x.budget_ms} --ranges {x.ranges} > {stage}/native.out 2>&1; echo RC=$?; cat {stage}/dump.bin.json; echo'
        o = root(cmd, t); (out/'native.txt').write_text(o); print(o[-3000:])
        res = json.loads([l for l in o.splitlines() if l.startswith('{')][-1])
        root(f'chmod 755 {stage}; chmod 644 {stage}/dump.bin; sha256sum {stage}/dump.bin > {stage}/dump.sha; chmod 644 {stage}/dump.sha'); ok = True
        (out/'meta.json').write_text(json.dumps(dict(boot=boot, device=dev, ranges=x.ranges, chunk=x.chunk, utc=time.strftime('%FT%TZ', time.gmtime()), result=res), indent=1))
    finally:
        if locked:
            try: root(mw.unlock_script('/tmp/s95f-watcher.lock', OWNER), 15)
            except Exception as e: print('unlock', e)
        PAUSE.unlink(missing_ok=True); t = time.time()
        print('watcher', wait_phase({'MASKED'}, t, 75))
        if not res:
            root(f'rm -rf {stage}', 15)
    try:
        import socket
        want = root(f'cut -d" " -f1 {stage}/dump.sha').strip(); port = 18771
        t = time.time(); h = hashlib.sha256(); n = 0
        if C.CFG['tv']['forward']:                            # optional fast path: helper --serve + a TCP forward (tv.forward)
            root(f'cd {stage}; setsid nohup /usr/bin/dotnet TconDump.dll --serve {port} {stage}/dump.bin >/dev/null 2>&1 </dev/null & sleep 3; echo started', 12)
            C.tv_forward(port)
            with socket.create_connection(('localhost', port), 20) as c, open(out/'dump.bin', 'wb') as f:
                c.settimeout(60)
                while True:
                    b = c.recv(1 << 20)
                    if not b: break
                    f.write(b); h.update(b); n += len(b)
            C.tv_forward(port, remove=True)
        else:                                                 # default: base64 over the root shell (slower, no extra setup)
            b = base64.b64decode(''.join(root(f'base64 {stage}/dump.bin', 900).split()))
            (out/'dump.bin').write_bytes(b); h.update(b); n = len(b)
        print('fetched', n, 'in %.1fs' % (time.time()-t), 'hash ok' if h.hexdigest() == want else f'HASH MISMATCH {want} {h.hexdigest()}')
    finally:
        root(f'rm -rf {stage}', 15)
main()
