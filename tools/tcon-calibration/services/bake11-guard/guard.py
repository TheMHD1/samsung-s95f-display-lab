#!/usr/bin/env python3
"""guard.py = unit s95f-bake11-guard (Claude 2026-11-20, v2 after review 1): keeps the owner-approved BAKE 11 on the TV.
Active only while the approved plans are in force (s0svc/plan.json = bake-11 words, rtsvc/rt_plan.json = rt_plan-bake11);
otherwise idle with one notice (e.g. after the RUN-BAKE11 fallback F to bake 10). Every 60 s, and nothing at all while
bake11/guard.disable or bake11/maintenance exists, a job of its own runs, or another TV tool runs:
- Health (5 min): s0-nightly / s95f-rt down 30 min -> notify (hourly), 2 h -> start. s0-nightly LATCHED -> notify daily
  (s0-nightly sends no alert itself), DISABLE -> notify once.
- Holds: only automatic holds ("bake11 H guard/restore") are ever lifted by the guard; a manual hold or the owner's
  rt.disable counts as trims-off and is left alone.
- Check (`restore_bake11.py --check`, read-only ~1 min; TV "lcdon", watcher MASKED >= 3 min): once per new controller boot
  (>= 10 min after it was first seen) and every 12 h. ok / drift -> bake 11 is stored (pending cleared; drift notified when
  it starts). foreign -> restore pending + hold H at once (RULE: trims off while the stored bake is not bake 11).
  error -> retry after 30 min.
- Jobs (transient units s95f-bake11-<mode>-<t>, recorded in guard_state.json BEFORE launch; the result
  bake11/last_<mode>.json is read when the unit has ended, also after a guard restart):
  hold  (`--hold`): pending and no hold yet -> trims off.  lift (`--lift`): a bake-11 hold, nothing pending and an ok/drift
  check on this controller boot -> plan back on.  restore (`--auto`): pending, s0-nightly not LATCHED/DISABLED, <= 2 per
  24 h, not auto_off, and QUIET for >= 10 min in a row (TV shows the Ugoos, no TV menu/screensaver, Kodi black screensaver
  on, no player; TV input = the Ugoos with no TV menu, or the TV's own screensaver up); the restore checks quiet again before it
  stops anything and before each bake (TV off ~12 min). rc 5 (retry deferred) counts for the rate limit; 3 in a row -> auto_off.
  2 failed restores in a row -> auto_off (reset: guard.py --reset). A restore that did not start (rc 4) -> retry after
  30 min, notified once per lost-bake episode.
SIGTERM/SIGINT: a running check is finished first, then the guard exits (jobs are separate units and keep running).
usage: guard.py --live | --status | --reset"""
import json, os, pathlib, signal, subprocess, sys, time
SRC = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SRC)); sys.path.insert(0, str(SRC.parent / 's95f-rt')); sys.path.insert(0, str(SRC.parents[1] / 'tcon'))
import restore_bake11 as R
C = R.C; HERE = C.BAKE11; TOP = C.TCON                          # state dir (guard_state.json, last_<mode>.json); tools dir
STATE, LOG, DISABLE, MAINT = HERE / 'guard_state.json', HERE / 'guard.log', HERE / 'guard.disable', HERE / 'maintenance'
S0LATCH, S0DIS = R.S0LATCH, R.S0DIS
POLL_S, HEALTH_S, MASKED_MIN_S, BOOT_WAIT_S, CHECK_EVERY_S, RETRY_S, QUIET_S = 60, 300, 180, 600, 12 * 3600, 1800, 600
MAX_RESTORES_24H, MAX_FAILS = 2, 2
EXTRA = set(R.TOOLS)
STOP = False
def _stop(*_):
    global STOP; STOP = True
def log(m):
    with LOG.open('a') as f: f.write(time.strftime('%FT%TZ ', time.gmtime()) + m + '\n')
def jload(p, d):
    try: return json.loads(p.read_text())
    except Exception: return d
def jsave(p, d):
    t = p.with_suffix('.tmp'); t.write_text(json.dumps(d, indent=1)); os.replace(t, p)
def notify(msg):
    if not msg: return
    R.notify(msg, 'S95F bake 11 guard'); log('notify: ' + msg)
def unit_state(u):
    return subprocess.run(['systemctl', '--user', 'is-active', u], capture_output=True, text=True).stdout.strip()
def others():
    import rt_service as RS
    o = RS.others_active()
    if o: return o
    me = os.getpid()
    for cp in pathlib.Path('/proc').glob('[0-9]*/cmdline'):
        if cp.parent.name == str(me): continue
        try: argv = [os.path.basename(x.decode(errors='replace')) for x in cp.read_bytes().split(b'\0')[:4] if x]
        except OSError: continue
        if any(n in EXTRA for n in argv): return f'{argv} (pid {cp.parent.name})'
    return None
# ---- decisions (pure, tested) -------------------------------------------------------------------------------------------
def want_check(st, now, ident, masked_for):
    if masked_for is None or masked_for < MASKED_MIN_S or not ident: return False
    if now < st.get('retry_after', 0): return False
    seen = st.setdefault('boots', {}).setdefault(ident, now)
    if st.get('checked_boot') != ident and now - seen >= BOOT_WAIT_S: return True
    return now - st.get('last_check', 0) >= CHECK_EVERY_S
def on_verdict(st, now, ident, r):
    """-> list of messages to notify. Updates st."""
    v = r.get('verdict'); out = []
    if v not in ('ok', 'drift', 'foreign'): st['retry_after'] = now + RETRY_S; return out
    prev = st.get('last_verdict')
    st.update(last_check=now, checked_boot=ident, last_verdict=v, last_result=r)
    if v in ('ok', 'drift'):
        if st.get('pending'): out.append('the stored bake is bake 11 again: no restore needed')
        st['pending'] = False; st['n_rc4'] = False
        if v == 'drift' and prev != 'drift':
            out.append(f'stored bake is {r.get("max_dev")} counts from the approved bake 11 (still bake 11; no action)')
    elif not st.get('pending'):
        st.update(pending=True, pending_since=now, held=False)
        out.append(f'bake 11 is NOT on the TV any more (max {r.get("max_dev")} counts off). Power-on trims are switched off now; '
                   'it is restored automatically when the TV shows the Ugoos with its screen blank for 10 min (TV off ~12 min).')
    return out
def needs_hold(st, now, owner_dis):
    return bool(st.get('pending')) and not st.get('held') and not owner_dis and now >= st.get('hold_retry_after', 0)
def needs_lift(st, now, ident, ours):
    return ours and not st.get('pending') and st.get('last_verdict') in ('ok', 'drift') and st.get('checked_boot') == ident \
        and now >= st.get('lift_retry_after', 0)
def may_restore(st, now, s0_blocked):
    if not st.get('pending') or st.get('auto_off') or s0_blocked or now < st.get('restore_retry_after', 0): return False
    runs = [t for t in st.get('restores', []) if now - t < 86400]; st['restores'] = runs
    return len(runs) < MAX_RESTORES_24H
def quiet_long_enough(st, now, is_quiet):
    if not is_quiet: st.pop('quiet_since', None); return False
    return now - st.setdefault('quiet_since', now) >= QUIET_S
def after_restore(st, now, rc, msg=''):
    """-> message to notify (or None)."""
    if rc == 4:
        st['restore_retry_after'] = now + RETRY_S
        if st.get('n_rc4'): return None
        st['n_rc4'] = True; return f'restore did not start ({msg}); retrying at quiet moments every 30 min'
    st.setdefault('restores', []).append(now); st['held'] = False   # re-assert hold H unless the bake is back (idempotent)
    if rc == 7:                                                 # TV dark after the bake even after one reboot (restore_bake11)
        st['auto_off'] = True; return 'TV dark after a restore bake: automatic restore is OFF until the owner checks the TV (guard.py --reset)'
    if rc == 5:                                                 # first bake not accepted, retry deferred (not quiet)
        st['deferred'] = st.get('deferred', 0) + 1
        if st['deferred'] >= 3: st['auto_off'] = True; return 'restore deferred 3 times in a row: automatic restore is OFF (guard.py --reset)'
        return None
    st['deferred'] = 0
    if rc == 0:
        st.update(pending=False, fails=0, last_check=0, checked_boot=None, n_rc4=False); return None   # restore notifies itself
    st['fails'] = st.get('fails', 0) + 1
    if st['fails'] >= MAX_FAILS:
        st['auto_off'] = True; return f'restore failed {st["fails"]} times: automatic restore is OFF (see bake11/restore.log; guard.py --reset)'
    return None                                                 # the restore itself notified the failure
def on_job_end(st, now, mode, rc, msg):
    if mode == 'restore': return after_restore(st, now, rc, msg)
    if mode == 'hold':
        if rc == 0: st['held'] = True; st['n_hold'] = False; return None
        st['hold_retry_after'] = now + RETRY_S
        if st.get('n_hold'): return None
        st['n_hold'] = True; return f'could not switch the power-on trims off yet ({msg}); retrying every 30 min'
    if mode == 'lift':
        if rc == 0: return 'bake 11 confirmed on the TV: power-on trims are back on'
        if 'stored bake is foreign' in msg:                     # the lift's own read disagrees with the check: treat as foreign
            st.update(pending=True, pending_since=now, held=True, last_verdict='foreign'); st.pop('checked_boot', None)
            return 'bake 11 is NOT on the TV (found by the lift): trims stay off; it is restored at the next quiet moment'
        st['lift_retry_after'] = now + RETRY_S; return None
    return None
# ---- jobs ---------------------------------------------------------------------------------------------------------------
def job_running(st, now):
    """True while our job unit runs. When it has ended: read its result once and clear the job."""
    j = st.get('job')
    if not j: return False
    if unit_state(j['unit']) in ('active', 'activating', 'deactivating', 'reloading'): return True
    r = jload(HERE / f'last_{j["mode"]}.json', {})
    rc, msg = (int(r['rc']), r.get('msg', '')) if float(r.get('t', 0)) >= j['t0'] and 'rc' in r else (1, 'no result (job killed?)')
    st.pop('job'); log(f'job {j["mode"]} ended rc {rc}: {msg}'); notify(on_job_end(st, now, j['mode'], rc, msg)); return False
def launch(st, mode, *args, run=subprocess.run):
    t0 = time.time(); u = f's95f-bake11-{mode}-{int(t0)}'
    st['job'] = dict(unit=u, mode=mode, t0=t0); jsave(STATE, st)                 # recorded BEFORE the launch
    p = run(['systemd-run', '--user', '--unit', u, '--collect', '-p', 'KillMode=mixed', '-p', 'TimeoutStopSec=900',
             f'--working-directory={TOP}', f'--setenv=TCON_KIT_CONFIG={C.CONFIG_FILE}', f'--setenv=TCON_KIT_WORK={C.WORK}',
             sys.executable, '-B', str(SRC / 'restore_bake11.py'), *args], capture_output=True, text=True)
    log(f'job {mode} launched as {u} (rc {p.returncode})')
    if p.returncode != 0:
        st.pop('job', None); notify(on_job_end(st, t0, mode, 4, f'systemd-run failed: {p.stderr[-150:]}'))
def run_check():
    p = subprocess.Popen([sys.executable, '-B', str(SRC / 'restore_bake11.py'), '--check'], stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, start_new_session=True)
    try: out, err = p.communicate(timeout=900)
    except subprocess.TimeoutExpired: out, err = R.stop_group(p, 120)
    try: return json.loads(out.strip().splitlines()[-1])
    except Exception: return {'verdict': 'error', 'why': ((out or '') + (err or ''))[-200:]}
# ---- loop ---------------------------------------------------------------------------------------------------------------
def health(st, now):
    """Never fights a deliberate stop: a down unit is reported after 30 min and started after 2 h, never while a TV tool
    runs. (tick() does not get here while maintenance or a job of ours runs.)"""
    busy = bool(others())
    for u in ('s0-nightly', 's95f-rt'):
        k = f'down_{u}'
        if unit_state(u) == 'active': st.pop(k, None); continue
        since = st.setdefault(k, now)
        if busy: continue
        if now - since >= 1800 and now - st.get(f'n_{u}', 0) > 3600:
            st[f'n_{u}'] = now; notify(f'{u} has not been running for {int((now - since) / 60)} min')
        if now - since >= 7200:
            subprocess.run(['systemctl', '--user', 'start', u], capture_output=True); log(f'started {u} (down 2 h)'); st.pop(k, None)
    if S0LATCH.exists() and now - st.get('n_latch', 0) > 86400:
        st['n_latch'] = now; notify('night service is LATCHED (bake 11 is not protected at scans): ' + S0LATCH.read_text()[:150])
    if S0DIS.exists() != bool(st.get('n_s0dis')):
        st['n_s0dis'] = S0DIS.exists()
        if S0DIS.exists(): notify('night service is DISABLED (s0svc/DISABLE): bake 11 is not protected at scans')
def tick(st, probe=None, check=None, is_quiet=None, start=None):
    import rt_service as RS
    probe, check, is_quiet, start = probe or RS.probe, check or run_check, is_quiet or R.quiet, start or launch
    now = time.time()
    if job_running(st, now): return 'job'
    if MAINT.exists(): return 'maintenance'
    if now - st.get('last_health', 0) >= HEALTH_S: st['last_health'] = now; health(st, now)
    if not R.plan_is_bake11():
        if not st.get('n_idle'): st['n_idle'] = True; notify('guard idle: the approved bake-11 plans are not in force (fallback?)')
        return 'idle'
    st['n_idle'] = False
    ps, up, ident = probe()
    if ps != 'lcdon' or not up: st.pop('quiet_since', None); return 'tv off'
    if others(): st.pop('quiet_since', None); return 'busy'
    owner_dis = R.RTDIS.exists() and not R.h_auto()             # owner's kill switch or a manual hold: trims already off
    if needs_hold(st, now, owner_dis): start(st, 'hold', '--hold', 'stored D4 is not bake 11', '--by-guard'); return 'hold'
    ms = RS.masked_since(now); masked_for = None if ms is None else now - ms
    if want_check(st, now, ident, masked_for):
        r = check(); log(f'check: {json.dumps(r)[:300]}')
        for m in on_verdict(st, now, ident, r): notify(m)
        if needs_hold(st, now, owner_dis): start(st, 'hold', '--hold', 'stored D4 is not bake 11', '--by-guard'); return 'hold'
    if needs_lift(st, now, ident, R.h_auto()): start(st, 'lift', '--lift', '--by-guard'); return 'lift'
    if may_restore(st, now, S0LATCH.exists() or S0DIS.exists()):
        try: q = is_quiet()
        except Exception as e: st.pop('quiet_since', None); log(f'quiet check failed {type(e).__name__}'); return 'waiting quiet'
        if quiet_long_enough(st, now, q): st.pop('quiet_since', None); start(st, 'restore', '--auto'); return 'restore'
        return 'waiting quiet'
    return 'ok'
def main(a):
    st = jload(STATE, {})
    if '--status' in a: print(json.dumps(st, indent=1)); return 0
    if '--reset' in a: st.update(auto_off=False, fails=0, restores=[], deferred=0); jsave(STATE, st); print('auto_off cleared'); return 0
    if '--live' not in a: print(__doc__); return 2
    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP): signal.signal(s, _stop)
    log('guard start')
    while not STOP:
        st = jload(STATE, {})
        if not DISABLE.exists():
            try: tick(st)
            except Exception as e:
                import traceback; tb = ' < '.join(f'{pathlib.Path(f.filename).name}:{f.lineno} {f.name}' for f in reversed(traceback.extract_tb(e.__traceback__)[-3:]))
                log(f'tick error {type(e).__name__}: {str(e)[:200]} at {tb}')
            for b in list(st.get('boots', {}))[:-5]: st['boots'].pop(b, None)   # keep the last 5 identities
            jsave(STATE, st)
        for _ in range(POLL_S):
            if STOP: break
            time.sleep(1)
    log('guard stop'); return 0
if __name__ == '__main__': sys.exit(main(sys.argv[1:]))
