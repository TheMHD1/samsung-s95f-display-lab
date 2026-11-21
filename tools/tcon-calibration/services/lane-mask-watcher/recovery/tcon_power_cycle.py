#!/usr/bin/env python3
"""One stock panel-controller power cycle (TV driver request operation 41, mode 2). Dry by default, never retries.

Optional recovery step for the lane-mask watcher, for a controller that has already faulted (picture off). Configure it
as the watcher's `mode2_cmd`: ["python3", "-B", "<kit>/services/lane-mask-watcher/recovery/tcon_power_cycle.py", "--run"]
(the watcher adds --output <file> and keeps the budgets: 3 per hour, 6 per day, spacing 0 / 90 / 600 s).

What it does: checks the TV's controller device node exists, copies the argument-free helper
tcon/helpers/tcon-power-cycle (build output in its bin/) to the TV with run_on_tv.py, runs it once under the same
boot id, and checks its output line by line against the one fixed schema. The helper opens /dev/tztv_tcon and sends
one ioctl 0xc010749f with the fixed payload 41, 2, 0, 0: the TV's own normal off-then-on sequence for the panel
controller. It has no arguments, retries, loops, protection changes, EEPROM or flash access.
A zero return is NOT proof of recovery (a missing callback can also return zero): the watcher decides from its own
next controller read. Exit 0 only when the helper ran and its output matched exactly.
Usage: tcon_power_cycle.py                       dry: print the plan, no TV contact
       tcon_power_cycle.py --run --output /abs/new-file.json
"""
import argparse, json, os, pathlib, re, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
import config as C                                     # kit config: tv.shell, helper paths

HELPER_BIN = C.HELPERS / 'tcon-power-cycle' / 'bin'
DLL = 'TconPowerCycleOnce.dll'
RUN_ON_TV = HERE.parent / 'run_on_tv.py'
STAGE_PREFIX = '/tmp/tcon-powercycle-'
DEVICE = '/dev/tztv_tcon'
RUN_TIMEOUT_S = 95                                     # < the watcher's MODE2_TIMEOUT_S (110)

FIELDS = {
    'ARCH', 'PTR_BYTES', 'STRUCT_BYTES', 'ENDIAN_LITTLE', 'OPERATION_OFFSET', 'MODE_OFFSET', 'RESERVED0_OFFSET',
    'RESERVED1_OFFSET', 'ARGUMENT_COUNT', 'UID', 'EUID', 'PID_LIBC', 'PID_SYSCALL', 'DEVICE', 'OPEN_FLAGS',
    'IOCTL_REQUEST', 'OPERATION_DECIMAL', 'MODE_DECIMAL', 'PAYLOAD_BEFORE', 'OPEN_RETURN', 'OPEN_ERRNO',
    'IOCTL_RETURN', 'IOCTL_ERRNO', 'PAYLOAD_AFTER', 'CLOSE_RETURN', 'CLOSE_ERRNO', 'CLASSIFICATION',
    'POWER_ACTION_ACKNOWLEDGED', 'RECOVERY_INFERRED', 'PHYSICAL_STATE_INFERRED',
}
FIXED = {
    'ARCH': 'Arm', 'PTR_BYTES': '4', 'STRUCT_BYTES': '16', 'ENDIAN_LITTLE': '1', 'OPERATION_OFFSET': '0',
    'MODE_OFFSET': '4', 'RESERVED0_OFFSET': '8', 'RESERVED1_OFFSET': '12', 'ARGUMENT_COUNT': '0', 'UID': '0',
    'EUID': '0', 'DEVICE': DEVICE, 'OPEN_FLAGS': '0x80002', 'IOCTL_REQUEST': '0xc010749f', 'OPERATION_DECIMAL': '41',
    'MODE_DECIMAL': '2', 'PAYLOAD_BEFORE': '00000029,00000002,00000000,00000000', 'OPEN_ERRNO': '0',
    'IOCTL_RETURN': '0', 'IOCTL_ERRNO': '0', 'PAYLOAD_AFTER': '00000029,00000002,00000000,00000000',
    'CLOSE_RETURN': '0', 'CLOSE_ERRNO': '0', 'CLASSIFICATION': 'kernel_return_zero_only',
    'POWER_ACTION_ACKNOWLEDGED': '0', 'RECOVERY_INFERRED': '0', 'PHYSICAL_STATE_INFERRED': '0',
}


class ContractError(ValueError):
    pass


def need(ok, message):
    if not ok:
        raise ContractError(message)


def parse_helper(text):
    """Helper stdout -> fields. Raises unless it is exactly the one fixed success schema."""
    lines = text.splitlines()
    need(lines[:1] == ['QD_TCON_POWER_CYCLE_ONCE_V1'] and lines[-1:] == ['POWER_CYCLE_REQUEST_COMPLETE'],
         'helper output bounds')
    values = [x for x in lines if '=' in x]
    need([x for x in lines if '=' not in x] == ['QD_TCON_POWER_CYCLE_ONCE_V1', 'POWER_CYCLE_REQUEST_COMPLETE'],
         'unexpected helper status line')
    need(all(x.count('=') == 1 for x in values), 'malformed helper line')
    fields = dict(x.split('=', 1) for x in values)
    need(set(fields) == FIELDS and len(values) == len(FIELDS), 'unknown or duplicate helper field')
    need(all(fields[k] == v for k, v in FIXED.items()), 'fixed schema mismatch')
    need(re.fullmatch(r'[0-9]+', fields['OPEN_RETURN']) is not None, 'device open failed')
    need(re.fullmatch(r'[1-9][0-9]*', fields['PID_LIBC']) is not None and fields['PID_LIBC'] == fields['PID_SYSCALL'],
         'helper pid mismatch')
    return fields


def plan():
    files = sorted(p.name for p in HELPER_BIN.iterdir() if p.is_file()) if HELPER_BIN.is_dir() else []
    return dict(dry_run=True, tv_contact=False, one_shot=True, retry=False, helper_bin=str(HELPER_BIN),
                helper_files=files, helper_built=DLL in files, device=DEVICE, ioctl='0xc010749f',
                payload=['0x00000029', '0x00000002', '0x00000000', '0x00000000'],
                classification='kernel_return_zero_only (not proof of recovery)')


def run(output, shell=C.tv_root, runner=subprocess.run):
    rec = dict(schema='tcon-power-cycle-once-v1', started=time.time(), accepted=False, recovery_inferred=False)
    work = output.with_suffix('.d')
    try:
        need((HELPER_BIN / DLL).is_file(), f'helper not built ({HELPER_BIN / DLL})')
        pre = shell(f'set -eu\ntest -c {DEVICE}\ncat /proc/sys/kernel/random/boot_id\n', 20).split()
        need(len(pre) == 1 and re.fullmatch(r'[0-9a-f-]{36}', pre[0]) is not None, 'preflight (device node / boot id)')
        rec['boot'] = pre[0]
        env = dict(os.environ, STAGE_PREFIX=STAGE_PREFIX)
        p = runner([sys.executable, '-B', str(RUN_ON_TV), str(HELPER_BIN), DLL, str(work), '--'],
                   capture_output=True, text=True, timeout=RUN_TIMEOUT_S, env=env)
        rec['runner_rc'] = p.returncode
        need(p.returncode == 0, 'run_on_tv failed: ' + (p.stderr or p.stdout)[-300:])
        ident = json.loads((work / 'identity.json').read_text())
        need(ident.get('boot') == rec['boot'], 'TV rebooted between preflight and run')
        need(re.search(r'^RC=0$', (work / 'run.txt').read_text(), re.M) is not None, 'helper exit code not 0')
        rec['fields'] = parse_helper((work / 'out.txt').read_text())
        rec['classification'] = 'kernel_return_zero_only'
        rec['accepted'] = True
    except Exception as e:
        rec['error'] = f'{type(e).__name__}: {e}'[-400:]
    rec['finished'] = time.time()
    output.write_text(json.dumps(rec, indent=2, sort_keys=True) + '\n')
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--run', action='store_true', help='live: one power-cycle request (default: dry plan only)')
    ap.add_argument('--output', type=pathlib.Path)
    a = ap.parse_args(argv)
    if not a.run:
        need(a.output is None, '--output only with --run')
        print(json.dumps(plan(), indent=2)); return 0
    need(a.output is not None and a.output.is_absolute() and not a.output.exists()
         and not a.output.with_suffix('.d').exists(), 'live mode needs --output /absolute/new-file.json')
    rec = run(a.output)
    print(json.dumps(dict(result=str(a.output), accepted=rec['accepted'], error=rec.get('error'),
                          recovery_inferred=False), sort_keys=True))
    if not rec['accepted']:
        print('Stopped: ' + rec.get('error', 'not accepted'), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except ContractError as e:
        print(f'Stopped: {e}', file=sys.stderr); sys.exit(2)
