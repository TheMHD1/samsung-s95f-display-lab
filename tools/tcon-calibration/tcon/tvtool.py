#!/usr/bin/env python3
"""Run TconDump --watch or --poke with the watcher paused and TV lock held."""
import base64, json, pathlib, secrets, sys, time
sys.argv, args = [sys.argv[0]], sys.argv[1:]
import importlib.util as u
s = u.spec_from_file_location('td', str(pathlib.Path(__file__).with_name('tvdump.py')))
src = pathlib.Path(s.origin).read_text().rsplit('main()', 1)[0]; g = {'__file__': s.origin}; exec(compile(src, s.origin, 'exec'), g)
root, mw, PAUSE, BIN, OWNER, wait_phase = g['root'], g['mw'], g['PAUSE'], g['BIN'], g['OWNER'], g['wait_phase']
def run(tool_args, timeout=115):
    start = time.time(); PAUSE.touch(); locked = False; stage = f'/tmp/claude-tcon-{secrets.token_hex(8)}'
    try:
        if not wait_phase({'PAUSED'}, start, 45): raise RuntimeError('watcher did not pause')
        if 'LOCK=ACQUIRED' not in root(mw.lock_script('/tmp/s95f-watcher.lock', OWNER, 120), 15): raise RuntimeError('lock')
        locked = True; i = root('cat /proc/sys/kernel/random/boot_id; cat /sys/bus/usb/devices/7-1/devnum').split(); root(f'umask 077; mkdir {stage}')
        for f in ('TconDump.dll', 'TconDump.runtimeconfig.json', 'TconDump.deps.json'):
            b = base64.b64encode((BIN/f).read_bytes()).decode()
            for k in range(0, len(b), 4500): root(f"printf %s '{b[k:k+4500]}' >> {stage}/{f}.b64")
            root(f'base64 -d {stage}/{f}.b64 > {stage}/{f}; rm {stage}/{f}.b64')
        q = ' '.join(tool_args[1:]); root(f'cd {stage}; /usr/bin/dotnet TconDump.dll {tool_args[0]} {stage}/r.json {i[1]} {i[0]} {q} > n.out 2>&1; echo $?', timeout)
        return json.loads(root(f'cat {stage}/r.json'))
    finally:
        try: root(f'rm -rf {stage}', 15)
        except Exception as e: print('cleanup', e)
        if locked: root(mw.unlock_script('/tmp/s95f-watcher.lock', OWNER), 15)
        PAUSE.unlink(missing_ok=True); print('watcher', wait_phase({'MASKED'}, time.time(), 75))
if __name__ == '__main__': print(json.dumps(run(args), indent=0)[:6000])
