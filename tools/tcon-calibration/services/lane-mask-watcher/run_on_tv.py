#!/usr/bin/env python3
"""Stage a .NET helper on the TV, run it once, fetch receipt/stdout/stderr, clean up.

Usage: run_on_tv.py <bin_dir> <dll_name> <output_dir> -- <helper args...>
The helper args may contain {DEVNUM} and {BOOT}, filled from live sysfs/boot_id.
No retries. Runs every TV command through the kit's configured TV shell (config tv.shell).
"""
import base64, hashlib, json, pathlib, shlex, subprocess, sys, uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import config as C


def root(cmd, timeout=60):
    """-> (exit_code, stdout, stderr) of CMD run as root on the TV (config tv.shell)."""
    assert len(cmd.encode()) <= 8192, 'command too long'
    try:
        return 0, C.tv_root(cmd, timeout), ''
    except RuntimeError as e:
        return 1, '', str(e)
    except subprocess.TimeoutExpired:
        raise SystemExit('TV shell timed out')


def must(cmd, timeout=60):
    rc, out, err = root(cmd, timeout)
    if rc != 0:
        raise SystemExit(f'remote rc={rc}\nstdout={out[-1500:]}\nstderr={err[-1500:]}')
    return out


def main():
    argv = sys.argv[1:]
    sep = argv.index('--')
    bin_dir, dll, out_dir = pathlib.Path(argv[0]), argv[1], pathlib.Path(argv[2])
    helper_args = argv[sep + 1:]
    out_dir.mkdir(parents=True, exist_ok=False)
    files = [p for p in sorted(bin_dir.iterdir()) if p.is_file()]
    import os
    persist = os.environ.get('PERSIST') == '1'
    prefix = os.environ.get('STAGE_PREFIX', '/tmp/tcon-helper-')
    # persistent stage: fixed 32-hex name derived from the helper files' hashes (survives until TV reboot)
    digest = hashlib.sha256(b''.join(hashlib.sha256(f.read_bytes()).digest() for f in files)).hexdigest()[:32]
    stage = prefix + (digest if persist else uuid.uuid4().hex)
    ident = must('cat /proc/sys/kernel/random/boot_id; cat /sys/bus/usb/devices/7-1/devnum').split()
    boot, devnum = ident[0], ident[1]
    (out_dir / 'identity.json').write_text(json.dumps({'boot': boot, 'devnum': devnum, 'stage': stage}))
    want = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    have = {}
    if persist:
        listing = must(f'test -d {stage} && cd {stage} && sha256sum ' + ' '.join(want) + ' 2>/dev/null; true')
        have = {l.split()[1]: l.split()[0] for l in listing.splitlines() if len(l.split()) == 2}
    if not persist or not have:
        must(f'umask 077; rm -rf -- {stage}; mkdir -m 700 {stage}; echo OK')
    try:
        for f in files:
            if have.get(f.name) == want[f.name]:
                continue
            must(f'rm -f -- {stage}/{f.name}; echo OK')
            raw = f.read_bytes(); enc = base64.b64encode(raw).decode(); target = f'{stage}/{f.name}'
            for off in range(0, len(enc), 6000):
                chunk = enc[off:off + 6000]
                must(f'printf %s {shlex.quote(chunk)} | base64 -d >> {target}; echo OK')
            got = must(f'sha256sum {target}').split()[0]
            assert got == hashlib.sha256(raw).hexdigest(), f'hash mismatch {f.name}'
        args = ' '.join(shlex.quote(a.replace('{DEVNUM}', devnum).replace('{BOOT}', boot)) for a in helper_args)
        cmd = (f'cd {stage}; test "$(cat /proc/sys/kernel/random/boot_id)" = {boot}; '
               f'/usr/bin/dotnet {stage}/{dll} {args} > {stage}/out.txt 2> {stage}/err.txt; echo "RC=$?"; '
               f'for r in {stage}/*.json {stage}/receipt* ; do test -f "$r" && echo "FILE=$r"; done; true')
        rc, out, err = root(cmd, 110)
        (out_dir / 'run.txt').write_text(out + '\n--stderr--\n' + err)
        for name in ['out.txt', 'err.txt'] + [l[5:].rsplit('/', 1)[1] for l in out.splitlines() if l.startswith('FILE=')]:
            data = must(f'base64 {stage}/{name}')
            (out_dir / name).write_bytes(base64.b64decode(data))
        print(out)
    finally:
        if persist:
            keep = ' '.join(want)
            print(must(f'cd {stage} && for x in *; do case " {keep} " in *" $x "*) ;; *) rm -f -- "$x";; esac; done; echo OUTPUTS_REMOVED'))
        else:
            print(must(f'rm -rf -- {stage}; test ! -e {stage} && echo STAGE_REMOVED'))


if __name__ == '__main__':
    main()
