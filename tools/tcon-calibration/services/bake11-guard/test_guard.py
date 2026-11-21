"""Offline tests (no TV) for bake11/guard.py v2 and bake11/restore_bake11.py v2. pytest -q bake11/test_guard.py"""
import json, os, sys, pathlib, subprocess, time
import pytest
HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE))
import guard as G, restore_bake11 as R
_IBW, _BH = R.in_bake_window, R.boot_healthy                       # originals (the sandbox fixture stubs them)
H = 3600
@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    """Every file the two modules write goes to tmp; notifications are collected, never sent."""
    for mod, names in ((G, ('STATE', 'LOG', 'DISABLE', 'MAINT')), (R, ('LOG', 'RTDIS', 'S0LATCH', 'S0DIS', 'PAUSE', 'S0OWN', 'L2MARK', 'GSTATE', 'GDIS', 'GMAINT'))):
        for n in names: monkeypatch.setattr(mod, n, tmp_path / f'{mod.__name__}-{n}')
    monkeypatch.setattr(G, 'HERE', tmp_path); monkeypatch.setattr(R, 'HERE', tmp_path)
    monkeypatch.setattr(R, 'DARK_DIR', tmp_path)                    # CONSULT-22: tests wrote dark-*.txt stubs into captures/
    monkeypatch.setattr(G, 'S0LATCH', R.S0LATCH); monkeypatch.setattr(G, 'S0DIS', R.S0DIS)
    monkeypatch.setattr(R, 'in_bake_window', lambda now=None: True); monkeypatch.setattr(R, 'boot_healthy', lambda root=None: None)
    # public kit: the default root channel is a TV that is on with its TCON present (dark_fix returns at once). The original
    # suite reached the live root channel here for dark_fix's read-only probe; no test may contact a TV.
    monkeypatch.setattr(R, '_root', lambda: (lambda c, t=30: '   string "lcdon"\nUSB=1\n'))
    sent = []; monkeypatch.setattr(R, 'notify', lambda m, t='': sent.append(m)); return sent
# ---- pure decisions -----------------------------------------------------------------------------------------------------
def test_no_check_until_masked_long_enough():
    st = {}
    assert not G.want_check(st, 1000, 'b/1', None) and not G.want_check(st, 1000, 'b/1', 100) and not G.want_check(st, 1000, None, 900)
def test_new_boot_waits_10_min_then_checks_once():
    st = {'last_check': 10 ** 9}; now = 10 ** 9 + 60
    assert not G.want_check(st, now, 'b/2', 900) and G.want_check(st, now + 600, 'b/2', 900)
    G.on_verdict(st, now + 600, 'b/2', {'verdict': 'ok'})
    assert not G.want_check(st, now + 700, 'b/2', 900) and G.want_check(st, now + 600 + 12 * H, 'b/2', 900)
def test_error_backs_off_30_min():
    st = {}; G.on_verdict(st, 5000, 'b/1', {'verdict': 'error'})
    assert not G.want_check(st, 5000 + 1700, 'b/1', 900) and 'last_check' not in st
def test_drift_notifies_when_it_starts_only():
    st = {}
    assert G.on_verdict(st, 1, 'b', {'verdict': 'drift', 'max_dev': 14})
    assert not G.on_verdict(st, 2, 'b', {'verdict': 'drift', 'max_dev': 15})          # new generation, still drift: quiet
    G.on_verdict(st, 3, 'b', {'verdict': 'ok'}); assert G.on_verdict(st, 4, 'b', {'verdict': 'drift', 'max_dev': 12})
def test_foreign_pending_hold_then_drift_clears():
    st = {}
    assert G.on_verdict(st, 1, 'b', {'verdict': 'foreign', 'max_dev': 300}) and st['pending'] and not st['held']
    assert G.needs_hold(st, 2, False) and not G.needs_hold(st, 2, True)                  # owner's rt.disable: never touched
    assert not G.on_verdict(st, 2, 'b', {'verdict': 'foreign', 'max_dev': 300})
    msgs = G.on_verdict(st, 3, 'b', {'verdict': 'drift', 'max_dev': 19}); assert not st['pending'] and msgs   # flip = bake 11
def test_lift_only_after_ok_on_this_boot():
    st = {'last_verdict': 'ok', 'checked_boot': 'b/1'}
    assert G.needs_lift(st, 1, 'b/1', True) and not G.needs_lift(st, 1, 'b/2', True) and not G.needs_lift(st, 1, 'b/1', False)
    st['pending'] = True; assert not G.needs_lift(st, 1, 'b/1', True)
def test_restore_gates():
    t = 10 ** 6
    assert G.may_restore({'pending': True}, t, False) and not G.may_restore({'pending': True}, t, True)    # LATCHED/DISABLED
    assert not G.may_restore({'pending': True, 'restore_retry_after': t + 1}, t, False)
    st = {'pending': True, 'restores': [t, t + 1]}; assert not G.may_restore(st, t + 100, False) and G.may_restore(st, t + 86402, False)
    assert not G.may_restore({}, t, False) and not G.may_restore({'pending': True, 'auto_off': True}, t, False)
def test_quiet_must_last_10_min():
    st = {}
    assert not G.quiet_long_enough(st, 0, True) and not G.quiet_long_enough(st, 599, True) and G.quiet_long_enough(st, 600, True)
    assert not G.quiet_long_enough(st, 601, False) and 'quiet_since' not in st
def test_after_restore_paths():
    st = {'pending': True, 'held': True}; t = 10 ** 6
    assert 'did not start' in G.after_restore(st, t, 4, 'not quiet') and st['restore_retry_after'] == t + 1800 and st['pending']
    assert G.after_restore(st, t + 1, 4, 'x') is None and not st.get('restores')                # rc 4: notified once, not counted
    assert G.after_restore(st, t + 2, 1) is None and st['fails'] == 1 and not st['held']        # failure: hold re-asserted
    assert 'OFF' in G.after_restore(st, t + 3, 1) and st['auto_off']
    st = {'pending': True}; G.after_restore(st, t, 0); assert not st['pending'] and st['fails'] == 0 and st['checked_boot'] is None
def test_hold_failure_notified_once():
    st = {}
    assert G.on_job_end(st, 1, 'hold', 4, 'busy') and not G.on_job_end(st, 2, 'hold', 4, 'busy') and st['hold_retry_after'] == 2 + 1800
    G.on_job_end(st, 3, 'hold', 0, ''); assert st['held'] and not st['n_hold']
# ---- tick order (mocked TV) ---------------------------------------------------------------------------------------------
class Fake:
    def __init__(s, verdict='ok', quiet=True): s.started = []; s.checks = 0; s.verdict = verdict; s.q = quiet
    def probe(s): return 'lcdon', True, 'b/1'
    def check(s): s.checks += 1; return {'verdict': s.verdict, 'max_dev': 300 if s.verdict == 'foreign' else 1}
    def quiet(s): return s.q
    def start(s, st, mode, *a): s.started.append(mode); st['job'] = {'unit': 'u', 'mode': mode, 't0': time.time()}
@pytest.fixture
def tv(monkeypatch):
    import rt_service as RS
    monkeypatch.setattr(G.R, 'plan_is_bake11', lambda: True); monkeypatch.setattr(G, 'others', lambda: None)
    monkeypatch.setattr(G, 'health', lambda st, now: None); monkeypatch.setattr(RS, 'masked_since', lambda now: now - 3600)
    monkeypatch.setattr(G, 'unit_state', lambda u: 'active')
def run(st, f): return G.tick(st, probe=f.probe, check=f.check, is_quiet=f.quiet, start=f.start)
def test_tick_foreign_holds_at_once_then_restores_when_quiet(tv, monkeypatch):
    f = Fake('foreign'); st = {'boots': {'b/1': 0}}
    assert run(st, f) == 'hold' and f.started == ['hold'] and st['pending']
    assert run(st, f) == 'job' and f.checks == 1                                   # job running: nothing else happens
    monkeypatch.setattr(G, 'unit_state', lambda u: 'inactive')
    (G.HERE / 'last_hold.json').write_text(json.dumps({'t': time.time() + 1, 'rc': 0, 'msg': 'held'}))
    assert run(st, f) == 'waiting quiet' and st['held'] and 'job' not in st       # quiet clock starts
    st['quiet_since'] -= 601; assert run(st, f) == 'restore' and f.started == ['hold', 'restore']
def test_tick_no_restore_while_latched_or_not_quiet(tv):
    st = {'pending': True, 'held': True, 'last_check': time.time(), 'checked_boot': 'b/1', 'quiet_since': 0}
    R.S0LATCH.write_text('x'); f = Fake('foreign'); assert run(st, f) == 'ok' and not f.started
    R.S0LATCH.unlink(); f = Fake('foreign', quiet=False); assert run(st, f) == 'waiting quiet' and 'quiet_since' not in st
def test_tick_lift_after_ok(tv):
    R.RTDIS.write_text('bake11 H manual x: y\n'); st = {'held': True, 'boots': {'b/1': 0}}; f = Fake('ok')
    assert run(st, f) == 'ok' and not f.started                                     # a manual hold is never lifted by the guard
    R.RTDIS.write_text('bake11 H guard x: y\n'); st = {'held': True, 'boots': {'b/1': 0}}; f = Fake('ok')
    assert run(st, f) == 'lift' and f.started == ['lift']
    R.RTDIS.write_text(''); st = {'boots': {'b/1': 0}}; f = Fake('ok')             # the owner's kill switch: never lifted
    assert run(st, f) == 'ok' and not f.started
def test_tick_idle_and_maintenance(tv, monkeypatch, sandbox):
    G.MAINT.write_text('x'); assert run({}, Fake()) == 'maintenance'; G.MAINT.unlink()
    monkeypatch.setattr(G.R, 'plan_is_bake11', lambda: False); st = {}
    assert run(st, Fake()) == 'idle' and run(st, Fake()) == 'idle' and sum('idle' in m for m in sandbox) == 1
def test_job_result_read_after_guard_restart(tv, monkeypatch):
    st = {'pending': True, 'job': {'unit': 'u', 'mode': 'restore', 't0': 100.0}}
    monkeypatch.setattr(G, 'unit_state', lambda u: 'inactive')
    (G.HERE / 'last_restore.json').write_text(json.dumps({'t': 50, 'rc': 0, 'msg': 'old result'}))       # older than the job
    assert not G.job_running(st, 200) and st['fails'] == 1 and st['pending']
def test_launch_records_job_before_systemd_run():
    st = {}; seen = {}
    def fake_run(cmd, **kw):
        seen['state'] = json.loads(G.STATE.read_text()); return subprocess.CompletedProcess(cmd, 0, '', '')
    G.launch(st, 'hold', '--hold', 'why', run=fake_run); assert seen['state']['job']['mode'] == 'hold' and st['job']
# ---- restore_bake11 paths (mocked) --------------------------------------------------------------------------------------
@pytest.fixture
def rmock(monkeypatch):
    calls = []
    monkeypatch.setattr(R, 'units', lambda *a: (calls.append(('units',) + a), (0, ''))[1])
    monkeypatch.setattr(R, 'start_units', lambda: calls.append(('start',)))
    monkeypatch.setattr(R, 'ensure_stock', lambda: (calls.append(('stock',)), True)[1])
    monkeypatch.setattr(R, 'apply_plan', lambda: (calls.append(('apply',)), True)[1])
    monkeypatch.setattr(R, 'clear_orphan_pause', lambda why: None); monkeypatch.setattr(R, 'prune', lambda *a: None)
    monkeypatch.setattr(R, 'sh', lambda cmd, t: (calls.append(('sh',) + tuple(cmd[:2])), (0, 'ok'))[1])
    monkeypatch.setattr(R.shutil, 'copyfile', lambda a, b: calls.append(('copy',)))
    monkeypatch.setattr(R, 'STARTED', False); return calls
def test_restore_ok_lifts_hold(rmock, monkeypatch):
    def bake(tag, auto, probe=False, l2=None): R.STARTED = True; return True, 'check rc 0, ok 1.0'
    monkeypatch.setattr(R, 'one_bake', bake)
    rc, msg = R.restore(True); assert rc == 0 and not R.RTDIS.exists() and ('apply',) in rmock and rmock[-1] == ('start',)
def test_restore_signal_mid_bake_keeps_hold_and_restarts_services(rmock, monkeypatch):
    def bake(tag, auto, probe=False, l2=None): R.STARTED = True; raise SystemExit(143)
    monkeypatch.setattr(R, 'one_bake', bake)
    rc, msg = R.restore(False); assert rc == 1 and R.h_ours() and ('apply',) not in rmock and rmock[-1] == ('start',)
    assert rmock.count(('stock',)) == 2                                            # before the bake and in the finally
def test_restore_not_quiet_before_first_bake_is_rc4(rmock, monkeypatch):
    monkeypatch.setattr(R, 'one_bake', lambda tag, auto, probe=False, l2=None: (False, 'not quiet any more'))
    rc, msg = R.restore(True); assert rc == 4 and 'not quiet' in msg and R.h_ours() and rmock[-1] == ('start',)
def test_restore_retries_once_then_fails(rmock, monkeypatch):
    tags = []
    def bake(tag, auto, probe=False, l2=None): R.STARTED = True; tags.append(tag); return False, 'stored D4 foreign (60 counts)'
    monkeypatch.setattr(R, 'one_bake', bake)
    rc, msg = R.restore(True); assert rc == 1 and len(tags) == 2 and R.h_ours()
def test_restore_deploy_failure_without_bake11_words_fails(rmock, monkeypatch):
    def bake(tag, auto, probe=False, l2=None): R.STARTED = True; return True, 'ok'
    monkeypatch.setattr(R, 'one_bake', bake); monkeypatch.setattr(R, 'sh', lambda cmd, t: (1, 'boom'))
    monkeypatch.setattr(R, 'plan_is_bake11', lambda: False)
    rc, msg = R.restore(False); assert rc == 1 and 'deploy' in msg and R.h_ours()
def test_restore_respects_owner_kill_switch(rmock, monkeypatch):
    R.RTDIS.write_text('')
    def bake(tag, auto, probe=False, l2=None): R.STARTED = True; return True, 'ok'
    monkeypatch.setattr(R, 'one_bake', bake)
    rc, msg = R.restore(False); assert rc == 0 and R.RTDIS.exists() and R.RTDIS.read_text() == '' and ('apply',) not in rmock
def test_hold_paths(rmock, monkeypatch):
    R.RTDIS.write_text(''); assert R.hold('x', 'guard')[0] == 4 and R.RTDIS.read_text() == ''
    R.RTDIS.unlink(); monkeypatch.setattr(R, 'tv_on', lambda: False)
    assert R.hold('gone', 'guard')[0] == 0 and R.h_auto() and ('stock',) not in rmock
    monkeypatch.setattr(R, 'tv_on', lambda: True); assert R.hold('gone', 'guard')[0] == 0 and ('stock',) in rmock
    assert R.hold('by hand', 'manual')[0] == 0 and R.h_ours() and not R.h_auto()         # manual hold replaces an automatic one
    assert R.hold('gone', 'guard')[0] == 4 and 'manual' in R.RTDIS.read_text()           # the guard never overwrites it
def test_restore_owner_switch_still_copies_plan(rmock, monkeypatch):
    R.RTDIS.write_text('bake11 H manual x')
    def bake(tag, auto, probe=False, l2=None): R.STARTED = True; return True, 'ok'
    monkeypatch.setattr(R, 'one_bake', bake)
    rc, msg = R.restore(False); assert rc == 0 and ('copy',) in rmock and ('apply',) not in rmock and 'manual' in R.RTDIS.read_text()
def test_restore_retry_deferred_is_rc5(rmock, monkeypatch):
    res = iter([(False, 'check_bake11 rc 4'), (False, 'not quiet any more')])
    def bake(tag, auto, probe=False, l2=None): R.STARTED = True; return next(res)
    monkeypatch.setattr(R, 'one_bake', bake)
    rc, msg = R.restore(True); assert rc == 5 and R.h_auto()
    st = {'pending': True}
    for k in range(2): assert G.after_restore(st, k, 5) is None
    assert 'OFF' in G.after_restore(st, 3, 5) and st['auto_off'] and st.get('fails', 0) == 0
def test_after_restore_rc4_keeps_held():
    st = {'pending': True, 'held': True}; G.after_restore(st, 1, 4, 'not quiet'); assert st['held']
def test_quiet_accepts_tv_screensaver(monkeypatch):
    import screencheck as SC, optical as O
    kodi = {'XBMC.GetInfoBooleans': '{"result":{"System.ScreenSaverActive":true}}', 'Player.GetActivePlayers': '{"result":[]}'}
    monkeypatch.setattr(O, 'rpc', lambda m, p=None: kodi[m])
    for good, info, want in ((True, {'src': 'SOURCE_TYPE_HDMI3', 'screensaver': '0'}, True),
                             (False, {'src': 'SOURCE_TYPE_HDMI3', 'screensaver': '1'}, True),     # TV screensaver up
                             (False, {'src': 'SOURCE_TYPE_HDMI3', 'screensaver': '0'}, False),    # TV menu open
                             (False, {'src': 'SOURCE_TYPE_TV', 'screensaver': '1'}, False)):
        monkeypatch.setattr(SC, 'ok', lambda g=good, i=info: (g, i)); assert R.quiet() is want
    kodi['Player.GetActivePlayers'] = '{"result":[{"playerid":1,"type":"video"}]}'           # paused film: not quiet
    monkeypatch.setattr(SC, 'ok', lambda: (True, {'src': 'SOURCE_TYPE_HDMI3', 'screensaver': '0'})); assert not R.quiet()
def test_plan_compare_ignores_note(tmp_path, monkeypatch):
    p11, p, s0 = tmp_path / 'p11.json', tmp_path / 'p.json', tmp_path / 's0.json'
    p11.write_text(json.dumps({'s1': {'627': ['a', 'b']}, 'blue': 820, 'note': 'x'}))
    p.write_text(json.dumps({'s1': {'627': ['a', 'b']}, 'blue': 820, 'note': 'edited'}))
    s0.write_text(json.dumps({'lanes': dict(x.split('=') for x in R.WORDS.split(','))}))
    monkeypatch.setattr(R, 'PLAN11', p11); monkeypatch.setattr(R, 'PLAN', p); monkeypatch.setattr(R, 'S0PLAN', s0)
    assert R.plan_is_bake11()
    p.write_text(json.dumps({'s1': {'627': ['a', 'c']}, 'blue': 820})); assert not R.plan_is_bake11()
def test_orphan_pause_only_inside_our_child_span(monkeypatch):
    monkeypatch.setattr(R, 'tools_running', lambda: []); monkeypatch.setattr(R, 'SPANS', [])
    R.PAUSE.write_text(''); R.clear_orphan_pause('t'); assert R.PAUSE.exists()          # no child ran: a hand pause stays
    R.run_group(['bash', '-c', f'touch {R.PAUSE}'], 10); R.clear_orphan_pause('t'); assert not R.PAUSE.exists()
    time.sleep(2.2); R.PAUSE.write_text(''); time.sleep(0.1)
    R.SPANS[:] = [[0, time.time() - 1]]; R.clear_orphan_pause('t'); assert R.PAUSE.exists()   # made after our child ended
def test_prune_by_tag(tmp_path, monkeypatch):
    cap = tmp_path / 'cap'; (cap / 'optical').mkdir(parents=True); monkeypatch.setattr(R, 'CAP', cap); monkeypatch.setattr(R, 'TOP', tmp_path); monkeypatch.setattr(R, 'LOGS', tmp_path)
    tags = [f'bake11r2026112{d}T0300' for d in range(6)] + ['bake11r20261125T0300b']
    for i, t in enumerate(tags):
        for d in (f'd4-pre-{t}', f'd4-{t}'): (cap / d).mkdir(); os.utime(cap / d, (i, i)) if d.startswith('d4-pre') else None
        for k in range(10): (cap / 'optical' / f'post-{t}-c{k}.npz').write_text('')
        (cap / 'optical' / f'post-{t}.jsonl').write_text(''); (tmp_path / f'after_{t}.log').write_text('')
    (cap / 'd4-bake11').mkdir()
    R.prune_tags(4)
    left = sorted(p.name[7:] for p in cap.glob('d4-pre-*')); assert left == sorted(tags[-4:])
    assert len(list((cap / 'optical').glob('post-bake11r20261125T0300-*'))) == 10 and (cap / 'd4-bake11').exists()
    assert not list((cap / 'optical').glob(f'post-{tags[0]}*')) and not (tmp_path / f'after_{tags[0]}.log').exists()
def test_preconditions(monkeypatch):
    monkeypatch.setattr(R, 'PLAN11', R.HERE / 'p11'); (R.HERE / 'p11').write_text('{}')          # public kit: no live plan /
    monkeypatch.setattr(R, 'CAP', R.HERE / 'cap'); (R.HERE / 'cap' / R.REF).mkdir(parents=True)  # reference D4 on disk
    (R.HERE / 'cap' / R.REF / 'dump.bin').write_text('x')
    monkeypatch.setattr(R, 'busy', lambda: None); monkeypatch.setattr(R, 'tv_on', lambda: True)
    monkeypatch.setattr(R, 'plan_is_bake11', lambda: True); monkeypatch.setattr(R, 'quiet', lambda: True)
    R.S0LATCH.write_text('x'); assert 'LATCHED' in R.preconditions('restore', True); R.S0LATCH.unlink()
    assert 'no bake-11 hold' in R.preconditions('lift', False)
    R.RTDIS.write_text('bake11 H manual x'); assert R.preconditions('lift', False) is None
    assert 'automatic' in R.preconditions('lift', False, by_guard=True); R.RTDIS.unlink()
    monkeypatch.setattr(R, 'plan_is_bake11', lambda: False); assert 'not in force' in R.preconditions('restore', True)
    assert R.preconditions('restore', False) is None                              # by hand: may switch back to bake 11
    R.PAUSE.write_text(''); assert 'paused' in R.preconditions('hold', False)
def test_main_busy_lock_writes_rc4(monkeypatch):
    import fcntl
    with open(R.HERE / 'restore.lock', 'w') as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        assert R.main(['--hold', 'x']) == 4
    assert json.loads((R.HERE / 'last_hold.json').read_text())['rc'] == 4
def test_run_group_timeout_kills_the_whole_group(tmp_path):
    pidf = tmp_path / 'pid'
    rc, out, err = R.run_group(['bash', '-c', f'sleep 60 & echo $! > {pidf}; sleep 60'], 1, 2)
    assert rc == 124
    pid = int(pidf.read_text()); time.sleep(0.2)
    try: os.kill(pid, 0); alive = open(f'/proc/{pid}/stat').read().split()[2] != 'Z'
    except ProcessLookupError: alive = False
    assert not alive
def test_compare_classifies_stored_captures():
    if not (R.CAP / 'd4-gen199' / 'dump.bin').exists(): return
    assert R.compare('d4-bake11')['verdict'] == 'ok' and R.compare('d4-bake10')['verdict'] == 'drift'
    assert R.compare('d4-gen199')['verdict'] == 'foreign' and R.compare('d4-bake2')['verdict'] == 'foreign'
def test_lift_finding_foreign_sets_pending():
    st = {'held': True}
    assert G.on_job_end(st, 1, 'lift', 4, 'not lifted: the stored bake is foreign (60.0 counts)') and st['pending'] and st['held']
    assert not G.needs_lift(st, 2, 'b/1', True) and G.may_restore(st, 2, False)
def test_probe_refused_outside_manual_restore():
    for extra in (['--auto'], ['--hold', 'x'], ['--lift']): assert R.main(['--probe'] + extra) == 4
def test_retry_bake_never_probes(rmock, monkeypatch):
    seen = []
    def bake(tag, auto, probe=False, l2=None): R.STARTED = True; seen.append(probe); return False, 'check_bake11 rc 4'
    monkeypatch.setattr(R, 'one_bake', bake); monkeypatch.setattr(R, 'PROBE', True)
    R.restore(False); assert seen == [True, False]
# ---- --l2 (CONSULT-17 6c L2 test bake) -----------------------------------------------------------------------------------
def test_l2_not_accepted_keeps_result_without_retry(rmock, monkeypatch):
    seen = []
    def bake(tag, auto, probe=False, l2=None): R.STARTED = True; seen.append(l2); return False, 'stored D4 foreign (60.0 counts)'
    monkeypatch.setattr(R, 'one_bake', bake); monkeypatch.setattr(R, 'L2', 'S:1281:990,M:1255:1260:900')
    rc, msg = R.restore(False)
    assert rc == 6 and seen == ['S:1281:990,M:1255:1260:900'] and R.h_auto() and ('apply',) not in rmock
    assert rmock.count(('stock',)) == 2 and rmock[-1] == ('start',) and 'L2 test bake stored' in msg
def test_l2_bake_now_failure_retries_plain_bake(rmock, monkeypatch):
    seen = []
    def bake(tag, auto, probe=False, l2=None): R.STARTED = True; seen.append(l2); return False, 'bake_now rc 3'
    monkeypatch.setattr(R, 'one_bake', bake); monkeypatch.setattr(R, 'L2', 'S:1281:990')
    rc, msg = R.restore(False); assert rc == 1 and R.h_auto() and 'FAILED' in msg and seen == ['S:1281:990', None]
def test_l2_without_s0_writes_retries_plain_bake_and_clears_marker(rmock, monkeypatch):
    seen = []
    def bake(tag, auto, probe=False, l2=None):
        R.STARTED = True; seen.append(l2)
        if l2: R.L2MARK.write_text('x'); return False, 'bake_now wrote no (or not all) S0 words: the L2 bake did not run as planned'
        return True, 'check rc 0, ok 1.0'
    monkeypatch.setattr(R, 'one_bake', bake); monkeypatch.setattr(R, 'L2', 'S:1281:990')
    rc, msg = R.restore(False); assert rc == 0 and seen == ['S:1281:990', None] and not R.L2MARK.exists() and ('apply',) in rmock
def test_l2_kept_result_keeps_marker(rmock, monkeypatch):
    def bake(tag, auto, probe=False, l2=None): R.STARTED = True; R.L2MARK.write_text('x'); return False, "stored D4 foreign (3.0 counts)"
    monkeypatch.setattr(R, 'one_bake', bake); monkeypatch.setattr(R, 'L2', 'S:1281:990')
    rc, msg = R.restore(False); assert rc == 6 and R.L2MARK.exists() and R.h_auto()
def test_s0_written():
    line = ' | '.join(f'03:01:52.153 +239777 write {a}:{o}->{n}' for a, o, n in (x.split(':') for x in R.POKES.split(',')))
    assert R.s0_written('TV x\nwrites: ' + line + '\nbake_now end')
    assert not R.s0_written('writes: ' + line.rsplit(' | ', 1)[0]) and not R.s0_written('no writes\nbake_now end')
def test_l2_marker_makes_compare_foreign():
    if not (R.CAP / 'd4-bake11' / 'dump.bin').exists(): return
    assert R.compare('d4-bake11')['verdict'] == 'ok'
    R.L2MARK.write_text('x'); c = R.compare('d4-bake11')
    assert c['verdict'] == 'foreign' and 'l2-test-bake' in c['signature'] and R.compare('d4-bake11', plain_bake=True)['verdict'] == 'ok'
def test_one_bake_l2_writes_marker_first_and_needs_s0_writes(monkeypatch):
    order = []
    monkeypatch.setattr(R, 'read_d4', lambda n: n)
    def rg(cmd, timeout, term_wait=120):
        order.append(('marker', R.L2MARK.exists(), os.path.basename(cmd[2]) if len(cmd) > 2 else cmd[0])); return 0, 'writes: nothing\n', ''
    monkeypatch.setattr(R, 'run_group', rg); monkeypatch.setattr(R, 'STARTED', False)
    ok, why = R.one_bake('t', False, False, 'S:1281:990')
    assert not ok and 'S0 words' in why and order == [('marker', True, 'bake_now.py')] and 'S:1281:990' in R.L2MARK.read_text()
def test_guard_can_restore(monkeypatch):
    act = {'rc': 0}; monkeypatch.setattr(R, 'sh', lambda cmd, t: (act['rc'], ''))
    assert R.guard_can_restore() is None
    act['rc'] = 3; assert 'not running' in R.guard_can_restore(); act['rc'] = 0
    R.GMAINT.write_text(''); assert 'maintenance' in R.guard_can_restore(); R.GMAINT.unlink()
    R.GSTATE.write_text(json.dumps({'auto_off': True})); assert 'OFF' in R.guard_can_restore()
    R.GSTATE.write_text(json.dumps({'restores': [time.time() - 100, time.time() - 200]})); assert '24 h' in R.guard_can_restore()
    R.GSTATE.write_text(json.dumps({'restores': [time.time() - 90000, time.time() - 200]})); assert R.guard_can_restore() is None
def test_l2_preconditions_need_the_guard(monkeypatch):
    monkeypatch.setattr(R, 'busy', lambda: None); monkeypatch.setattr(R, 'tv_on', lambda: True)
    monkeypatch.setattr(R, 'L2', 'S:1281:990'); monkeypatch.setattr(R, 'guard_can_restore', lambda: 'the bake-11 guard is not running')
    assert 'guard' in R.preconditions('restore', False)
def test_l2_accepted_is_a_normal_restore(rmock, monkeypatch):
    seen = []
    def bake(tag, auto, probe=False, l2=None): R.STARTED = True; seen.append(l2); return True, 'check rc 0, ok 1.0'
    monkeypatch.setattr(R, 'one_bake', bake); monkeypatch.setattr(R, 'L2', 'S:1281:990')
    rc, msg = R.restore(False); assert rc == 0 and seen == ['S:1281:990'] and ('apply',) in rmock and not R.RTDIS.exists()
def test_l2_main_refusals(monkeypatch):
    monkeypatch.setattr(R, 'L2', None)
    for a in (['--l2'], ['--l2', 'S:1281:1000'], ['--l2', 'S:+1281:995'], ['--l2', 'S:1281:990', '--auto'],
              ['--l2', 'S:1281:990', '--probe'], ['--l2', 'S:1281:990', '--hold', 'x'], ['--l2', 'S:1281:990', '--lift'],
              ['--l2', 'S:1281:990', '--check']):
        assert R.main(a) == 4, a
    assert not (R.HERE / 'last_restore.json').exists()              # refused before the lock: nothing recorded, no TV contact
B12 = '586919d0:40ca40ca:33783055,586919d4:40ca40ca:343a2cb4,586919d8:40ca40ca:40ca3904'
def test_l2_pokes_used_for_l2_bake_only(monkeypatch):
    cmds = []
    monkeypatch.setattr(R, 'read_d4', lambda n: n); monkeypatch.setattr(R, 'STARTED', False); monkeypatch.setattr(R, 'L2POKES', B12)
    def rg(cmd, timeout, term_wait=120): cmds.append(cmd); return 0, 'writes: nothing\n', ''
    monkeypatch.setattr(R, 'run_group', rg)
    ok, why = R.one_bake('t', False, False, 'M:1255:1260:900')
    assert not ok and 'S0 words' in why and cmds[0][3] == B12 and cmds[0][4] == 'M:1255:1260:900'
    monkeypatch.setattr(R, 'compare', lambda n, plain_bake=False: {'verdict': 'foreign', 'max_dev': 0})
    cmds.clear(); R.one_bake('t2', False, False, None)
    assert cmds[0][2] == 'bake_now.py' and cmds[0][3] == R.POKES                        # plain / retry bake: bake-11 words
def test_s0_written_custom_pokes():
    line = ' | '.join(f'03:01:52.153 +239777 write {a}:{o}->{n}' for a, o, n in (x.split(':') for x in B12.split(',')))
    assert R.s0_written('writes: ' + line, B12) and not R.s0_written('writes: ' + line, R.POKES)
def test_pokes_refusals(monkeypatch):
    monkeypatch.setattr(R, 'L2', None); monkeypatch.setattr(R, 'L2POKES', None)
    for a in (['--l2', 'M:1255:1260:900', '--pokes'], ['--l2', 'M:1255:1260:900', '--pokes', '586919d0:40ca40ca:20003055'],
              ['--pokes', B12], ['--l2', 'M:1255:1260:900', '--pokes', B12 + ',586919d0:40ca40ca:33783055']):
        assert R.main(a) == 4, a
    assert not (R.HERE / 'last_restore.json').exists()
def test_compare_catches_the_split_bake():
    if not (R.CAP / 'd4-l2ev-test2' / 'dump.bin').exists(): return
    c = R.compare('d4-l2ev-test2', plain_bake=True)                   # no marker: the row blocks alone
    assert c['verdict'] == 'foreign' and c['max_dev'] > 50
    assert R.compare('d4-l2ev-bake11-0741', plain_bake=True)['verdict'] == 'ok'
class DarkTV:                                  # fake root channel + clock for dark_fix
    def __init__(self, states): self.states, self.cmds, self.t = list(states), [], 0.0
    def root(self, cmd, t):
        self.cmds.append(cmd)
        if '(sleep 2; reboot)' in cmd: return 'scheduled'
        if 'poweronmode' in cmd: return '=== diag'
        st, usb, dark = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return f'   string "{st}"\nUSB={1 if usb else 0}\n[  1.0] [TCON:QDF] m_get_tcon_status: QD tcon status [NG], tcon power({0 if dark else 1})'
    def clock(self): return self.t
    def nap(self, s): self.t += s
    def reboots(self): return sum('(sleep 2; reboot)' in c for c in self.cmds)
def test_dark_fix_controller_present():
    tv = DarkTV([('lcdon', True, False)]); assert R.dark_fix(tv.root, tv.clock, tv.nap) == 'ok' and tv.reboots() == 0
def test_dark_fix_controller_comes_late():
    tv = DarkTV([('lcdon', False, True)] * 5 + [('lcdon', True, False)]); assert R.dark_fix(tv.root, tv.clock, tv.nap) == 'ok' and tv.reboots() == 0
def test_dark_fix_standby_never_reboots():
    tv = DarkTV([('standby', False, True)]); assert R.dark_fix(tv.root, tv.clock, tv.nap) == 'not-on' and tv.reboots() == 0
def test_dark_fix_no_tcon_power0_line_never_reboots():
    tv = DarkTV([('lcdon', False, False)]); assert R.dark_fix(tv.root, tv.clock, tv.nap) == 'not-on' and tv.reboots() == 0
def test_dark_fix_reboots_once_and_recovers(sandbox):
    n = R.DARK_WAIT_S // R.DARK_POLL_S + 1
    tv = DarkTV([('lcdon', False, True)] * (n + 3) + [('lcdon', True, False)])
    assert R.dark_fix(tv.root, tv.clock, tv.nap) == 'rebooted-ok' and tv.reboots() == 1 and any('rebooting' in m for m in sandbox)
    assert tv.t >= R.DARK_WAIT_S
def test_dark_fix_still_dark_after_one_reboot(sandbox):
    tv = DarkTV([('lcdon', False, True)])
    assert R.dark_fix(tv.root, tv.clock, tv.nap) == 'rebooted-still-dark' and tv.reboots() == 1 and any('owner' in m for m in sandbox)
def test_dark_fix_probe_errors_never_reboot():
    def bad(cmd, t): raise RuntimeError('channel down')
    clk = [0.0]
    assert R.dark_fix(bad, lambda: clk[0], lambda s: clk.__setitem__(0, clk[0] + s)) == 'not-on'
def test_one_bake_dark_after_reboot_not_accepted(monkeypatch):
    monkeypatch.setattr(R, 'read_d4', lambda n: n); monkeypatch.setattr(R, 'STARTED', False)
    monkeypatch.setattr(R, 'run_group', lambda cmd, timeout, term_wait=120: (0, 'writes: x', ''))
    monkeypatch.setattr(R, 'dark_fix', lambda: 'rebooted-still-dark')
    ok, why = R.one_bake('t', False, False, None); assert not ok and 'dark' in why
def test_one_bake_dark_check_also_after_failed_bake_now(monkeypatch):
    seen = []; monkeypatch.setattr(R, 'read_d4', lambda n: n); monkeypatch.setattr(R, 'STARTED', False)
    monkeypatch.setattr(R, 'dark_fix', lambda: (seen.append(1), 'ok')[1])
    for rc, out, want in ((1, 'Traceback ...', 1), (5, '', 1), (2, 'refused', 0), (3, 'request not accepted', 1),
                          (1, 'TV not on; RequestOffSensing needs power state normal', 0)):
        seen.clear(); monkeypatch.setattr(R, 'run_group', lambda cmd, timeout, term_wait=120, rc=rc, out=out: (rc, out, ''))
        ok, why = R.one_bake('t', False, False, None); assert not ok and len(seen) == want, (rc, out, seen)
def test_restore_dark_stops_without_retry(rmock, monkeypatch, sandbox):
    n = []
    def bake(tag, auto, probe=False, l2=None): n.append(tag); R.STARTED = True; return False, R.DARK_WHY
    monkeypatch.setattr(R, 'one_bake', bake); monkeypatch.setattr(R, 'L2', 'M:1255:1260:900')
    rc, msg = R.restore(False); assert rc == 7 and len(n) == 1 and 'DARK' in msg and any('DARK' in m for m in sandbox)
def test_guard_rc7_turns_auto_restore_off():
    st = {}; m = G.after_restore(st, 1000.0, 7, 'dark'); assert st['auto_off'] and 'automatic restore is OFF' in m
def test_l2_lock_refuses(monkeypatch, tmp_path):
    top = tmp_path / 'top'; (top / 'l2').mkdir(parents=True); (top / 'l2' / 'DISABLED').write_text('x')
    monkeypatch.setattr(R, 'TOP', top); monkeypatch.setattr(R, 'L2', None)
    assert R.main(['--l2', 'M:1255:1260:900']) == 4
def test_bake_window(monkeypatch):
    import datetime
    monkeypatch.setattr(R.C, 'TV_TZ', '+00:00'); monkeypatch.setattr(R.C, 'BAKE_WINDOW', ('10:30', '01:15'))
    tz = datetime.timezone.utc
    def at(h, m): return datetime.datetime(2026, 11, 20, h, m, tzinfo=tz).timestamp()
    assert _IBW(at(10, 30)) and _IBW(at(23, 0)) and _IBW(at(1, 15)) and _IBW(at(0, 5))
    assert not _IBW(at(1, 16)) and not _IBW(at(2, 3)) and not _IBW(at(10, 29))
def test_boot_healthy():
    ok = lambda c, t: 'USB=1\n[ 5.0] QD tcon status [OK], tcon power(1)\n[ 5.1] HSM Status : 0x0 (tcon:1)'
    assert _BH(ok) is None
    assert 'absent' in _BH(lambda c, t: 'USB=0')
    assert 'power(0)' in _BH(lambda c, t: 'USB=1\n QD tcon status [NG], tcon power(0)')
    assert 'HSM' in _BH(lambda c, t: 'USB=1\n HSM Status : 0x10 (tcon:0)')
    assert _BH(lambda c, t: 'USB=1') is None                           # lines rotated out: no evidence against
def test_restore_refused_outside_window(monkeypatch):
    monkeypatch.setattr(R, 'busy', lambda: None); monkeypatch.setattr(R, 'tv_on', lambda: True)
    monkeypatch.setattr(R, 'in_bake_window', lambda now=None: False); monkeypatch.setattr(R, 'L2', None)
    (R.CAP / R.REF).mkdir(parents=True, exist_ok=True) if False else None
    monkeypatch.setattr(R, 'PLAN11', R.HERE / 'p11'); (R.HERE / 'p11').write_text('{}')
    monkeypatch.setattr(R, 'CAP', R.HERE / 'cap'); (R.HERE / 'cap' / R.REF).mkdir(parents=True); (R.HERE / 'cap' / R.REF / 'dump.bin').write_text('x')
    why = R.preconditions('restore', False); assert why and 'window' in why
    monkeypatch.setattr(R, 'in_bake_window', lambda now=None: True); monkeypatch.setattr(R, 'boot_healthy', lambda root=None: 'kernel reports tcon power(0)')
    assert 'marginal' in R.preconditions('restore', False)
    monkeypatch.setattr(R, 'boot_healthy', lambda root=None: None); assert R.preconditions('restore', False) is None
def test_dark_fix_saves_diagnostics(sandbox, monkeypatch):
    monkeypatch.setattr(R, 'CAP', R.HERE); n = R.DARK_WAIT_S // R.DARK_POLL_S + 1; tv = DarkTV([('lcdon', False, True)] * (n + 3) + [('lcdon', True, False)])
    assert R.dark_fix(tv.root, tv.clock, tv.nap) == 'rebooted-ok' and any('poweronmode' in c for c in tv.cmds)
    assert list(R.HERE.glob('dark-*.txt'))
def test_every_bake_checks_window(rmock, monkeypatch):
    calls = []
    monkeypatch.setattr(R, 'read_d4', lambda n: n); monkeypatch.setattr(R, 'in_bake_window', lambda now=None: False)
    monkeypatch.setattr(R, 'run_group', lambda *a, **k: (calls.append(a), (0, '', ''))[1])
    ok, why = R.one_bake('t', False, False, None); assert not ok and why.startswith(R.WINDOW_WHY) and not calls
    monkeypatch.setattr(R, 'in_bake_window', lambda now=None: True); monkeypatch.setattr(R, 'boot_healthy', lambda root=None: 'HSM Status 0x10')
    ok, why = R.one_bake('t', False, False, None); assert not ok and 'marginal' in why and not calls
def test_retry_outside_window_is_deferred(rmock, monkeypatch):
    n = []
    def bake(tag, auto, probe=False, l2=None):
        n.append(tag)
        if len(n) == 1: R.STARTED = True; return False, 'stored D4 foreign (40 counts)'
        return False, R.WINDOW_WHY
    monkeypatch.setattr(R, 'one_bake', bake); rc, msg = R.restore(True); assert rc == 5 and len(n) == 2
def test_bake_now_copies_refuse_outside_window():
    for f in ('bake_now.py', 'probe/bake_now.py', 'l2/bake_now.py'):
        if not (R.TOP / f).exists(): continue                      # public kit: only tcon/bake_now.py ships
        src = (R.TOP / f).read_text(); assert "_in_window()" in src and src.index('_in_window()') < src.index('root(REQ'), f

