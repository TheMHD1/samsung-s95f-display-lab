"""Offline checks for the optional recovery tools (simulated TV shell; no TV, no network). Run: python3 -m pytest -q"""
import importlib, io, json, pathlib, sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
BOOT = '0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d'


def load(name, tmp_path, monkeypatch):
    cfg = tmp_path / 'kit.json'
    cfg.write_text(json.dumps({'work_dir': str(tmp_path / 'work')}))
    monkeypatch.setenv('TCON_KIT_CONFIG', str(cfg))
    monkeypatch.delenv('TV_INPUT_KEYEVENT_SHA256', raising=False)
    sys.path.insert(0, str(HERE / 'recovery'))
    for m in ('config', name):
        sys.modules.pop(m, None)
    return importlib.import_module(name)


class FakeTV:
    """Simulated home UI: source focus, cached tab, screensaver, power; keys move along a scripted tab map."""
    def __init__(self, A, tab, focused=False, power='lcdon', moves=None, lose_focus_after=None):
        self.A, self.tab, self.focused, self.power = A, tab, focused, power
        self.moves = moves or {}
        self.sent, self.lose_focus_after = [], lose_focus_after

    def topvwins(self):
        mark = 'O' if self.focused else '-'
        return (f'1 0x1a 0 0 1920 1080 0 0 L {"-" if self.focused else "O"} /usr/apps/tv-viewer.dll\n'
                f'2 0x2b 0 0 1920 1080 0 0 L {mark} {self.A.CSFS}\n')

    def __call__(self, cmd):
        assert f'boot_id)" = {BOOT}' in cmd
        if 'GetPowerState' in cmd:
            return f'method return\n   string "{self.power}"\nmethod return\n   int32 1\n'
        if 'input_keyevent' in cmd:
            key = next(k for k, v in self.A.KEYSYMS.items() if f'input_keyevent {v} down' in cmd)
            self.sent.append(key)
            if key == 'home':
                self.focused, self.tab = True, self.tab if self.tab.startswith('d/') else 'd/ug.tab@ForYou'
            else:
                self.tab = self.moves.get((self.tab, key, len(self.sent)), self.moves.get((self.tab, key), self.tab))
            if self.lose_focus_after is not None and len(self.sent) > self.lose_focus_after:
                self.focused = False
            return 'LOCAL_KEY_DOWN_EXIT=0\nLOCAL_KEY_UP_EXIT=0\n'
        return f'{BOOT}\n1.0 1.0\nmemory/eden/current_tab, value = {self.tab} (string)\n{self.topvwins()}1.1 1.1\n'


def run_apps(A, tv, tmp_path, check=False):
    out = io.StringIO()
    args = ['--boot', BOOT, '--output', str(tmp_path / 'apps')] + (['--check'] if check else [])
    try:
        rc = A.main(args, shell=tv, out=out, sleep=lambda s: None)
    except ValueError:
        rc = 1
    return rc, json.loads(out.getvalue().strip().splitlines()[-1])


def test_switch_from_hdmi_via_home_and_live(tmp_path, monkeypatch):
    A = load('tv_apps_home', tmp_path, monkeypatch)
    tv = FakeTV(A, 'hdmi', moves={('d/ug.tab@ForYou', 'right'): 'd/ug.tab@Live', ('d/ug.tab@Live', 'right'): 'd/apps.tab'})
    rc, res = run_apps(A, tv, tmp_path)
    assert rc == 0 and res['ok'] and res['keys'] == ['home', 'right', 'right'] == tv.sent and res['tab'] == 'd/apps.tab'


def test_already_on_apps_sends_nothing(tmp_path, monkeypatch):
    A = load('tv_apps_home', tmp_path, monkeypatch)
    tv = FakeTV(A, 'd/apps.tab', focused=True)
    rc, res = run_apps(A, tv, tmp_path)
    assert rc == 0 and res['keys'] == [] and tv.sent == []


def test_check_mode_sends_no_keys(tmp_path, monkeypatch):
    A = load('tv_apps_home', tmp_path, monkeypatch)
    tv = FakeTV(A, 'd/ug.tab@Live', focused=True)
    rc, res = run_apps(A, tv, tmp_path, check=True)
    assert rc == 1 and res['ok'] is False and res['keys'] == [] and tv.sent == []


def test_stops_on_focus_loss(tmp_path, monkeypatch):
    A = load('tv_apps_home', tmp_path, monkeypatch)
    tv = FakeTV(A, 'hdmi', moves={('d/ug.tab@ForYou', 'right'): 'd/ug.tab@ForYou'}, lose_focus_after=1)
    rc, res = run_apps(A, tv, tmp_path)
    assert rc == 1 and res['ok'] is False and tv.sent == ['home', 'right']    # no key after the focus loss


def test_stops_when_tv_off(tmp_path, monkeypatch):
    A = load('tv_apps_home', tmp_path, monkeypatch)
    tv = FakeTV(A, 'hdmi', power='lcdoff')
    rc, res = run_apps(A, tv, tmp_path)
    assert rc == 1 and tv.sent == [] and res['keys'] == []


def test_only_allowed_keys(tmp_path, monkeypatch):
    A = load('tv_apps_home', tmp_path, monkeypatch)
    assert set(A.KEYSYMS) == {'home', 'right', 'up'}
    with pytest.raises(ValueError):
        A.Run(BOOT, tmp_path, shell=lambda c: '').key('enter', 'x')


GOOD = """QD_TCON_POWER_CYCLE_ONCE_V1
ARCH=Arm
PTR_BYTES=4
STRUCT_BYTES=16
ENDIAN_LITTLE=1
OPERATION_OFFSET=0
MODE_OFFSET=4
RESERVED0_OFFSET=8
RESERVED1_OFFSET=12
ARGUMENT_COUNT=0
UID=0
EUID=0
PID_LIBC=4242
PID_SYSCALL=4242
DEVICE=/dev/tztv_tcon
OPEN_FLAGS=0x80002
IOCTL_REQUEST=0xc010749f
OPERATION_DECIMAL=41
MODE_DECIMAL=2
PAYLOAD_BEFORE=00000029,00000002,00000000,00000000
OPEN_RETURN=7
OPEN_ERRNO=0
IOCTL_RETURN=0
IOCTL_ERRNO=0
PAYLOAD_AFTER=00000029,00000002,00000000,00000000
CLOSE_RETURN=0
CLOSE_ERRNO=0
CLASSIFICATION=kernel_return_zero_only
POWER_ACTION_ACKNOWLEDGED=0
RECOVERY_INFERRED=0
PHYSICAL_STATE_INFERRED=0
POWER_CYCLE_REQUEST_COMPLETE
"""


def test_power_cycle_parser(tmp_path, monkeypatch):
    P = load('tcon_power_cycle', tmp_path, monkeypatch)
    assert P.parse_helper(GOOD)['OPEN_RETURN'] == '7'
    for bad in (GOOD.replace('MODE_DECIMAL=2', 'MODE_DECIMAL=3'), GOOD.replace('IOCTL_RETURN=0', 'IOCTL_RETURN=-1'),
                GOOD.replace('PID_SYSCALL=4242', 'PID_SYSCALL=1'), GOOD.replace('POWER_CYCLE_REQUEST_COMPLETE\n', ''),
                GOOD.replace('UID=0\n', 'UID=0\nUID=0\n', 1), 'QD_TCON_POWER_CYCLE_ONCE_V1\nREFUSED_ARCH_ABI\n'):
        with pytest.raises(P.ContractError):
            P.parse_helper(bad)


def test_power_cycle_dry_and_guards(tmp_path, monkeypatch, capsys):
    P = load('tcon_power_cycle', tmp_path, monkeypatch)
    assert P.main([]) == 0 and json.loads(capsys.readouterr().out)['tv_contact'] is False
    with pytest.raises(P.ContractError):
        P.main(['--run'])                                   # no --output
    with pytest.raises(P.ContractError):
        P.main(['--run', '--output', 'relative.json'])


def test_power_cycle_unbuilt_helper_never_touches_tv(tmp_path, monkeypatch):
    P = load('tcon_power_cycle', tmp_path, monkeypatch)
    monkeypatch.setattr(P, 'HELPER_BIN', tmp_path / 'nobin')
    calls = []
    rec = P.run(tmp_path / 'r.json', shell=lambda *a: calls.append(a) or '', runner=lambda *a, **k: calls.append(a))
    assert rec['accepted'] is False and 'not built' in rec['error'] and calls == []
