#!/usr/bin/env python3
"""On-demand S0 bake via the TV's own Screen Optimization off-sensing (Claude 2026-11-19, v2 after final-reviewer).
deviced RequestOffSensing(int32 0) = the stock Screen Optimization "Start Now" call (userscan/REPORT-full.md): TV on ->
standby with display off -> mode-3 QFS scan -> TV turns itself back on (reboot type 2).
TV-side waiter: after the TV reports standby, every helper run first waits for the controller (USB 7-1) to power OFF and
then lets the proven `TconDump --armwait` write when it powers back ON (the scan wake), exactly like the standby route.
If the controller never power-cycles, nothing is written (the run is an unarmed observation). No re-run after any write.
Watcher: paused just before the request, released at the scan end, at TV-on, at the first channel error, or on exit.
Usage: bake_now.py POKES [--dry]   (--dry = stage + start monitors only; no request, no helper)"""
import base64, os, pathlib, re, secrets, signal, subprocess, sys, time
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent)); import config as C; C.ensure_dirs(); LOG = C.WORK / 'bake_now.log'
# CONSULT-20A §3 (2026-11-20): on-demand runs only inside config tv.bake_window (S95F: 10:30..01:15 TV local, after 2 dark
# QFS returns at 02:03 / 02:53 local). Keep a window that is proven on YOUR TV.
def _in_window():
    return C.in_bake_window()
if not _in_window() and '--dry' not in sys.argv: print(f'outside the on-demand bake window {C.window_text()} (CONSULT-20A); not baking'); sys.exit(2)
def log(m):
    with LOG.open('a') as f: f.write(time.strftime('%FT%TZ ', time.gmtime()) + m + '\n')
    print(m, flush=True)
for cp in pathlib.Path('/proc').glob('[0-9]*/cmdline'):
    if cp.parent.name == str(os.getpid()): continue
    try: c = cp.read_bytes().split(b'\0')
    except OSError: continue
    if any(os.path.basename(x) in (b'arm_wake.py', b'bake_now.py', b's0_nightly.py') for x in c[:3]):
        print(f'another arm tool is running (PID {cp.parent.name}); stop it first'); sys.exit(2)
for unit in ('s95f-arm-keep', 's95f-arm-bake2', 's0-nightly'):
    if subprocess.run(['systemctl', '--user', 'is-active', unit], capture_output=True, text=True).stdout.strip() in ('active', 'activating'):
        print(f'{unit} is active; stop it first'); sys.exit(2)
pokes = sys.argv[1]; dry = '--dry' in sys.argv
for item in pokes.split(','):                                  # S0 lanes 600-679 only, x0.65..x1.00, stock pre-value
    ad, old, new = (int(v, 16) for v in item.split(':'))
    lane = (ad - 0x58691000) // 4; lo, hi = new & 0xFFFF, new >> 16
    ok = ad % 4 == 0 and 600 <= lane < 680 and old == 0x40CA40CA and 0x2A1C <= lo <= 0x40CA and 0x2A1C <= hi <= 0x40CA   # floor x0.65
    ok = ok and (lo == hi or 626 <= lane <= 632 or (lane == 640 and min(lo, hi) >= 0x4000))   # per-column halves: band lanes 626-632; lane 640 rider only
    if not ok: print(f'poke outside bounds: {item}'); sys.exit(2)       # explicit (asserts vanish under python -O)
src = (HERE / 'tvdump.py').read_text().rsplit('main()', 1)[0]; g = {'__file__': str(HERE / 'tvdump.py')}; av = sys.argv
try: sys.argv = av[:1]; exec(compile(src, str(HERE / 'tvdump.py'), 'exec'), g)
finally: sys.argv = av
root, PAUSE, BIN = g['root'], g['PAUSE'], g['BIN']
D = ('dbus-send --system --print-reply --dest=org.tizen.system.deviced /Org/Tizen/System/DeviceD/Display '
     'org.tizen.system.deviced.display.GetPowerState 2>/dev/null | tail -1')
REQ = ('dbus-send --system --print-reply --dest=org.tizen.system.deviced /Org/Tizen/System/DeviceD/Display '
       'org.tizen.system.deviced.display.RequestOffSensing int32:0 2>&1; true')
USB = '/sys/bus/usb/devices/7-1'
def power():
    o = root(D, 20)
    return 'standby' if ('standby' in o or 'lowpower' in o) else ('on' if 'string' in o else 'unknown')
paused = False
def unpause(why):
    global paused
    if paused:
        PAUSE.unlink(missing_ok=True); paused = False; log(f'watcher unpaused ({why})')
signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(143)))
signal.signal(signal.SIGHUP, lambda s, f: (_ for _ in ()).throw(SystemExit(129)))
stage = f'/tmp/claude-bn-{secrets.token_hex(6)}'; seen = set(); staged = False
def pull():
    """Fetch the TV timeline and helper log separately; log every new line once. Returns (timeline, armlog, new_lines)."""
    txt = root(f'cat {stage}/timeline.log 2>/dev/null; echo @@ARM@@; grep -v GC_INFO {stage}/arm.log 2>/dev/null; true', 30)
    tl, _, al = txt.partition('@@ARM@@'); new = []
    for line in (tl + '\n' + al).splitlines():
        if line.strip() and line not in seen: seen.add(line); new.append(line); log('TV ' + line)
    return tl, al, new
log(f'bake_now start pokes={pokes} dry={dry}')
if power() != 'on': log('TV not on; RequestOffSensing needs power state normal'); sys.exit(1)
try:
    try:
        root(f'umask 077; mkdir {stage}'); staged = True
        for f in ('TconDump.dll', 'TconDump.runtimeconfig.json', 'TconDump.deps.json'):
            b = base64.b64encode((BIN / f).read_bytes()).decode()
            for k in range(0, len(b), 4500): root(f"printf %s '{b[k:k+4500]}' >> {stage}/{f}.b64")
            root(f'base64 -d {stage}/{f}.b64 > {stage}/{f}; rm {stage}/{f}.b64')
        T = f'{stage}/timeline.log'
        dog = (f"echo $$ > {stage}/dog.pid; while true; do if {D} | grep -q -e standby -e lowpower; then touch {stage}/arm.log.standby; "
               f"else rm -f {stage}/arm.log.standby; echo \"$(date +%T.%N) dog: TV left standby\" >> {T}; "
               f"pkill -f \"[T]conDump.dll --armwait\"; break; fi; sleep 0.5; done")
        run = ("echo dry >> timeline.log" if dry else
               # each run: wait for the controller to power OFF, then the helper waits for it to come back ON (scan wake);
               # no run after any write; the dog removes the flag (and kills the helper) when the TV leaves standby
               f"k=0; lim=6000; while [ $k -lt 3 ] && [ -e arm.log.standby ] && ! grep -q -e ' write ' -e 'usb present' arm.log 2>/dev/null; do k=$((k+1)); "
               f"echo \"$(date +%T.%N) waiter: run $k waits for controller OFF\" >> timeline.log; "
               f"j=0; late=0; while [ -e arm.log.standby ] && test -e {USB}; do j=$((j+1)); if [ $j -gt $lim ]; then late=1; break; fi; sleep 0.05; done; "
               f"if [ $late = 1 ]; then echo \"$(date +%T.%N) waiter: controller still up ~300 s after standby; not arming\" >> timeline.log; break; fi; "
               f"lim=$((lim-j)); [ -e arm.log.standby ] || break; "
               f"echo \"$(date +%T.%N) waiter: controller OFF, helper armed\" >> timeline.log; "
               f"/usr/bin/dotnet TconDump.dll --armwait {stage}/arm.log {pokes} 1500 600 >> {stage}/n.out 2>&1 < /dev/null; sleep 1; done; "
               f"echo \"$(date +%T.%N) waiter: done\" >> timeline.log")
        waiter = (f"cd {stage}; echo $$ > waiter.pid; n=0; while ! {D} | grep -q -e standby -e lowpower; do sleep 0.2; n=$((n+1)); "
                  f"if [ $n -gt 1500 ]; then echo \"$(date +%T.%N) waiter: no standby in 300 s\" >> timeline.log; exit 0; fi; done; "
                  f"echo \"$(date +%T.%N) waiter: standby\" >> timeline.log; touch arm.log.standby; "
                  f"setsid nohup sh -c \"$(cat dog.sh)\" > /dev/null 2>&1 < /dev/null & " + run)
        usbmon = (f"cd {stage}; echo $$ > usbmon.pid; p=x; i=0; while [ $i -lt 12000 ]; do if test -e {USB}; then u=UP; else u=OFF; fi; "
                  f"if [ $u != $p ]; then echo \"$(date +%T.%N) usb $u\" >> timeline.log; p=$u; fi; i=$((i+1)); sleep 0.2; done")
        for name, body in (('dog.sh', dog), ('waiter.sh', waiter), ('usbmon.sh', usbmon)):
            root(f"cd {stage}; echo {base64.b64encode(body.encode()).decode()} | base64 -d > {name}", 20)
        root(f"cd {stage}; setsid nohup sh -c \"$(cat usbmon.sh)\" > /dev/null 2>&1 < /dev/null & "
             f"setsid nohup sh -c \"$(cat waiter.sh)\" > /dev/null 2>&1 < /dev/null & echo staged", 20)
        log(f'staged {stage}')
        if dry:
            time.sleep(3); pull(); log('dry: pids ' + root(f'cat {stage}/waiter.pid {stage}/usbmon.pid 2>/dev/null | tr "\\n" " "; true', 20).strip()); sys.exit(0)
        PAUSE.touch(); paused = True; log('watcher paused before the request')
        r = root(REQ, 30); log(f'RequestOffSensing(0) -> {r.strip()[-200:]!r}')
        m = re.search(r'int32 (-?\d+)', r)
        if 'method return' not in r or not m or m[1] != '0':
            log(f'request not accepted (reply value {m[1] if m else None}); aborting'); sys.exit(3)
        t_req = time.time(); seen_sb = progressed = False
        while time.time() - t_req < 45 * 60:                 # supervise
            time.sleep(3)
            try:
                p = power(); tl, al, new = pull()
            except Exception as e:
                log(f'supervise error {e}'); unpause('channel error'); continue
            if 'rec 0008' in al: progressed = True
            if p == 'standby' and not seen_sb: seen_sb = True; log('TV in standby')
            if progressed and ('exit rc=' in al.rsplit('rec 0008', 1)[-1] or any('usb OFF' in l for l in new)):
                unpause('scan ended')
            if seen_sb and p == 'on': unpause('TV back on'); log('TV back on'); break
            if not seen_sb and time.time() - t_req > 300: log('TV never reached standby within 300 s'); break
            if 'waiter: done' in tl and not paused and p == 'on': break
    finally:
        unpause('exit')
finally:
    if staged:
        try:
            tl, al, _ = pull(); (C.CAPTURES / f'bake_now-{int(time.time())}.log').write_text(tl + '\n----\n' + al)
            root(f"for f in waiter usbmon dog; do kill $(cat {stage}/$f.pid 2>/dev/null) 2>/dev/null; done; pkill -f '[T]conDump.dll --armwait'; "
                 f"sleep 1; rm -rf {stage}; true", 20)
        except Exception as e: log(f'cleanup error {e} (stage {stage} may remain; /tmp is cleared at TV reboot)')
    w = sorted(l for l in seen if ' write ' in l)
    log(('writes: ' + ' | '.join(w)) if w else 'no writes'); log('bake_now end')
