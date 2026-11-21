"""Offline checks for the public lane-mask watcher port (no TV, no network). Run: python3 -m pytest -q"""
import importlib, json, os, pathlib, sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent


@pytest.fixture()
def W(tmp_path, monkeypatch):
    cfg = tmp_path / 'kit.json'
    cfg.write_text(json.dumps({'work_dir': str(tmp_path / 'work'), 'watcher': {'enabled': True, 'dir': str(tmp_path / 'w')}}))
    monkeypatch.setenv('TCON_KIT_CONFIG', str(cfg))
    monkeypatch.delenv('S95F_WATCHER_CONFIG', raising=False)
    sys.path.insert(0, str(HERE.parents[1])); sys.path.insert(0, str(HERE))
    for m in ('config', 'mask_watcher'):
        sys.modules.pop(m, None)
    mod = importlib.import_module('mask_watcher')
    pathlib.Path(mod.DEFAULTS['runs']).mkdir(parents=True, exist_ok=True)
    return mod


def test_defaults_private_free(W):
    d = W.DEFAULTS
    assert d['ntfy_url'] is None and d['apps_cmd'] is None and d['mode2_cmd'] is None
    assert d['heartbeat_bind'] == '127.0.0.1' and d['heartbeat_port'] is None
    assert all(str(W.C.WATCHER_DIR) in d[k] for k in ('state', 'log', 'runs', 'pause', 'busy'))
    src = (HERE / 'mask_watcher.py').read_text() + (HERE / 'run_on_tv.py').read_text()
    for bad in ('/home/', '/Users/', '192.168.', 'root-access'):
        assert bad not in src


def test_helpers_point_into_kit(W):
    for p in (W.ServerTV.KA, W.ServerTV.KB, W.ServerTV.KB_STARTUP):
        assert p.parent.parent == W.C.HELPERS and p.name == 'bin'
    assert W.ServerTV.RUN == HERE / 'run_on_tv.py'


def test_no_tv_shell_fails_safe(W):
    tv = W.ServerTV(W.DEFAULTS, lambda *a: None)
    assert tv.root('true') is None and 'tv.shell' in tv.last_error
    assert tv.probe() is None


def test_recovery_withheld_when_not_configured(W):
    tv = W.ServerTV(W.DEFAULTS, lambda *a: None)
    assert tv.tv_apps('0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d') == (False, [])      # nothing sent
    assert 'apps_cmd' in tv.last_error
    ok, why = tv.mode2()
    assert ok is False and 'mode2_cmd' in why


def test_unreachable_tv_is_safe(W):
    cfg, err = W.load_cfg()
    assert err is None
    w = W.Watcher(cfg, None)
    w.tv = W.ServerTV(cfg, w.log)
    delay = w.step()
    assert w.phase == 'UNREACHABLE' and delay > 0
