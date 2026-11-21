#!/usr/bin/env python3
"""Put the TV on its own Apps home screen from any source (optional recovery step for the lane-mask watcher).

Why: on the S95F, a faulted controller on the media-player HDMI input kept resetting and the mask could not be
applied; it went on only after the TV showed its own Apps home. The watcher calls this before every controller power
cycle (and runs --check, 0 keys, right before it), and when a Clean controller stays not-ready on an HDMI input.
Configure it as the watcher's `apps_cmd`: ["python3", "-B", "<kit>/services/lane-mask-watcher/recovery/tv_apps_home.py"].

How (stock key events only, through the kit's TV shell, config tv.shell):
  * Every command runs under `test boot_id = <boot>` (the boot the watcher just checked).
  * Home first: unless the home UI (csfs) already has focus with no screensaver, exactly ONE Home key is sent, then
    csfs must be present and focused with no screensaver, or the run stops.
  * Then only the owner-verified paths, one observed step at a time: Live -> Right -> Apps;
    For You -> Right -> (Apps | Live -> Right | For You -> Up, Up, Right, Right). Any other state stops the run.
  * After every navigation key csfs must still have focus, so a key never follows a focus loss (on the S95F,
    keys once went to the HDMI input because the TV viewer had focus).
  * Power: the 'before' and 'after-home' snapshots also read deviced PowerState (lcdon) and ScreenState (1); anything
    else stops the run (the owner turned the TV off).
Bound: 1 Home + 8 navigation keys; only home / right / up. No controller, USB, power, settings or source writes.
Tizen details (verify on your TV): home UI = com.samsung.tv.csfs, focus = column 'O' in `enlightenment_info
-topvwins`, current tab = vconf memory/eden/current_tab, keys via /usr/bin/input_keyevent (optionally pinned by
sha256 with TV_INPUT_KEYEVENT_SHA256).
Modes:
  (default) switch: exit 0 only when the final snapshot shows the Apps tab with csfs present AND focused and no
            screensaver. stdout is always ONE JSON line {"ok", "keys", "tab", "focused", "saver", "error"} (also on
            failure, so the caller knows whether any key was sent); "keys" lists every key attempted, in order.
  --check : one snapshot, 0 keys. exit 0 only when on Apps (same test). Same JSON line, keys [].
"""
import argparse, json, os, pathlib, re, shlex, sys, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import config as C                                     # kit config: tv.shell

CSFS = '/opt/usr/apps/com.samsung.tv.csfs/bin/csfs.dll'
APPS, LIVE, FOR_YOU = 'd/apps.tab', 'd/ug.tab@Live', 'd/ug.tab@ForYou'
KEYSYMS = {'home': 'XF86Home', 'right': 'Right', 'up': 'Up'}   # never wake (VolUp), enter, back, left or down
INPUT_KEYEVENT_SHA256 = os.environ.get('TV_INPUT_KEYEVENT_SHA256') or None
HOME_SETTLE_S = 3
MAX_NAV_KEYS = 8
SHELL_TIMEOUT_S = 45
BOOT_RE = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'


def need(ok, message):
    if not ok:
        raise ValueError(message)


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def tv_shell(cmd):
    try:
        return C.tv_root(cmd, SHELL_TIMEOUT_S)
    except RuntimeError as e:
        raise ValueError(f'TV shell failed: {e}') from None


def csfs_focused(text):
    """True when a topvwins row of the home UI (csfs) carries the focus mark 'O' (column Foc, after L and an optional
    Zone number)."""
    for line in (text or '').splitlines():
        if CSFS not in line:
            continue
        t = line.split()
        if len(t) > 10 and (t[9] == 'O' or (t[10] == 'O' and t[9].isdigit())):
            return True
    return False


def parse_tab(text):
    prefix = 'memory/eden/current_tab, value = '
    for line in (text or '').splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].split(' (', 1)[0]
    return None


def power_script(boot):
    return ('set -eu\n'
            f'test "$(cat /proc/sys/kernel/random/boot_id)" = {boot}\n'
            'dbus-send --system --print-reply --reply-timeout=1500 --dest=org.tizen.system.deviced '
            '/Org/Tizen/System/DeviceD/Display org.tizen.system.deviced.display.GetPowerState\n'
            'dbus-send --system --print-reply --reply-timeout=1500 --dest=org.tizen.system.deviced '
            '/Org/Tizen/System/DeviceD/Display org.tizen.system.deviced.display.GetScreenState\n')


def parse_power(text):
    """PowerState string "lcdon" and ScreenState int32 1."""
    ints = re.findall(r'^\s+int32 ([0-9]+)\s*$', text or '', re.M)
    return 'string "lcdon"' in (text or '') and ints == ['1']


def on_apps(s):
    return (s['cached_current_tab'] == APPS and s['csfs_window_present'] and s['csfs_focused']
            and not s['screensaver_windows_present'])


class Run:
    def __init__(self, boot, out, shell=tv_shell, sleep=time.sleep):
        self.boot, self.out, self.shell, self.sleep = boot, out, shell, sleep
        self.keys, self.nav_keys = [], 0

    def guard(self):
        return f'test "$(cat /proc/sys/kernel/random/boot_id)" = {self.boot}\n'

    def snap(self, phase, power=False, in_nav=False):
        text = self.shell('set -eu\n' + self.guard() + 'cat /proc/sys/kernel/random/boot_id\ncat /proc/uptime\n'
                          'vconftool get memory/eden/current_tab\nenlightenment_info -topvwins\ncat /proc/uptime\n')
        (self.out / (phase + '-snapshot.txt')).write_text(text)
        s = dict(cached_current_tab=parse_tab(text), csfs_window_present=CSFS in text, csfs_focused=csfs_focused(text),
                 screensaver_windows_present='ScreenSaver.dll' in text or 'ScreenSaverContent.dll' in text)
        if power:
            p = self.shell(power_script(self.boot))
            (self.out / (phase + '-power.txt')).write_text(p)
            s['power_on'] = parse_power(p)
        save(self.out / (phase + '-summary.json'), s)
        if power:
            need(s['power_on'], f'TV not on (PowerState/ScreenState) at {phase}; no key sent after it')
        if in_nav:
            need(s['csfs_focused'], f'home UI lost focus during navigation ({phase}); stopped')
        return s

    def key(self, action, label):
        """One stock key down/up pair. Recorded BEFORE it is sent (the caller then counts it as sent)."""
        need(action in KEYSYMS, f'key {action!r} refused')
        self.keys.append(action)
        q = shlex.quote(KEYSYMS[action])
        pin = (f'test "$(sha256sum /usr/bin/input_keyevent | cut -d " " -f1)" = {INPUT_KEYEVENT_SHA256}\n'
               if INPUT_KEYEVENT_SHA256 else '')
        text = self.shell('set -eu\n' + self.guard() + 'test -x /usr/bin/input_keyevent\n' + pin +
                          f'down_status=0\n/usr/bin/input_keyevent {q} down >/dev/null 2>&1 || down_status=$?\n'
                          f'sleep 0.15\nup_status=0\n/usr/bin/input_keyevent {q} up >/dev/null 2>&1 || up_status=$?\n'
                          'printf "LOCAL_KEY_DOWN_EXIT=%s\\n" "$down_status"\nprintf "LOCAL_KEY_UP_EXIT=%s\\n" "$up_status"\n')
        (self.out / f'key-{label}.txt').write_text(text)
        m = re.fullmatch(r'LOCAL_KEY_DOWN_EXIT=([0-9]+)\nLOCAL_KEY_UP_EXIT=([0-9]+)\n?', text.strip() + '\n')
        need(m is not None, 'local key result contract')
        need(m.group(1) == '0' and m.group(2) == '0', 'stock key down/up failed')

    def step(self, action):
        self.nav_keys += 1
        need(self.nav_keys <= MAX_NAV_KEYS, 'navigation key bound')
        label = f'{self.nav_keys:02d}-{action}'
        self.key(action, label)
        return self.snap('after-' + label, in_nav=True)

    def navigate(self, cur):
        """For You -> Live -> Apps along the owner-verified paths only; any other state is terminal."""
        need(not cur['screensaver_windows_present'] and cur['csfs_window_present'] and cur['csfs_focused'],
             'navigation refused: home UI not focused')
        tab = cur['cached_current_tab']
        need(tab in (APPS, LIVE, FOR_YOU), f'navigation refused on an unexpected page ({tab})')
        if tab == APPS:
            return cur
        if tab == LIVE:
            plan = [('right', APPS)]
        else:   # the first Right from For You has two observed valid outcomes: Home content (still For You) or Live
            cur = self.step('right')
            tab = cur['cached_current_tab']
            if tab == APPS:
                return cur
            if tab == LIVE:
                plan = [('right', APPS)]
            elif tab == FOR_YOU:
                plan = [('up', FOR_YOU), ('up', FOR_YOU), ('right', LIVE), ('right', APPS)]
            else:
                raise ValueError('unexpected cached page or focus state; stopped')
        for action, expected in plan:
            cur = self.step(action)
            if cur['cached_current_tab'] == APPS:
                return cur
            need(cur['cached_current_tab'] == expected and not cur['screensaver_windows_present']
                 and cur['csfs_window_present'], 'unexpected cached page or focus state; stopped')
        raise ValueError('bounded navigation plan ended without target')

    def check(self):
        cur = self.snap('check')
        return dict(schema='tv-apps-home-v2', mode='check', ok=on_apps(cur), before=cur, after=cur, keys=[])

    def switch(self):
        cur = self.snap('before', power=True)
        first = dict(cur)
        if not (cur['csfs_focused'] and not cur['screensaver_windows_present']):
            self.key('home', 'home')                     # exactly one Home, never VolUp
            self.sleep(HOME_SETTLE_S)
            cur = self.snap('after-home', power=True)
            need(cur['csfs_focused'] and cur['csfs_window_present'] and not cur['screensaver_windows_present'],
                 'Home key did not bring the TV home screen to the foreground (csfs not focused)')
        if cur['cached_current_tab'] != APPS:
            cur = self.navigate(cur)
        need(on_apps(cur), f'not on Apps afterwards (cached tab {cur["cached_current_tab"]}, csfs focused '
                           f'{cur["csfs_focused"]}, screensaver {cur["screensaver_windows_present"]})')
        return dict(schema='tv-apps-home-v2', mode='switch', ok=True, before=first, after=cur, keys=list(self.keys))


def line(ok, keys, after=None, error=None):
    a = after or {}
    return json.dumps(dict(ok=ok, keys=keys, tab=a.get('cached_current_tab'), focused=a.get('csfs_focused'),
                           saver=a.get('screensaver_windows_present'), error=error), separators=(',', ':'))


def main(argv=None, shell=tv_shell, out=sys.stdout, sleep=time.sleep):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--boot', required=True)
    ap.add_argument('--output', type=pathlib.Path, required=True)
    ap.add_argument('--check', action='store_true', help='one snapshot, 0 keys: exit 0 only when on Apps')
    a = ap.parse_args(argv)
    r = None
    try:
        need(re.fullmatch(BOOT_RE, a.boot) is not None, 'bad --boot')
        need(a.output.is_absolute() and not a.output.exists(), 'fresh absolute --output required')
        a.output.mkdir(parents=True)
        r = Run(a.boot, a.output, shell, sleep)
        res = r.check() if a.check else r.switch()
    except Exception as e:               # keys: exactly those attempted ([] when stopped before any key could go)
        print(line(False, list(r.keys) if r else [], error=f'{type(e).__name__}: {e}'[-300:]), file=out, flush=True)
        raise
    save(a.output / 'apps-result.json', res)
    print(line(res['ok'], res['keys'], res['after']), file=out, flush=True)
    if not res['ok']:
        raise ValueError(f'not on Apps (cached tab {res["after"]["cached_current_tab"]})')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        print(f'Stopped: {type(e).__name__}: {e}', file=sys.stderr)
        sys.exit(1)
