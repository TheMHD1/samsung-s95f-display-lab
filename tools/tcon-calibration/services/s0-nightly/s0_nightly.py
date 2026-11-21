#!/usr/bin/env python3
"""S95F nightly S0 sensing-gain trim, v3 (Claude 2026-11-19; after final-reviewer REVIEW-1 and the v2 review).
At each TV standby with off-sensing due, arm the plan.json S0 trim so the stock power-off scan rebuilds D4/C1 for the
damaged columns (bakes 2-5 today: core 0.14-0.35 -> ~0.85 of healthy). The trim only lasts until the next UNARMED scan,
so every qualifying standby is armed. Built on the proven arm_wake.py flow + TconDump --armwait (helper-bin/ = TconDump
with SIGTERM cancel, restore on any abnormal exit, fresh-flag check; sha256-pinned in plan.json).
After a bake the stored D4 + live C1 are audited once the TV has been on >= 5 min; a FAILED audit or any abnormal bake
LATCHES the service (rm LATCHED to reset). A still-pending audit does not block the next standby (an unarmed scan would
undo the fix); the newer bake supersedes it.
Files (this dir): plan.json, status.json, s0_nightly.log, DISABLE / LATCHED, owns_pause (marker: this service set the
watcher pause; ExecStopPost removes the pause only then). Usage: s0_nightly.py --live | --status | --reset (clear LATCHED after checking why)"""
import base64, hashlib, json, os, pathlib, re, secrets, signal, subprocess, sys, time

SRC = pathlib.Path(__file__).resolve().parent                     # this service's code (morning_audit.py)
sys.path.insert(0, str(SRC.parents[1])); import config as C; C.ensure_dirs()
HERE = C.S0SVC; TOP = C.TCON; CAP = C.CAPTURES                     # state dir; tools dir (cwd of child tools); captures
LOG, STATUS, PLAN = HERE / 's0_nightly.log', HERE / 'status.json', HERE / 'plan.json'
DISABLE, LATCHED, OWN = HERE / 'DISABLE', HERE / 'LATCHED', HERE / 'owns_pause'
HELPER = C.HELPERS / 'scan-arm' / 'bin'; FILES = ('TconDump.dll', 'TconDump.runtimeconfig.json', 'TconDump.deps.json')
CAMERA_LOCK = C.CAMERA_LOCK
S0 = 0x58691000; STOCK = 0x40CA; FLOOR = 0x2A1C          # gain clamp x0.65 .. x1.00 (never above stock)
LANES_OK = range(600, 680)                                # damaged strip lanes only
WAKE_MIN, WAKE_MAX = 11 * 60, 21 * 60                     # accept the off-sensing controller wake 11-21 min after standby
SAMPLE_S = 600                                            # helper holds/samples up to 10 min (scans take ~6 min)
OTHER_TOOLS = (b'arm_wake.py', b'bake_now.py')
OTHER_UNITS = ('s95f-arm-keep', 's95f-arm-bake2')
D = ('dbus-send --system --print-reply --dest=org.tizen.system.deviced /Org/Tizen/System/DeviceD/Display '
     'org.tizen.system.deviced.display.GetPowerState 2>/dev/null | tail -1')
_root = None; _pause = None

def log(m):
    with LOG.open('a') as f: f.write(time.strftime('%FT%TZ ', time.gmtime()) + m + '\n')
    print(m, flush=True)
def jload(p, d):
    try: return json.loads(p.read_text())
    except Exception: return d
def jsave(p, d):
    t = p.with_suffix('.tmp'); t.write_text(json.dumps(d, indent=1)); os.replace(t, p)
def latch(why):
    LATCHED.write_text(time.strftime('%FT%TZ ', time.gmtime()) + why + '\n'); log('LATCHED: ' + why)
    u = os.environ.get('S0_ALERT_URL') or C.ALERT_URL                 # optional (config alert.url)
    if u:
        try: subprocess.run(['curl', '-s', '-m', '10', '-d', 'S95F S0 service LATCHED: ' + why, u], timeout=20)
        except Exception: pass

def tvdump_ns():
    """tvdump.py's root() (BlockingIOError retry + watcher.busy) and PAUSE path; loaded the same way arm_wake.py does."""
    s = TOP / 'tvdump.py'; src = s.read_text().rsplit('main()', 1)[0]; g = {'__file__': str(s)}; argv = sys.argv
    try: sys.argv = argv[:1]; exec(compile(src, str(s), 'exec'), g)
    finally: sys.argv = argv
    return g
def root(cmd, t=20):
    return _root(cmd, t)
def pause_path():
    global _pause
    if _pause is None: _pause = tvdump_ns()['PAUSE']
    return _pause
def pause():
    OWN.touch(); pause_path().touch()
def unpause():
    if OWN.exists(): pause_path().unlink(missing_ok=True); OWN.unlink(missing_ok=True); log('watcher unpaused')
def state():
    """(standby, tcon_up) with one retry on an empty/odd reply; raises if the power state is still unreadable."""
    for k in range(2):
        o = root(D + '; test -e /sys/bus/usb/devices/7-1 && echo TCONUP; true', 20)
        if 'string' in o: return (('standby' in o) or ('lowpower' in o)), ('TCONUP' in o)
        time.sleep(3)
    raise RuntimeError('no power state')

def halves(word):
    """'0xWWWW' -> (W, W); '0xHHHHLLLL' -> (H, L); the format is chosen by digit count (review v3.2)."""
    d = word.lower().removeprefix('0x')
    if not d or any(c not in '0123456789abcdef' for c in d) or len(d) not in (4, 8): raise ValueError(f'bad word {word!r}')
    return (int(d, 16), int(d, 16)) if len(d) == 4 else (int(d[:4], 16), int(d[4:], 16))

def same_words(a, b):
    try: return a is not None and sorted(a) == sorted(b) and all(halves(a[k]) == halves(b[k]) for k in b)
    except (ValueError, TypeError): return False

def load_plan():
    p = json.loads(PLAN.read_text()); pokes = []
    for lane, word in sorted(p['lanes'].items()):
        # '0xWWWW' = both halves; '0xHHHHLLLL' = per column (bake 9 FACT: low half = even column 2L, high half = odd 2L+1)
        L = int(lane); hi, lo = halves(word)
        if L not in LANES_OK or not (FLOOR <= lo <= STOCK and FLOOR <= hi <= STOCK):
            raise ValueError(f'plan lane {L} word {word} outside bounds')
        if hi != lo and not 626 <= L <= 632:                   # review v3.3: as deploy.sh (stricter than bake_now.py: no 640 rider)
            raise ValueError(f'plan lane {L} word {word}: unequal halves only on band lanes 626-632')
        pokes.append(f'{S0 + 4 * L:08x}:{STOCK:04x}{STOCK:04x}:{hi:04x}{lo:04x}')
    for f in FILES:
        h = hashlib.sha256((HELPER / f).read_bytes()).hexdigest()
        if h != p['helper_sha256'][f]: raise ValueError(f'helper {f} sha256 {h} not pinned')
    return p, ','.join(pokes)

def others_active():
    """Another arming tool (one-shot arm_wake / on-demand bake_now) or its unit is running -> never arm concurrently."""
    me = str(os.getpid())
    for cp in pathlib.Path('/proc').glob('[0-9]*/cmdline'):
        if cp.parent.name == me: continue
        try: c = cp.read_bytes().split(b'\0')
        except OSError: continue
        if any(os.path.basename(x) in OTHER_TOOLS for x in c[:3]): return f'process {cp.parent.name} {c[:3]}'
    units = list(OTHER_UNITS)
    try:
        out = subprocess.run(['systemctl', '--user', 'list-units', '--no-legend', '--state=active,activating', 's95f-bake-now*'],
                             capture_output=True, text=True, timeout=20).stdout
        units += [l.split()[0] for l in out.splitlines() if l.strip()]
    except Exception: pass
    for u in units:
        r = subprocess.run(['systemctl', '--user', 'is-active', u], capture_output=True, text=True, timeout=20)
        if r.stdout.strip() in ('active', 'activating'): return f'unit {u}'
    return None

def gated():
    return DISABLE.exists() or LATCHED.exists()

def wait_for(cond, every):
    """Poll state() until cond(standby, up). Transient errors back off 180 s (never latch)."""
    while True:
        if gated(): return None
        try: st = state()
        except Exception as e: log(f'state error {e}; retry in 180 s'); time.sleep(180); continue
        if cond(*st): return st
        time.sleep(every)

def classify(txt):
    if 'write transfer failed' in txt or 'restore failed' in txt or 'restore impossible' in txt or 'MISMATCH' in txt:
        return 'abnormal', 'helper write/restore failed'
    if 'stop: InvalidOperationException: cancelled' in txt and re.search(r'restore \w+:\w+->\w+ ok', txt) \
            and not re.search(r'restore skip', txt):
        return 'aborted', 'TV left standby during the bake; trims restored cleanly'
    if 'restore' in txt: return 'abnormal', 'helper restored after a write (no clean cancel)'
    writes = re.findall(r' write (5869\w+):\w+->(\w+)', txt)
    if not writes: return 'none', 'no write'
    if 'normal end' in txt: return 'ok', 'scan reached power-down with trims held'
    return 'abnormal', 'writes without a confirmed scan end'

def standby_due():
    """Right after entering standby: True if the kernel logged a fresh 'off sensing required' line (< 150 s)."""
    try:
        q = root("cut -d' ' -f1 /proc/uptime; dmesg | grep -a -E 'off sensing required before power off|off_type' | tail -n 2", 20)
        lines = q.strip().split('\n'); now = float(lines[0])
        fresh = [l for l in lines[1:] if '[' in l and now - float(l.split('[')[1].split(']')[0]) < 150]
    except Exception as e:
        log(f'dmesg check failed {e}; not arming this standby'); return False
    log('standby; ' + ' | '.join(fresh)[:300])
    return any('off sensing required before power off' in l for l in fresh)

def arm_after_standby(pokes, t_sb, mark):
    """Standby with off-sensing due has just begun (at t_sb). Wait to WAKE_MIN, then arm once."""
    st = wait_for(lambda sb, up: (not sb) or (time.time() - t_sb >= WAKE_MIN - 60), 10)
    if st is None: return None
    if not st[0]: log('TV left standby before arming; nothing written'); return dict(result='skipped')
    if st[1]: log('controller already up before arming (scan may have started); skipping this standby'); return dict(result='skipped')
    o = others_active()
    if o: log(f'another arming tool active ({o}); not arming'); return dict(result='skipped')
    return run_helper(pokes, t_sb, mark)

DOG = ("n=0; while true; do s=$({D}); if echo \"$s\" | grep -q -e standby -e lowpower; then n=0; touch {st}/arm.log.standby; "
       "elif echo \"$s\" | grep -q string; then n=$((n+1)); if [ $n -ge 2 ]; then rm -f {st}/arm.log.standby; "
       "pkill -f \"[T]conDump.dll --armwait\"; break; fi; fi; sleep 0.5; done")

def run_helper(pokes, t_sb, mark):
    stage = f'/tmp/claude-s0-{secrets.token_hex(6)}'; launched = False; txt = ''
    wait_s = max(60, int(WAKE_MAX - (time.time() - t_sb)))
    try:
        root(f'umask 077; mkdir {stage}')
        for f in FILES:
            b = base64.b64encode((HELPER / f).read_bytes()).decode()
            for k in range(0, len(b), 4500): root(f"printf %s '{b[k:k+4500]}' >> {stage}/{f}.b64")
            root(f'base64 -d {stage}/{f}.b64 > {stage}/{f}; rm {stage}/{f}.b64')
        sums = root(f'cd {stage}; sha256sum ' + ' '.join(FILES), 20)
        for f in FILES:
            if hashlib.sha256((HELPER / f).read_bytes()).hexdigest() not in sums: raise RuntimeError(f'staged {f} hash mismatch')
        dog = DOG.format(D=D, st=stage)
        root(f"cd {stage}; touch arm.log.standby; echo {base64.b64encode(dog.encode()).decode()} | base64 -d > dog.sh; "
             f"setsid nohup sh -c \"$(cat dog.sh)\" > /dev/null 2>&1 < /dev/null & echo $! > {stage}/dog.pid; echo dog", 20)
        sb, up = state()
        if not sb or up: log(f'state changed before launch (standby={sb} tcon_up={up}); not launching'); return dict(result='skipped')
        pause(); mark()                                    # pause + in_progress only right before the launch
        root(f'cd {stage}; setsid nohup /usr/bin/dotnet TconDump.dll --armwait {stage}/arm.log {pokes} {wait_s} {SAMPLE_S} > {stage}/n.out 2>&1 < /dev/null & '
             f'echo $! > {stage}/helper.pid; echo started', 20)
        launched = True; log(f'armed on TV in {stage}: {pokes} wait {wait_s} s')
        t0, errs_since = time.time(), None
        while True:                                        # supervise every 2 s
            time.sleep(2)
            try:
                sb, up = state(); txt = root(f'cat {stage}/arm.log 2>/dev/null; kill -0 $(cat {stage}/helper.pid) 2>/dev/null && echo ALIVE', 20)
                errs_since = None
            except Exception as e:
                errs_since = errs_since or time.time(); log(f'supervise error {e}')
                if time.time() - errs_since > 120: unpause(); log('root channel down > 120 s (TV dog still guards the helper)')
                continue
            if 'exit rc=' in txt: log('helper finished'); unpause(); break
            if not sb:
                log('TV left standby -> unpause now, cancel helper (it restores)'); unpause()
                root(f"kill $(cat {stage}/helper.pid) 2>/dev/null; true", 20)
                for k in range(8):
                    time.sleep(2)
                    try:
                        txt = root(f'cat {stage}/arm.log 2>/dev/null', 20)
                        if 'exit rc=' in txt: break
                    except Exception: pass
                break
            if 'ALIVE' not in txt: log('helper died without exit line'); unpause(); break
            if time.time() - t0 > wait_s + SAMPLE_S + 300:
                log('supervise cap reached -> cancel helper'); unpause(); root(f"kill $(cat {stage}/helper.pid) 2>/dev/null; true", 20); time.sleep(10); break
    finally:
        unpause()                                          # first: never leave the watcher paused
        try:
            if launched: txt = root(f'cat {stage}/arm.log {stage}/n.out 2>/dev/null; true', 30) or txt
            (CAP / f's0svc-arm-{int(time.time())}.log').write_text(txt)
            root(f"kill $(cat {stage}/dog.pid 2>/dev/null) 2>/dev/null; kill $(cat {stage}/helper.pid 2>/dev/null) 2>/dev/null; rm -rf {stage}; true", 20)
        except Exception as e: log(f'cleanup error {e}')
    if not launched: return dict(result='skipped')
    r, why = classify(txt); log(f'bake result {r}: {why}')
    return dict(result=r, why=why, log_tail=txt[-1500:])

def capture(cmd, out=None, t=900):
    """Run a read-only capture tool. It pauses the watcher itself; if it is killed, its pause is removed via OWN."""
    OWN.touch()
    try:
        p = subprocess.run(cmd, cwd=TOP, capture_output=True, text=True, timeout=t)
        if out: out.write_text(p.stdout)
        log(f'capture {cmd[2]} rc={p.returncode} {(p.stdout + p.stderr)[-200:]!r}'); return p.returncode == 0
    except subprocess.TimeoutExpired:
        log(f'capture {cmd[2]} timed out'); return False
    finally:
        unpause()

def drift_note(st, d4, c1, lanes):
    """Visibility only (review v3.1): band movement of this passed scan against the deploy-time reference. Never latches."""
    dref = st.get('deploy_ref')
    if not dref or dref == d4: return
    try:
        p = subprocess.run(['python3', '-B', str(SRC / 'morning_audit.py'), '--ref', dref, '--new', d4, '--c1', c1, '--lanes', lanes,
                            '--band-delta'], cwd=TOP, capture_output=True, text=True, timeout=900)
        bf = json.loads(p.stdout.strip().splitlines()[-1]).get('band_fails', [])
        log(f'drift vs deploy ref {dref}: ' + ('; '.join(bf) if bf else 'band within 10/15 counts'))
    except Exception as e:
        log(f'drift note error {type(e).__name__}: {e}')

def audit_when_ready(st, plan):
    """Audit st['last_bake'] once the TV has been on >= 5 min with the camera idle and the watcher not paused.
    Returns 'done' (pass/fail recorded), 'standby' (TV went to standby first; returns its time), or 'gated'."""
    on_since = None; seen_on = False
    while True:
        if gated(): return 'gated', None
        try: sb, up = state()
        except Exception as e: log(f'audit state error {e}'); time.sleep(60); continue
        if sb:
            if seen_on: return 'standby', time.time()          # a NEW standby after the TV was on
            time.sleep(60); continue                           # still the bake's own standby: wait for TV-on
        seen_on = True; on_since = on_since or time.time()
        try: cam = time.time() - CAMERA_LOCK.stat().st_mtime < 600
        except FileNotFoundError: cam = False
        if time.time() - on_since >= 300 and not cam and not pause_path().exists(): break
        time.sleep(30)
    lb = st['last_bake']; n = lb.get('audit_tries', 0) + 1; tag = f"s0-{lb['id']}-t{n}"; d4, c1 = f'd4-{tag}', f'c1-{tag}'
    lb['audit_tries'] = n; jsave(STATUS, st)
    R = ','.join(f'{0x755b8000 + k * 0x388400:x}:fe000' for k in range(12))
    ok = (capture(['python3', '-B', 'd4store.py', 'live', d4], CAP / f'{d4}.json')
          and capture(['python3', '-B', 'tvdump.py', '--name', c1, '--chunk', '4096', '--budget-ms', '15000', '--ranges', R]))
    if not ok:
        if n >= 3: latch(f'audit captures failed {n} times')
        return 'done', None
    lanes = ','.join(sorted(plan['lanes'])); prev = ','.join(st.get('prev_lanes', []))
    extra = ['--band-min', str(plan.get('band_min_excess', -30))]
    if same_words(st.get('ref_words'), plan['lanes']): extra.append('--band-delta')   # ref scan used the same words
    try:
        p = subprocess.run(['python3', '-B', str(SRC / 'morning_audit.py'), '--ref', st['ref_d4'], '--new', d4, '--c1', c1, '--lanes', lanes,
                            '--prev-lanes', prev, '--floor', str(plan.get('floor_below_ref', 150)), '--json', str(HERE / f'audit-{lb["id"]}.json')]
                           + extra, cwd=TOP, capture_output=True, text=True, timeout=900)
        rc, out = p.returncode, p.stdout.strip()
    except subprocess.TimeoutExpired:
        rc, out = 1, 'audit timed out'
    log(f'audit {lb["id"]}: rc={rc} {out[-400:]}')
    if rc == 0:
        lb['audit'] = 'pass'; st['ref_d4'] = d4; st['prev_lanes'] = sorted(plan['lanes']); st['ref_words'] = dict(plan['lanes'])
        st['soft_fails'] = 0; drift_note(st, d4, c1, lanes)
    elif rc == 3 and st.get('soft_fails', 0) == 0:            # band only, first time: a repair flip clears at the next scan
        lb['audit'] = 'soft-fail'; st['soft_fails'] = 1; log(f'audit {lb["id"]}: band soft-fail; the next standby re-arms and re-scans')
    else: lb['audit'] = 'fail'; latch(f'audit failed for bake {lb["id"]} (rc {rc}): {out[-200:]}')
    jsave(STATUS, st); return 'done', None

def bake(st, pokes, t_sb):
    def mark():
        st['last_bake'] = dict(id=time.strftime('%Y%m%dT%H%MZ', time.gmtime()), pokes=pokes, result='in_progress', audit='n/a')
        jsave(STATUS, st)
    res = arm_after_standby(pokes, t_sb, mark)
    if res is None or res['result'] in ('skipped', 'none', 'aborted'):
        if res and 'last_bake' in st and st['last_bake'].get('result') == 'in_progress':
            st['last_bake'].update(result=res['result'], audit='n/a'); jsave(STATUS, st)
        if res: log(f"no bake this standby ({res['result']})")
        return
    st['last_bake'].update(result=res['result'], why=res['why'], audit='pending' if res['result'] == 'ok' else 'n/a')
    jsave(STATUS, st)
    if res['result'] != 'ok': latch(f"bake {st['last_bake']['id']} {res['result']}: {res['why']}")

def main():
    if '--status' in sys.argv:
        print(json.dumps(jload(STATUS, {}), indent=1), 'LATCHED' if LATCHED.exists() else '', 'DISABLE' if DISABLE.exists() else ''); return 0
    if '--reset' in sys.argv:
        st = jload(STATUS, {}); lb = st.get('last_bake', {})
        if lb.get('result') == 'in_progress': lb['result'] = 'reset'; jsave(STATUS, st)
        LATCHED.unlink(missing_ok=True); log('reset by owner/operator (LATCHED cleared)'); return 0
    if '--live' not in sys.argv: print(__doc__); return 2
    for sg in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sg, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))   # run finally blocks (unpause)
    global _root; load_plan(); _root = tvdump_ns()['root']; log('s0_nightly v3 start')
    st = jload(STATUS, {})
    if st.get('last_bake', {}).get('result') == 'in_progress': latch('previous run stopped in the middle of a bake')
    try:
        while True:
            if gated(): time.sleep(300); continue
            plan, pokes = load_plan(); st = jload(STATUS, {})
            if 'ref_d4' not in st: latch('status.json has no ref_d4 (seed it with the last audited D4 capture)'); continue
            lb = st.get('last_bake', {})
            t_sb = None
            if lb.get('audit') == 'pending':
                r, t_sb = audit_when_ready(st, plan)
                if r != 'standby': continue
                if not standby_due(): log('standby before the audit, no off-sensing due; audit stays pending'); continue
                log('qualifying standby before the audit could run; the new bake supersedes it')
                lb['audit'] = 'superseded'; jsave(STATUS, st); bake(st, pokes, t_sb); continue
            if t_sb is None:
                if wait_for(lambda sb, up: not sb, 60) is None: continue
                log('TV on; waiting for standby')
                if wait_for(lambda sb, up: sb, 30) is None: continue
                t_sb = time.time()
            if standby_due(): bake(st, pokes, t_sb)
            else: log('no off-sensing due this standby; keep waiting')
    finally:
        unpause()

if __name__ == '__main__':
    sys.exit(main())
