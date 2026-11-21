#!/usr/bin/env python3
"""Run TconDump-rt --rt MODE PLAN on the TV (Claude 2026-11-19; rtsvc/RT-SPEC.md §2, review-1 fixes).
Flow as tvtool_e2.py (pause the watcher, hold the TV lock, stage the helper, run it, always unlock + unpause), plus:
- one rt_tool at a time on this host (flock rtsvc/rt_tool.lock); refuses if the watcher is already paused by someone else;
- per-run TV lock owner (claude-rt-<token>), so no run ever re-enters a lock held by tvtool/tvdump or another rt_tool;
- pause marker rtsvc/owns_pause = {owner, pid, pause mtime}: only a pause this tool created is ever removed (here, by
  rt_service after any exit, or by the unit's ExecStopPost via --clear-own-pause);
- helper sha256 checked against rt_plan.json locally and after staging; TV must report exactly "lcdon" right before launch;
- the helper runs DETACHED on the TV (setsid nohup); r.json is polled with short root calls that also refresh the TV lock,
  so neither the host access flock nor the TV lock is held/aged by one long call. Each poll also refreshes a TV-side
  flag <stage>/r.json.lcdon, written only while deviced reports "lcdon"; the helper refuses any write unless it is 0..20 s old;
- bounded: helper launched <= 150 s after start, polling ends by 480 - 90 s, whole run <= 480 s. SIGTERM: stop before
  launch, or stop polling; 2 failed polls in a row (channel lost) or SIGTERM while the helper may run: release our pause,
  skip TV-side cleanup (the helper holds the USB claim; the TV lock expires by itself).
Usage: rt_tool.py audit | apply | apply-s1 | restore   -> prints ONE JSON line on stdout (diagnostics on stderr)
       rt_tool.py audit|apply|apply-s1 --plan <work>/rtsvc/rt_plan-e9-NAME.json   (identification sets, by hand only:
                                                        same bounds, same pinned helper, another plan file)
       rt_tool.py --clear-own-pause                     -> remove an orphaned pause of this tool (no TV contact)
Exit 0 = helper rc 0; 1 = helper refused/failed; 3 = no helper result (result has 'tool_error')."""
import base64, fcntl, hashlib, json, os, pathlib, re, secrets, signal, subprocess, sys, time

TOP = pathlib.Path(__file__).resolve().parent                     # tcon/ (tvdump.py)
sys.path.insert(0, str(TOP.parent)); import config as C; C.ensure_dirs()
HERE = C.RTSVC                                                     # state: rt_plan.json, owns_pause, rt_tool.lock
PLAN = HERE / 'rt_plan.json'; BIN = C.HELPERS / 'runtime' / 'bin'; OWN = HERE / 'owns_pause'; HOSTLOCK = HERE / 'rt_tool.lock'
FILES = ('TconDump.dll', 'TconDump.runtimeconfig.json', 'TconDump.deps.json')
LOCK = '/tmp/s95f-watcher.lock'
MODES = ('audit', 'apply', 'apply-s1', 'restore')
# lane -> (S1 address, stored stock word). Must match TconDump-rt RtS1/RtStock.
LANES = {'627': (0x586955CC, 0x40AA40AE), '628': (0x586955D0, 0x40A340A6),
         '629': (0x586955D4, 0x409B409F), '630': (0x586955D8, 0x40944098)}
FLOOR, STEP, BLUE_MIN, BLUE_MAX = 9900, 8000, 205, 820   # CONSULT-15: blue pair bound 205..820
HELPER_S = {'apply': 150, 'apply-s1': 150, 'audit': 40, 'restore': 40}   # apply worst case ~3 s rec + 100 s flip + 5 s + ~4 s
KILL_GRACE_S, POLL_S = 30, 3          # helper still alive HELPER_S + 30 s after launch -> kill -9 (state unknown -> audit)
PRELAUNCH_MAX_S = 150                 # never launch the helper later than this after start
TOTAL_MAX_S = 480                     # whole run incl. cleanup; < rt_service TOOL_TIMEOUT (540)
CLEANUP_S = 90                        # reserved after polling: rm + unlock (<= 35 s each) + margin
D = ('dbus-send --system --print-reply --dest=org.tizen.system.deviced /Org/Tizen/System/DeviceD/Display '
     'org.tizen.system.deviced.display.GetPowerState 2>/dev/null | tail -1')
_ns = None; TERM = []

def err(*a): print(*a, file=sys.stderr, flush=True)

def power_state(o):
    """deviced GetPowerState reply -> 'lcdon' | 'lcdoff' | 'standby' | 'suspend' | 'lowpower' | 'poweroff' | 'start' | None."""
    m = re.search(r'string "(\w+)"', o or ''); return m.group(1) if m else None

# ---- plan ------------------------------------------------------------------------------------------------------------
def word(s):
    if not isinstance(s, str) or not re.fullmatch(r'0x[0-9a-fA-F]{8}', s): raise ValueError(f'bad word {s!r} (want 0xHHHHLLLL)')
    return int(s, 16)

def check_s1(lane, stock, new):
    """Same bounds as TconDump-rt RtParse: STOCK = stored word; NEW halves in [9900, stock half], step <= 8000, NEW != STOCK."""
    if lane not in LANES: raise ValueError(f'lane {lane} not allowed (only 627..630)')
    if stock != LANES[lane][1]: raise ValueError(f'lane {lane} STOCK {stock:08x} is not the stored stock {LANES[lane][1]:08x}')
    if new == stock: raise ValueError(f'lane {lane} NEW equals STOCK')
    for sh in (16, 0):
        h, st = (new >> sh) & 0xFFFF, (stock >> sh) & 0xFFFF
        if h > st: raise ValueError(f'lane {lane} NEW half {h:#06x} above stock {st:#06x}')
        if h < FLOOR: raise ValueError(f'lane {lane} NEW half {h} below {FLOOR}')
        if st - h > STEP: raise ValueError(f'lane {lane} step {st - h} > {STEP}')

def check_helper(p, bin_dir=None):
    bin_dir = bin_dir or BIN
    for f in FILES:
        h = hashlib.sha256((bin_dir / f).read_bytes()).hexdigest()
        if h != p['helper_sha256'][f]: raise ValueError(f'helper {f} sha256 {h} not pinned in rt_plan.json')

def load_plan(path=None, bin_dir=None):
    """-> (plan dict, PLAN argument for --rt). Raises ValueError on any bound or sha mismatch."""
    p = json.loads((path or PLAN).read_text()); s1 = p['s1']
    if sorted(s1) != sorted(LANES): raise ValueError(f'plan lanes {sorted(s1)} must be exactly 627..630')
    items = []
    for lane in sorted(s1):
        pair = s1[lane]
        if not isinstance(pair, list) or len(pair) != 2: raise ValueError(f'lane {lane}: want [STOCK, NEW]')
        stock, new = word(pair[0]), word(pair[1]); check_s1(lane, stock, new)
        items.append(f'{LANES[lane][0]:08x}:{stock:08x}:{new:08x}')
    b = p['blue']
    if type(b) is not int or not BLUE_MIN <= b <= BLUE_MAX: raise ValueError(f'blue {b!r} outside {BLUE_MIN}..{BLUE_MAX}')
    check_helper(p, bin_dir)
    return p, ','.join(items) + f',{b}'

# ---- host side: TV access, pause ownership, host lock -----------------------------------------------------------------
def ns():
    """tvdump.py namespace (mw, PAUSE, wait_phase, root, W); loaded like tvtool.py."""
    global _ns
    if _ns is None:
        s = TOP / 'tvdump.py'; src = s.read_text().rsplit('main()', 1)[0]; g = {'__file__': str(s)}; argv = sys.argv
        try: sys.argv = argv[:1]; exec(compile(src, str(s), 'exec'), g)
        finally: sys.argv = argv
        _ns = g
    return _ns

def root(cmd, timeout=20):
    """tvdump.root() with a bounded wall time: timeout must be 1..120; subprocess cap timeout + 60 s (config.tv_root)."""
    if not 1 <= timeout <= 120: raise ValueError(f'root timeout {timeout} outside 1..120')
    g = ns()
    return g['root'](cmd, timeout)

def host_lock():
    f = open(HOSTLOCK, 'a')
    try: fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: f.close(); raise RuntimeError('another rt_tool is running on this host')
    return f

def host_lock_free():
    try: f = open(HOSTLOCK, 'a')
    except OSError: return False
    try: fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB); return True
    except BlockingIOError: return False
    finally: f.close()

def own_read():
    try: return json.loads(OWN.read_text())
    except Exception: return {} if OWN.exists() else None

def take_pause(pause, owner):
    """Marker first (so a crash never leaves an unmarked pause of ours), then the pause, then record its mtime."""
    OWN.write_text(json.dumps(dict(owner=owner, pid=os.getpid(), pause_mtime_ns=None)))
    pause.touch(); OWN.write_text(json.dumps(dict(owner=owner, pid=os.getpid(), pause_mtime_ns=pause.stat().st_mtime_ns)))

def release_pause(pause):
    """Remove the watcher pause only if it is still the one this tool created (same mtime); always drop the marker."""
    o = own_read()
    if o is None: return False
    removed = False
    try:
        want = o.get('pause_mtime_ns'); pm = pause.stat().st_mtime_ns
        if want is None:                                   # died between pause and mtime record: ours if made just after the marker
            try: om = OWN.stat().st_mtime_ns
            except FileNotFoundError: om = None
            ours = om is not None and 0 <= pm - om < 5 * 10**9
        else: ours = pm == want
        if ours: pause.unlink(); removed = True
        else: err('watcher pause was touched by someone else; left in place')
    except FileNotFoundError: pass
    OWN.unlink(missing_ok=True); return removed

def clear_own_pause(pause=None):
    """For rt_service / ExecStopPost: if a marker exists and no rt_tool holds the host lock, it is orphaned -> release."""
    if not OWN.exists() or not host_lock_free(): return None
    return release_pause(pause or ns()['PAUSE'])

def check_term(t0=None):
    if TERM: raise RuntimeError(f'terminated (signal {TERM[0]})')
    if t0 is not None and time.time() - t0 > PRELAUNCH_MAX_S: raise RuntimeError('pre-launch budget exceeded; helper not started')

def helper_probe(stage):
    """POSIX sh: 'ALIVE <pid>' for each process whose cmdline starts with our exact helper command (pid file first, else a
    /proc scan, so a wrong $! reads as 'FOREIGN', not as 'exited'); nothing if no helper of this stage runs."""
    m = f'TconDump.dll --rt {stage}/r.json '
    return (f'm="{m}"; ok() {{ c=$(tr "\\0" " " < /proc/$1/cmdline 2>/dev/null); case "$c" in "/usr/bin/dotnet $m"*|"dotnet $m"*) return 0;; esac; return 1; }}; '
            f'p=$(cat {stage}/helper.pid 2>/dev/null); '
            f'if [ -n "$p" ] && ok "$p"; then echo "ALIVE $p"; else '
            f'[ -n "$p" ] && [ -e /proc/$p ] && echo "FOREIGN $p"; '
            f'for d in /proc/[0-9]*; do q=${{d#/proc/}}; ok "$q" && echo "ALIVE $q"; done; fi')

LCDON = ('s=$(' + D + '); case "$s" in *\"lcdon\"*) touch {flag};; esac')   # TV-side flag, only while deviced says lcdon

# ---- one helper run --------------------------------------------------------------------------------------------------
def poll(stage, mode, owner, pause, mw, t_launch, deadline):
    """Every 3 s one short root call: refresh the TV lock, keep the lcdon flag fresh (only if deviced says lcdon), read
    r.json, check the helper process. Returns the helper result, or a tool_error dict with 'helper_launched' and
    'tv_cleanup' (False = the helper may still run or the channel is gone: skip TV-side cleanup, keep the TV lock to expire).
    Stops at the total deadline, on SIGTERM, or after 2 consecutive failed polls (root channel lost)."""
    hard = min(t_launch + HELPER_S[mode] + KILL_GRACE_S, deadline)
    q = (f'( {mw.lock_script(LOCK, owner, 120)} ); ' + LCDON.format(flag=f'{stage}/r.json.lcdon') +
         f'; echo "==R"; cat {stage}/r.json 2>/dev/null; echo; echo "==A"; {helper_probe(stage)}; true')
    fails = 0
    def alive_pids(txt): return [l.split()[1] for l in txt.splitlines() if l.startswith('ALIVE ')]
    while True:
        time.sleep(POLL_S)
        if TERM: return {'tool_error': f'terminated (signal {TERM[0]}) while the helper ran', 'helper_launched': True, 'tv_cleanup': False}
        if not pause.exists():                              # someone removed the pause mid-run: put it back (ours)
            err('watcher pause vanished during the helper run; re-pausing'); take_pause(pause, owner)
        try: o = root(q, 15); fails = 0
        except Exception as e:
            fails += 1; err('poll error', e)
            if fails >= 2:
                release_pause(pause)                        # helper holds the USB claim; TV lock expires by itself
                return {'tool_error': f'helper launched, root channel lost: {e}', 'helper_launched': True, 'tv_cleanup': False}
            continue
        if 'LOCK=ACQUIRED' not in o.split('==R')[0]: err('TV lock refresh failed:', o.split('==R')[0].strip()[-100:])
        body = o.split('==R', 1)[-1].split('==A', 1); res = body[0].strip(); probe = body[1] if len(body) > 1 else ''
        if 'FOREIGN ' in probe: err('helper.pid is not our helper:', probe.strip()[:80])
        if res:
            try:
                r = json.loads(res)
                if 'rc' in r: return r
            except ValueError: pass                         # partially written: next poll
        pids = alive_pids(probe)
        if not pids:
            time.sleep(1)
            try:
                r = json.loads(root(f'cat {stage}/r.json', 15))
                if 'rc' in r: return r
            except Exception: pass
            tail = ''
            try: tail = root(f'tail -c 300 {stage}/n.out 2>/dev/null; true', 15).strip()
            except Exception: pass
            return {'tool_error': f'helper exited without result: {tail[-200:]}', 'helper_launched': True}
        if time.time() > hard:
            try: root(f'{helper_probe(stage)} | while read a b; do [ "$a" = ALIVE ] && kill -9 "$b"; done; true', 15); gone = True
            except Exception as e: err('kill', e); gone = False
            return {'tool_error': f'helper still running at its time limit ({int(hard - t_launch)} s after launch): killed',
                    'helper_launched': True, 'killed': True, 'tv_cleanup': gone}

def run(mode, plan_arg):
    g = ns(); mw, PAUSE, wait_phase = g['mw'], g['PAUSE'], g['wait_phase']
    t0 = time.time(); hl = host_lock()
    try:
        if OWN.exists(): err('orphaned own pause from an earlier run:', release_pause(PAUSE))   # we hold the host lock
        if PAUSE.exists(): raise RuntimeError('watcher already paused by someone else')
        owner = f'claude-rt-{secrets.token_hex(4)}'; stage = f'/tmp/claude-rt-{secrets.token_hex(8)}'; locked = False; tv_cleanup = True
        take_pause(PAUSE, owner)
        try:
            if not wait_phase({'PAUSED'}, t0, 45): raise RuntimeError('watcher did not pause')
            check_term(t0)
            o = root(mw.lock_script(LOCK, owner, 120), 15)
            if 'LOCK=ACQUIRED' not in o: raise RuntimeError('TV lock ' + o.strip()[-100:])
            locked = True
            i = root('cat /proc/sys/kernel/random/boot_id; cat /sys/bus/usb/devices/7-1/devnum').split()
            if len(i) != 2 or not i[1].isdigit(): raise RuntimeError(f'no controller device ({i})')
            root(f'umask 077; mkdir {stage}')
            for f in FILES:
                check_term(t0); b = base64.b64encode((BIN / f).read_bytes()).decode()
                for k in range(0, len(b), 4500): root(f"printf %s '{b[k:k+4500]}' >> {stage}/{f}.b64")
                root(f'base64 -d {stage}/{f}.b64 > {stage}/{f}; rm {stage}/{f}.b64')
            sums = root(f'cd {stage}; sha256sum ' + ' '.join(FILES), 20)
            for f in FILES:
                if hashlib.sha256((BIN / f).read_bytes()).hexdigest() not in sums: raise RuntimeError(f'staged {f} hash mismatch')
            if 'LOCK=ACQUIRED' not in root(mw.lock_script(LOCK, owner, 120), 15): raise RuntimeError('TV lock refresh')
            # Exactly "lcdon" and the controller present right before the helper; boot/devnum unchanged since the claim.
            q = root(D + '; test -e /sys/bus/usb/devices/7-1 && echo TCONUP; cat /proc/sys/kernel/random/boot_id; '
                     'cat /sys/bus/usb/devices/7-1/devnum 2>/dev/null; ' + LCDON.format(flag=f'{stage}/r.json.lcdon') + '; true', 20)
            ps = power_state(q)
            if ps != 'lcdon' or 'TCONUP' not in q: raise RuntimeError(f'TV not on (power state {ps}) / controller absent')
            if i[0] not in q.split() or i[1] not in q.split(): raise RuntimeError('controller boot changed during staging')
            check_term(t0)
            root(f'cd {stage}; setsid nohup /usr/bin/dotnet TconDump.dll --rt {stage}/r.json {i[1]} {i[0]} {mode} {plan_arg} '
                 f'> {stage}/n.out 2>&1 < /dev/null & echo $! > {stage}/helper.pid; echo started', 20)
            res = poll(stage, mode, owner, PAUSE, mw, time.time(), t0 + TOTAL_MAX_S - CLEANUP_S)
            tv_cleanup = res.pop('tv_cleanup', True)
            return res
        finally:
            if tv_cleanup:
                try: root(f'rm -rf {stage}', 15)
                except Exception as e: err('cleanup', e)
                if locked:
                    try: root(mw.unlock_script(LOCK, owner), 15)
                    except Exception as e: err('unlock', e)
            else: err('skipping TV-side cleanup (helper may still run / channel lost); TV lock expires by itself')
            release_pause(PAUSE)
            left = TOTAL_MAX_S - (time.time() - t0)
            if not TERM and tv_cleanup and left > 5: err('watcher', wait_phase({'MASKED'}, time.time(), min(75, left)))
    finally:
        hl.close()

def main(argv):
    if argv == ['--clear-own-pause']:
        r = clear_own_pause(); err('own pause', {None: 'none / rt_tool running', True: 'removed', False: 'marker dropped'}[r]); return 0
    alt = None
    if len(argv) == 3 and argv[1] == '--plan' and argv[0] in ('audit', 'apply', 'apply-s1'):
        alt = pathlib.Path(argv[2]).resolve()
        if alt.parent != HERE.resolve() or not re.fullmatch(r'rt_plan-e9-[A-Za-z0-9]{1,12}\.json', alt.name):
            err('--plan must be <work>/rtsvc/rt_plan-e9-NAME.json'); return 2
        argv = argv[:1]
    if len(argv) != 1 or argv[0] not in MODES: err(__doc__); return 2
    for sg in (signal.SIGTERM, signal.SIGHUP): signal.signal(sg, lambda s, f: TERM.append(s))
    mode = argv[0]
    try:
        if mode == 'restore':
            check_helper(json.loads(PLAN.read_text())); plan_arg = '-'            # restore uses the helper's hard-coded stock
        else: plan_arg = load_plan(alt)[1]
        res = run(mode, plan_arg)
    except Exception as e:
        res = {'tool_error': f'{type(e).__name__}: {e}'}
    print(json.dumps(res), flush=True)
    return 3 if 'rc' not in res else (0 if res['rc'] == 0 else 1)

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
