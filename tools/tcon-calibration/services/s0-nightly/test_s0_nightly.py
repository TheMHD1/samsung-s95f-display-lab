#!/usr/bin/env python3
"""Offline tests for s0_nightly.py v2 and morning_audit.py v2. Never contacts the TV (root/state are mocked)."""
import dataclasses, json, pathlib, sys, time, types
import numpy as np, pytest
HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parents[1] / 'tcon'))
import s0_nightly as N, morning_audit as A, bake_eval as BE

# Public kit: a SYNTHETIC helper log in the format of the first real bake (the real capture is not published).
BAKE1 = (HERE / 'fixtures' / 'arm-example.log').read_text()
EXAMPLE_PLAN = HERE.parents[1] / 'examples' / 's0-plan-bake11.json'

@pytest.fixture(autouse=True)
def fake_helper(tmp_path, monkeypatch):
    """No helper binaries ship with the kit: 3 small fake files stand in, and the example plan is pinned to them."""
    b = tmp_path / 'fake-helper-bin'; b.mkdir()
    for f in N.FILES: (b / f).write_text(f'fake {f}\n')
    monkeypatch.setattr(N, 'HELPER', b)
    p = json.loads(EXAMPLE_PLAN.read_text()); p['helper_sha256'] = {f: N.hashlib.sha256((b / f).read_bytes()).hexdigest() for f in N.FILES}
    f = tmp_path / 'plan-pinned.json'; f.write_text(json.dumps(p)); monkeypatch.setattr(N, 'PLAN', f)

def _captures(*names):
    """The morning-audit tests below ran on real D4/C1 captures of the S95F; they are skipped where those are absent."""
    if not all((BE.CAPTURES / n / 'dump.bin').exists() for n in names): pytest.skip('real D4/C1 captures not present (not published)')

# ---- plan bounds -------------------------------------------------------------------------------------------------
def _plan(tmp_path, lanes, monkeypatch, bad_hash=False):
    p = json.loads(N.PLAN.read_text()); p['lanes'] = lanes
    if bad_hash: p['helper_sha256']['TconDump.dll'] = '0' * 64
    f = tmp_path / 'plan.json'; f.write_text(json.dumps(p)); monkeypatch.setattr(N, 'PLAN', f); return N.load_plan()

def test_plan_ok(tmp_path, monkeypatch):
    p, pokes = _plan(tmp_path, {'628': '0x33D5', '629': '0x33D5'}, monkeypatch)
    assert pokes == '586919d0:40ca40ca:33d533d5,586919d4:40ca40ca:33d533d5'

@pytest.mark.parametrize('lanes', [{'628': '0x40CB'}, {'628': '0x2A1B'}, {'500': '0x3712'}, {'700': '0x3712'}])
def test_plan_bounds(tmp_path, monkeypatch, lanes):
    with pytest.raises(ValueError): _plan(tmp_path, lanes, monkeypatch)

def test_plan_hash_pinned(tmp_path, monkeypatch):
    with pytest.raises(ValueError): _plan(tmp_path, {'628': '0x33D5'}, monkeypatch, bad_hash=True)

# ---- result classification ----------------------------------------------------------------------------------------
def test_classify():
    assert N.classify('armed x\nexit rc=1')[0] == 'none'
    assert N.classify(BAKE1 + '\nnormal end: controller powered down after the scan\nexit rc=3')[0] == 'ok'
    assert N.classify(BAKE1)[0] == 'abnormal'                       # old helper: no normal-end line -> not trusted
    assert N.classify(BAKE1 + '\nwrite transfer failed: no further traffic')[0] == 'abnormal'
    assert N.classify('15:00:00.000 +1 write 586919d0:40ca40ca->33d533d5\nstop: cancelled\nrestore 586919d0:33d533d5->40ca40ca ok\nexit rc=1')[0] == 'abnormal'
    assert N.classify('15:00:00.000 +1 write 586919d0:40ca40ca->33d533d5\nrec 00080301 x\nexit rc=1')[0] == 'abnormal'

# ---- supervision with a fake TV -------------------------------------------------------------------------------------
class FakeTV:
    """Scripted TV: states is a list of (standby, tcon_up) returned by successive state() calls (last one repeats)."""
    def __init__(self, states, log=''):
        self.states, self.log, self.cmds, self.killed = list(states), log, [], False
    def root(self, cmd, t=20):
        self.cmds.append(cmd)
        if cmd.startswith('dbus-send') and 'GetPowerState' in cmd:
            sb, up = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            return ('string "standby"' if sb else 'string "lcdon"') + ('\nTCONUP' if up else '')
        if cmd.startswith('kill $(cat') and 'helper.pid' in cmd and 'dog.pid' not in cmd:
            self.killed = True; self.log += '\nstop: cancelled\nrestore 586919d0:33d533d5->40ca40ca ok\nexit rc=1'; return ''
        if 'sha256sum' in cmd:
            return '\n'.join(N.hashlib.sha256((N.HELPER / f).read_bytes()).hexdigest() + '  ' + f for f in N.FILES)
        if cmd.startswith('cat ') and 'arm.log' in cmd:
            return self.log + ('\nALIVE' if 'kill -0' in cmd and not self.killed else '')
        return ''

def _setup(monkeypatch, tmp_path, tv):
    pause = tmp_path / 'watcher.pause'
    monkeypatch.setattr(N, '_root', tv.root); monkeypatch.setattr(N, '_pause', pause)
    monkeypatch.setattr(N, 'OWN', tmp_path / 'owns_pause'); monkeypatch.setattr(N, 'STATUS', tmp_path / 'status.json')
    monkeypatch.setattr(N, 'LOG', tmp_path / 'log'); monkeypatch.setattr(N, 'TOP', tmp_path); (tmp_path / 'captures').mkdir()
    monkeypatch.setattr(N, 'CAP', tmp_path / 'captures')
    monkeypatch.setattr(N.time, 'sleep', lambda s: None)
    return pause

MARKS = []
def mark(): MARKS.append(1)
LIVE = 'armed\nusb present\n15:00:00.000 +1 write 586919d0:40ca40ca->33d533d5'

def test_tv_on_during_supervision_unpauses_and_cancels(monkeypatch, tmp_path):
    tv = FakeTV([(True, False), (True, True), (False, True)], log=LIVE)
    pause = _setup(monkeypatch, tmp_path, tv)
    r = N.run_helper('586919d0:40ca40ca:33d533d5', time.time() - 660, mark)
    assert tv.killed and not pause.exists() and r['result'] == 'abnormal'

def test_normal_scan_end_ok(monkeypatch, tmp_path):
    tv = FakeTV([(True, False), (True, True)], log=BAKE1 + '\nnormal end: controller powered down after the scan\nexit rc=3')
    pause = _setup(monkeypatch, tmp_path, tv)
    r = N.run_helper('586919d0:40ca40ca:33d533d5', time.time() - 660, mark)
    assert r['result'] == 'ok' and not pause.exists() and not tv.killed and not (tmp_path / 'owns_pause').exists()

def test_no_launch_if_controller_already_up(monkeypatch, tmp_path):
    tv = FakeTV([(True, True)]); pause = _setup(monkeypatch, tmp_path, tv); n = len(MARKS)
    r = N.run_helper('586919d0:40ca40ca:33d533d5', time.time() - 660, mark)
    assert r['result'] == 'skipped' and not any('dotnet TconDump.dll --armwait' in c for c in tv.cmds)
    assert not pause.exists() and len(MARKS) == n                    # no pause and no in_progress mark without a launch

def test_pause_only_around_launch(monkeypatch, tmp_path):
    tv = FakeTV([(True, False)], log=LIVE + '\nnormal end: x\nexit rc=3'); pause = _setup(monkeypatch, tmp_path, tv)
    seen = {}
    real = tv.root
    def spy(cmd, t=20):
        if 'base64 -d' in cmd and 'TconDump.dll' in cmd: seen['staging_paused'] = pause.exists()
        if 'dotnet TconDump.dll --armwait' in cmd: seen['launch_paused'] = pause.exists()
        return real(cmd, t)
    monkeypatch.setattr(N, '_root', spy)
    N.run_helper('586919d0:40ca40ca:33d533d5', time.time() - 660, mark)
    assert seen == {'staging_paused': False, 'launch_paused': True} and not pause.exists()

def test_root_errors_release_pause(monkeypatch, tmp_path):
    tv = FakeTV([(True, False)], log='armed'); pause = _setup(monkeypatch, tmp_path, tv)
    calls = {'n': 0}; real = tv.root
    def flaky(cmd, t=20):
        if 'kill -0' in cmd:
            calls['n'] += 1
            if calls['n'] > 60: return 'armed\nexit rc=1'
            raise RuntimeError('BlockingIOError')
        return real(cmd, t)
    monkeypatch.setattr(N, '_root', flaky)
    clock = {'t': 1000.0}; monkeypatch.setattr(N.time, 'time', lambda: clock.__setitem__('t', clock['t'] + 5) or clock['t'])
    N.run_helper('586919d0:40ca40ca:33d533d5', 1000.0 - 660, mark)
    assert 'root channel down > 120 s' in (tmp_path / 'log').read_text() and not pause.exists()

def test_unpause_only_own_pause(monkeypatch, tmp_path):
    tv = FakeTV([(True, False)]); pause = _setup(monkeypatch, tmp_path, tv)
    pause.touch(); N.unpause(); assert pause.exists()                 # someone else's pause stays
    N.pause(); N.unpause(); assert not pause.exists()

def test_other_tool_blocks_arming(monkeypatch, tmp_path):
    tv = FakeTV([(True, False)]); _setup(monkeypatch, tmp_path, tv)
    monkeypatch.setattr(N, 'others_active', lambda: 'unit s95f-arm-keep')
    r = N.arm_after_standby('x', time.time() - 700, mark)
    assert r['result'] == 'skipped' and not any('armwait' in c for c in tv.cmds)

def test_bake_records_in_progress_then_result(monkeypatch, tmp_path):
    tv = FakeTV([(True, False)]); _setup(monkeypatch, tmp_path, tv)
    def fake_arm(pokes, t_sb, mk):
        mk(); assert json.loads((tmp_path / 'status.json').read_text())['last_bake']['result'] == 'in_progress'
        return dict(result='ok', why='w')
    monkeypatch.setattr(N, 'arm_after_standby', fake_arm); st = {'ref_d4': 'x'}
    N.bake(st, 'p', time.time()); assert st['last_bake']['result'] == 'ok' and st['last_bake']['audit'] == 'pending'

# ---- standby gating -----------------------------------------------------------------------------------------------
def test_standby_due(monkeypatch, tmp_path):
    tv = FakeTV([(True, False)]); _setup(monkeypatch, tmp_path, tv)
    monkeypatch.setattr(N, '_root', lambda c, t=20: '1000.0\n[ 990.0][DISPLAY] off_type(0)/state(idle)/time(100)')
    assert N.standby_due() is False
    monkeypatch.setattr(N, '_root', lambda c, t=20: '1000.0\n[ 995.0][DISPLAY] off sensing required before power off\n[ 995.1] off_type(0)')
    assert N.standby_due() is True
    monkeypatch.setattr(N, '_root', lambda c, t=20: '1000.0\n[ 700.0][DISPLAY] off sensing required before power off')
    assert N.standby_due() is False                                   # stale line from an earlier standby

# ---- morning audit on real captures ---------------------------------------------------------------------------------
@pytest.fixture(scope='module')
def caps():
    _captures('d4-gen199', 'd4-gen200', 'c1-ddr-post')
    return BE.read_d4('d4-gen199'), BE.read_d4('d4-gen200'), BE.read_c1('c1-ddr-post')

def test_audit_bake1_passes(caps):
    ref, new, c1 = caps                                           # hard checks pass; v3.2 band now sees bake 1's real
    r = A.audit(ref, new, c1, [629, 640], [], 150)                # lane-640 bright line (FINDINGS: C1 -94, 1.28-1.61x)
    assert r['verdict'] == 'BAND' and not r['fails'] and {'1280', '1281'} == {f.split()[2] for f in r['band_fails']}

def test_audit_overtrim_fails(caps):
    ref, new, c1 = caps; m = new.medians.copy(); m[:, 1258] -= 600
    r = A.audit(ref, dataclasses.replace(new, medians=m), c1, [629, 640], [], 150)
    assert r['verdict'] == 'FAIL' and any('over-trim col 1258' in f for f in r['fails'])

def test_audit_shift_plus_one_bad_column_fails(caps):
    ref, new, c1 = caps; m = new.medians.copy() - 40; m[0, 500] += 80
    r = A.audit(ref, dataclasses.replace(new, medians=m), c1, [629, 640], [], 150)
    assert r['verdict'] == 'FAIL' and r['drift']['R']['bad'] == [500] and r['drift']['G']['n_bad'] == 0

def test_audit_c1_mismatch_fails(caps):
    ref, new, c1 = caps; bad = c1.copy(); bad[1, 7] += 1
    assert A.audit(ref, new, bad, [629, 640], [], 150)['verdict'] == 'FAIL'

def test_audit_same_generation_fails(caps):
    ref, new, c1 = caps
    assert A.audit(new, new, c1, [629, 640], [], 150)['verdict'] == 'FAIL'

# ---- audit gating after a bake (v3 blocker: the bake's own standby must not supersede its audit) --------------------
def _audit_env(monkeypatch, tmp_path, states):
    tv = FakeTV(states); _setup(monkeypatch, tmp_path, tv)
    clock = {'t': 5000.0}; monkeypatch.setattr(N.time, 'time', lambda: clock.__setitem__('t', clock['t'] + 31) or clock['t'])
    monkeypatch.setattr(N, 'CAMERA_LOCK', tmp_path / 'no.lock')
    calls = []; monkeypatch.setattr(N, 'capture', lambda cmd, out=None, t=900: calls.append(cmd[2]) or False)
    st = {'ref_d4': 'd4-x', 'last_bake': {'id': 'B1', 'result': 'ok', 'audit': 'pending'}}
    return st, calls

def test_audit_waits_through_bakes_own_standby(monkeypatch, tmp_path):
    st, calls = _audit_env(monkeypatch, tmp_path, [(True, False)] * 5 + [(False, True)])
    r, t = N.audit_when_ready(st, {'lanes': {'628': '0x2EA6'}})
    assert r == 'done' and calls == ['d4store.py']            # reached the capture step, not 'standby'

def test_audit_returns_standby_only_after_tv_on(monkeypatch, tmp_path):
    st, calls = _audit_env(monkeypatch, tmp_path, [(True, False), (False, True), (True, False)])
    r, t = N.audit_when_ready(st, {'lanes': {'628': '0x2EA6'}})
    assert r == 'standby' and calls == []

def test_classify_tv_on_cancel_is_aborted_not_latched():
    txt = ('15:00:00.000 +1 write 586919d0:40ca40ca->2ea62ea6\nstop: InvalidOperationException: cancelled\n'
           'restore 586919d0:2ea62ea6->40ca40ca ok\nexit rc=1')
    assert N.classify(txt)[0] == 'aborted'
    assert N.classify(txt.replace(' ok', ' MISMATCH'))[0] == 'abnormal'

# ---- v3.1 band checks (CONSULT-12: repair flips / unrepaired 1261) ---------------------------------------------------
@pytest.fixture(scope='module')
def caps67():
    _captures('d4-bake6', 'd4-bake7', 'c1-ddr-bake7')
    return BE.read_d4('d4-bake6'), BE.read_d4('d4-bake7'), BE.read_c1('c1-ddr-bake7')

def test_band_pass_on_repeat_scan(caps67):
    ref, new, c1 = caps67
    r = A.audit(ref, new, c1, [628, 629], [628, 629], 150, band_delta=True)
    assert r['verdict'] == 'PASS' and r['band'][1261]['R']['delta'] == pytest.approx(-1, abs=3)

def test_band_flip_is_soft(caps67):
    ref, new, c1 = caps67; m = new.medians.copy(); m[0:2, 1255] -= 33          # 1255 repaired: R/G about -27/-36
    r = A.audit(ref, dataclasses.replace(new, medians=m), c1, [628, 629], [628, 629], 150, band_delta=True)
    assert r['verdict'] == 'BAND' and not r['fails'] and any('1255' in f for f in r['band_fails'])

def test_band_unrepaired_1261_without_delta(caps67):
    ref, new, c1 = caps67; m = new.medians.copy(); m[1, 1261] -= 45              # G -41: bright line
    r = A.audit(ref, dataclasses.replace(new, medians=m), c1, [628, 629, 630], [628, 629], 150, band_delta=False)
    assert r['verdict'] == 'BAND' and any('1261 G: excess' in f for f in r['band_fails'])

def test_band_and_hard_is_fail(caps67):
    ref, new, c1 = caps67; m = new.medians.copy(); m[1, 1261] -= 45; bad = c1.copy(); bad[0, 3] += 1
    assert A.audit(ref, dataclasses.replace(new, medians=m), bad, [628, 629], [628, 629], 150)['verdict'] == 'FAIL'

def _audit_rc(monkeypatch, tmp_path, rc, st):
    tv = FakeTV([(False, True)])
    if not (tmp_path / 'captures').exists(): _setup(monkeypatch, tmp_path, tv)
    else: monkeypatch.setattr(N, '_root', tv.root)
    clock = {'t': 5000.0}; monkeypatch.setattr(N.time, 'time', lambda: clock.__setitem__('t', clock['t'] + 31) or clock['t'])
    monkeypatch.setattr(N, 'CAMERA_LOCK', tmp_path / 'no.lock'); monkeypatch.setattr(N, 'LATCHED', tmp_path / 'LATCHED')
    monkeypatch.setattr(N, 'capture', lambda cmd, out=None, t=900: True)
    seen = {}
    def run(cmd, **k):
        seen['cmd'] = cmd; return types.SimpleNamespace(returncode=rc, stdout='{"verdict": "x"}', stderr='')
    monkeypatch.setattr(N.subprocess, 'run', run)
    r = N.audit_when_ready(st, {'lanes': {'628': '0x3055', '629': '0x3055', '630': '0x3E96'}})
    return r, seen['cmd']

def test_soft_fail_once_then_latch(monkeypatch, tmp_path):
    st = {'ref_d4': 'd4-x', 'ref_words': {'628': '0x3055', '629': '0x3055', '630': '0x3E96'},
          'last_bake': {'id': 'B1', 'result': 'ok', 'audit': 'pending'}}
    r, cmd = _audit_rc(monkeypatch, tmp_path, 3, st)
    assert st['last_bake']['audit'] == 'soft-fail' and st['soft_fails'] == 1 and not (tmp_path / 'LATCHED').exists()
    assert '--band-delta' in cmd and st['ref_d4'] == 'd4-x'                       # ref not advanced on a soft fail
    st['last_bake'] = {'id': 'B2', 'result': 'ok', 'audit': 'pending'}
    _audit_rc(monkeypatch, tmp_path, 3, st)
    assert st['last_bake']['audit'] == 'fail' and (tmp_path / 'LATCHED').exists()

def test_pass_resets_soft_fails_and_records_words(monkeypatch, tmp_path):
    st = {'ref_d4': 'd4-x', 'soft_fails': 1, 'last_bake': {'id': 'B3', 'result': 'ok', 'audit': 'pending'}}
    r, cmd = _audit_rc(monkeypatch, tmp_path, 0, st)
    assert '--band-delta' not in cmd                                              # no ref_words yet -> absolute check only
    assert st['soft_fails'] == 0 and st['ref_words']['630'] == '0x3E96' and st['ref_d4'].startswith('d4-s0-B3')

def test_hard_fail_latches_immediately(monkeypatch, tmp_path):
    st = {'ref_d4': 'd4-x', 'last_bake': {'id': 'B4', 'result': 'ok', 'audit': 'pending'}}
    _audit_rc(monkeypatch, tmp_path, 1, st)
    assert st['last_bake']['audit'] == 'fail' and (tmp_path / 'LATCHED').exists()

def test_usage_error_rc2_is_hard(monkeypatch, tmp_path):
    st = {'ref_d4': 'd4-x', 'last_bake': {'id': 'B5', 'result': 'ok', 'audit': 'pending'}}
    _audit_rc(monkeypatch, tmp_path, 2, st)
    assert st['last_bake']['audit'] == 'fail' and (tmp_path / 'LATCHED').exists()

def test_drift_note_never_latches(monkeypatch, tmp_path):
    st = {'ref_d4': 'd4-x', 'deploy_ref': 'd4-dep', 'last_bake': {'id': 'B6', 'result': 'ok', 'audit': 'pending'}}
    _audit_rc(monkeypatch, tmp_path, 0, st)
    assert st['last_bake']['audit'] == 'pass' and not (tmp_path / 'LATCHED').exists()
    assert 'drift' in (tmp_path / 'log').read_text()

def test_plan_per_column_words(monkeypatch, tmp_path):
    import json as J
    plan = J.loads(N.PLAN.read_text()); plan['lanes'] = {'627': '0x3E9640CA', '630': '0x40CA3E96', '628': '0x3055'}
    f = tmp_path / 'plan.json'; f.write_text(J.dumps(plan)); monkeypatch.setattr(N, 'PLAN', f)
    p, pokes = N.load_plan()
    assert '586919cc:40ca40ca:40ca3e96' not in pokes and '586919cc:40ca40ca:3e9640ca' in pokes
    assert '586919d8:40ca40ca:40ca3e96' in pokes and '586919d0:40ca40ca:30553055' in pokes
    for bad in ('0x2A0040CA', '0x40CB40CA', '0x140CA40CA'):
        plan['lanes'] = {'630': bad}; f.write_text(J.dumps(plan))
        with pytest.raises(ValueError): N.load_plan()
    plan['lanes'] = {'640': '0x407740CA'}; f.write_text(J.dumps(plan))   # v3.3: unequal halves off the band lanes
    with pytest.raises(ValueError): N.load_plan()
    plan['lanes'] = {'640': '0x3E96', '626': '0x40CA3E96', '632': '0x3E9640CA'}; f.write_text(J.dumps(plan)); N.load_plan()

def test_word_format_by_digits():
    assert N.halves('0x3055') == (0x3055, 0x3055) and N.halves('0x40CA3E96') == (0x40CA, 0x3E96)
    for bad in ('0x00003055', '0x305', '0x3055305', 'zz'):
        if bad == '0x00003055': assert N.halves(bad) == (0, 0x3055); continue      # parsed per column, then rejected by bounds
        with pytest.raises(ValueError): N.halves(bad)
    assert N.same_words({'628': '0x3055'}, {'628': '0x30553055'}) and not N.same_words({'628': '0x3055'}, {'628': '0x3056'})

def test_band_covers_all_trimmed_lanes(caps67):
    ref, new, c1 = caps67
    r = A.audit(ref, new, c1, [626, 628, 629, 632], [], 150)
    assert {1252, 1253, 1264, 1265} <= set(r['band_columns'])
