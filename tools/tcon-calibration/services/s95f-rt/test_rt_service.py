#!/usr/bin/env python3
"""Offline tests for rt_service.py / rt_tool.py (RT-SPEC §5). Never contacts the TV: probe, helper, watcher are mocked.
RT_CSHARP=1 additionally runs the built TconDump-rt --rt bound checks in docker (no device, fake boot id, no network)."""
import json, os, pathlib, shutil, subprocess, sys, time
import pytest
HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parents[1] / 'tcon'))
import rt_service as S, rt_tool as RT

@pytest.fixture(autouse=True)
def with_watcher(monkeypatch, tmp_path):
    """These tests cover the blackout-watcher integration (MASKED waits); the kit default is no watcher (see the last test).
    Public kit: no helper binaries and no live rt_plan.json ship, so a fake helper bin (3 small files) and a plan pinned to
    it (examples/rt_plan-bake11.json) stand in for them."""
    monkeypatch.setattr(S.C, 'WATCHER_ENABLED', True)
    b = tmp_path / 'fake-helper-bin'; b.mkdir()
    for f in RT.FILES: (b / f).write_text(f'fake {f}\n')
    pins = {f: RT.hashlib.sha256((b / f).read_bytes()).hexdigest() for f in RT.FILES}
    plan = json.loads((HERE.parents[1] / 'examples' / 'rt_plan-bake11.json').read_text()); plan['helper_sha256'] = pins
    (tmp_path / 'rt_plan.json').write_text(json.dumps(plan))
    monkeypatch.setattr(RT, 'BIN', b); monkeypatch.setattr(RT, 'PLAN', tmp_path / 'rt_plan.json'); PINS.clear(); PINS.update(pins)

PINS = {}
BASE10 = {'s1': {'627': ['0x40AA40AE', '0x3A333A36'], '628': ['0x40A340A6', '0x2E8A2E8C'],       # bake-10 runtime plan (S95F)
                 '629': ['0x409B409F', '0x280E2811'], '630': ['0x40944098', '0x325F3262']}, 'blue': 820}

IDENT = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/12'
PLAN_RES = dict(rc=0, s1_state='plan', blue_state='plan', weights=[205, 205, 615, 205, 205, 615])

class Clock:
    def __init__(self, t=10_000.0): self.t = t
    def __call__(self): return self.t
    def adv(self, s): self.t += s

class Env:
    """Fake TV: power/identity, watcher MASKED start, other tools, and a scripted helper (results per mode)."""
    def __init__(self, tmp, monkeypatch):
        self.clock = Clock(); self.ps, self.up, self.ident = 'lcdon', True, IDENT; self.orphans = []
        self.masked_at = self.clock.t - 3600; self.other = None
        self.calls, self.notes = [], []
        self.results = {'apply': [dict(rc=0)], 'apply-s1': [dict(rc=0)], 'audit': [PLAN_RES], 'restore': [dict(rc=0)]}
        monkeypatch.setattr(S, 'LOG', tmp / 'rt_service.log'); monkeypatch.setattr(S, 'DISABLE', tmp / 'rt.disable')
        self.svc = S.Service(probe=self.probe, tool=self.tool, masked=lambda now: self.masked_at, others=lambda: self.other,
                             notify=self.notes.append, clock=self.clock, blue=615, status=tmp / 'rt_status.json',
                             orphan=lambda: self.orphans.pop(0) if self.orphans else False)
    def probe(self): return self.ps, self.up, (self.ident if self.up else None)
    def tool(self, mode):
        self.calls.append((mode, self.clock.t)); q = self.results[mode]
        return dict(q.pop(0) if len(q) > 1 else q[0])
    def modes(self): return [m for m, t in self.calls]
    def run(self, seconds, step=15):
        for _ in range(int(seconds // step)): self.svc.tick(); self.clock.adv(step)

@pytest.fixture
def env(tmp_path, monkeypatch): return Env(tmp_path, monkeypatch)

# ---- readiness -------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize('ps', ['standby', 'lowpower', 'lcdoff', 'start', 'suspend', 'poweroff', None])
def test_only_lcdon_counts_as_on(env, ps):
    env.ps = ps; env.run(600); assert env.calls == []
    env.ps = 'lcdon'; env.masked_at = env.clock.t - 5; env.run(30); assert env.modes() == ['apply']

def test_probe_parses_power_state(monkeypatch):
    for reply, want in [('   string "lcdon"\nTCONUP\nBOOT=aaaaaaaa-bbbb\nDEV=12', ('lcdon', True, 'aaaaaaaa-bbbb/12')),
                        ('   string "lcdoff"\nTCONUP\nBOOT=aaaaaaaa-bbbb\nDEV=12', ('lcdoff', True, 'aaaaaaaa-bbbb/12')),
                        ('   string "standby"\nBOOT=aaaaaaaa-bbbb\nDEV=', ('standby', False, None))]:
        monkeypatch.setattr(S.RT, 'root', lambda c, t=20, r=reply: r); assert S.probe() == want
    assert RT.power_state('method return\n   string "suspend"') == 'suspend' and RT.power_state('') is None

def test_no_call_in_standby_or_tcon_absent(env):
    env.ps = 'standby'; env.run(600); assert env.calls == []
    env.ps, env.up = 'lcdon', False; env.run(600); assert env.calls == []
    env.up = True; env.masked_at = env.clock.t - 5; env.run(30); assert env.modes() == ['apply']

def test_waits_for_masked_20s(env):
    env.masked_at = None; env.run(120); assert env.calls == []
    env.masked_at = env.clock.t - 10; env.svc.tick(); assert env.calls == []
    env.clock.adv(11); env.svc.tick(); assert env.modes() == ['apply']

def test_new_boot_waits_for_remask(env):
    env.svc.tick(); assert env.modes() == ['apply']                    # first boot seen at startup: current MASKED is fine
    env.ident = 'ffffffff-0000-1111-2222-333333333333/13'; env.clock.adv(60)
    env.run(60); assert env.modes() == ['apply']                       # MASKED phase predates the new boot: wait
    env.masked_at = env.clock.t; env.run(45); assert env.modes() == ['apply', 'apply']

def test_kill_switch(env, tmp_path):
    (tmp_path / 'rt.disable').touch(); env.run(600); assert env.calls == []
    (tmp_path / 'rt.disable').unlink(); env.svc.tick(); assert env.modes() == ['apply']

def test_other_tool_guard(env):
    env.other = 'e3.py (pid 42)'; env.run(600); assert env.calls == []
    env.other = None; env.svc.tick(); assert env.modes() == ['apply']

def test_others_active_proc_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(S, 'S0OWN', tmp_path / 'no'); monkeypatch.setattr(S, 'S0STATUS', tmp_path / 'no.json')
    monkeypatch.setattr(S, 'S0LOG', tmp_path / 's0.log')
    proc = tmp_path / 'proc'
    def p(pid, argv, cg='0::/user.slice\n'):
        d = proc / str(pid); d.mkdir(parents=True); (d / 'cmdline').write_bytes(b'\0'.join(argv) + b'\0'); (d / 'cgroup').write_text(cg)
    p(10, [b'/usr/bin/python3', b'-B', b'/x/rt_service.py', b'--live'])
    assert S.others_active(str(proc)) is None
    p(11, [b'python3', b'-B', b'/x/s0svc/s0_nightly.py', b'--live'], '0::/user.slice/app.slice/s0-nightly.service\n')
    assert S.others_active(str(proc)) is None                          # the s0-nightly unit is allowed
    (tmp_path / 's0.log').write_text('2026-11-19T00:00:00Z TV on; waiting for standby\n2026-11-19T00:00:01Z armed on TV in /tmp/x\n')
    assert 's0-nightly busy' in S.others_active(str(proc))
    (tmp_path / 's0.log').write_text('2026-11-19T00:00:00Z TV on; waiting for standby\n'); assert S.others_active(str(proc)) is None
    for i, name in enumerate([b'e3.py', b'tvtool_e2.py', b'/a/arm_wake.py', b'bake_now.py', b's0_nightly.py', b'after_now.sh']):
        d = tmp_path / f'proc{i}'; proc2 = d
        (d / '7').mkdir(parents=True); (d / '7' / 'cmdline').write_bytes(b'python3\0-B\0' + name + b'\0'); (d / '7' / 'cgroup').write_text('0::/\n')
        assert S.others_active(str(proc2)), name

def test_masked_since_state_and_log(tmp_path, monkeypatch):
    monkeypatch.setattr(S, 'WSTATE', tmp_path / 'st.json'); monkeypatch.setattr(S, 'WLOG', tmp_path / 'w.log')
    now = 2_000_000_000.0
    (tmp_path / 'st.json').write_text(json.dumps(dict(phase='MASKED', phase_since=now - 30, heartbeat_t=now - 5)))
    assert S.masked_since(now) == now - 30
    (tmp_path / 'st.json').write_text(json.dumps(dict(phase='PAUSED', phase_since=now - 30, heartbeat_t=now - 5)))
    assert S.masked_since(now) is None
    (tmp_path / 'st.json').write_text('{bad')
    (tmp_path / 'w.log').write_text('2026-11-19T21:04:38 [host] phase PAUSED -> MASKED after 62s: limit 40 T=32\n')
    assert S.masked_since(now) == time.mktime(time.strptime('2026-11-19T21:04:38', '%Y-%m-%dT%H:%M:%S'))
    (tmp_path / 'w.log').write_text('2026-11-19T21:04:38 [h] phase PAUSED -> MASKED after 62s\n2026-11-19T21:05:00 [h] phase MASKED -> PAUSED after 22s\n')
    assert S.masked_since(now) is None

# ---- apply budget --------------------------------------------------------------------------------------------------
def test_at_most_3_applies_2_min_apart(env):
    env.results['apply'] = [dict(rc=1, error='InvalidOperationException: weights changing (fade-in not finished)')]
    env.run(3600)
    ts = [t for m, t in env.calls if m == 'apply']
    assert len(ts) == 3 and all(b - a >= 120 for a, b in zip(ts, ts[1:]))
    assert env.svc.st['stopped'] and env.notes                          # 4th wanted apply -> stop + notify

def test_new_boot_resets_counters(env):
    env.results['apply'] = [dict(rc=1, error='InvalidOperationException: no bank flip within 100 s')]
    env.run(3600); assert len(env.calls) == 3 and env.svc.st['stopped']
    env.ident = 'ffffffff-0000-1111-2222-333333333333/13'; env.masked_at = env.clock.t + 5; env.results['apply'] = [dict(rc=0)]
    env.run(120)
    assert env.svc.st['identity'] == env.ident and not env.svc.st['stopped'] and len(env.svc.st['applies']) == 1

def test_tool_error_not_counted_but_spaced(env):
    env.results['apply'] = [{'tool_error': 'RuntimeError: watcher did not pause'}]
    env.run(600); assert len(env.calls) == 5 and env.svc.st['applies'] == []

def test_audit_schedule(env):
    env.svc.tick(); t0 = env.calls[0][1]
    env.run(3 * 3600)
    at = [t - t0 for m, t in env.calls if m == 'audit']
    assert 90 <= at[0] < 120 and 600 <= at[1] < 630 and all(1800 <= b - a < 1830 for a, b in zip(at[1:], at[2:]))
    assert env.modes().count('apply') == 1

# ---- audit -> action table -----------------------------------------------------------------------------------------
def _audit_then(env, audit_results, seconds=900):
    env.results['audit'] = audit_results; env.svc.tick(); env.run(seconds)

def test_row_plan_plan_ok(env):
    _audit_then(env, [PLAN_RES]); assert env.modes()[:3] == ['apply', 'audit', 'audit'] and env.modes().count('apply') == 1

def test_row_stock_stock_full_apply(env):
    st = dict(rc=0, s1_state='stock', blue_state='stock', weights=[205] * 6)
    _audit_then(env, [st, PLAN_RES], 400)
    assert env.modes()[:4] == ['apply', 'audit', 'apply', 'audit']

def test_row_fade_weights_full_apply(env):
    fade = dict(rc=0, s1_state='stock', blue_state='other', weights=[120] * 6)
    _audit_then(env, [fade, PLAN_RES], 400); assert env.modes()[:3] == ['apply', 'audit', 'apply'] and not env.svc.st.get('stopped')

def test_row_plan_stock_reapply_then_s1_only(env):
    ps = dict(rc=0, s1_state='plan', blue_state='stock', weights=[205] * 6)
    ss = dict(rc=0, s1_state='stock', blue_state='stock', weights=[205] * 6)
    env.results['audit'] = [ps, ps, ss, ps]; env.svc.tick(); env.run(1200)
    m = env.modes()
    assert m[:4] == ['apply', 'audit', 'apply', 'audit']               # first blue rewrite: apply once more
    assert env.svc.st['s1_only'] and 'apply-s1' in m                    # second within 10 min: S1 only; stock -> apply-s1
    assert m.count('apply') == 2 and not env.svc.st.get('stopped')

def test_row_stock_plan_restore_then_apply(env):
    sp = dict(rc=0, s1_state='stock', blue_state='plan', weights=[205, 205, 615, 205, 205, 615])
    _audit_then(env, [sp, PLAN_RES], 400)
    assert env.modes()[:4] == ['apply', 'audit', 'restore', 'apply'] and not env.svc.st.get('stopped')

@pytest.mark.parametrize('bad', [dict(s1_state='other', blue_state='plan'), dict(s1_state='plan', blue_state='other'),
                                 dict(s1_state='plan', blue_state='plan', weights=[137, 137, 615, 137, 137, 615])])
def test_row_other_restore_stop_notify(env, bad):
    _audit_then(env, [dict(dict(rc=0, weights=[205, 205, 615, 205, 205, 615]), **bad)], 3600)
    assert env.modes() == ['apply', 'audit', 'restore'] and env.svc.st['stopped'] and env.notes

@pytest.mark.parametrize('err', ['InvalidOperationException: before: controller not Clean/limit40 (0, 1, 1, 40)',
                                 'InvalidOperationException: record is not type 3 mode 8'])
def test_helper_refusal_fatal(env, err):
    env.results['apply'] = [dict(rc=1, error=err)]; env.run(3600)
    assert env.modes() == ['apply', 'restore'] and env.svc.st['stopped'] and env.notes

def test_audit_refusal_fatal(env):
    _audit_then(env, [dict(rc=1, error='InvalidOperationException: after: controller not Clean/limit40 (0, 0, 0, 40)')], 3600)
    assert env.modes() == ['apply', 'audit', 'restore'] and env.svc.st['stopped'] and env.notes

def test_s1_not_stock_plan_refusal(env):
    env.results['apply'] = [dict(rc=1, error='InvalidOperationException: S1 not stock/plan')]; env.run(3600)
    assert env.modes() == ['apply', 'restore'] and env.svc.st['stopped']

def test_write_transfer_failure_no_more_traffic(env):
    env.results['apply'] = [dict(rc=1, error='IOException: bulk OUT', writes=['write transfer failed: no further traffic (no undo)'])]
    env.run(3600); assert env.modes() == ['apply'] and env.svc.st['stopped'] and env.notes

def test_blue_refusal_goes_to_audit(env):
    env.results['apply'] = [dict(rc=1, error='InvalidOperationException: blue pair 615 with S1 not all plan'), dict(rc=0)]
    sp = dict(rc=0, s1_state='stock', blue_state='plan', weights=[205, 205, 615, 205, 205, 615])
    env.results['audit'] = [sp, PLAN_RES]; env.svc.tick(); env.run(400)
    assert env.modes()[:4] == ['apply', 'audit', 'restore', 'apply']

def test_status_persists_and_resumes(env, tmp_path):
    env.svc.tick(); st = json.loads((tmp_path / 'rt_status.json').read_text())
    assert st['identity'] == IDENT and len(st['applies']) == 1 and st['next_audit']
    svc2 = S.Service(probe=env.probe, tool=env.tool, masked=lambda now: env.masked_at, others=lambda: None, notify=env.notes.append,
                     clock=env.clock, blue=615, status=tmp_path / 'rt_status.json')
    svc2.tick(); assert env.modes() == ['apply']                        # same boot after a restart: no second apply

# ---- plan bounds (Python mirror of the C# RtParse) -------------------------------------------------------------------
def _plan(tmp_path, mutate, sha=True):
    p = json.loads(json.dumps(BASE10)); p['helper_sha256'] = dict(PINS); mutate(p)   # fixed base (the live plan changes)
    f = tmp_path / 'plan.json'; f.write_text(json.dumps(p)); return RT.load_plan(f)

def test_plan_ok(tmp_path):
    p, arg = _plan(tmp_path, lambda p: None)
    assert arg == '586955cc:40aa40ae:3a333a36,586955d0:40a340a6:2e8a2e8c,586955d4:409b409f:280e2811,586955d8:40944098:325f3262,820'

@pytest.mark.parametrize('mutate', [
    lambda p: p['s1'].update({'631': p['s1'].pop('630')}),                    # bad address (lane 631)
    lambda p: p['s1'].pop('630'),                                             # lane missing
    lambda p: p['s1'].update({'627': ['0x40AA40AE', '0x40AB3A36']}),          # NEW above stock
    lambda p: p['s1'].update({'628': ['0x40A340A6', '0x26AB2E8C']}),          # half 9899 below floor
    lambda p: p['s1'].update({'628': ['0x40A340A7', '0x2E8A2E8C']}),          # STOCK not the stored word
    lambda p: p['s1'].update({'629': ['0x409B409F', '0x409B409F']}),          # NEW == STOCK
    lambda p: p['s1'].update({'629': ['0x409B409F', '0x280E281']}),           # malformed word
    lambda p: p.update(blue=821), lambda p: p.update(blue=204), lambda p: p.update(blue=615.0), lambda p: p.update(blue=True)])
def test_plan_bounds(tmp_path, mutate):
    with pytest.raises(ValueError): _plan(tmp_path, mutate)

def test_plan_blue_820_allowed(tmp_path):                                 # CONSULT-15: blue pair bound 205..820
    _plan(tmp_path, lambda p: p.update(blue=820)); _plan(tmp_path, lambda p: p.update(blue=720))

def test_plan_step_bound(monkeypatch):
    monkeypatch.setattr(RT, 'FLOOR', 0)                                       # isolate the step check (the floor implies it)
    with pytest.raises(ValueError, match='step'): RT.check_s1('628', 0x40A340A6, 0x216240A6)   # 16547-8546 = 8001 > 8000
    RT.check_s1('628', 0x40A340A6, 0x216340A6)                                # exactly 8000: allowed

def test_plan_floor_inclusive():
    RT.check_s1('629', 0x409B409F, 0x26AC26AC)                                # 9900 allowed

def test_helper_sha_mismatch_refused(tmp_path):
    with pytest.raises(ValueError, match='sha256'): _plan(tmp_path, lambda p: p['helper_sha256'].update({'TconDump.dll': '0' * 64}))
    b = tmp_path / 'bin'; shutil.copytree(RT.BIN, b); (b / 'TconDump.deps.json').write_text('{}')
    with pytest.raises(ValueError, match='sha256'): RT.load_plan(RT.PLAN, b)

def test_rt_tool_main_refuses_bad_plan(tmp_path, monkeypatch, capsys):
    p = json.loads(RT.PLAN.read_text()); p['blue'] = 821; f = tmp_path / 'plan.json'; f.write_text(json.dumps(p))
    monkeypatch.setattr(RT, 'PLAN', f); monkeypatch.setattr(RT, 'run', lambda *a: pytest.fail('helper must not run'))
    monkeypatch.setattr(RT.signal, 'signal', lambda *a: None)
    assert RT.main(['apply']) == 3 and 'blue 821' in json.loads(capsys.readouterr().out.strip().splitlines()[-1])['tool_error']
    assert RT.main(['poke']) == 2

# ---- rt_tool run with a fake TV root (detached helper, polling, pause ownership) ----------------------------------------
class FakeClock:
    def __init__(self): self.t = 1_000_000.0
    def time(self): return self.t
    def sleep(self, s): self.t += s

class FakeRoot:
    """Scripted TV for rt_tool.run: helper result appears after `ready` polls (None = never); alive while not ready."""
    def __init__(self, ps='lcdon', ready=2, result=None, dies=False, probe_extra='', fail_polls=()):
        self.cmds, self.ps, self.ready, self.polls, self.dies = [], ps, ready, 0, dies
        self.probe_extra, self.fail_polls = probe_extra, set(fail_polls)
        self.result = result or dict(rc=0, mode='apply')
    def done(self): return self.ready is not None and self.polls >= self.ready
    def __call__(self, cmd, timeout=20):
        assert 1 <= timeout <= 120, timeout                       # the original root channel accepted only 1..120
        self.cmds.append(cmd)
        if cmd.startswith('( LOCKSCRIPT') and '==R' in cmd:
            self.polls += 1
            if self.polls in self.fail_polls: raise RuntimeError('remote channel down')
            res = json.dumps(self.result) if self.done() else ''
            alive = not self.done() and not (self.dies and self.polls >= 2)
            return f'LOCK=ACQUIRED\n==R\n{res}\n==A\n' + self.probe_extra + ('ALIVE 4242\n' if alive else '')
        if cmd.startswith('LOCKSCRIPT'): return 'LOCK=ACQUIRED\n'
        if cmd.startswith('UNLOCK'): return 'LOCK=RELEASED\n'
        if cmd.startswith('cat /proc/sys/kernel/random/boot_id'): return 'b00t-id\n12\n'
        if 'sha256sum' in cmd: return '\n'.join(RT.hashlib.sha256((RT.BIN / f).read_bytes()).hexdigest() + '  ' + f for f in RT.FILES)
        if 'GetPowerState' in cmd: return f'   string "{self.ps}"\nTCONUP\nb00t-id\n12\n'
        if cmd.startswith('cat ') and 'r.json' in cmd:
            if self.done(): return json.dumps(self.result)
            raise RuntimeError('remote rc=1 no such file')
        if cmd.startswith('tail -c 300'): return 'Unhandled exception. System.Exception: boom'
        return ''
    def launches(self): return [c for c in self.cmds if 'dotnet TconDump.dll --rt' in c]

def _fake_tool(monkeypatch, tmp_path, root):
    pause = tmp_path / 'watcher.pause'
    mw = type('mw', (), dict(lock_script=staticmethod(lambda p, o, s: f'LOCKSCRIPT {o}'),
                             unlock_script=staticmethod(lambda p, o: f'UNLOCK {o}')))
    monkeypatch.setattr(RT, '_ns', dict(mw=mw, PAUSE=pause, wait_phase=lambda want, since, lim: next(iter(want))))
    monkeypatch.setattr(RT, 'root', root); monkeypatch.setattr(RT, 'OWN', tmp_path / 'owns_pause')
    monkeypatch.setattr(RT, 'HOSTLOCK', tmp_path / 'rt_tool.lock'); monkeypatch.setattr(RT, 'TERM', [])
    monkeypatch.setattr(RT, 'time', FakeClock()); return pause

def test_rt_tool_detached_launch_and_poll(tmp_path, monkeypatch):
    root = FakeRoot(ready=3); pause = _fake_tool(monkeypatch, tmp_path, root)
    r = RT.run('apply', 'PLANARG')
    assert r['rc'] == 0 and not pause.exists() and not (tmp_path / 'owns_pause').exists()
    [launch] = root.launches()
    assert 'setsid nohup' in launch and launch.rstrip().endswith('echo started') and ' & ' in launch
    assert ' 12 b00t-id apply PLANARG ' in launch and root.polls == 3
    owners = {c.replace('( ', '').split()[1] for c in root.cmds if c.startswith(('LOCKSCRIPT', 'UNLOCK', '( LOCKSCRIPT'))}
    assert len(owners) == 1 and owners.pop().startswith('claude-rt-')        # one per-run owner; every poll refreshes it
    assert any(c.startswith('UNLOCK claude-rt-') for c in root.cmds)
    polls = [c for c in root.cmds if c.startswith('( LOCKSCRIPT')]
    assert all('r.json.lcdon' in c and '"lcdon"' in c and '/proc/$1/cmdline' in c for c in polls)   # flag + process check
    assert any('GetPowerState' in c and 'r.json.lcdon' in c for c in root.cmds if not c.startswith('( '))  # fresh before launch

def test_rt_tool_channel_lost_releases_pause_fast(tmp_path, monkeypatch):
    root = FakeRoot(ready=None, fail_polls={2, 3}); pause = _fake_tool(monkeypatch, tmp_path, root); seen = {}
    orig = root.__call__
    def spy(cmd, timeout=20):
        if cmd.startswith('( LOCKSCRIPT') and root.polls == 2: seen['paused_at_2nd_fail'] = pause.exists()
        return orig(cmd, timeout)
    monkeypatch.setattr(RT, 'root', spy); t0 = RT.time.time()
    r = RT.run('apply', 'P'); n = len(root.cmds)
    assert 'channel lost' in r['tool_error'] and r['helper_launched'] and not pause.exists() and not RT.OWN.exists()
    after = root.cmds[[i for i, c in enumerate(root.cmds) if c.startswith('( LOCKSCRIPT')][-1] + 1:]
    assert after == [] and RT.time.time() - t0 < 60                      # no rm/unlock/kill after the loss; quick

def test_rt_tool_term_while_helper_runs(tmp_path, monkeypatch):
    root = FakeRoot(ready=None); pause = _fake_tool(monkeypatch, tmp_path, root)
    orig = root.__call__
    def spy(cmd, timeout=20):
        if cmd.startswith('( LOCKSCRIPT') and root.polls == 2: RT.TERM.append(15)
        return orig(cmd, timeout)
    monkeypatch.setattr(RT, 'root', spy)
    r = RT.run('apply', 'P')
    assert 'terminated' in r['tool_error'] and not pause.exists() and not any(c.startswith(('UNLOCK', 'rm -rf')) for c in root.cmds)

def test_rt_tool_total_deadline(tmp_path, monkeypatch):
    root = FakeRoot(ready=None); pause = _fake_tool(monkeypatch, tmp_path, root)
    monkeypatch.setattr(RT, 'HELPER_S', {'apply': 10_000}); t0 = RT.time.time()
    r = RT.run('apply', 'P'); assert r.get('killed') and RT.time.time() - t0 <= RT.TOTAL_MAX_S - RT.CLEANUP_S + 5

def test_rt_tool_foreign_pid_is_not_exit(tmp_path, monkeypatch):
    root = FakeRoot(ready=3, probe_extra='FOREIGN 1\n'); _fake_tool(monkeypatch, tmp_path, root)
    assert RT.run('apply', 'P')['rc'] == 0 and root.polls == 3              # our helper found by scan: kept polling
    root = FakeRoot(ready=None, dies=True, probe_extra='FOREIGN 1\n'); _fake_tool(monkeypatch, tmp_path, root)
    assert 'exited without result' in RT.run('apply', 'P')['tool_error']   # only a foreign pid: our helper is gone

def test_take_pause_marker_first(tmp_path, monkeypatch):
    pause = _fake_tool(monkeypatch, tmp_path, FakeRoot()); seen = []
    real = pathlib.Path.touch
    def touch(self, *a, **k):
        if self == pause: seen.append(RT.OWN.exists())
        return real(self, *a, **k)
    monkeypatch.setattr(pathlib.Path, 'touch', touch); RT.take_pause(pause, 'claude-rt-x')
    assert seen == [True] and json.loads(RT.OWN.read_text())['pause_mtime_ns'] == pause.stat().st_mtime_ns
    RT.OWN.write_text(json.dumps(dict(owner='claude-rt-x', pid=1, pause_mtime_ns=None))); pause.touch()   # crash in between
    assert RT.clear_own_pause(pause) is True and not pause.exists()

def test_rt_tool_late_result(tmp_path, monkeypatch):
    root = FakeRoot(ready=40); _fake_tool(monkeypatch, tmp_path, root)      # ~120 s of polling before the result
    r = RT.run('apply', 'P'); assert r['rc'] == 0 and root.polls == 40 and not any('kill -9' in c for c in root.cmds)

def test_rt_tool_kills_hung_helper(tmp_path, monkeypatch):
    root = FakeRoot(ready=None); pause = _fake_tool(monkeypatch, tmp_path, root)
    t0 = RT.time.time(); r = RT.run('apply', 'P')
    assert r.get('killed') and r['helper_launched'] and 'rc' not in r and any('kill -9' in c for c in root.cmds)
    assert RT.time.time() - t0 <= RT.TOTAL_MAX_S and not pause.exists()

def test_rt_tool_helper_died_without_result(tmp_path, monkeypatch):
    root = FakeRoot(ready=None, dies=True); _fake_tool(monkeypatch, tmp_path, root)
    r = RT.run('audit', 'P'); assert r['helper_launched'] and 'boom' in r['tool_error']

@pytest.mark.parametrize('ps', ['lcdoff', 'standby', 'start', 'suspend'])
def test_rt_tool_no_launch_unless_lcdon(tmp_path, monkeypatch, ps):
    root = FakeRoot(ps=ps); pause = _fake_tool(monkeypatch, tmp_path, root)
    with pytest.raises(RuntimeError, match='TV not on'): RT.run('apply', 'x')
    assert not root.launches() and not pause.exists()

def test_rt_tool_refuses_foreign_pause(tmp_path, monkeypatch):
    root = FakeRoot(); pause = _fake_tool(monkeypatch, tmp_path, root); pause.touch()
    with pytest.raises(RuntimeError, match='already paused'): RT.run('apply', 'x')
    assert pause.exists() and root.cmds == []                           # someone else's pause stays, no TV traffic

def test_rt_tool_host_lock_serialises(tmp_path, monkeypatch):
    root = FakeRoot(); pause = _fake_tool(monkeypatch, tmp_path, root); held = RT.host_lock()
    try:
        with pytest.raises(RuntimeError, match='another rt_tool'): RT.run('restore', '-')
        assert root.cmds == [] and not pause.exists() and RT.clear_own_pause(pause) is None
    finally: held.close()

def test_rt_tool_repauses_if_pause_removed(tmp_path, monkeypatch):
    root = FakeRoot(ready=3); pause = _fake_tool(monkeypatch, tmp_path, root); seen = []
    orig = root.__call__
    def spy(cmd, timeout=20):
        if cmd.startswith('( LOCKSCRIPT') and root.polls == 0: pause.unlink()          # e.g. tvtool's unconditional unlink
        if cmd.startswith('( LOCKSCRIPT'): seen.append(pause.exists())
        return orig(cmd, timeout)
    monkeypatch.setattr(RT, 'root', spy)
    assert RT.run('apply', 'P')['rc'] == 0 and seen == [False, True, True] and not pause.exists()   # re-paused before the next poll

def test_clear_own_pause(tmp_path, monkeypatch):
    pause = _fake_tool(monkeypatch, tmp_path, FakeRoot())
    assert RT.clear_own_pause(pause) is None                             # no marker
    RT.take_pause(pause, 'claude-rt-x'); assert RT.clear_own_pause(pause) is True and not pause.exists()
    RT.take_pause(pause, 'claude-rt-x'); st = pause.stat(); os.utime(pause, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    assert RT.clear_own_pause(pause) is False and pause.exists() and not RT.OWN.exists()   # re-touched by someone else: left

def test_rt_tool_term_before_launch(tmp_path, monkeypatch):
    root = FakeRoot(); pause = _fake_tool(monkeypatch, tmp_path, root); RT.TERM.append(15)
    with pytest.raises(RuntimeError, match='terminated'): RT.run('apply', 'P')
    assert not root.launches() and not pause.exists()

# ---- rt_service: run_tool timeout/kill, orphan pause, classification, s0 age, late notify ---------------------------------
class FakeProc:
    def __init__(self, script): self.script, self.signals, self.returncode = list(script), [], None
    def communicate(self, timeout=None):
        step = self.script.pop(0)
        if step == 'hang': raise S.subprocess.TimeoutExpired('rt_tool', timeout)
        self.returncode = step[0]; return step[1], step[2]
    def terminate(self): self.signals.append('TERM')
    def kill(self): self.signals.append('KILL')

def test_run_tool_timeout_term_then_kill(monkeypatch, tmp_path):
    monkeypatch.setattr(S, 'LOG', tmp_path / 'log'); cleared = []
    monkeypatch.setattr(S.RT, 'clear_own_pause', lambda: cleared.append(1) or True)
    p = FakeProc(['hang', 'hang', (-9, '', '')])
    r = S.run_tool('apply', popen=lambda *a, **k: p)
    assert p.signals == ['TERM', 'KILL'] and r['helper_launched'] and 'rc' not in r and cleared == [1]
    assert 'orphaned rt_tool watcher pause removed' in (tmp_path / 'log').read_text()

def test_run_tool_term_suffices(monkeypatch, tmp_path):
    monkeypatch.setattr(S, 'LOG', tmp_path / 'log'); monkeypatch.setattr(S.RT, 'clear_own_pause', lambda: None)
    p = FakeProc(['hang', (143, '{"tool_error": "x"}\n', '')]); r = S.run_tool('audit', popen=lambda *a, **k: p)
    assert p.signals == ['TERM'] and r['helper_launched']

def test_run_tool_normal(monkeypatch, tmp_path):
    monkeypatch.setattr(S, 'LOG', tmp_path / 'log'); monkeypatch.setattr(S.RT, 'clear_own_pause', lambda: None)
    p = FakeProc([(0, 'noise\n{"rc": 0, "s1_state": "plan"}\n', 'watcher MASKED')])
    assert S.run_tool('audit', popen=lambda *a, **k: p) == {'rc': 0, 's1_state': 'plan'}
    p = FakeProc([(3, '', 'Traceback')]); assert 'no JSON' in S.run_tool('audit', popen=lambda *a, **k: p)['tool_error']

def test_orphan_pause_cleared_each_tick(env):
    env.orphans = [True]; env.svc.tick()
    assert any('orphaned' in n for n in env.notes) and env.modes() == ['apply']

def test_orphan_pause_real_files(tmp_path, monkeypatch):
    pause = _fake_tool(monkeypatch, tmp_path, FakeRoot()); monkeypatch.setattr(S, 'LOG', tmp_path / 'log')
    RT.take_pause(pause, 'claude-rt-dead')                               # rt_tool was SIGKILLed: marker + pause left
    assert S.clear_orphan_pause('tick') and not pause.exists() and not RT.OWN.exists()
    assert not S.clear_orphan_pause('tick')                              # nothing left

@pytest.mark.parametrize('res, want', [
    (dict(rc=1, error='InvalidOperationException: bulk IN len=16 r=-1 errno=19', writes=[]), 'transient'),
    (dict(rc=1, error='InvalidOperationException: bulk IN len=16 r=-1 errno=19 (fake)',
          writes=['586955cc:40aa40ae->3a333a36', 'undo 586955cc=40aa40ae']), 'failed'),
    (dict(rc=1, error='IOException: x', writes=['write transfer failed: no further traffic (no undo)']), 'transfer'),
    (dict(rc=1, error='InvalidOperationException: CA block differs from stored copy: lane 640 ...', writes=[]), 'other'),
    (dict(rc=1, error='InvalidOperationException: record is not type 3 mode 8 (before blue step 333: 00110802)',
          writes=['586955cc:40aa40ae->3a333a36']), 'fatal'),
    (dict(rc=1, error='InvalidOperationException: blue pair unequal', writes=[]), 'blue'),
    (dict(rc=1, error='InvalidOperationException: no bank flip within 100 s', writes=[]), 'transient'),
    (dict(rc=1, error='InvalidOperationException: TV not lcdon: flag 12 s old (before S1 writes)', writes=[]), 'transient'),
    (dict(rc=1, error='InvalidOperationException: TV not lcdon: flag 11 s old (before blue step 333)',
          writes=['586955cc:40aa40ae->3a333a36', 'undo 586955cc=40aa40ae']), 'transient'),   # clean undo -> retry (review)
    (dict(rc=1, error='InvalidOperationException: TV not lcdon: flag 25 s old (before blue step 333)',
          writes=['586955cc:40aa40ae->3a333a36', 'undo readback mismatch 586955cc']), 'failed')])
def test_kind_classification(res, want):
    assert S.kind(res) == want

def test_bulk_read_error_before_writes_is_retried(env):
    env.results['apply'] = [dict(rc=1, error='InvalidOperationException: bulk IN len=16 r=-1 errno=19', writes=[]), dict(rc=0)]
    env.run(300); assert env.modes()[:2] == ['apply', 'apply'] and not env.svc.st.get('stopped')

def test_bulk_read_error_after_writes_restores_and_stops(env):
    env.results['apply'] = [dict(rc=1, error='InvalidOperationException: bulk IN len=16 r=-1 errno=19',
                                 writes=['586955cc:40aa40ae->3a333a36', 'undo 586955cc=40aa40ae'])]
    env.run(600); assert env.modes() == ['apply', 'restore'] and env.svc.st['stopped'] and env.notes

def test_ca_differs_restores_and_stops(env):
    env.results['apply'] = [dict(rc=1, error='InvalidOperationException: CA block differs from stored copy', writes=[])]
    env.run(600); assert env.modes() == ['apply', 'restore'] and env.svc.st['stopped']

def test_s0_busy_age_limit(tmp_path, monkeypatch):
    for k, v in (('S0OWN', 'own'), ('S0STATUS', 'st.json'), ('S0LOG', 's0.log')): monkeypatch.setattr(S, k, tmp_path / v)
    (tmp_path / 's0.log').write_text('2026-11-19T00:00:01Z armed on TV in /tmp/x\n')
    (tmp_path / 'st.json').write_text(json.dumps({'last_bake': {'result': 'in_progress'}})); (tmp_path / 'own').touch()
    assert S.s0_busy()
    old = time.time() - S.S0_BUSY_MAX_S - 60
    for f in ('s0.log', 'st.json', 'own'): os.utime(tmp_path / f, (old, old))
    assert S.s0_busy() is None

def test_late_notify_once(env):
    env.masked_at = None; env.run(25 * 60)
    late = [n for n in env.notes if 'nothing applied' in n]
    assert env.calls == [] and len(late) == 1 and 'MASKED' in late[0]

def test_no_late_notify_when_applied(env):
    env.run(25 * 60); assert not any('nothing applied' in n for n in env.notes)

def test_notify_uses_token_no_proxy(tmp_path, monkeypatch):
    tok = tmp_path / 'tok'; tok.write_text('secret-token\n'); monkeypatch.setattr(S, 'ALERT_TOKEN', tok); monkeypatch.setattr(S, 'ALERT', 'http://alert.invalid/topic'); seen = {}
    class Op:
        def open(self, req, timeout=None):
            seen['auth'], seen['data'] = req.get_header('Authorization'), req.data
            return type('R', (), {'__enter__': lambda s: s, '__exit__': lambda s, *a: None, 'read': lambda s: b''})()
    def build(*handlers):
        seen['proxy'] = [h for h in handlers if isinstance(h, S.urllib.request.ProxyHandler)]; return Op()
    monkeypatch.setattr(S.urllib.request, 'build_opener', build); S.notify('hello')
    assert seen['auth'] == 'Bearer secret-token' and seen['data'] == b'S95F rt: hello' and seen['proxy'][0].proxies == {}
    assert 'secret-token' not in pathlib.Path(S.__file__).read_text()

# ---- optional: the C# itself (docker, no device) ------------------------------------------------------------------------
# ---- optional: the C# bounds themselves (docker, no device) ----------------------------------------------------------
GOOD = '586955cc:40aa40ae:3a333a36,586955d0:40a340a6:2e8a2e8c,586955d4:409b409f:280e2811,586955d8:40944098:325f3262,820'
CS_CASES = {
    'good': (GOOD, 'boot changed'),
    'addr': (GOOD.replace('586955d8', '586955dc'), 'not allowed'),
    'twice': (GOOD.replace('586955d8:40944098', '586955d4:409b409f'), 'twice'),
    'above': (GOOD.replace('3a333a36', '40ab3a36'), 'outside bounds'),
    'floor': (GOOD.replace('2e8a2e8c', '26ab2e8c'), 'outside bounds'),
    'stock': (GOOD.replace('40a340a6:', '40a340a7:'), 'stored stock'),
    'blue821': (GOOD[:-3] + '821', 'BLUE outside'), 'blue204': (GOOD[:-3] + '204', 'BLUE outside'),
    'count': (GOOD.rsplit(',', 1)[0], '4 S1 entries'),
    'rg': (GOOD[:-3] + '330/330/430', 'boot changed'), 'rg431': (GOOD[:-3] + '431/330/430', 'RED/GREEN outside'),
    'rg204': (GOOD[:-3] + '330/204/430', 'RED/GREEN outside'), 'rgform': (GOOD[:-3] + '330/430', 'BLUE or RED/GREEN/BLUE'),
    'rgblue': (GOOD[:-3] + '330/330/821', 'BLUE outside'), 'rgsign': (GOOD[:-3] + '+330/330/430', 'RED/GREEN outside'),
}
@pytest.mark.skipif(os.environ.get('RT_CSHARP') != '1' or not shutil.which('docker'), reason='set RT_CSHARP=1 (needs docker)')
def test_csharp_rt_bounds(tmp_path):
    script = ''.join(f'echo "== {k}"; dotnet /h/TconDump.dll --rt /o/{k}.json 1 fake-boot apply {v[0]}; '
                     for k, v in CS_CASES.items()) + 'echo "== mode"; dotnet /h/TconDump.dll --rt /o/m.json 1 fake-boot poke x'
    os.chmod(tmp_path, 0o777)
    p = subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--user', f'{os.getuid()}:{os.getgid()}', '-e', 'HOME=/tmp',
                        '-e', 'DOTNET_ROLL_FORWARD=Major', '-e', 'DOTNET_CLI_TELEMETRY_OPTOUT=1', '-v', f'{RT.BIN}:/h:ro',
                        '-v', f'{tmp_path}:/o', 'mcr.microsoft.com/dotnet/sdk:10.0', 'sh', '-c', script],
                       capture_output=True, text=True, timeout=300)
    for k, (_, want) in CS_CASES.items():
        r = json.loads((tmp_path / f'{k}.json').read_text()); assert r['rc'] == 1 and want in r['error'], (k, r)
    assert 'rt mode' in json.loads((tmp_path / 'm.json').read_text())['error']

# Fake-device harness: rtsvc/csfake builds TconDump-rt/Program.cs with RT_FAKE (FakeDev.cs replaces the USB transfers).
NEWW = {0x586955CC: 0x3A333A36, 0x586955D0: 0x2E8A2E8C, 0x586955D4: 0x280E2811, 0x586955D8: 0x325F3262}
STOCKW = {0x586955CC: 0x40AA40AE, 0x586955D0: 0x40A340A6, 0x586955D4: 0x409B409F, 0x586955D8: 0x40944098}
PLANSET = ','.join(f'set:{a:x}={v:x}' for a, v in NEWW.items()) + ',set:58602700=267,set:58622700=267'
GOODRG = GOOD[:-3] + '330/300/430'                                              # CONSULT-18: red 330, green 300, blue 430
RGP = ','.join(f'set:{a:x}={v:x}' for a, v in NEWW.items())
RGSET = RGP + ',set:58602700=1ae,set:58622700=1ae,set:586026f8=14a,set:586226f8=14a,set:586026fc=12c,set:586226fc=12c'
RGW = [0x586026F8, 0x586226F8, 0x586026FC, 0x586226FC]
FAKE = {   # name: (mode, RT_FAKE[, PLAN])
    'ok': ('apply', ''), 's1only': ('apply-s1', ''), 'already': ('apply', PLANSET), 'wfail': ('apply', 'wfail:586955d4'),
    'wdrop': ('apply', 'wdrop:58622700'), 'recbad': ('apply', 'recbad:6'), 'rbfail': ('apply', 'rbfail:2'),
    'cadiff': ('apply', 'set:58695a00=40000000'), 'audcadiff': ('audit', 'set:58695600=40000000'), 'audstock': ('audit', ''),
    'other': ('apply', 'set:586955d0=30003000'), 'noflag': ('apply', ''), 'staleflag': ('apply', ''), 'restore': ('restore', PLANSET), 'restcadiff': ('restore', 'set:58695a00=40000000'),
    'rgok': ('apply', '', GOODRG), 'rgalready': ('apply', RGSET, GOODRG), 'rgaudit': ('audit', RGSET, GOODRG),
    'rgonly': ('apply', RGP + ',set:58602700=1ae,set:58622700=1ae', GOODRG),                 # R/G rewritten to 205: R/G only
    'rgblue': ('apply', RGP + ',set:586026f8=14a,set:586226f8=14a,set:586026fc=12c,set:586226fc=12c', GOODRG),   # blue only
    'rgnots1': ('apply', 'set:586026f8=14a,set:586226f8=14a,set:586026fc=12c,set:586226fc=12c', GOODRG),       # R/G plan, S1 stock
    'rgodd': ('apply', 'set:586026f8=12c,set:586226f8=12c', GOODRG), 'rgrecbad': ('apply', 'recbad:16', GOODRG),
    'rgrestore': ('restore', RGSET), 'rgplain': ('apply', 'set:586026f8=14a,set:586226f8=14a'),   # plain BLUE plan, R/G not 205
}
@pytest.mark.skipif(os.environ.get('RT_CSHARP') != '1' or not shutil.which('docker') or not (HERE / 'csfake').exists(),
                    reason='set RT_CSHARP=1 (needs docker and the csfake harness, not part of the public kit)')
def test_csharp_fake_device(tmp_path):
    top = HERE.parent; uid = f'{os.getuid()}:{os.getgid()}'
    b = subprocess.run(['docker', 'run', '--rm', '--user', uid, '-e', 'HOME=/tmp', '-e', 'DOTNET_CLI_TELEMETRY_OPTOUT=1', '-e', 'NUGET_PACKAGES=/cache',
                        '-v', f'{RT.BIN.parent}:/w:ro', '-v', f'{HERE}/csfake:/f', '-v', f'{RT.C.WORK}/.nuget-cache:/cache',
                        'mcr.microsoft.com/dotnet/sdk:10.0', 'dotnet', 'build', '/f/RtFake.csproj', '-c', 'Release', '-o', '/f/bin'],
                       capture_output=True, text=True, timeout=600)
    assert ' 0 Error(s)' in b.stdout, b.stdout[-2000:]
    shutil.copy(RT.C.CAPTURES / '007-ca-state/ca0.bin', tmp_path / 'ca0.bin'); os.chmod(tmp_path, 0o777)   # read-only copy
    def flag(k):                                                    # TV-side lcdon flag, as rt_tool's polls keep it fresh
        if k == 'noflag': return ''
        if k == 'staleflag': return f"touch -d '30 seconds ago' /o/{k}.json.lcdon; "
        return f'(while :; do touch /o/{k}.json.lcdon; sleep 1; done) & T=$!; '
    script = ''.join(f'{flag(k)}RT_FAKE="{f}" RT_FAKE_LOG=/o/{k}.log dotnet /h/TconDumpFake.dll --rt /o/{k}.json 1 b {m} '
                     f'{(v[2] if len(v) > 2 else GOOD) if m != "restore" else "-"} >/dev/null; ' + ('kill $T; ' if flag(k).startswith('(') else '')
                     for k, (m, f, *rest) in FAKE.items() for v in [(m, f, *rest)])
    subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--user', uid, '-e', 'HOME=/tmp', '-e', 'DOTNET_ROLL_FORWARD=Major',
                    '-e', 'RT_FAKE_CA=/o/ca0.bin', '-v', f'{HERE}/csfake/bin:/h:ro', '-v', f'{tmp_path}:/o',
                    'mcr.microsoft.com/dotnet/sdk:10.0', 'sh', '-c', script], capture_output=True, text=True, timeout=900)
    R, W, F, A = {}, {}, {}, {}
    for k in FAKE:
        R[k] = json.loads((tmp_path / f'{k}.json').read_text()); lines = (tmp_path / f'{k}.log').read_text().splitlines()
        W[k] = [(int(l.split()[1], 16), int(l.split()[2], 16)) for l in lines if l.startswith('W ')]
        F[k] = {int(l.split()[1], 16): int(l.split()[2], 16) for l in lines if l.startswith('FINAL ')}
        A[k] = [l for l in lines if l.startswith(('WFAIL', 'AFTER_WFAIL'))]
    ok = R['ok']; assert ok['rc'] == 0 and ok['s1_state'] == 'plan' and ok['blue_state'] == 'plan' and ok['ca_equal']
    assert [a for a, v in W['ok'][:4]] == list(NEWW) and all(v == NEWW[a] for a, v in W['ok'][:4])
    ramp = W['ok'][4:]; assert [a for a, v in ramp] == [0x58602700, 0x58622700] * 7
    steps = [205] + [v for a, v in ramp[::2]]; assert steps[-1] == 615 and all(0 < b - a <= 64 for a, b in zip(steps, steps[1:]))
    assert R['s1only']['rc'] == 0 and len(W['s1only']) == 4 and R['s1only']['blue_state'] == 'stock'
    assert R['already']['rc'] == 0 and R['already']['already'] and W['already'] == []
    wf = R['wfail']; assert wf['rc'] == 1 and any('write transfer failed' in x for x in wf['writes'])
    assert [a for a, v in W['wfail']] == [0x586955CC, 0x586955D0] and A['wfail'] == ['WFAIL 586955d4']   # no traffic after
    for k in ('wdrop', 'recbad', 'rbfail'):                                     # failure after writes: undone in reverse order
        assert R[k]['rc'] == 1 and all(F[k][a] == v for a, v in STOCKW.items()) and F[k][0x58602700] == 205, (k, R[k])
    assert 'record is not type 3 mode 8 (before blue step 333' in R['recbad']['error']
    undo = [a for a, v in W['recbad'][6:]]; assert undo == [0x58602700, 0x58622700, 0x586955D8, 0x586955D4, 0x586955D0, 0x586955CC]
    assert [a for a, v in W['rbfail'][2:]] == [0x586955D0, 0x586955CC]
    assert R['cadiff']['rc'] == 1 and 'CA block differs' in R['cadiff']['error'] and W['cadiff'] == []
    ad = R['audcadiff']; assert ad['rc'] == 0 and ad['s1_state'] == 'other' and not ad['ca_equal'] and 'lane 640' in ad['ca_s1_diff'][0]
    st = R['audstock']; assert st['s1_state'] == 'stock' and st['blue_state'] == 'stock' and st['ca_equal']
    assert R['other']['rc'] == 1 and 'S1 not stock/plan' in R['other']['error'] and W['other'] == []
    rs = R['restore']; assert rs['rc'] == 0 and rs['ca_equal'] and len(W['restore']) == 6 and all(F['restore'][a] == v for a, v in STOCKW.items())
    assert R['restcadiff']['rc'] == 1 and 'CA block differs from stored copy after restore' in R['restcadiff']['error']
    assert R['noflag']['rc'] == 1 and 'TV not lcdon: flag missing (before S1 writes)' in R['noflag']['error'] and W['noflag'] == []
    assert R['staleflag']['rc'] == 1 and 's old (before S1 writes)' in R['staleflag']['error'] and W['staleflag'] == []
    # CONSULT-18 red/green pairs
    assert ok['rg_state'] == 'stock' and all(a not in RGW for a, v in W['ok'])                  # plain BLUE plan: R/G untouched
    g = R['rgok']; assert g['rc'] == 0 and g['s1_state'] == 'plan' and g['blue_state'] == 'plan' and g['rg_state'] == 'plan', g
    w = W['rgok']; assert [a for a, v in w[:4]] == list(NEWW) and [a for a, v in w[4:12]] == [0x58602700, 0x58622700] * 4
    bsteps = [205] + [v for a, v in w[4:12:2]]; assert bsteps[-1] == 430 and all(0 < b - a <= 64 for a, b in zip(bsteps, bsteps[1:]))
    rg = w[12:]; assert all(a in RGW for a, v in rg)
    for reg, top in ((0x586026F8, 330), (0x586226F8, 330), (0x586026FC, 300), (0x586226FC, 300)):
        st = [205] + [v for a, v in rg if a == reg]; assert st[-1] == top and all(0 < b - a <= 64 for a, b in zip(st, st[1:])), (reg, st)
        assert F['rgok'][reg] == top
    assert R['rgalready']['rc'] == 0 and R['rgalready']['already'] and W['rgalready'] == []
    ga = R['rgaudit']; assert ga['rc'] == 0 and ga['rg_state'] == 'plan' and ga['blue_state'] == 'plan' and ga['s1_state'] == 'plan'
    assert R['rgonly']['rc'] == 0 and W['rgonly'] and all(a in RGW for a, v in W['rgonly']) and R['rgonly']['rg_state'] == 'plan'
    assert R['rgblue']['rc'] == 0 and W['rgblue'] and all(a in (0x58602700, 0x58622700) for a, v in W['rgblue'])
    assert R['rgnots1']['rc'] == 1 and 'R/G weights not 205' in R['rgnots1']['error'] and W['rgnots1'] == []
    assert R['rgodd']['rc'] == 1 and 'R/G weights not 205' in R['rgodd']['error'] and W['rgodd'] == []
    gr = R['rgrecbad']; assert gr['rc'] == 1 and 'before R/G step 330/300' in gr['error'], gr     # after the first R/G step
    undo = W['rgrecbad'][16:]; assert [a for a, v in undo] == RGW + [0x58602700, 0x58622700] + list(NEWW)[::-1], undo
    assert all(v == 205 for a, v in undo[:6]) and all(F['rgrecbad'][a] == v for a, v in STOCKW.items())
    assert all(F['rgrecbad'][a] == 205 for a in RGW + [0x58602700, 0x58622700])
    rr = R['rgrestore']; assert rr['rc'] == 0 and rr['rg_state'] == 'stock' and rr['blue_state'] == 'stock' and rr['s1_state'] == 'stock'
    assert sorted(a for a, v in W['rgrestore'] if a in RGW) == sorted(RGW) and all(v == 205 for a, v in W['rgrestore'] if a in RGW)
    assert R['rgplain']['rc'] == 1 and 'R/G weights not 205' in R['rgplain']['error'] and W['rgplain'] == []


# ---- public kit: no blackout watcher configured ----------------------------------------------------------------------
def test_no_watcher_means_no_mask_wait(tmp_path, monkeypatch):
    monkeypatch.setattr(S.C, 'WATCHER_ENABLED', False)
    now = 2_000_000_000.0; assert now - S.masked_since(now) >= 3600                 # never waits for a MASKED phase
    monkeypatch.setattr(S, 'LOG', tmp_path / 'rt_service.log'); monkeypatch.setattr(S, 'DISABLE', tmp_path / 'rt.disable')
    calls = []; clock = Clock(); ident = ['aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/12']
    svc = S.Service(probe=lambda: ('lcdon', True, ident[0]), tool=lambda m: calls.append(m) or dict(rc=0) if m != 'audit' else dict(PLAN_RES),
                    masked=S.masked_since, others=lambda: None, notify=lambda m: None, clock=clock, blue=615,
                    status=tmp_path / 'st.json', orphan=lambda: False)
    svc.tick(); assert calls == ['apply']
    ident[0] = 'ffffffff-0000-1111-2222-333333333333/13'; clock.adv(60); svc.tick()
    assert calls == ['apply', 'apply']                                               # new controller boot: applied at once
