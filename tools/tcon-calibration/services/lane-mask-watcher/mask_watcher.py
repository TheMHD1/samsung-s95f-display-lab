#!/usr/bin/env python3
"""Lane-mask watcher: keeps the blackout fix (controller lane skip flags, lanes 540-661) in place across controller
restarts. Reference implementation from the S95F project: read it and adapt it before use (README.md in this folder).

Every 15 s (3 s while something is changing) it:
  * probes the TV (boot id, controller USB device number, current source) through the kit's TV shell (config tv.shell);
  * reads the controller's lane table with the lane-mask-read helper and classifies the controller (Clean and masked,
    Clean and unmasked, Quiescent, Faulted, first scan after power-on, unexpected);
  * Clean and unmasked: writes the 122 skip flags with lane-mask-write and requires an exact read-back;
  * first scan after power-on (AC1 phase, before the scan can fault): uses lane-mask-firstscan, which writes the same
    122 flags but ignores the six free-running scan-counter bytes when it compares two reads;
  * Faulted: optional recovery (config apps_cmd and mode2_cmd: put the TV on its own Apps home, then one stock
    controller power-cycle) under strict budgets (3 per hour, 6 per day, spacing 0 / 90 / 600 s). Without those
    commands it withholds recovery and alerts. An ambiguous first-scan write holds all controller access on that
    controller instance, even across a watcher restart.

Coordination: every controller access holds a TV-side lock (/tmp/s95f-watcher.lock, shared with the line-fix tools);
the line-fix tools pause it with <watcher_dir>/watcher.pause; watcher.busy is touched while it works. Phases are logged
once per change; alerts (config alert.url) back off 30 min -> 1 h -> 2 h per kind.
Config: JSON file $S95F_WATCHER_CONFIG (default <watcher_dir>/watcher.json); every key optional (see DEFAULTS).
Roles: 'primary' (default). The 'backup' role is not safe yet; leave it off.
"""
import datetime, http.server, ipaddress, json, os, pathlib, re, socket, subprocess, sys, threading, time, urllib.request
from contextlib import contextmanager

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import config as C                                     # kit config: tv.shell, watcher.dir, alert.url

WORK = C.WATCHER_DIR
DEFAULTS = dict(
    role='primary', owner=socket.gethostname(), peer_url=None, peer_stale_s=60,
    heartbeat_port=None, heartbeat_bind='127.0.0.1',
    lock_dir='/tmp/s95f-watcher.lock', ledger='/tmp/s95f-watcher.ledger', lock_stale_s=120,
    ntfy_url=C.ALERT_URL, ntfy_token_file=str(C.ALERT_TOKEN_FILE),
    apps_cmd=None, mode2_cmd=None,               # optional recovery commands (argv lists); None = recovery withheld + alert
    state=str(WORK / 'watcher-v3-state.json'), log=str(WORK / 'watcher-v3.log'), runs=str(WORK / 'watcher-runs'),
    pause=str(WORK / 'watcher.pause'), busy=str(WORK / 'watcher.busy'),
    budget_ack=str(WORK / 'watcher-v3.budget-ack'), v2_state=str(WORK / 'watcher-state.json'),
)
POLL_S, FAST_S, REVERIFY_S, FAST_WINDOW_S = 15, 3, 60, 180
MAX_MODE2_PER_HOUR, MAX_MODE2_PER_DAY = 3, 6
MODE2_GAPS = (0, 90, 600)          # seconds required since the previous MODE2, by how many ran in the last hour
QUIESCENT_FAST_S, QUIESCENT_ALERT_S, ABSENT_ALERT_S = 60, 300, 180
STARTUP_FAST_S, STARTUP_ALERT_S = 60, 300
STARTUP_UNCERTAIN_RELEASE_CAP = 2
MASK_FAILED_FAST_S, MASK_FAILED_ALERT_S = 60, 300
ACK_AUTOCLEAR_S = 86400
NOT_MASKED_ALERT_S = 300
FUTURE_SKEW_S = 60
ALERT_REPEAT_S, ALERT_MAX_REPEAT_S = 1800, 7200
BUSY_EVERY_S, POST_MODE2_BUSY_MAX_S = 2.0, 300
HOLD_PHASES = ('MODE2_SPACING', 'BUDGET_EXHAUSTED', 'RECOVERY_WITHHELD', 'FAULT_AFTER_RESET')   # stay put while Faulted
MASKED_LANES = 122
# Mode 1 settle before an Apps switch (review W-M1). Natural mode1 -> mode2 came 32-41 s after the controller appeared
# (08 §0.5, F4; two clean samples). The timer counts from the LATEST of: mask loss / episode start (0-15 s after a
# spontaneous reset), the last Apps attempt, MODE2 completion, and the first sighting of the post-MODE2 controller.
# After a MODE2 the new controller appears up to ~8 s after completion (3-12 s after the start, MODE2 takes 4-5 s), so
# counting from completion alone 55 s puts the switch >= 47 s after the controller appeared: 6 s above the slowest
# observed settle (45 s gave 33-42 s, inside the window). From the first sighting it is >= 55 s. 60 s would add only
# 5 s more margin for 5 s more unmasked time per stuck episode; 50 s would leave 1 s of margin on the completion path.
APPS_SETTLE_S = 55
APPS_MAX_PER_HOUR, APPS_MAX_PER_DAY = 4, 8
APPS_NOTE = 'panel protected again; TV was switched to Apps — switch back to your input when ready'
APPS_NOTE_PARTIAL = ('panel protected again; the watcher pressed Home on the TV (Apps not confirmed) — switch '
                     'back to your input when ready')
APPS_NOTE_TTL_S = 3600             # a pending owner note older than this (or from another TV boot) is dropped
APPS_KEYS = ('home', 'right', 'up')   # the only keys tv_apps_home.py may send


def lock_script(path, owner, stale):
    """POSIX sh run on the TV: prints LOCK=ACQUIRED or LOCK=BUSY <owner> <t>. Re-entrant for the same owner (refresh).
    Steal of a stale lock is serialised by a second mkdir (<path>.steal); inside it staleness is re-checked from scratch
    (owner time, or the dir mtime while the owner file is not yet written) and the new lock is taken before the guard
    is released, so a fresh lock is never removed (verified by a 4-way concurrent steal test)."""
    return (f'L={path}; O={owner}; S={int(stale)}; n=$(date +%s)\n'
            'take() { mkdir "$L" 2>/dev/null && echo "$O $n" > "$L/owner" && echo LOCK=ACQUIRED; }\n'
            'take && exit 0\n'
            'o=; t=; read o t < "$L/owner" 2>/dev/null\n'
            'if [ "$o" = "$O" ]; then echo "$O $n" > "$L/owner"; echo LOCK=ACQUIRED; exit 0; fi\n'
            'tt=${t:-$(stat -c %Y "$L" 2>/dev/null || echo 0)}\n'
            'if [ $((n - tt)) -gt $S ]; then\n'
            '  g=$(stat -c %Y "$L.steal" 2>/dev/null || echo $n); [ $((n - g)) -gt $S ] && rmdir "$L.steal" 2>/dev/null\n'
            '  if mkdir "$L.steal" 2>/dev/null; then\n'
            '    if [ -d "$L" ]; then\n'
            '      o2=; t2=; read o2 t2 < "$L/owner" 2>/dev/null\n'
            '      t2=${t2:-$(stat -c %Y "$L" 2>/dev/null || echo 0)}\n'
            '      [ "$o2" != "$O" ] && [ $((n - t2)) -gt $S ] && rm -rf "$L"\n'
            '    fi\n'
            '    take; r=$?; rmdir "$L.steal"; [ $r = 0 ] && exit 0\n'
            '  fi\n'
            'fi\n'
            'echo "LOCK=BUSY ${o:-?} ${t:-?}"\n')


def unlock_script(path, owner):
    return (f'L={path}; O={owner}; o=; read o t < "$L/owner" 2>/dev/null\n'
            '[ "$o" = "$O" ] && rm -rf "$L"; echo LOCK=RELEASED\n')


def ledger_add_script(path):
    return f'date +%s >> {path}; tail -n 50 {path} > {path}.n && mv {path}.n {path}; echo LEDGER=OK\n'


def ledger_read_script(path):
    return f'echo NOW=$(date +%s); cat {path} 2>/dev/null; true\n'


def gate_script(boot, dev=None):
    """Boot-agnostic copy of the reviewed public reject checks, plus: same boot id and (dev given) same controller
    devnum. The Apps-switch gate passes dev=None: the switch does not touch the controller (review W-L2)."""
    return ('set -eu\n'
            f'test "$(cat /proc/sys/kernel/random/boot_id)" = {boot}\n'
            + (f'test "$(cat /sys/bus/usb/devices/7-1/devnum)" = {dev}\n' if dev is not None else '') +
            'vconftool get memory/enterprise/swupgrade/working_status\n'
            'dbus-send --system --print-reply --reply-timeout=1500 --dest=org.tizen.system.deviced '
            '/Org/Tizen/System/DeviceD/Display org.tizen.system.deviced.display.GetPowerState\n'
            'dbus-send --system --print-reply --reply-timeout=1500 --dest=org.tizen.system.deviced '
            '/Org/Tizen/System/DeviceD/Display org.tizen.system.deviced.display.GetScreenState\n'
            'dbus-send --system --print-reply --reply-timeout=1000 --dest=org.tizen.system.deviced '
            '/Org/Tizen/System/DeviceD/Display org.tizen.system.deviced.display.BurnInProtectionInProgress\n')


def parse_probe(out):
    """-> (boot, dev, src) or None. Tagged fields, order-independent; src 'UNKNOWN' when buxton gave nothing usable."""
    f = dict(re.findall(r'^(BOOT|DEV|SRC)=(.*)$', out or '', re.M))
    if not f.get('BOOT', '').strip() or not f.get('DEV', '').strip():
        return None
    src = re.search(r'SOURCE_TYPE_[A-Z0-9_]+', f.get('SRC', ''))
    return f['BOOT'].strip(), f['DEV'].strip(), (src[0] if src else 'UNKNOWN')


def parse_gate(out):
    ints = re.findall(r'^\s+int32 ([0-9]+)\s*$', out, re.M)
    return 'value = 0 (Int32)' in out and 'string "lcdon"' in out and ints == ['1', '0']


def parse_apps(out):
    """Last JSON line of tv_apps_home.py stdout -> dict, or None. 'keys' is kept only as a list of known key names
    (anything else -> None = unknown, counted as keys sent)."""
    for line in reversed((out or '').strip().splitlines()):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if isinstance(d, dict):
            k = d.get('keys')
            d['keys'] = list(k) if isinstance(k, list) and all(x in APPS_KEYS for x in k) else None
            return d
    return None


def parse_ledger(out):
    now = re.search(r'^NOW=(\d+)\s*$', out or '', re.M)
    if not now:
        return None
    return int(now[1]), [int(x) for x in re.findall(r'^(\d+)\s*$', out, re.M)]


class ServerTV:
    """The TV shell (config tv.shell) and the lane-mask helpers built from tcon/helpers/lane-mask-*."""
    RUN = pathlib.Path(__file__).resolve().parent / 'run_on_tv.py'
    KA = C.HELPERS / 'lane-mask-read' / 'bin'
    KB = C.HELPERS / 'lane-mask-write' / 'bin'
    KB_STARTUP = C.HELPERS / 'lane-mask-firstscan' / 'bin'   # first-scan writer: scan counters excluded from the stability check
    APPS_TIMEOUT_S = 90              # under the TV lock (refreshed before and after); < lock_stale_s
    APPS_CHECK_TIMEOUT_S = 40        # --check: one snapshot, 0 keys
    MODE2_TIMEOUT_S = 110            # < lock_stale_s after the refresh

    def __init__(self, cfg, log):
        self.cfg, self.log, self.last_error, self._n = cfg, log, '', 0
        self.runs = pathlib.Path(cfg['runs'])

    def _dir(self, kind):
        self._n += 1
        return self.runs / f'{time.strftime("%Y%m%dT%H%M%S")}-{self._n:04d}-{kind}'

    def busy(self):
        try:
            pathlib.Path(self.cfg['busy']).touch()     # line-fix keeper yields the access lock while this is fresh
        except Exception:
            pass

    def root(self, cmd, timeout=20):
        """-> stdout of the remote command, or None (remote rc != 0 or transport failure; reason in last_error)."""
        self.busy()
        try:
            return C.tv_root(cmd, timeout)
        except subprocess.TimeoutExpired:
            self.last_error = 'TV shell timeout'; return None
        except RuntimeError as e:
            self.last_error = str(e)[-200:]; return None

    def probe(self):
        out = self.root('echo BOOT=$(cat /proc/sys/kernel/random/boot_id); '
                        'echo DEV=$(cat /sys/bus/usb/devices/7-1/devnum 2>/dev/null || echo NONE); '
                        'echo SRC=$(buxton2ctl get memory memory/eden/source/current_source 2>/dev/null | tail -1)', 15)
        if not out:
            return None
        r = parse_probe(out)
        if r is None:
            self.last_error = 'probe output malformed'
        return r

    def _helper(self, kind, prefix, bindir, dll, args):
        out = self._dir(kind)
        self.busy()
        env = dict(os.environ, STAGE_PREFIX=prefix, PERSIST='1')
        p = subprocess.run([sys.executable, '-B', str(self.RUN), str(bindir), dll, str(out), '--'] + args,
                           capture_output=True, text=True, timeout=300, env=env)
        try:
            return json.loads((out / 'native.receipt.json').read_text())
        except Exception:
            self.last_error = (p.stdout + p.stderr)[-300:]
            return None

    def read(self):
        for i in range(10):
            r = self._helper('read', '/tmp/tcon-lanemask-ka-', self.KA, 'LaneMaskRead.dll',
                             ['--execute-read', '--device', '{DEVNUM}', '--expected-boot', '{BOOT}'])
            if r is not None or i == 9 or 'BlockingIOError' not in self.last_error:
                return r
            time.sleep(0.4)

    def mask(self):
        return self._helper('mask', '/tmp/tcon-lanemask-kb-', self.KB, 'LaneMaskWrite.dll',
                            ['--execute-mask', '--device', '{DEVNUM}', '--expected-boot', '{BOOT}'])

    def mask_startup(self, inst):
        return self._helper('startup-mask', '/tmp/tcon-lanemask-kb-', self.KB_STARTUP, 'LaneMaskWrite.dll',
                            ['--execute-startup-mask', '--device', inst[1], '--expected-boot', inst[0]])

    def gate(self, boot, dev=None):
        if not re.fullmatch(r'[0-9a-fA-F-]{8,64}', boot or '') or (dev is not None and
                                                                  not re.fullmatch(r'[0-9]{1,4}', dev or '')):
            return False, f'gate refused: unexpected boot/devnum {boot!r} {dev!r}'
        out = self.root(gate_script(boot, dev), 25)
        if not out:
            return False, 'gate command failed (boot id or devnum changed, or a check failed): ' + self.last_error
        return parse_gate(out), out.strip().replace('\n', ' | ')[-300:]

    def mode2(self):
        out = self._dir('mode2'); out.mkdir(parents=True, exist_ok=True)
        try:
            if not self.cfg.get('mode2_cmd'):
                return False, 'mode2 recovery not configured (config mode2_cmd)'
            p = subprocess.run(list(self.cfg['mode2_cmd']) + ['--output', str(out / 'mode2.json')],
                               capture_output=True, text=True, timeout=self.MODE2_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            (out / 'stderr.txt').write_text(f'watcher: MODE2 helper timed out after {self.MODE2_TIMEOUT_S}s\n')
            return False, f'helper timeout after {self.MODE2_TIMEOUT_S}s'
        (out / 'stdout.txt').write_text(p.stdout); (out / 'stderr.txt').write_text(p.stderr)
        return p.returncode == 0, p.stderr[-300:]

    def _apps(self, boot, check):
        what = 'apps check' if check else 'apps switch'
        self.busy()
        if not self.cfg.get('apps_cmd'):
            self.last_error = f'{what}: not configured (config apps_cmd)'
            return False, []                 # nothing sent
        argv = list(self.cfg['apps_cmd']) + ['--boot', boot, '--output',
                str(self._dir('apps-check' if check else 'apps'))] + (['--check'] if check else [])
        try:
            p = subprocess.run(argv, capture_output=True, text=True,
                               timeout=self.APPS_CHECK_TIMEOUT_S if check else self.APPS_TIMEOUT_S)
        except Exception as e:
            self.last_error = f'{what} {type(e).__name__}'
            return False, None
        res = parse_apps(p.stdout)
        ok = p.returncode == 0 and bool(res) and res.get('ok') is True
        if not ok:
            self.last_error = f'{what}: ' + (p.stderr.strip() or f'rc={p.returncode}')[-200:]
        return ok, (res['keys'] if res else None)

    def tv_apps(self, boot):
        """TV's own Apps home from any source (stock keys via the root channel only; the media player is never used).
        -> (ok, keys): ok only when the wrapper verified Apps with csfs focused; keys = list of keys it attempted, or
        None when unknown (timeout / crash / no JSON: the caller counts that as keys sent)."""
        return self._apps(boot, False)

    def tv_apps_check(self, boot):
        """0-key check -> (on Apps with csfs focused and no screensaver, detail)."""
        ok, _ = self._apps(boot, True)
        return ok, 'on Apps' if ok else self.last_error

    # TV-side coordination (same root channel)
    def lock(self, owner):
        out = self.root(lock_script(self.cfg['lock_dir'], owner, self.cfg['lock_stale_s']), 10) or ''
        return 'LOCK=ACQUIRED' in out, out.strip()[-80:] or self.last_error

    def unlock(self, owner):
        self.root(unlock_script(self.cfg['lock_dir'], owner), 10)

    def ledger(self):
        return parse_ledger(self.root(ledger_read_script(self.cfg['ledger']), 10))

    def ledger_add(self):
        return bool(self.root(ledger_add_script(self.cfg['ledger']), 10))


class Clock:
    monotonic = staticmethod(time.monotonic)
    sleep = staticmethod(time.sleep)
    time = staticmethod(time.time)          # last: this name shadows the time module inside the class body


class BusyKeeper:
    """Touches watcher.busy every BUSY_EVERY_S (real time) from a thread while any reason is held."""
    def __init__(self, touch, every=BUSY_EVERY_S):
        self.touch, self.every = touch, every
        self.reasons, self.lk, self.wake, self.thread = set(), threading.Lock(), threading.Event(), None

    def hold(self, reason):
        with self.lk:
            self.reasons.add(reason)
            self.touch()
            if self.thread is None:
                self.wake.clear()
                self.thread = threading.Thread(target=self._run, daemon=True, name='busy-touch')
                self.thread.start()

    def drop(self, reason):
        with self.lk:
            self.reasons.discard(reason)
            if not self.reasons:
                self.wake.set()

    def held(self, reason):
        return reason in self.reasons

    def _run(self):
        while True:
            self.wake.wait(self.every)
            with self.lk:
                if not self.reasons:
                    self.thread = None; return
                self.wake.clear()
            self.touch()


class Watcher:
    def __init__(self, cfg, tv, clock=Clock, push=None, peer=None):
        self.cfg, self.tv, self.clock = cfg, tv, clock
        self.owner = re.sub(r'[^A-Za-z0-9._-]', '_', cfg['owner'])[:40] or 'watcher'
        self.push_fn = push or self._ntfy
        self.peer_fn = peer or self._peer
        self.locked = False
        self.phase, self.phase_since, self.phase_detail = 'START', clock.time(), ''
        self.tick_mono = clock.monotonic()
        self.unmasked_since = None
        self.post_mode2_t = None
        self.episode_t = None                   # start of the current unmasked episode (same TV boot, reachable)
        self.apps_skip = ''                     # last logged reason an Apps switch was skipped (log once)
        self.apps_tried = set()                 # instances the stuck trigger already ran the wrapper on (any result)
        self.apps_last_try = 0                  # wall time of the last wrapper run (settle timer, incl. 0-key runs)
        self.last_logged = {}
        self.busyk = BusyKeeper(self.busy)
        self.seed_note = ''
        self.pending_alert = None
        self.s = self.load()
        if self.pending_alert:
            self.alert(*self.pending_alert)

    # -- persistence / logging -------------------------------------------------------------------------------------
    def load(self):
        """Absent state file -> seed from v2 (first run only). Unreadable/corrupt -> keep a .corrupt copy, start empty
        but latched (ack_required: no automatic MODE2 until the owner acks), ALERT once the watcher is up (N9)."""
        p = pathlib.Path(self.cfg['state'])
        if not p.exists():
            s = self._seed_from_v2()
        else:
            try:
                s = json.loads(p.read_text())
                if not isinstance(s, dict):
                    raise ValueError('state is not an object')
            except Exception as e:
                bad = p.with_name(p.name + '.corrupt')
                try:
                    bad.write_bytes(p.read_bytes())
                except OSError:
                    pass
                self.pending_alert = ('state-corrupt', f'state file {p} unreadable ({type(e).__name__}); copy kept as '
                                      f'{bad.name}; started empty with the MODE2 budget latched until the owner acks')
                s = dict(ack_required=self.clock.time())
        for k, v in (('instance', None), ('masked', False), ('recovered_instances', []), ('mode2_times', []),
                     ('last_verify', 0), ('instance_since', 0), ('masked_fault_times', []), ('alerts', {}),
                     ('alert_n', {}), ('ack_required', None), ('apps_times', []), ('apps_instances', []),
                     ('apps_note_pending', None), ('apps_note_ok', True), ('apps_note_boot', None),
                     ('mode2_done_t', 0), ('mode2_inst_pending', False), ('mode2_inst_t', 0),
                     ('startup_mask_uncertain', None), ('uncertain_releases', [None, 0])):
            s.setdefault(k, v)
        return s

    def _seed_from_v2(self):
        """First run (no v3 state): carry over v2's MODE2 times and recovered instances (REVIEW-v3 M1)."""
        p = self.cfg.get('v2_state')
        try:
            v2 = json.loads(pathlib.Path(p).read_text())
            times = [float(t) for t in v2.get('recovery_times', []) if isinstance(t, (int, float))]
            insts = [str(k) for k in v2.get('recovered_instances', []) if isinstance(k, str)][-20:]
        except Exception as e:
            self.seed_note = f'no v2 state seeded ({type(e).__name__} reading {p})'
            return {}
        self.seed_note = f'seeded from v2 state {p}: {len(times)} MODE2 times, {len(insts)} recovered instances'
        return dict(mode2_times=times, recovered_instances=insts, seeded_from_v2=p)

    def save(self, durable=False):
        p = pathlib.Path(self.cfg['state'])
        tmp = p.with_suffix('.tmp')
        with tmp.open('w') as f:
            f.write(json.dumps(dict(self.s, phase=self.phase, phase_since=self.phase_since, heartbeat_t=self.clock.time(),
                                   role=self.cfg['role'], owner=self.owner), indent=1))
            if durable:
                f.flush()
                os.fsync(f.fileno())
        tmp.replace(p)
        if durable:
            fd = os.open(str(p.parent), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def log(self, msg):
        line = f'{datetime.datetime.fromtimestamp(self.clock.time()).isoformat(timespec="seconds")} [{self.owner}] {msg}'
        print(line, flush=True)
        try:
            with open(self.cfg['log'], 'a') as f:
                f.write(line + '\n')
        except Exception:
            pass

    def log_once(self, tag, msg):
        """Log msg unless it repeats the previous message for this tag (repeating 30 s retries stay quiet)."""
        if self.last_logged.get(tag) != msg:
            self.last_logged[tag] = msg; self.log(msg)

    def set_phase(self, phase, detail=''):
        if phase != self.phase:
            dur = self.clock.time() - self.phase_since
            self.log(f'phase {self.phase} -> {phase} after {dur:.0f}s{": " + detail if detail else ""}')
            self.phase, self.phase_since = phase, self.clock.time()
            if phase == 'MASKED':
                self.s['alert_n'] = {}            # episode over: next alert of any kind starts at the 30 min interval
                self.last_logged = {}
        self.phase_detail = detail

    def phase_age(self):
        return self.clock.time() - self.phase_since

    def push(self, title, msg, priority):
        try:
            self.push_fn(f'S95F watcher ({self.owner}): {title}', msg, priority)
        except Exception as e:
            self.log(f'ntfy push failed: {type(e).__name__}')

    def alert(self, kind, msg):
        """ALERT line + high-priority push. Repeats while the condition lasts back off 30 min -> 1 h -> 2 h (L5)."""
        now = self.clock.time()
        n = self.s['alert_n'].get(kind, 0)
        interval = min(ALERT_REPEAT_S * 2 ** max(0, n - 1), ALERT_MAX_REPEAT_S)
        if now - self.s['alerts'].get(kind, 0) >= interval:
            self.log(f'ALERT {msg}')
            self.s['alerts'][kind] = now; self.s['alert_n'][kind] = n + 1; self.save()
            self.push(kind, msg, 'high')

    def _ntfy(self, title, msg, priority='high'):
        h = {'Title': title, 'Priority': priority, 'Tags': 'tv,warning' if priority == 'high' else 'tv'}
        tf = self.cfg.get('ntfy_token_file')
        if tf and os.path.exists(tf):
            h['Authorization'] = 'Bearer ' + open(tf).read().strip()
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                urllib.request.Request(self.cfg['ntfy_url'], data=msg.encode(), headers=h), timeout=10) as r:
            r.read()
            return r.status

    def busy(self):
        try:
            pathlib.Path(self.cfg['busy']).touch()
        except Exception:
            pass

    @contextmanager
    def busy_during(self, reason):
        self.busyk.hold(reason)
        try:
            yield
        finally:
            self.busyk.drop(reason)

    # -- coordination --------------------------------------------------------------------------------------------
    def _peer(self):
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(self.cfg['peer_url'], timeout=3) as r:
                return json.load(r)
        except Exception:
            return None

    def peer_in_control(self):
        """Backup defers while the peer's heartbeat is fresh and the peer reaches the TV (or is paused by the owner)."""
        if self.cfg['role'] != 'backup' or not self.cfg.get('peer_url'):
            return False, ''
        hb = self.peer_fn()
        if not hb:
            return False, 'peer heartbeat unreachable'
        age = hb.get('tick_age_s')
        if not isinstance(age, (int, float)) or age > self.cfg['peer_stale_s']:
            return False, f'peer heartbeat stale (tick_age_s={age})'
        if hb.get('phase') in ('UNREACHABLE', 'START'):
            return False, f'peer cannot reach the TV ({hb.get("phase")})'
        return True, f'peer {hb.get("owner")} phase {hb.get("phase")}'

    def acquire(self):
        """TV lock for any KA/KB/recovery work. Re-entrant (refreshes the timestamp)."""
        ok, detail = self.tv.lock(self.owner)
        if ok:
            self.locked = True; self.busy()
        return ok, detail

    def release(self):
        if self.locked:
            try:
                self.tv.unlock(self.owner)
            finally:
                self.locked = False

    def heartbeat(self):
        return dict(v=3, owner=self.owner, role=self.cfg['role'], phase=self.phase, phase_detail=self.phase_detail,
                    phase_age_s=round(self.phase_age()), tick_age_s=round(self.clock.monotonic() - self.tick_mono, 1),
                    masked=self.s['masked'], instance=self.s['instance'], locked=self.locked)

    # -- budget --------------------------------------------------------------------------------------------------
    def _drop_future(self, now, times, where):
        ok = [t for t in times if t <= now + FUTURE_SKEW_S]
        if len(ok) != len(times):
            bad = max(times) - now
            self.alert('ledger-future', f'{len(times) - len(ok)} MODE2 {where} entr(y/ies) up to {bad:.0f}s in the '
                                        f'future (clock stepped back?); ignored for the budget')
        return ok

    def mode2_history(self):
        """-> [(now, [times within 24 h])] per available source: TV ledger (TV clock) and local copy (local clock)."""
        local_now = self.clock.time()
        local = [t for t in self._drop_future(local_now, self.s['mode2_times'], 'local') if local_now - t < 86400]
        out = [(local_now, local)]
        led = self.tv.ledger()
        if led is not None:
            tv_now, times = led
            out.append((tv_now, [t for t in self._drop_future(tv_now, times, 'TV ledger') if tv_now - t < 86400]))
        return out

    def budget_check(self):
        """-> (allowed, wait_s, reason). wait_s None = exhausted (owner ack needed). Each measure takes the more
        conservative of TV ledger and local copy (TV /tmp is wiped on TV reboot; the local copy then still counts)."""
        hist = self.mode2_history()
        hour_n = max(sum(1 for t in ts if now - t < 3600) for now, ts in hist)
        day_n = max(len(ts) for now, ts in hist)
        self.counts = (hour_n, day_n)
        if day_n >= MAX_MODE2_PER_DAY:
            return False, None, f'daily MODE2 cap ({MAX_MODE2_PER_DAY}/24 h) used'
        if hour_n >= MAX_MODE2_PER_HOUR:
            return False, None, f'reset budget ({MAX_MODE2_PER_HOUR}/hour) used'
        if self.s.get('ack_required'):
            ack = pathlib.Path(self.cfg['budget_ack'])
            if not ack.exists():
                return False, None, f'budget was exhausted; waiting for owner ack (touch {ack})'
            try:
                ack.unlink()
            except OSError:
                pass
            self.s['ack_required'] = None; self.save()
            self.log(f'owner ack found ({ack}): automatic MODE2 allowed again (hour/day caps still apply)')
        gap = MODE2_GAPS[min(hour_n, len(MODE2_GAPS) - 1)]
        recent = [now - max(ts) for now, ts in hist if any(now - t < 3600 for t in ts)]
        since = max(0.0, min(recent)) if recent else 1e9
        if since < gap:
            return False, gap - since, f'MODE2 #{hour_n + 1} this hour needs {gap}s after the previous ({since:.0f}s so far)'
        return True, 0, ''

    def budget_hold(self, src):
        """-> None when a MODE2 is allowed now, else the delay (and phase/ALERT set)."""
        ok, wait, why = self.budget_check()
        if ok:
            return None
        if wait is None:
            if not self.s.get('ack_required'):
                self.s['ack_required'] = self.clock.time()
                try:
                    pathlib.Path(self.cfg['budget_ack']).unlink()      # an ack must come after this exhaustion
                except OSError:
                    pass
                self.save()
            self.set_phase('BUDGET_EXHAUSTED', why)
            self.alert('budget', f'{why}; panel black, no automatic MODE2 until the owner acks '
                                 f'(touch {self.cfg["budget_ack"]}) (source {src})')
            return 120
        self.set_phase('MODE2_SPACING', why)
        return max(FAST_S, min(30, int(wait) + 1))

    # -- recovery ------------------------------------------------------------------------------------------------
    def recover(self, inst, src):
        with self.busy_during('recover'):
            return self._recover(inst, src)

    def _recover(self, inst, src):
        key = ':'.join(inst[:2])
        if key in self.s['recovered_instances']:
            self.set_phase('FAULT_AFTER_RESET', src)
            self.alert('fault-after-reset', f'panel black again on the same controller instance after a reset; '
                                            f'waiting for owner (source {src})')
            return 120
        hold = self.budget_hold(src)
        if hold is not None:
            return hold
        ok, detail = self.tv.gate(inst[0], inst[1])       # read-only gate BEFORE touching the TV UI (L2)
        if not ok:
            self.set_phase('RECOVERY_WITHHELD', f'public reject checks not passed ({detail})'); return 30
        if self.phase != 'RECOVERY_WITHHELD':            # a 30 s retry of a withheld recovery stays quiet in the log
            self.set_phase('RECOVERING', src)
        on_apps, how = self.switch_to_apps(inst, src, 'before MODE2', check_if_skipped=True)   # TV only, never the box
        if on_apps is None:
            self.set_phase('LOCK_BUSY', how); return FAST_S
        if not on_apps:
            return self.apps_withheld(src, how)
        self.clock.sleep(2)
        ok, detail = self.tv.gate(inst[0], inst[1])       # again after the precondition: same boot AND devnum (H1)
        if not ok:
            self.set_phase('RECOVERY_WITHHELD', f'after precondition: public/instance checks not passed ({detail})')
            return 30
        ok, info = self.tv.tv_apps_check(inst[0])         # 0 keys: still on Apps with csfs focused, right before MODE2
        if not ok:
            return self.apps_withheld(src, f'{how}; 0-key check before MODE2: {info}')
        ok, detail = self.acquire()                       # refresh the TV lock right before MODE2
        if not ok:
            self.set_phase('LOCK_BUSY', detail); return FAST_S
        hold = self.budget_hold(src)                      # another watcher may have spent budget meanwhile
        if hold is not None:
            return hold
        r = self.tv.read()                                # last look: still Faulted on this very instance?
        if not (r and r.get('readComplete') and r.get('observedState') == 'Faulted'
                and str(r.get('device', inst[1])) == inst[1] and r.get('expectedBootId', inst[0]) == inst[0]):
            got = 'no receipt' if not r else f'{r.get("observedState")} dev={r.get("device")} mcMode={r.get("mcMode")}'
            self.log(f'MODE2 withheld: final read is not Faulted on {key[:8]}..:{inst[1]} ({got})')
            self.set_phase('RECOVERY_WITHHELD', f'final read not Faulted ({got})')
            return 30
        hour_n, day_n = self.counts
        self.s['recovered_instances'] = (self.s['recovered_instances'] + [key])[-20:]
        now = self.clock.time()
        self.s['mode2_times'] = [t for t in self.s['mode2_times'] if -FUTURE_SKEW_S <= now - t < 86400] + [now]
        self.tv.ledger_add(); self.save()        # counted before the call: an uncertain MODE2 still uses budget
        self.log(f'recovering black panel: source {src}; {how}; Apps verified (0-key check); public checks ok; final '
                 f'read Faulted; running one stock MODE2 (#{hour_n + 1} this hour, #{day_n + 1} in 24 h)')
        done, err = self.tv.mode2()
        res = 'accepted' if done else f'uncertain (budget counted): {err!r}'
        self.log(f'MODE2 {res}')
        self.push('MODE2', f'MODE2 #{hour_n + 1} this hour / #{day_n + 1} in 24 h on source {src}: {res}; '
                           f'{how}; Apps verified before MODE2', 'default')
        end = self.clock.time()                           # W-M1: the settle timer counts from MODE2 completion ...
        self.s.update(instance_since=end, mode2_done_t=end, mode2_inst_pending=True)   # ... and the new instance
        self.save()
        self.post_mode2_t = self.clock.monotonic()
        self.busyk.hold('post-mode2')                    # keeper stays off until MASKED (max POST_MODE2_BUSY_MAX_S)
        return FAST_S

    # -- TV Apps precondition (server-side, TV only) ---------------------------------------------------------------
    def apps_allowed(self, inst):
        """-> (ok, reason). One counted switch per controller instance, APPS_MAX_PER_HOUR / APPS_MAX_PER_DAY rolling."""
        if ':'.join(inst[:2]) in self.s['apps_instances']:
            return False, 'already switched to Apps on this controller instance'
        now = self.clock.time()
        times = [t for t in self.s['apps_times'] if 0 <= now - t < 86400]
        if sum(1 for t in times if now - t < 3600) >= APPS_MAX_PER_HOUR:
            return False, f'Apps switch cap {APPS_MAX_PER_HOUR}/hour used'
        if len(times) >= APPS_MAX_PER_DAY:
            return False, f'Apps switch cap {APPS_MAX_PER_DAY}/24 h used'
        return True, ''

    def apps_withheld(self, src, why):
        """W-H2: the TV is not verified on Apps -> no MODE2; high-priority ALERT (back-off as every ALERT)."""
        self.log_once('apps-withheld', f'MODE2 withheld: TV not on Apps ({why[-240:]})')
        self.set_phase('RECOVERY_WITHHELD', f'TV not on Apps: {why[-200:]}')
        self.alert('apps-withheld', f'panel black; could not put the TV on Apps, so no MODE2 ({why[-200:]}). Put the TV '
                                    f'on its Apps home (Home -> Apps) or check it (source {src})')
        return 30

    def switch_to_apps(self, inst, src, why, check_if_skipped=False):
        """Bounded TV Apps switch -> (on_apps, short description); on_apps None = not run (TV lock busy).
        Caps, the per-instance list and the owner note count only when the wrapper sent keys (or cannot say:
        timeout/crash). Counted provisionally before the call (crash-safe) and un-counted when it reports 0 keys.
        A cap-skipped switch with check_if_skipped runs the 0-key check instead (the TV may already be on Apps)."""
        ok, reason = self.apps_allowed(inst)
        if not ok:
            if not check_if_skipped:
                return False, f'TV Apps switch skipped ({reason})'
            on, info = self.tv.tv_apps_check(inst[0])
            desc = f'TV Apps switch skipped ({reason}); 0-key check: ' + ('TV on Apps' if on else f'not on Apps ({info})')
            self.log_once('apps-skip', f'{desc} ({why}; source {src})')
            return on, desc
        ok, detail = self.acquire()                       # W-L5: fresh TV lock for the up-to-90 s wrapper run
        if not ok:
            return None, f'TV Apps switch not run: TV lock busy ({detail})'
        now = self.clock.time()
        key = ':'.join(inst[:2])
        prev_inst = list(self.s['apps_instances'])
        self.s['apps_instances'] = (prev_inst + [key])[-20:]
        self.s['apps_times'] = [t for t in self.s['apps_times'] if 0 <= now - t < 86400] + [now]
        self.save()                                       # provisional: a crash mid-call still counts
        self.apps_tried.add(key); self.apps_last_try = now
        with self.busy_during('apps'):
            done, keys = self.tv.tv_apps(inst[0])
            try:
                self.acquire()                            # W-L5: refresh again after the wrapper (lost lock shows later)
            except Exception:
                pass
        if keys == []:                                    # 0 keys (TV was already on Apps / stopped before any key)
            self.s['apps_instances'] = prev_inst
            if self.s['apps_times'][-1:] == [now]:
                self.s['apps_times'] = self.s['apps_times'][:-1]
        else:                                             # keys sent, or unknown: counted; one owner note once MASKED
            self.s.update(apps_note_pending=now, apps_note_ok=bool(done), apps_note_boot=inst[0])
        kdesc = 'unknown (counted)' if keys is None else (','.join(keys) or 'none')
        res = 'ok' if done else 'failed: ' + self.tv.last_error[-160:]
        self.log(f'TV Apps switch ({why}; source {src}): {res}; keys {kdesc}')
        self.save()
        return bool(done), f'TV Apps switch {"ok" if done else "failed"} (keys {kdesc})'

    def apps_if_stuck(self, inst, src, why):
        """HDMI source, Clean but not maskable (mcMode 1 / Quiescent / KB 'mode1 flags') APPS_SETTLE_S after the mask
        was lost, after the last Apps attempt and after the last MODE2 completed / its new controller was first seen
        -> gate (boot id + public checks; no devnum, W-L2) -> TV Apps, before any further mask attempt or MODE2 budget.
        One wrapper run per controller instance (a 0-key run too). -> True when a switch was attempted."""
        if 'HDMI' not in src:
            return False
        now = self.clock.time()
        since = max([self.episode_t or now, self.apps_last_try, self.s.get('mode2_done_t') or 0,
                     self.s.get('mode2_inst_t') or 0] + self.s['apps_times'][-1:] + self.s['mode2_times'][-1:])
        if now - since < APPS_SETTLE_S:
            return False
        ok, reason = self.apps_allowed(inst)
        if ok and ':'.join(inst[:2]) in self.apps_tried:
            ok, reason = False, 'already tried on this controller instance (0 keys: TV was on Apps)'
        if not ok:
            if reason != self.apps_skip:
                self.log(f'{why} on {src} for {now - since:.0f}s; TV Apps switch skipped ({reason})')
                self.apps_skip = reason
            return False
        ok, detail = self.tv.gate(inst[0])
        if not ok:
            if self.apps_skip != 'gate':
                self.log(f'{why} on {src}; TV Apps switch withheld: public checks not passed ({detail[-160:]})')
                self.apps_skip = 'gate'
            return False
        self.apps_skip = ''
        self.switch_to_apps(inst, src, f'{why} for {now - since:.0f}s')
        return True

    # -- main step -----------------------------------------------------------------------------------------------
    def mask_first_scan(self, inst):
        """AC=1 is the first IO scan, not a display mode. A separate finite native policy
        admits only AA0/AC1 Clean40 and stable R/M/C plus an entirely zero lane window.
        Persist intent before calling; an ambiguous vendor transaction forbids further
        controller requests until the hold is released. USB/boot probing remains possible.
        """
        self.s['startup_mask_uncertain'] = list(inst)
        self.save(durable=True)
        with self.busy_during('startup-mask'):
            m = self.tv.mask_startup(inst)
        complete = bool(m and m.get('protocolPhase') == 'ReadyForHeader'
                        and m.get('released') is True and m.get('closed') is True)
        ok = bool(complete and m.get('admissionPolicy') == 'first-scan-clean40-v1'
                  and m.get('contextStable') is True and m.get('afterAa') == 0 and m.get('afterAc') in (1, 2)
                  and m.get('readComplete') is True and m.get('writeVerified') is True
                  and m.get('afterState') == 'Clean' and m.get('afterLimit') == 40
                  and m.get('afterSkippedLanes') == list(range(540, 662)))
        refused_before_write = bool(complete and m.get('writeAttempted') is False)
        if ok or refused_before_write:
            self.s['startup_mask_uncertain'] = None
        self.s['masked'] = ok
        self.s['last_verify'] = self.clock.time()
        self.log(f'first-scan mask applied ok={ok} state={m and m.get("observedState")} '
                 f'AC={m and m.get("mcMode")} errors={m and m.get("errors")}')
        if ok:
            self.set_phase('MASKED', 'first-scan mask verified; limit 40')
            return POLL_S
        if refused_before_write:
            self.set_phase('STARTUP_ADMISSION', f'no write: {str(m.get("errors"))[-160:]}')
            return FAST_S
        self.set_phase('STARTUP_WRITE_UNCERTAIN', 'controller access held after ambiguous first-scan write; inspect receipt')
        return 30

    def step(self):
        try:
            return self._step()
        finally:
            try:
                self.release()                     # a failing unlock must not skip the bookkeeping below (N8)
            except Exception as e:
                self.log(f'lock release failed: {type(e).__name__}: {e}')
            self.tick_mono = self.clock.monotonic()
            try:
                self._after_step()
            finally:
                self.save()

    def _after_step(self):
        now = self.clock.time()
        if self.s['masked']:
            self.episode_t = None
        pend = self.s.get('apps_note_pending')
        nb = self.s.get('apps_note_boot')
        if pend and (not 0 <= now - pend <= APPS_NOTE_TTL_S or (nb and (self.s['instance'] or [nb])[0] != nb)):
            self.s['apps_note_pending'] = None      # W-L1: stale (> 1 h, or another TV boot): never sent hours later
            self.log(f'owner note dropped: pending since {now - pend:.0f}s'
                     f'{"" if (self.s["instance"] or [nb])[0] == nb else " and the TV rebooted"}')
        elif pend and self.s['masked'] and self.phase == 'MASKED':
            self.s['apps_note_pending'] = None      # cleared first: one note per switch episode, even if the push fails
            note = APPS_NOTE if self.s.get('apps_note_ok', True) else APPS_NOTE_PARTIAL
            self.log(f'owner note: {note}')
            self.push('Apps', note, 'default')
        if self.busyk.held('post-mode2') and (
                self.phase in ('MASKED', 'PAUSED', 'UNREACHABLE')
                or self.clock.monotonic() - (self.post_mode2_t or 0) > POST_MODE2_BUSY_MAX_S):
            self.busyk.drop('post-mode2')
        if self.s.get('ack_required') and self.s['masked'] and self.phase == 'MASKED' \
                and not any(0 <= now - t < ACK_AUTOCLEAR_S for t in self.s['mode2_times']) \
                and now - self.s['ack_required'] >= ACK_AUTOCLEAR_S:
            self.s['ack_required'] = None           # latched >= 24 h, no MODE2 in 24 h, panel masked: clears (N5)
            self.log('budget ack latch cleared automatically: masked and no MODE2 in the last 24 h')
        # generic catch-all: based on the mask itself, not on phase names (N2); only while the TV is reachable
        if self.s['masked'] or self.phase in ('UNREACHABLE', 'PAUSED', 'BACKUP_STANDBY', 'START'):
            self.unmasked_since = None
            return
        if self.unmasked_since is None:
            self.unmasked_since = now
        elif now - self.unmasked_since > NOT_MASKED_ALERT_S:
            others = [t for k, t in self.s['alerts'].items() if k != 'not-masked' and t >= self.unmasked_since]
            if not others or now - max(others) >= ALERT_MAX_REPEAT_S:  # a specific ALERT of THIS episode covers it (N3)
                self.alert('not-masked', f'panel not masked for {now - self.unmasked_since:.0f}s while the TV is '
                                         f'reachable (phase {self.phase}: {self.phase_detail[:160]})')

    def _step(self):
        if os.path.exists(self.cfg['pause']):
            self.set_phase('PAUSED'); return POLL_S
        p = self.tv.probe()
        if p is None:
            self.episode_t = None                     # standby / channel down: the next episode starts fresh
            self.set_phase('UNREACHABLE', self.tv.last_error); return POLL_S
        boot, dev, src = p
        now = self.clock.time()
        if dev == 'NONE':
            self.set_phase('CONTROLLER_ABSENT', f'TCON USB 7-1 missing, source {src}')
            if self.phase_age() >= ABSENT_ALERT_S:
                self.alert('controller-absent', f'TCON USB absent for {self.phase_age():.0f}s while the TV is reachable')
            return POLL_S
        inst = [boot, dev]
        if not self.s['instance'] or self.s['instance'][:2] != inst:
            self.log(f'new controller instance boot={boot[:8]} devnum={dev} source={src}')
            if (self.s['instance'] or [None])[0] != boot:
                self.episode_t = None                 # TV reboot: settle time counts from now (not on devnum churn)
            self.s.update(instance=inst, masked=False, instance_since=now)
            if self.s.get('mode2_inst_pending'):          # W-M1: first sighting of the post-MODE2 controller
                self.s.update(mode2_inst_pending=False, mode2_inst_t=now)
        if not self.s['masked'] and self.episode_t is None:
            self.episode_t = now
        defer, why = self.peer_in_control()
        if defer:
            self.set_phase('BACKUP_STANDBY', why); return POLL_S
        if self.cfg['role'] == 'backup' and self.cfg.get('peer_url') and self.phase in ('BACKUP_STANDBY', 'START'):
            self.set_phase('TAKEOVER', why)
        release_boot, releases = self.s['uncertain_releases']
        if release_boot != boot:
            releases = 0
            self.s['uncertain_releases'] = [boot, releases]
            self.s['alerts'].pop('startup_uncertain_cap', None)
            self.s['alert_n'].pop('startup_uncertain_cap', None)
        pending = self.s.get('startup_mask_uncertain')
        if pending is not None:
            # A devnum change marks controller re-enumeration after a TCON power reset and releases the hold,
            # at most twice per TV boot. The startup helper refuses unless Clean/AA0/AC1 and all 122 lane words are zero.
            valid_boot = (isinstance(pending, list) and len(pending) == 2
                          and isinstance(pending[0], str)
                          and re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', pending[0]))
            if (not valid_boot or not re.fullmatch(r'[0-9]{1,4}', str(pending[1]))
                    or not re.fullmatch(r'[0-9]{1,4}', str(dev))
                    or (pending[0] == boot and str(pending[1]) == str(dev))):
                self.set_phase('STARTUP_WRITE_UNCERTAIN', 'controller access held after ambiguous first-scan write; inspect receipt')
                return 30
            if pending[0] != boot:
                self.log('new TV boot after uncertain first-scan write; retaining old receipts')
            elif releases >= STARTUP_UNCERTAIN_RELEASE_CAP:
                detail = f'first-scan retry cap reached ({STARTUP_UNCERTAIN_RELEASE_CAP} releases this TV boot); inspect receipt'
                self.set_phase('STARTUP_WRITE_UNCERTAIN', detail)
                if 'startup_uncertain_cap' not in self.s['alerts']:
                    self.alert('startup_uncertain_cap', detail)
                return 30
            else:
                self.log(f'controller re-enumerated (devnum {pending[1]} -> {dev}) after uncertain first-scan write; retrying')
                self.s['uncertain_releases'] = [boot, releases + 1]
            self.s['startup_mask_uncertain'] = None
            self.save()
        fast = now - self.s.get('instance_since', 0) < FAST_WINDOW_S
        if self.s['masked'] and now - self.s['last_verify'] < REVERIFY_S:
            return POLL_S
        ok, detail = self.acquire()
        if not ok:
            self.set_phase('LOCK_BUSY', detail); return FAST_S if fast else POLL_S
        with self.busy_during('read'):
            r = self.tv.read()
        if r is None or not r.get('readComplete'):
            self.set_phase('READ_INCOMPLETE', str(None if r is None else r.get('errors'))[-200:])
            return FAST_S if fast else 30
        state, skipped, mc = r['observedState'], r['skippedCount'], r.get('mcMode')
        self.s['last_verify'] = now
        if state == 'Clean' and skipped == MASKED_LANES:
            self.set_phase('MASKED', f'limit {r.get("observedLimit")} T={r.get("sampledTemperature")}')
            self.s['masked'] = True; return POLL_S
        self.s['masked'] = False
        if state == 'Clean' and skipped == 0:
            if mc == 1:
                return self.mask_first_scan(inst)
            if mc is not None and mc != 2:
                self.set_phase('STARTUP', f'mcMode {mc}; mask waits for mode 2')
                if self.apps_if_stuck(inst, src, f'Clean in mcMode {mc}'):
                    return FAST_S
                if self.phase_age() >= STARTUP_ALERT_S:
                    self.alert('startup', f'controller stuck in startup (mcMode {mc}) for {self.phase_age():.0f}s; '
                                          f'mask cannot be applied')
                return FAST_S if (self.phase_age() < STARTUP_FAST_S or fast) else POLL_S   # fast: post-MODE2 window
            with self.busy_during('mask'):
                m = self.tv.mask()
            ok = bool(m and m.get('writeVerified') and len(m.get('afterSkippedLanes', [])) == MASKED_LANES)
            self.log(f'mask applied ok={ok} startupProfile={m and m.get("startupProfileWrite")} '
                     f'state={m and m.get("observedState")} mcMode={m and m.get("mcMode")} errors={m and m.get("errors")}')
            self.s['masked'] = ok; self.s['last_verify'] = self.clock.time()
            if ok:
                self.set_phase('MASKED', 'just applied')
                return POLL_S
            self.set_phase('MASK_FAILED', f'KB write not verified: {str(m and m.get("errors"))[-160:]}')
            if 'mode1' in str(m and m.get('errors')) and self.apps_if_stuck(inst, src, 'KB "mode1 flags"'):
                return FAST_S
            if self.phase_age() >= MASK_FAILED_ALERT_S:
                self.alert('mask-failed', f'mask write failing for {self.phase_age():.0f}s on a Clean mode-2 controller')
            return FAST_S if self.phase_age() < MASK_FAILED_FAST_S else POLL_S
        if state == 'Quiescent':
            self.set_phase('QUIESCENT', f'mcMode {mc}')
            # W-M3: Quiescent itself must be APPS_SETTLE_S old (owner powering off: Quiescent comes ~6 s before standby)
            if self.phase_age() >= APPS_SETTLE_S and self.apps_if_stuck(inst, src, 'Quiescent'):
                return FAST_S
            if self.phase_age() >= QUIESCENT_ALERT_S:
                self.alert('quiescent', f'controller Quiescent for {self.phase_age():.0f}s while the TV is reachable')
            return FAST_S if self.phase_age() < QUIESCENT_FAST_S else POLL_S
        if state == 'Faulted':
            if self.phase not in HOLD_PHASES:              # log once, not FAULTED <-> MODE2_SPACING every tick
                self.set_phase('FAULTED', f'skipped {skipped} source {src}')
            if skipped == MASKED_LANES:
                self.s['masked_fault_times'] = [t for t in self.s['masked_fault_times'] if now - t < 600] + [now]
                self.alert('faulted-masked', f'panel faulted WITH the mask present '
                                             f'({len(self.s["masked_fault_times"])} in 10 min)')
                if len(self.s['masked_fault_times']) >= 2:
                    return 300
            return self.recover(inst, src)
        self.set_phase('UNHANDLED', f'state={state} skipped={skipped} nonBit0={r.get("nonBit0Lanes")}')
        return 30


HB_LAN_KEYS = ('v', 'phase', 'tick_age_s')
HB_CLIENT_TIMEOUT_S = 10


def heartbeat_payload(w):
    """Full heartbeat on a loopback bind; on any other (LAN) bind only what a peer/the box needs (hb-lan H3): no
    phase_detail (TV-side stderr), instance, owner or lock state leaves the host."""
    hb = w.heartbeat()
    try:
        loopback = ipaddress.ip_address(w.cfg['heartbeat_bind']).is_loopback
    except (TypeError, ValueError):
        loopback = False
    return hb if loopback else {k: hb.get(k) for k in HB_LAN_KEYS}


def serve_heartbeat(w):
    class H(http.server.BaseHTTPRequestHandler):
        timeout = HB_CLIENT_TIMEOUT_S   # hb-lan H1: an idle/slow client never holds a handler thread for long

        def do_GET(self):
            body = json.dumps(heartbeat_payload(w)).encode() if self.path in ('/hb', '/') else b'{}'
            self.send_response(200 if self.path in ('/hb', '/') else 404)
            self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer((w.cfg['heartbeat_bind'], int(w.cfg['heartbeat_port'])), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def start_heartbeat(w, retry_s=60, sleep=time.sleep):
    """Serve the read-only heartbeat (GET /hb only; other methods 501) without ever stopping the fixer: a bind failure
    (LAN IP not up yet at boot, port taken) is logged once and retried every retry_s from a daemon thread. The media player
    box's watch-only backup (s95f-watch-backup) reads it; nothing the heartbeat serves can change the watcher."""
    def run():
        logged = False
        while True:
            try:
                srv = serve_heartbeat(w)
                w.log(f'heartbeat served on {w.cfg["heartbeat_bind"]}:{srv.server_address[1]} (GET /hb)')
                return
            except Exception as e:       # hb-lan H2: any bind error (OSError, bad value) is logged, never fatal
                if not logged:
                    w.log(f'heartbeat {w.cfg["heartbeat_bind"]}:{w.cfg["heartbeat_port"]} not served yet '
                          f'({type(e).__name__}: {e}); retrying every {retry_s}s')
                    logged = True
            sleep(retry_s)
    t = threading.Thread(target=run, daemon=True, name='heartbeat')
    t.start()
    return t


def load_cfg(path=None):
    """-> (cfg, error). Any problem with the file -> pure DEFAULTS (primary, no peer) and the error text (L3)."""
    p = pathlib.Path(path or os.environ.get('S95F_WATCHER_CONFIG', WORK / 'watcher.json'))
    if not p.exists():
        return dict(DEFAULTS), None
    try:
        user = json.loads(p.read_text())
        if not isinstance(user, dict):
            raise ValueError('config is not a JSON object')
        cfg = dict(DEFAULTS, **user)
        if cfg['role'] not in ('primary', 'backup'):
            raise ValueError(f'bad role {cfg["role"]!r}')
        for k in ('peer_stale_s', 'lock_stale_s'):
            if not isinstance(cfg[k], (int, float)) or isinstance(cfg[k], bool) or cfg[k] <= 0:
                raise ValueError(f'bad {k} {cfg[k]!r}')
        hp = cfg['heartbeat_port']
        if hp is not None and (not isinstance(hp, int) or isinstance(hp, bool) or not 1 <= hp <= 65535):
            raise ValueError(f'bad heartbeat_port {hp!r}')
        try:                                                    # hb-lan H2: a literal IPv4/IPv6 address string only
            if not isinstance(cfg['heartbeat_bind'], str):
                raise TypeError
            ipaddress.ip_address(cfg['heartbeat_bind'])
        except (TypeError, ValueError):
            raise ValueError(f'bad heartbeat_bind {cfg["heartbeat_bind"]!r} (must be an IP address)') from None
        return cfg, None
    except Exception as e:
        return dict(DEFAULTS), f'config {p} rejected ({type(e).__name__}: {e}); running with DEFAULTS (primary, no peer)'


def main(tv_factory=ServerTV):
    cfg, cfg_err = load_cfg()
    pathlib.Path(cfg['runs']).mkdir(parents=True, exist_ok=True)
    w = Watcher(cfg, None)
    w.tv = tv_factory(cfg, w.log)
    if cfg.get('heartbeat_port'):
        start_heartbeat(w)
    w.log(f'watcher v3 start role={cfg["role"]} peer={cfg.get("peer_url")} heartbeat_port={cfg.get("heartbeat_port")}')
    if w.seed_note:
        w.log(w.seed_note)
    if cfg_err:
        w.alert('config', cfg_err)
    while True:
        try:
            delay = w.step()
        except Exception as e:
            w.log(f'error {type(e).__name__}: {e}')
            delay = 30
        time.sleep(delay)


if __name__ == '__main__':
    main()
