#!/usr/bin/env python3
"""restore_bake11.py (Claude 2026-11-20, v2 after review 1): keep / put back the owner-approved BAKE 11.
REFERENCE IMPLEMENTATION - ADAPT BEFORE USE: WORDS / POKES / REF / the column checks below are the S95F 77-inch values for
one firmware (worked example); replace them with your own approved bake. Paths come from config.py (<work>/...).
Approved state (S95F worked example):
  S0 bake words 627 0x408A40CA, 628 0x32E03055, 629 0x339A2CB4, 630 0x40CA3904 (stored D4 reference captures/d4-bake11);
  runtime S1 + blue 820 = <work>/rtsvc/rt_plan-bake11.json (applied at every power-on by s95f-rt).
RULE (RUN-BAKE11.md): s95f-rt may apply only while the stored D4 is bake 11. "Hold H" = rtsvc/rt.disable written by these
tools + S1/blue back to stock. Its text says who made it: "bake11 H guard ..." / "bake11 H restore ..." (automatic: the guard
may lift it) or "bake11 H manual ..." (by hand: only a lift by hand ends it). An rt.disable with any other text is the
owner's kill switch; neither it nor a manual hold is ever written over or removed automatically.
Modes (one at a time: flock <work>/bake11/restore.lock; each mode except --check/--dry writes bake11/last_<mode>.json at its end):
  --check      read-only: stored D4 (d4store, ~40 s) vs d4-bake11 -> ONE JSON line: verdict ok (<= 10 counts: a normal
               re-bake of the same words) | drift (<= 25) | foreign (> 25 or a repair-did-not-run signature: bake 11 is
               gone) | error (also: busy, watcher paused, TV off). Exit 0 ok, 1 drift, 2 foreign, 3 error.
  --hold WHY   apply hold H, marked manual (--by-guard: marked guard) (TV off: rt.disable only; the RAM trims are gone
               with the controller power anyway).
  --lift       end a bake-11 hold: read the stored D4 first (must be ok/drift), stop s95f-rt, rt_tool apply (3 tries) +
               audit = plan/plan, remove rt.disable, start s95f-rt. Needs the approved plans in force. --by-guard: only
               an automatic (guard/restore) hold.
  (none)       restore = RUN-BAKE11.md: stop s95f-rt + s0-nightly, hold H, save the current D4, bake_now with the bake-11
               words (TV off ~12 min, it turns itself back on), after_now.sh, check_bake11 --same --after AND compare() ok
               or drift, one retry; then rt_plan-bake11 -> rt_plan.json, apply (3 tries, audit plan), deploy.sh (words +
               d4-bake11), lift H. Refused while s0-nightly is LATCHED or DISABLED.
  --auto       restore as started by the guard: also needs the approved plans already in force and a quiet TV
               (quiet(): TV input = the Ugoos with no TV menu, or the TV's own screensaver up (no TV-remote input for
               >= 2 min); Kodi black screensaver on; no player); quiet is checked again right before anything is stopped
               and before each bake.
  --probe      (NOT in the public kit: refused) (by hand only, not with --auto) the restore's bake runs probe/bake_now.py = the same bake with the read-only
               CONSULT-17 6c raw-plane timing probe (TconDump-probe --armprobe); probe files land in captures/probe-<t>/.
  --l2 SPEC    (NOT in the public kit: refused) (by hand only, not with --auto/--probe) CONSULT-17 6c L2 test: the restore's FIRST bake runs l2/bake_now.py
               SPEC = the same bake with bounded writes to the blue raw sensing plane (TconDump-l2 --arml2; files in
               captures/l2-<t>/). Needs the guard able to bring bake 11 back (unit active, no guard.disable / maintenance /
               auto_off, < 2 restores in 24 h). Before that bake the marker bake11/l2_pending is written: while it exists
               compare() calls every stored D4 'foreign' (an L2 bake is never taken for bake 11, whatever it changed: the
               guard restores it and nothing lifts the hold); only an accepted plain bake-11 bake removes it. If the L2 bake
               ran (bake_now rc 0 with all four S0 writes) -> NO retry bake: the L2 result stays stored for measurement,
               hold H (automatic), exit 6. If it did not run as planned -> the retry is a plain bake-11 bake.
  --pokes P    (with --l2 only) S0 words of the L2 bake (ADDR:OLD:NEW list, l2spec.pokes_ok bounds = bake_now's); default
               the bake-11 words. The retry bake and every plain restore always use the bake-11 words.
  --dry        preconditions of the restore only.
Every path ends with s0-nightly and s95f-rt running (s95f-rt idles while rt.disable exists); a failed restore/lift leaves
hold H. Child tools run in their own process group: a timeout or SIGTERM sends SIGTERM to the group (bake_now and rt_tool
clean up), then SIGKILL; afterwards an orphaned watcher pause is removed: only one whose time stamp falls inside a run of
one of our child tools, while no TV tool runs and s0-nightly does not own the pause (a pause set by hand while none of
our child tools runs is kept; never set one by hand while a restore runs - bake11/maintenance is the way to pause).
Exit 0 done, 1 failed, 4 not started (nothing changed, or (--auto) the TV stopped being quiet before the first bake),
5 (--auto) the first bake was not accepted and the TV was not quiet for the retry (retry deferred), 6 (--l2) the L2 bake is
stored and is not bake 11 (trims held off; bake 11 comes back by the guard or a plain restore)."""
import contextlib, fcntl, json, os, pathlib, re, shutil, signal, subprocess, sys, time
import numpy as np
SRC = pathlib.Path(__file__).resolve().parent                     # code; services/ siblings: s0-nightly, s95f-rt
sys.path.insert(0, str(SRC.parents[1])); import config as C; C.ensure_dirs()
HERE = C.BAKE11; TOP = C.TCON; CAP = C.CAPTURES; LOGS = C.WORK      # state dir; tools dir (cwd of child tools); captures; logs
DARK_DIR = CAP                                                  # dark-screen diagnostics (tests point it at tmp)
sys.path.insert(0, str(TOP)); sys.path.insert(0, str(SRC.parent / 's0-nightly')); sys.path.insert(0, str(SRC.parent / 's95f-rt'))
sys.path.insert(0, str(C.MEASURE))                              # screencheck / optical (quiet())
WORDS = '627=0x408A40CA,628=0x32E03055,629=0x339A2CB4,630=0x40CA3904'
POKES = '586919cc:40ca40ca:408a40ca,586919d0:40ca40ca:32e03055,586919d4:40ca40ca:339a2cb4,586919d8:40ca40ca:40ca3904'
REF = 'd4-bake11'; L2MARK = HERE / 'l2_pending'; GSTATE, GDIS, GMAINT = HERE / 'guard_state.json', HERE / 'guard.disable', HERE / 'maintenance'
PLAN11 = C.RTSVC / 'rt_plan-bake11.json'; PLAN = C.RTSVC / 'rt_plan.json'
RTDIS = C.RTSVC / 'rt.disable'; S0OWN = C.S0SVC / 'owns_pause'; S0PLAN = C.S0SVC / 'plan.json'
S0LATCH, S0DIS = C.S0SVC / 'LATCHED', C.S0SVC / 'DISABLE'; LOG = HERE / 'restore.log'
PAUSE = C.WATCHER_DIR / 'watcher.pause'
TOOLS = ('bake_now.py', 'arm_wake.py', 'after_now.sh', 'postbake.py', 'e1.py', 'e2.py', 'e3.py', 'e4.py', 'e5.py', 'e6.py',
         'e7.py', 'e8.py', 'e9.py', 'e10.py', 'brightset.py', 'lut_tool.py', 'rt_tool.py', 'tvtool.py', 'tvtool_e2.py', 'tvdump_rd.py', 'tvdump.py',
         'd4store.py', 'check_bake11.py', 'restore_bake11.py')
BAND = range(1255, 1263); CTRL = range(1268, 1293)          # CTRL: L2 control columns (+-2), reported only
def log(m):
    line = time.strftime('%FT%TZ ', time.gmtime()) + m
    with LOG.open('a') as f: f.write(line + '\n')
    print(line, flush=True)
def notify(msg, title='S95F bake 11'):
    """Optional alert (config alert.url / alert.token_file, as rt_service); token in a header (never on a command line)."""
    try:
        import urllib.request, rt_service as RS
        if not RS.ALERT: log('alert (no alert.url configured): ' + msg[:200]); return
        h = {'Title': title, 'Priority': 'high', 'Tags': 'tv,warning'}
        if RS.ALERT_TOKEN.exists(): h['Authorization'] = 'Bearer ' + RS.ALERT_TOKEN.read_text().strip()
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                urllib.request.Request(RS.ALERT, data=('S95F bake 11: ' + msg)[:300].encode(), headers=h), timeout=10) as r: r.read()
    except Exception as e: log(f'notify failed: {type(e).__name__}')
def _term(sig, _f):
    for s in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT): signal.signal(s, signal.SIG_IGN)
    raise SystemExit(128 + sig)
def quiet_signals():
    for s in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT): signal.signal(s, signal.SIG_IGN)
# ---- child processes -----------------------------------------------------------------------------------------------------
SPANS = []                                                  # [start, end] of each child tool run (orphan-pause rule)
def stop_group(p, wait):
    with contextlib.suppress(ProcessLookupError): os.killpg(p.pid, signal.SIGTERM)
    try: return p.communicate(timeout=wait)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError): os.killpg(p.pid, signal.SIGKILL)
        return p.communicate()
def run_group(cmd, timeout, term_wait=120):
    """cmd in its own process group -> (rc, stdout, stderr). Timeout -> SIGTERM to the group, term_wait, SIGKILL (rc 124).
    Our own SIGTERM (SystemExit) or any exception while waiting -> the same group stop, then re-raised."""
    span = [time.time() - 2, None]; SPANS.append(span)
    try:
        p = subprocess.Popen(cmd, cwd=str(TOP), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        return _wait(p, cmd, timeout, term_wait)
    finally: span[1] = time.time() + 2
def _wait(p, cmd, timeout, term_wait):
    try: out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        log(f'{os.path.basename(cmd[min(2, len(cmd) - 1)])} exceeded {timeout} s: SIGTERM to its group')
        out, err = stop_group(p, term_wait); return 124, out or '', err or ''
    except BaseException:
        quiet_signals(); log(f'stopping {os.path.basename(cmd[min(2, len(cmd) - 1)])} (signal)'); stop_group(p, term_wait); raise
    return p.returncode, out or '', err or ''
def sh(cmd, t):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=t, cwd=str(TOP))
    return p.returncode, (p.stdout or '') + (p.stderr or '')
def tools_running():
    me = os.getpid(); out = []
    for d in pathlib.Path('/proc').iterdir():
        if not d.name.isdigit() or int(d.name) == me: continue
        try: c = (d / 'cmdline').read_bytes().split(b'\0')
        except OSError: continue
        if any(os.path.basename(a.decode(errors='ignore')) in TOOLS for a in c[:3]): out.append(d.name)
    return out
def busy():
    o = tools_running()
    if o: return f'TV tool running (pids {o})'
    import rt_service as RS
    return RS.others_active()                                   # incl. a fresh s0-nightly pause / bake in progress
def clear_orphan_pause(why):
    """Remove a watcher pause only if it was made during a run of one of OUR child tools (its time stamp inside a span),
    no TV tool runs now and s0-nightly does not own it: a child killed before its own cleanup. A pause set by hand stays."""
    try: t = PAUSE.stat().st_mtime
    except OSError: return
    if S0OWN.exists() or tools_running(): return
    if any(a <= t <= (b if b is not None else time.time() + 2) for a, b in SPANS):
        PAUSE.unlink(missing_ok=True); log(f'removed an orphaned watcher pause ({why})')
# ---- TV / plan state -----------------------------------------------------------------------------------------------------
def tv_on():
    import s0_nightly as N
    if N._root is None: N._root = N.tvdump_ns()['root']
    sb, up = N.state(); return (not sb) and up
# ---- dark TCON after the QFS reboot (two incidents on 2026-11-20, FINDINGS / CONSULT-19) -------------------------
DARK_WAIT_S, DARK_BOOT_WAIT_S, DARK_POLL_S = 180, 420, 20   # CONSULT-20A: waiting does not help (latched); ~3 min
DARK_WHY = 'TV dark after the bake (TCON unpowered) even after one reboot'
WINDOW_WHY = f'no bake now (outside {C.window_text()} or marginal boot)'
DARK_PROBE = ('dbus-send --system --print-reply --dest=org.tizen.system.deviced /Org/Tizen/System/DeviceD/Display '
              'org.tizen.system.deviced.display.GetPowerState 2>/dev/null | tail -1; '
              'echo USB=$(test -e /sys/bus/usb/devices/7-1 && echo 1 || echo 0); dmesg | grep -a "tcon power(" | tail -1')
def _root():
    import s0_nightly as N
    if N._root is None: N._root = N.tvdump_ns()['root']
    return N._root
# CONSULT-20A: read-only diagnostics BEFORE the one reboot (settles which TV fault-monitor route latched the TCON off)
DARK_DIAG = ('echo === uptime; cat /proc/uptime; echo === poweronmode; cat /sys/class/tv_system/micom_info/poweronmode 2>&1; '
             'echo === fastvideo; ls /tmp/avoc_fastvideo_* 2>&1; echo === keys; '
             'vconftool get db/frc_tcon/pmic_error_count_2_prd 2>&1; vconftool get db/frc_tcon/pmic_error_count_3_prd 2>&1; '
             'echo === dlog; dlogutil -d 2>/dev/null | grep -a -E "stop tcon system|reboot_try|QD_TCON_OFF|SP_DRV_ERR|reboot tcon" | tail -40; '
             'echo === dmesg; dmesg | grep -a -E "Tcon Power|err_det|i2c Error|tcon state ng|tcon power\\(|HSM Status|vx1tx_lock" | tail -60')
def tv_local(now=None):
    return C.tv_local(now)                                      # config tv.timezone (TV local time)
def in_bake_window(now=None):
    """CONSULT-20A §3: on-demand runs only inside config tv.bake_window (S95F: 10:30..01:15 TV local; 14 normal returns
    10:39-01:43, 2 dark at 02:03 / 02:53)."""
    return C.in_bake_window(now)
def boot_healthy(root=None):
    """CONSULT-20A §2 pre-run check: the present boot must not look marginal (USB 7-1 present, last 'tcon power(' line = 1
    if there is one, HSM 0x0 if there is a line). -> None or why not."""
    root = root or _root()
    out = root('echo USB=$(test -e /sys/bus/usb/devices/7-1 && echo 1 || echo 0); dmesg | grep -a "tcon power(" | tail -1; '
               'dmesg | grep -a "HSM Status" | tail -1', 30)
    if 'USB=1' not in out: return 'TCON USB 7-1 absent'
    if 'tcon power(0)' in out: return 'kernel reports tcon power(0)'
    hs = re.search(r'HSM Status : (0x[0-9a-fA-F]+)', out)
    if hs and int(hs[1], 16) != 0: return f'HSM Status {hs[1]}'
    return None
def dark_probe(root):
    """-> (deviced power state, TCON USB 7-1 present, last kernel 'tcon power(N)' line says 0)."""
    out = root(DARK_PROBE, 30); st = re.search(r'string "([^"]*)"', out)
    return (st.group(1) if st else 'unknown'), 'USB=1' in out, 'tcon power(0)' in out
def dark_fix(root=None, clock=time.time, nap=time.sleep):
    """After OUR on-demand bake only. Twice on 2026-11-20 the QFS reboot that ends a bake brought the TV back 'lcdon' with the TCON
    unpowered (USB 7-1 absent, kernel 'tcon power(0)' every 60 s, dark screen); CEC and the remote did nothing, a TV reboot fixed it.
    Wait up to DARK_WAIT_S for USB 7-1. Still lcdon + absent + 'tcon power(0)' -> ONE reboot over the root channel, then wait up
    to DARK_BOOT_WAIT_S. Never reboots in standby / unknown state. -> 'ok' | 'not-on' | 'rebooted-ok' | 'rebooted-still-dark'."""
    root = root or _root(); t0 = clock(); last = None
    while True:
        try:
            last = dark_probe(root)
            if last[1]: return 'ok'
        except Exception as e: log(f'dark check: probe failed {e!r}'[:200]); last = None
        if clock() - t0 >= DARK_WAIT_S: break
        nap(DARK_POLL_S)
    if last is None or last[0] != 'lcdon' or not last[2]: return 'not-on'
    log(f'dark check: TV lcdon, TCON USB absent and "tcon power(0)" for {clock() - t0:.0f} s after the bake -> ONE TV reboot')
    try:
        diag = root(DARK_DIAG, 60); f = DARK_DIR / f'dark-{time.strftime("%Y%m%dT%H%M%S", time.gmtime())}.txt'; f.write_text(diag)
        log(f'dark check: diagnostics saved to {f.name}')
    except Exception as e: log(f'dark check: diagnostics failed {e!r}'[:200])
    notify('TV came back dark after the bake (TCON unpowered); rebooting the TV once')
    try: root('sync; (sleep 2; reboot) > /dev/null 2>&1 & echo scheduled', 20)
    except Exception as e: log(f'dark check: reboot command {e!r}'[:200])
    nap(60); t1 = clock()
    while clock() - t1 < DARK_BOOT_WAIT_S:
        try:
            if dark_probe(root)[1]: log('dark check: TCON back after the reboot'); return 'rebooted-ok'
        except Exception: pass
        nap(DARK_POLL_S)
    notify('TV still dark after one reboot (TCON unpowered): needs the owner (power cycle at the TV)')
    return 'rebooted-still-dark'
def plan_is_bake11():
    """The approved plans are in force: s0-nightly arms the bake-11 words and s95f-rt holds the bake-11 plan."""
    try:
        lanes = {k: int(v, 16) for k, v in json.loads(S0PLAN.read_text())['lanes'].items()}
        a, b = json.loads(PLAN.read_text()), json.loads(PLAN11.read_text())
        return lanes == {k: int(v, 16) for k, v in (x.split('=') for x in WORDS.split(','))} and \
            (a.get('s1'), a.get('blue')) == (b.get('s1'), b.get('blue')) and b.get('s1') is not None
    except Exception: return False
def _dis(): return RTDIS.read_text(errors='replace') if RTDIS.exists() else None
def h_ours():                                               # any bake-11 hold (automatic or manual)
    t = _dis(); return t is not None and t.startswith('bake11')
def h_auto():                                               # a hold the guard / a restore made (the guard may lift it)
    t = _dis(); return t is not None and t.startswith(('bake11 H guard', 'bake11 H restore'))
def quiet():
    """Nobody is watching: TV input = the player with no TV menu, or with the TV's own screensaver up (no TV-remote input
    for >= 2 min); Kodi's black screensaver on; no player (playing or paused)."""
    import screencheck as SC, optical as O
    good, info = SC.ok()                                    # good = player input, no TV screensaver, no TV menu
    tv_idle = info.get('src') == C.PLAYER_INPUT and (good or info.get('screensaver') not in ('0', '?', None))
    if not tv_idle: return False                            # (the TV's own screensaver = no TV-remote input >= 2 min)
    b = O.rpc('XBMC.GetInfoBooleans', {'booleans': ['System.ScreenSaverActive']}); p = O.rpc('Player.GetActivePlayers', {})
    return '"System.ScreenSaverActive":true' in b and '"result":[]' in p.replace(' ', '')
def units(action, *u): return sh(['systemctl', '--user', action, *u], 720)   # s95f-rt waits for a running rt_tool (<= 480 s)
def start_units():
    for u in ('s0-nightly', 's95f-rt'):
        if sh(['systemctl', '--user', 'is-active', u], 30)[0] != 0: units('start', u)
def rt(mode):
    rc, out, err = run_group([sys.executable, '-B', 'rt_tool.py', mode], 900, 120)
    lines = [l for l in out.splitlines() if l.startswith('{')]
    try: return json.loads(lines[-1])
    except (IndexError, ValueError): return {'rc': None, 'tool_error': (out + err)[-300:]}
def stock(a): return a.get('s1_state') == 'stock' and a.get('blue_state') == 'stock'
def hold_file(why, by):
    if RTDIS.exists() and not h_auto() and not (by == 'manual' and h_ours()):
        return False                                        # the owner's kill switch / a manual hold: keep it as it is
    RTDIS.write_text(f'bake11 H {by} {time.strftime("%FT%TZ", time.gmtime())}: {why}\n'); return True
def ensure_stock():
    a = rt('audit')
    if stock(a): return True
    r = rt('restore'); log(f'rt restore rc {r.get("rc")}'); return r.get('rc') == 0
def apply_plan():
    for k in range(3):
        r = rt('apply'); log(f'rt apply rc {r.get("rc")} {str(r.get("error") or r.get("tool_error") or "")[:150]}')
        if r.get('rc') == 0:
            a = rt('audit')
            if a.get('s1_state') == 'plan' and a.get('blue_state') == 'plan': return True
            log(f'apply rc 0 but audit {a.get("s1_state")}/{a.get("blue_state")}')
        time.sleep(60)
    log('apply failed 3 times: S1/blue back to stock (hold H)'); ensure_stock(); return False
# ---- stored D4 -----------------------------------------------------------------------------------------------------------
def compare(name, plain_bake=False):
    """Stored D4 capture NAME vs d4-bake11 on columns 1255..1262 (centred delta, as check_bake11), the worst of the whole-column
    medians and the 8 row blocks of 270 rows (l2/rowaudit.py; re-bake noise <= 3 per block). While the L2 marker exists
    the verdict is 'foreign' (signature 'l2-test-bake'), except for the result of a plain bake-11 bake (plain_bake=True)."""
    import bake_eval as E
    import rowaudit as RA                                       # tcon/rowaudit.py
    old, new = E.read_d4(REF), E.read_d4(name)
    d = new.medians - old.medians; cen = d - np.median(d, axis=1)[:, None]
    stored = new.medians - np.median(new.medians[:, 1200:1250], axis=1)[:, None]
    col_dev = float(np.max(np.abs(cen[:, list(BAND)]))); ctrl = float(np.max(np.abs(cen[:, list(CTRL)])))
    blk = RA.change(RA.blocks(name), RA.blocks(REF))            # (3, 8, W): CONSULT-18, a split bake must not pass
    dev = max(col_dev, float(np.max(np.abs(blk[:, :, list(BAND)])))); ctrl = max(ctrl, float(np.max(np.abs(blk[:, :, list(CTRL)]))))
    sig = [c for c in (1256, 1258, 1260) if stored[0, c] < -100] + [c for c in (1257, 1259) if stored[2, c] >= 110]
    if L2MARK.exists() and not plain_bake: sig.append('l2-test-bake')
    verdict = 'foreign' if sig or dev > 25 else ('drift' if dev > 10 else 'ok')
    return dict(verdict=verdict, max_dev=round(dev, 1), col_dev=round(col_dev, 1), ctrl_dev=round(ctrl, 1), signature=sig, generations=list(new.generations),
                ref_generations=list(old.generations), capture=name)
def read_d4(name):
    shutil.rmtree(CAP / name, ignore_errors=True)
    try: rc, out, err = run_group([sys.executable, '-B', 'd4store.py', 'live', name], 600, 60)
    finally: clear_orphan_pause(f'after reading {name}')
    if rc != 0: raise RuntimeError(f'd4store rc {rc}: {(out + err)[-300:]}')
    return name
def tag_files(tag):
    """Everything one restore bake TAG leaves (exact names: tag ...T0300 never matches ...T0300b)."""
    out = [CAP / f'd4-pre-{tag}', CAP / f'd4-{tag}', CAP / f'd4-{tag}.json', CAP / f'c1-ddr-{tag}', CAP / f'eval-{tag}.txt',
           LOGS / f'after_{tag}.log', CAP / 'optical' / f'post-{tag}.jsonl']
    return [p for p in out if p.exists()] + sorted((CAP / 'optical').glob(f'post-{tag}-*'))
def prune_tags(keep):
    tags = sorted({p.name[len('d4-pre-'):] for p in CAP.glob('d4-pre-bake11r*') if p.is_dir()},
                  key=lambda t: (CAP / f'd4-pre-{t}').stat().st_mtime)
    for t in tags[:-keep]:
        for p in tag_files(t): shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
def prune(prefix, base, keep):
    for d in sorted(base.glob(prefix + '*'), key=lambda p: p.stat().st_mtime)[:-keep]:
        shutil.rmtree(d, ignore_errors=True) if d.is_dir() else d.unlink(missing_ok=True)
@contextlib.contextmanager
def lock():
    with open(HERE / 'restore.lock', 'w') as lk:
        try: fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB); got = True
        except BlockingIOError: got = False
        yield got
def read_precheck():
    o = busy()
    if o: return o
    if PAUSE.exists(): return 'watcher paused by someone else'
    if not tv_on(): return 'TV is not on'
    return None
def check():
    try:
        with lock() as got:
            why = read_precheck() if got else 'a restore / hold / lift is running'
            if why: r = dict(verdict='error', why=why)
            else: r = compare(read_d4(f'd4-g{time.strftime("%Y%m%dT%H%M%S", time.gmtime())}')); prune('d4-g2', CAP, 6)
    except BaseException as e: r = dict(verdict='error', why=repr(e)[:300])
    print(json.dumps(r), flush=True); return {'ok': 0, 'drift': 1, 'foreign': 2}.get(r['verdict'], 3)
# ---- TV-changing modes ---------------------------------------------------------------------------------------------------
STARTED = False; PROBE = False; L2 = None; L2POKES = None    # L2POKES: --pokes (S0 words of the L2 bake), default POKES
def one_bake(tag, auto, probe=False, l2=None):
    """quiet re-check (auto) + bake_now + after_now + check. -> (accepted, why)."""
    global STARTED
    pre = f'd4-pre-{tag}'
    if auto and not quiet(): return False, 'not quiet any more'
    if not in_bake_window(): return False, WINDOW_WHY                 # review: EVERY bake (the retry too), CONSULT-20A §3
    try: b = boot_healthy()
    except Exception as e: b = f'boot check failed {e!r}'[:120]
    if b: return False, f'{WINDOW_WHY}: present TV boot looks marginal ({b})'
    read_d4(pre)
    if l2: L2MARK.write_text(f'{time.strftime("%FT%TZ", time.gmtime())} {tag} {l2}\n')   # before anything can be written
    STARTED = True; log(f'bake {tag}: bake_now (TV off ~12 min)')
    pk = (L2POKES or POKES) if l2 else POKES                    # the retry / plain bakes always use the bake-11 words
    cmd = [sys.executable, '-B', 'l2/bake_now.py', pk, l2] if l2 else [sys.executable, '-B', 'probe/bake_now.py' if probe else 'bake_now.py', POKES]
    rc, out, err = run_group(cmd, 75 * 60, 600)
    log(f'bake_now rc {rc}: ' + ' | '.join(l for l in (out + err).splitlines() if 'write' in l or 'end' in l or 'refus' in l)[-300:])
    # the dark return comes from the QFS reboot, not from our helper: check whenever the off-sensing request may have been sent
    # (review: not only after rc 0). Not for bake_now rc 2 or "TV not on" (refused before RequestOffSensing).
    if not (rc == 2 or (rc == 1 and 'RequestOffSensing needs power state normal' in out + err)):   # rc 3 too (review: reply may be lost)
        d = dark_fix(); log(f'dark check: {d}')
        if d == 'rebooted-still-dark': return False, DARK_WHY
    if rc != 0: return False, f'bake_now rc {rc}'
    if l2 and not s0_written(out, pk): return False, 'bake_now wrote no (or not all) S0 words: the L2 bake did not run as planned'
    rc, _, _ = run_group(['bash', 'after_now.sh', tag, 'bake11'], 45 * 60, 120); log(f'after_now rc {rc}')
    rc, out, _ = run_group([sys.executable, '-B', 'check_bake11.py', '--same', '--after', pre, REF, f'd4-{tag}'], 300, 30)
    log(f'check_bake11 rc {rc}: ' + (out.strip().splitlines()[-1][:300] if out.strip() else ''))
    if rc not in (0, 3): return False, f'check_bake11 rc {rc}'
    c = compare(f'd4-{tag}', plain_bake=not l2); log(f'compare {json.dumps(c)[:200]}')
    if c['verdict'] not in ('ok', 'drift'): return False, f'stored D4 {c["verdict"]} ({c["max_dev"]} counts)'
    return True, f'check rc {rc}, {c["verdict"]} {c["max_dev"]}'
def s0_written(out, pokes=POKES):
    """bake_now's final 'writes:' line holds every S0 word of POKES, read back (helper line 'write ADDR:OLD->NEW')."""
    last = next((l for l in reversed(out.splitlines()) if l.startswith('writes: ')), '')
    return all(f'write {a}:{o}->{n}' in last for a, o, n in (x.lower().split(':') for x in pokes.split(',')))
def guard_can_restore():
    """--l2 precondition: the guard will bring bake 11 back by itself -> None, else why not."""
    if sh(['systemctl', '--user', 'is-active', 's95f-bake11-guard'], 30)[0] != 0: return 'the bake-11 guard is not running'
    if GDIS.exists() or GMAINT.exists(): return 'guard.disable or bake11/maintenance is present'
    try: st = json.loads(GSTATE.read_text())
    except (OSError, ValueError): st = {}
    if st.get('auto_off'): return 'the guard has automatic restore OFF (guard.py --reset first)'
    if len([t for t in st.get('restores', []) if time.time() - t < 86400]) >= 2: return 'the guard used its 2 restores of the last 24 h'
    return None
def restore(auto):
    ts = time.strftime('%Y%m%dT%H%M', time.gmtime()); ok = False; note = []; reason = ''; deferred = False; l2_kept = False; dark = False
    owner_dis = RTDIS.exists() and not h_auto()                 # the owner's kill switch or a manual hold: kept, no apply
    try:
        notify('restoring the approved bake 11 now: the TV turns off for ~12 min and back on by itself')
        log(f'restore start (auto={auto}, owner rt.disable={owner_dis})'); hold_file('bake-11 restore in progress', 'restore')
        rc, out = units('stop', 's95f-rt', 's0-nightly')
        if rc != 0: raise RuntimeError(f'could not stop the services: {out[-200:]}')
        if not ensure_stock(): raise RuntimeError('S1/blue could not be put back to stock')
        for k, tag in enumerate((f'bake11r{ts}', f'bake11r{ts}b')):
            ok, why = one_bake(tag, auto, PROBE and k == 0, L2 if k == 0 else None); reason = why   # the retry never probes / writes
            log(f'bake {tag}: ' + ('accepted' if ok else 'not accepted') + f' ({why})')
            if ok: break
            if why == DARK_WHY: dark = True; break                  # owner needed: no retry bake, no L2 "kept" message
            if L2 and k == 0:                                   # L2 bake ran: keep the result (no retry bake)
                l2_kept = STARTED and not why.startswith('bake_now')
                if l2_kept: break
                log('the L2 bake did not run as planned: the retry is a plain bake-11 bake')
            if why == 'not quiet any more' or why.startswith(WINDOW_WHY): deferred = k == 1; break   # first bake: rc 4; retry: rc 5
        if ok:
            L2MARK.unlink(missing_ok=True)                      # a plain bake-11 bake was accepted: no L2 result stored any more
            shutil.copyfile(PLAN11, PLAN)                       # always: the plan must match the stored bake 11
            if not owner_dis: ok = apply_plan()
        if ok:                                                  # stored D4 = bake 11 and S1 = bake-11 plan: consistent pair
            rc, out = sh(['bash', str(SRC.parent / 's0-nightly' / 'deploy.sh'), WORDS, REF], 300); log(f'deploy rc {rc}: {out.strip().splitlines()[-1][:200] if out.strip() else ""}')
            if rc != 0 and not plan_is_bake11():
                ok = False; note.append('deploy.sh failed and s0-nightly does not hold the bake-11 words'); ensure_stock()
            elif rc != 0: note.append('deploy.sh failed (s0-nightly already held the bake-11 words)')
        if ok and not owner_dis: RTDIS.unlink(missing_ok=True)
    except BaseException as e: ok = False; reason = f'{e!r}'[:150]; log(f'restore stopped: {e!r}'[:300])
    finally:
        quiet_signals()
        if sh(['systemctl', '--user', 'is-active', 's0-nightly'], 30)[0] != 0: units('start', 's0-nightly')   # first
        if not ok:
            hold_file('bake-11 restore did not finish', 'restore')
            try: ensure_stock()
            except BaseException as e: log(f'ensure_stock failed {e!r}')
        start_units(); clear_orphan_pause('after restore')
        try: prune_tags(4); prune('probe-', CAP, 10); prune('l2-', CAP, 10)
        except Exception as e: log(f'prune failed {e!r}')
    if not ok and not STARTED: return 4, f'not started: {reason or "stopped before the first bake"}'
    if not ok and dark:
        msg = ('the TV stayed DARK after the bake (TCON unpowered) even after one reboot: please power-cycle the TV at the wall '
               '(10 s). The guard then lifts the hold if bake 11 checks ok; its automatic restore stays OFF until guard.py --reset'
               ); notify(msg); return 7, msg
    if not ok and l2_kept:
        msg = (f'L2 test bake stored ({reason}); power-on trims held off. Bake 11 comes back by the guard at the next quiet '
               'moment or by a plain restore'); notify(msg); return 6, msg
    if not ok and deferred:
        msg = f'first bake not accepted; the retry is deferred ({reason[:80]})'; notify(msg); return 5, msg
    msg = ('bake 11 restored and verified' + ('; ' + '; '.join(note) if note else '')) if ok else \
        'bake 11 restore FAILED: night service on, power-on trims held off; see <work>/bake11/restore.log' + ('; ' + '; '.join(note) if note else '')
    notify(msg); return (0 if ok else 1), msg
def hold(why, by):
    if RTDIS.exists() and not h_ours(): return 4, "the owner's rt.disable is present: left as it is"
    if by == 'guard' and h_ours() and not h_auto(): return 4, 'a manual hold is present: left as it is'
    hold_file(why, by); ok = False
    try:
        if not tv_on(): return 0, 'held (TV off: rt.disable only)'
        rc, out = units('stop', 's95f-rt')
        if rc != 0: raise RuntimeError(f'could not stop s95f-rt: {out[-200:]}')
        ok = ensure_stock()
    except BaseException as e: log(f'hold error {e!r}'[:300])
    finally: quiet_signals(); start_units(); clear_orphan_pause('after hold')
    return (0, 'held: power-on trims off, S1/blue at stock') if ok else (1, 'hold: S1/blue could not be put back to stock')
def lift():
    ok = False
    try:
        c = compare(read_d4(f'd4-g{time.strftime("%Y%m%dT%H%M%S", time.gmtime())}')); prune('d4-g2', CAP, 6)
        log(f'lift: stored D4 {json.dumps(c)[:200]}')
        if c['verdict'] not in ('ok', 'drift'): return 4, f'not lifted: the stored bake is {c["verdict"]} ({c["max_dev"]} counts)'
        rc, out = units('stop', 's95f-rt')
        if rc != 0: raise RuntimeError(f'could not stop s95f-rt: {out[-200:]}')
        ok = apply_plan()
        if ok: RTDIS.unlink(missing_ok=True)
    except BaseException as e: log(f'lift error {e!r}'[:300])
    finally: quiet_signals(); start_units(); clear_orphan_pause('after lift')
    return (0, 'bake 11 confirmed: power-on trims re-enabled (plan applied)') if ok else (1, 'lift failed: hold kept (trims off)')
def preconditions(mode, auto, by_guard=False):
    o = busy()
    if o: return f'another tool is running: {o}'
    if PAUSE.exists(): return 'watcher paused by someone else'
    if mode == 'hold': return None
    if mode == 'lift' and not (h_auto() if by_guard else h_ours()): return 'no bake-11 hold to lift' + (' (automatic)' if by_guard else '')
    if (mode == 'lift' or auto) and not plan_is_bake11(): return 'the approved plans are not in force (fallback?)'
    if mode == 'restore':
        if S0LATCH.exists() or S0DIS.exists(): return 's0-nightly is LATCHED/DISABLED (check why first; then --reset it)'
        g = guard_can_restore() if L2 else None
        if g: return g
        if not PLAN11.exists() or not (CAP / REF / 'dump.bin').exists(): return 'approved plan or reference D4 missing'
    if not tv_on(): return 'TV is not on'
    if auto and not quiet(): return 'not quiet (someone may be watching)'
    if mode == 'restore':
        if not in_bake_window(): return f'outside the on-demand bake window {C.window_text()} (now {tv_local():%H:%M}; CONSULT-20A)'
        try: b = boot_healthy()
        except Exception as e: b = f'boot check failed {e!r}'[:120]
        if b: return f'present TV boot looks marginal ({b}); no bake (CONSULT-20A)'
    return None
def finish(mode, rc, msg):
    log(f'{mode} rc {rc}: {msg}')
    j = HERE / f'last_{mode}.json'; t = j.with_suffix('.tmp')
    t.write_text(json.dumps({'t': time.time(), 'rc': rc, 'msg': msg})); os.replace(t, j); return rc
def main(a):
    global PROBE, L2, L2POKES
    for s in (signal.SIGTERM, signal.SIGHUP): signal.signal(s, _term)
    PROBE = '--probe' in a
    if PROBE and ('--auto' in a or '--hold' in a or '--lift' in a): print('--probe is for a restore by hand only'); return 4
    if '--l2' in a:
        print('--l2 refused: the L2 research mode is not part of this kit (unreliable controller writes, CONSULT-19)'); return 4
    if PROBE:
        print('--probe refused: the raw-plane timing probe is not part of this kit'); return 4
    if '--l2' in a:
        L2 = a[a.index('--l2') + 1] if len(a) > a.index('--l2') + 1 else ''
        if PROBE or any(x in a for x in ('--auto', '--hold', '--lift', '--check')): print('--l2 is for a restore by hand only'); return 4
        sys.path.insert(0, str(TOP / 'l2')); from l2spec import spec_ok, pokes_ok
        if not spec_ok(L2): print(f'--l2 SPEC outside bounds: {L2!r} (see l2/l2spec.py)'); return 4
        if '--pokes' in a:
            L2POKES = a[a.index('--pokes') + 1] if len(a) > a.index('--pokes') + 1 else ''
            if not pokes_ok(L2POKES): print(f'--pokes outside bounds: {L2POKES!r} (see l2/l2spec.py pokes_ok)'); return 4
    elif '--pokes' in a: print('--pokes only with --l2'); return 4
    if '--check' in a: return check()
    mode = 'hold' if '--hold' in a else 'lift' if '--lift' in a else 'restore'; auto = '--auto' in a
    why = a[a.index('--hold') + 1] if mode == 'hold' and len(a) > a.index('--hold') + 1 else 'stored D4 is not bake 11'
    try:
        with lock() as got:
            if not got: return finish(mode, 4, 'another restore / hold / lift is running')
            pre = preconditions(mode, auto, '--by-guard' in a)
            if pre: return finish(mode, 4, pre) if '--dry' not in a else (print('preconditions:', pre) or 4)
            if '--dry' in a: print('dry run: preconditions ok (stop services, hold, bake_now bake-11 words, check, apply, deploy)'); return 0
            rc, msg = hold(why, 'guard' if '--by-guard' in a else 'manual') if mode == 'hold' else lift() if mode == 'lift' else restore(auto)
            return finish(mode, rc, msg)
    except BaseException as e: return finish(mode, 1 if STARTED else 4, f'stopped: {e!r}'[:200])
if __name__ == '__main__': sys.exit(main(sys.argv[1:]))
