#!/usr/bin/env python3
"""S95F power-on runtime service (Claude; tcon/RT-SPEC.md §4, design note CONSULT-14 §5-§6).
The runtime S1 gains on lanes 627-630 and the blue weight are RAM-only and clear at each controller boot. Every 15 s:
read the power state + controller boot identity (TV boot_id + USB devnum); once the TV is on, the watcher is MASKED >= 20 s
and no other TV tool runs, call `rt_tool.py apply` (at most 3 apply calls per controller boot, >= 2 min apart), then
read-only audits at +90 s, +10 min and every 30 min, acted on by the CONSULT-14 §6 table. Never calls the helper unless
deviced reports exactly "lcdon" and the TCON USB device is present. Kill switch: touch <work>/rtsvc/rt.disable.
Files (<work>/rtsvc/): rt_service.log, rt_status.json, rt.disable. Usage: rt_service.py --live | --status"""
import json, os, pathlib, re, signal, subprocess, sys, time, urllib.request

SRC = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SRC.parents[1])); import config as C; C.ensure_dirs()
HERE, TOP, W = C.RTSVC, C.TCON, C.WATCHER_DIR                  # state dir; tools dir (rt_tool.py); optional blackout watcher
sys.path.insert(0, str(TOP))
import rt_tool as RT

LOG, STATUS, DISABLE = HERE / 'rt_service.log', HERE / 'rt_status.json', HERE / 'rt.disable'
WSTATE, WLOG = W / 'watcher-v3-state.json', W / 'watcher-v3.log'
S0LOG, S0OWN, S0STATUS = C.S0SVC / 's0_nightly.log', C.S0SVC / 'owns_pause', C.S0SVC / 'status.json'
ALERT, ALERT_TOKEN = C.ALERT_URL, C.ALERT_TOKEN_FILE           # optional (config alert.url / alert.token_file); token read at runtime only
POLL_S, MASKED_S, HEARTBEAT_S = 15, 20, 180
S0_BUSY_MAX_S, NOAPPLY_NOTIFY_S = 45 * 60, 20 * 60      # s0 busy signals older than 45 min are ignored; notify if nothing applied
TOOL_TIMEOUT, TERM_WAIT_S = 540, 60                      # rt_tool bounds itself to 480 s; then SIGTERM, 60 s, SIGKILL
MAX_APPLY, APPLY_GAP_S, AUDIT_AFTER, AUDIT_EVERY = 3, 120, (90, 600), 1800
BLUE_RW_WINDOW, RETRY_S, MAX_TOOL_FAIL, REMASK_GRACE_S = 600, 60, 10, 600
# Tools that must not run concurrently (RT-SPEC §4). Matched on the basename of argv[0..3].
OTHER_EXACT = {'bake_now.py', 's0_nightly.py', 'e1.py', 'e2.py', 'e3.py', 'e4.py', 'brightset.py', 'after_now.sh',
               'postbake.py', 'tvdump.py', 'd4store.py', 'rt_tool.py'}
OTHER_PREFIX = ('arm_wake', 'tvtool')
S0_BUSY = ('armed on TV', 'standby;', 'supervise', 'cancel helper', 'helper finished', 'helper died', 'capture ')
# Helper refusals (RT-SPEC §4 table last row): restore if reachable, stop for this boot, notify.
FATAL = ('not Clean', 'limit40', 'record is not type 3 mode 8')
# Refusals before any write that can clear by themselves (fade still running, no flip yet, USB re-enumerated).
TRANSIENT = ('R/G weights not 205', 'weights changing', 'no bank flip', 'boot changed', 'ids', 'device', 'usb not active',
             'open', 'claim', 'interface driver', 'bulk ', 'TV not lcdon')
D = RT.D
PROBE = (D + '; test -e /sys/bus/usb/devices/7-1 && echo TCONUP; echo BOOT=$(cat /proc/sys/kernel/random/boot_id); '
         'echo DEV=$(cat /sys/bus/usb/devices/7-1/devnum 2>/dev/null); true')

def log(m):
    with LOG.open('a') as f: f.write(time.strftime('%FT%TZ ', time.gmtime()) + m + '\n')
    print(m, flush=True)
def jload(p, d):
    try: return json.loads(p.read_text())
    except Exception: return d
def jsave(p, d):
    t = p.with_suffix('.tmp'); t.write_text(json.dumps(d, indent=1)); os.replace(t, p)
def tail_lines(p, n=4096):
    try:
        with open(p, 'rb') as f:
            f.seek(0, 2); f.seek(max(0, f.tell() - n)); return f.read().decode(errors='replace').splitlines()
    except OSError: return []

def notify(msg):
    """Optional alert (config alert.url): POST one line, Bearer token from alert.token_file (read at runtime, never logged),
    no proxy; best effort."""
    if not ALERT: log('alert (no alert.url configured): ' + msg[:200]); return
    h = {'Title': 'TCON runtime service', 'Priority': 'high', 'Tags': 'tv,warning'}
    try:
        if ALERT_TOKEN.exists(): h['Authorization'] = 'Bearer ' + ALERT_TOKEN.read_text().strip()
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                urllib.request.Request(ALERT, data=('S95F rt: ' + msg)[:300].encode(), headers=h), timeout=10) as r: r.read()
    except Exception as e: log(f'notify failed: {type(e).__name__}')

# ---- TV probes (root channel = tvdump.py root(), as s0_nightly) --------------------------------------------------------
def probe():
    """-> (power state string, tcon_up, identity 'boot_id/devnum' or None). Same dbus call as s0_nightly.state(); one retry.
    Only 'lcdon' counts as TV on (deviced also reports start/lcdoff/standby/suspend/lowpower/poweroff)."""
    for k in range(2):
        o = RT.root(PROBE, 20); ps = RT.power_state(o)
        if ps:
            b = re.search(r'BOOT=([0-9a-fA-F-]{8,})', o); d = re.search(r'DEV=(\d+)', o); up = 'TCONUP' in o
            return ps, up, (f'{b.group(1)}/{d.group(1)}' if b and d and up else None)
        time.sleep(3)
    raise RuntimeError('no power state')

def masked_since(now):
    """Start time of the watcher's current MASKED phase, or None. State file (fresh heartbeat) first, else watcher log.
    No blackout watcher configured (config watcher.enabled false): always 'masked for an hour' (nothing to wait for)."""
    if not C.WATCHER_ENABLED: return now - 3600
    d = jload(WSTATE, None)
    if isinstance(d, dict):
        try:
            if now - float(d.get('heartbeat_t', 0)) <= HEARTBEAT_S:
                return float(d['phase_since']) if d.get('phase') == 'MASKED' else None
        except (TypeError, ValueError, KeyError): pass
    for line in reversed(tail_lines(WLOG, 16384)):
        m = re.match(r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d) \[[^\]]*\] phase \S+ -> (\S+)', line)
        if m:
            return time.mktime(time.strptime(m.group(1), '%Y-%m-%dT%H:%M:%S')) if m.group(2) == 'MASKED' else None
    return None

def in_unit(pid, unit, proc='/proc'):
    try: return unit in (pathlib.Path(proc) / str(pid) / 'cgroup').read_text()
    except OSError: return False

def fresh(p, now=None):
    """File modified within S0_BUSY_MAX_S (stale s0 signals, e.g. a crashed bake, must not block this service forever)."""
    try: return (now or time.time()) - p.stat().st_mtime < S0_BUSY_MAX_S
    except OSError: return False

def s0_busy():
    if S0OWN.exists() and fresh(S0OWN): return 's0-nightly holds the watcher pause'
    if jload(S0STATUS, {}).get('last_bake', {}).get('result') == 'in_progress' and fresh(S0STATUS): return 's0-nightly bake in progress'
    last = next((l for l in reversed(tail_lines(S0LOG)) if l.strip()), '')
    if any(p in last for p in S0_BUSY) and fresh(S0LOG): return 's0-nightly busy: ' + last[-100:]
    return None

def others_active(proc='/proc'):
    me = os.getpid()
    for cp in pathlib.Path(proc).glob('[0-9]*/cmdline'):
        pid = cp.parent.name
        if pid == str(me): continue
        try: argv = [os.path.basename(x.decode(errors='replace')) for x in cp.read_bytes().split(b'\0')[:4] if x]
        except OSError: continue
        for n in argv:
            if n in OTHER_EXACT or n.startswith(OTHER_PREFIX):
                if n == 's0_nightly.py' and in_unit(pid, 's0-nightly.service', proc): continue   # the unit itself is allowed
                return f'{n} (pid {pid})'
    return s0_busy()

def clear_orphan_pause(why):
    """A pause marker of rt_tool with no rt_tool running = orphan (e.g. SIGKILL): remove that pause. -> True if cleared."""
    try: r = RT.clear_own_pause()
    except Exception as e: log(f'orphan pause check failed: {type(e).__name__}: {e}'); return False
    if r is None: return False
    log(f'orphaned rt_tool watcher pause {"removed" if r else "marker dropped (pause not ours)"} ({why})'); return True

def run_tool(mode, popen=subprocess.Popen):
    """rt_tool.py MODE in a child process -> its JSON result (dict); {'tool_error': ...} if it gave none.
    On timeout: SIGTERM, TERM_WAIT_S, SIGKILL. After ANY exit an orphaned own pause is removed."""
    out, timed_out, rc = '', False, None
    try:
        p = popen([sys.executable, '-B', str(TOP / 'rt_tool.py'), mode], cwd=TOP, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try: out, errs = p.communicate(timeout=TOOL_TIMEOUT)
        except subprocess.TimeoutExpired:
            timed_out = True; log(f'rt_tool {mode} exceeded {TOOL_TIMEOUT} s: SIGTERM'); p.terminate()
            try: out, errs = p.communicate(timeout=TERM_WAIT_S)
            except subprocess.TimeoutExpired: log('rt_tool did not exit: SIGKILL'); p.kill(); out, errs = p.communicate()
        rc = p.returncode
    finally:
        clear_orphan_pause(f'after rt_tool {mode} exit')
    lines = [l for l in (out or '').splitlines() if l.startswith('{')]
    if lines and not timed_out: return json.loads(lines[-1])
    if timed_out: return {'tool_error': 'rt_tool timed out and was terminated', 'helper_launched': True}
    return {'tool_error': f'no JSON (exit {rc}): {(errs or "").strip()[-200:]}'}

# ---- the service -------------------------------------------------------------------------------------------------------
def kind(res):
    """Classify a helper result with rc != 0."""
    e = res.get('error', '') or ''; msg = e.partition(': ')[2] or e; writes = res.get('writes') or []
    if any('write transfer failed' in w for w in writes): return 'transfer'
    if any(k in e for k in FATAL): return 'fatal'
    if 'S1 not stock/plan' in e or 'CA block differs' in e: return 'other'
    if 'TV not lcdon' in e and not any('mismatch' in w or 'undo failed' in w for w in writes): return 'transient'   # review: clean undo -> retry
    if not writes and msg.startswith('blue pair'): return 'blue'
    if not writes and (msg.startswith(TRANSIENT) or e.startswith(('FileNotFoundException', 'DirectoryNotFoundException', 'IOException'))):
        return 'transient'
    return 'failed'

class Service:
    def __init__(self, probe=probe, tool=run_tool, masked=masked_since, others=others_active, notify=notify,
                 clock=time.time, blue=None, status=None, orphan=None):
        self.probe, self.tool, self.masked, self.others, self.notify, self.clock = probe, tool, masked, others, notify, clock
        self.orphan = orphan
        self.blue = blue if blue is not None else json.loads(RT.PLAN.read_text())['blue']
        self.status = status or STATUS
        self.st = jload(self.status, {}); self.st.setdefault('identity', None); self.seen_any = False; self._saved = None

    # helpers
    def save(self):
        s = json.dumps(self.st, sort_keys=True)
        if s != self._saved: jsave(self.status, self.st); self._saved = s
    def why(self, m):
        if self.st.get('why') != m: self.st['why'] = m; log(m)
    def stop(self, why):
        self.st['stopped'] = why; self.st['want'] = None; self.st['next_audit'] = None
        log('STOP for this controller boot: ' + why); self.notify('stopped for this power cycle: ' + why)
    def new_boot(self, ident, now):
        startup = not self.seen_any                             # first identity seen since service start: no re-mask wait
        log(f'controller boot {ident} (previous {self.st.get("identity")}): per-boot counters reset')
        self.st.update(identity=ident, first_seen=now, applies=[], last_attempt=0, tool_fail=0, want='apply', stopped=None,
                       s1_only=False, blue_rewrites=[], audit_plan=[], next_audit=None, applied_ok=None, late_notified=False,
                       masked_after=0 if startup else now - POLL_S - 5)
    def call(self, mode):
        log(f'rt_tool {mode}')
        try: res = self.tool(mode)
        except Exception as e: res = {'tool_error': f'{type(e).__name__}: {e}'}
        if not isinstance(res, dict): res = {'tool_error': f'bad result {res!r}'[:200]}
        short = {k: res.get(k) for k in ('rc', 'error', 'tool_error', 'already', 's1_state', 'blue_state', 'weights', 'writes', 'flip_ms') if k in res}
        self.st['last_result'] = dict(mode=mode, t=self.clock(), **short); log(f'rt_tool {mode} -> {json.dumps(short)[:600]}')
        if 'rc' not in res:
            self.st['tool_fail'] = self.st.get('tool_fail', 0) + 1
            if self.st['tool_fail'] >= MAX_TOOL_FAIL and not self.st.get('stopped'): self.stop(f'rt_tool failed {MAX_TOOL_FAIL} times this boot')
        return res
    def restore(self):
        r = self.call('restore'); ok = r.get('rc') == 0
        log('restore ' + ('ok' if ok else 'FAILED')); return ok
    def schedule_audits(self, t):
        self.st['audit_plan'] = [t + d for d in AUDIT_AFTER]; self.st['next_audit'] = self.st['audit_plan'][0]

    def tick(self):
        try:
            if clear_orphan_pause('tick') if self.orphan is None else self.orphan():
                self.notify('removed an orphaned watcher pause left by rt_tool')
            self._tick(); self.late_check()
        finally: self.save()
    def late_check(self):
        """Notify once per boot if the TV has been on with this controller boot for 20 min and nothing was applied."""
        st = self.st
        if DISABLE.exists() or st.get('tv') != 'on' or not st.get('identity') or st.get('applied_ok') or st.get('stopped'): return
        if self.clock() - st.get('first_seen', self.clock()) >= NOAPPLY_NOTIFY_S and not st.get('late_notified'):
            st['late_notified'] = True; log('nothing applied 20 min after controller boot: ' + str(st.get('why')))
            self.notify('nothing applied 20 min after power-on: ' + str(st.get('why'))[:160])

    def _tick(self):
        st = self.st; now = self.clock()
        if DISABLE.exists(): self.why('kill switch rt.disable present: idle'); return
        try: ps, up, ident = self.probe()
        except Exception as e: self.why(f'power probe error {type(e).__name__}: {str(e)[:120]}'); return
        st['tv'] = ('on' if up else 'on, TCON absent') if ps == 'lcdon' else str(ps)
        if ps != 'lcdon' or not up or not ident: self.why(f'TV {st["tv"]}: no helper calls'); return
        if ident != st.get('identity'): self.new_boot(ident, now)
        self.seen_any = True
        if st.get('stopped'): self.why('stopped for this boot: ' + st['stopped']); return
        ms = self.masked(now)
        if ms is None or now - ms < MASKED_S: self.why('waiting for watcher MASKED >= 20 s'); return
        if C.WATCHER_ENABLED and ms < st.get('masked_after', 0) and now - st.get('first_seen', now) < REMASK_GRACE_S:
            self.why('waiting for the watcher to re-mask after this controller boot'); return
        o = self.others()
        if o: self.why('other tool active: ' + o); return
        if st.get('want') == 'apply': self.why('ready: apply'); self.apply()
        elif st.get('next_audit') is not None and now >= st['next_audit']: self.why('ready: audit'); self.audit()
        else: self.why('idle (plan applied)' if st.get('applied_ok') else 'idle')

    def apply(self):
        st = self.st; now = self.clock()
        if len(st['applies']) >= MAX_APPLY: return self.stop(f'{MAX_APPLY} apply calls this boot without a confirmed plan state')
        if now - st['last_attempt'] < APPLY_GAP_S: self.why('apply: waiting 2 min since the last apply call'); return
        mode = 'apply-s1' if st.get('s1_only') else 'apply'; st['last_attempt'] = now
        res = self.call(mode); t = self.clock()
        if 'rc' not in res:
            if res.get('helper_launched'):                      # helper ran but its result is unknown: count it, audit now
                st['applies'].append(now); st['want'] = None; st['next_audit'] = t
            return
        st['applies'].append(now)
        if res['rc'] == 0:
            st['want'] = None; st['applied_ok'] = t; self.schedule_audits(t)
            log(f'{mode} ok' + (' (already in plan state, no writes)' if res.get('already') else '') + f'; audits at +90 s, +10 min'); return
        k = kind(res)
        if k == 'transfer': return self.stop(f'{mode}: USB write transfer failed ({res.get("error")}); no further traffic, no restore')
        if k == 'transient': log(f'{mode} refused before any write ({res.get("error")}); retry in >= 2 min'); return
        if k == 'blue': st['want'] = None; st['next_audit'] = t; log(f'{mode} refused ({res.get("error")}); audit decides'); return
        self.restore(); self.stop(f'{mode} {k}: {res.get("error")}')

    def audit(self):
        st = self.st
        res = self.call('audit'); t = self.clock()
        if 'rc' not in res: st['next_audit'] = t + RETRY_S; return
        if res['rc'] != 0:
            if kind(res) == 'fatal': self.restore(); return self.stop('audit refused: ' + str(res.get('error')))
            st['next_audit'] = t + RETRY_S; log(f'audit failed ({res.get("error")}); retry in 60 s'); return
        st['last_audit'] = dict(t=t, s1=res.get('s1'), s1_state=res.get('s1_state'), blue_state=res.get('blue_state'),
                                weights=res.get('weights'), rec=res.get('rec'), state=res.get('state'))
        plan = [x for x in st.get('audit_plan', []) if x > t]; st['audit_plan'] = plan
        st['next_audit'] = plan[0] if plan else t + AUDIT_EVERY
        self.table(res, t)

    def table(self, res, t):
        """CONSULT-14 §6 / RT-SPEC §4 audit -> action table."""
        st = self.st; s1, bl, w = res.get('s1_state'), res.get('blue_state'), res.get('weights') or []
        if self.blue == 205 and bl == 'stock': bl = 'plan'          # plan without a blue lift: stock == plan
        if len(w) != 6: self.restore(); return self.stop(f'audit: bad weights {w}')
        if any(w[i] != 205 for i in (0, 1, 3, 4)):
            if s1 == 'stock' and len(set(w)) == 1:                 # whole fade running: fresh boot, full apply (helper waits)
                log(f'audit: weights {w} (fade) with S1 stock -> full apply'); st['want'] = 'apply'; return
            self.restore(); return self.stop(f'audit: R/G weights not 205 {w} (s1 {s1})')
        key = (s1, bl)
        if 'other' in key or None in key: self.restore(); return self.stop(f'audit: s1 {s1}, blue {bl} (unknown writer) {res.get("s1")} {w}')
        if key == ('plan', 'plan'): log('audit ok: s1 plan, blue plan'); return
        if key == ('plan', 'stock'):
            if st.get('s1_only'): log('audit ok: s1 plan, blue stock (S1-only for this boot)'); return
            recent = [x for x in st.get('blue_rewrites', []) if t - x <= BLUE_RW_WINDOW]; st['blue_rewrites'] = recent + [t]
            if recent:
                st['s1_only'] = True; log('audit: blue weight back at 205 twice within 10 min -> apply-s1 only for the rest of this boot')
                return
            log('audit: s1 plan, blue stock (weight rewritten) -> apply once more'); st['want'] = 'apply'; return
        if key == ('stock', 'stock'):
            log('audit: s1 stock, blue stock (controller rebooted without identity change?) -> full apply'); st['want'] = 'apply'; return
        if key == ('stock', 'plan'):
            log('audit: s1 stock, blue plan (table reloaded) -> restore, then apply')
            if self.restore(): st['want'] = 'apply'
            else: self.stop('restore failed after s1 stock / blue plan')

def main(argv):
    if '--status' in argv: print(json.dumps(jload(STATUS, {}), indent=1), 'DISABLED' if DISABLE.exists() else ''); return 0
    if '--live' not in argv: print(__doc__); return 2
    stop = []
    for sg in (signal.SIGTERM, signal.SIGHUP): signal.signal(sg, lambda s, f: stop.append(s))   # finish a running call first
    try: RT.load_plan()
    except Exception as e: log(f'rt_plan.json / helper refused: {e}'); return 1
    svc = Service(); log('rt_service start')
    while not stop:
        try: svc.tick()
        except Exception as e: log(f'tick error {type(e).__name__}: {e}')
        for _ in range(POLL_S):
            if stop: break
            time.sleep(1)
    log(f'rt_service stop (signal {stop[0]})'); return 128 + stop[0]

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
