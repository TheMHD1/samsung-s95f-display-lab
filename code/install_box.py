#!/usr/bin/env python3
"""Install / remove / inspect the box-side parts (CoreELEC): relay, HDR shader override, 4K GUI setting.

  python3 install_box.py install [--no-shader] [--restart-kodi]
  python3 install_box.py status
  python3 install_box.py uninstall

What `install` does (all under /storage, nothing in the read-only system image):
  1. sets Kodi's GUI to native 4K (coreelec.amlogic.disableguiscaling = true) - required for a pixel-exact layer
  2. uploads relay.py + relay.json + linefix-relay.service and enables it
  3. (HDR) downloads the box's OWN stock gles_gui_composite.frag, applies box/shaders/gles_gui_composite.linefix.patch
     to it with `patch`, writes the shader window from config, uploads it + the stock md5 (guard) + shader-mount.sh +
     linefix-shaders.service and enables it. If the patch does not apply cleanly, the HDR part is skipped.
     The shader is only active after the next Kodi start (--restart-kodi, or reboot the box).
Then run `python3 linefix_skin.py install` (skin layer + profiles) and `python3 keeper.py` (optional supervisor).
"""
import argparse, json, os, re, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lfconfig as C

BOX = os.path.join(C.HERE, 'box')
STOCK = '/usr/share/kodi/system/shaders/GLES/2.0/gles_gui_composite.frag'
UNITS = '/storage/.config/system.d'


def set_4k_gui():
    out = C.rpc('Settings.SetSettingValue', {'setting': 'coreelec.amlogic.disableguiscaling', 'value': True})
    print('4K GUI (disableguiscaling=true):', 'ok' if '"result":true' in out.replace(' ', '') else out.strip()[:200])


def stock_shader_text():
    """Read the stock shader even if our override is already bind-mounted over it."""
    out = C.ssh(f'if mountpoint -q /usr/share/kodi/system/shaders; then '
                f'  mkdir -p /tmp/lf-ro && mount --bind /usr/share/kodi /tmp/lf-ro 2>/dev/null; '
                f'  cat /tmp/lf-ro/system/shaders/GLES/2.0/gles_gui_composite.frag; umount /tmp/lf-ro 2>/dev/null; '
                f'else cat {STOCK}; fi', timeout=30)
    return out


def build_shader():
    """-> (patched text, stock md5) or (None, reason)."""
    stock = stock_shader_text()
    if 'gl_FragColor' not in stock:
        return None, 'could not read the stock shader (is this a GLES CoreELEC build with HDR GUI compositing?)'
    if 'LINEFIX v2' in stock:
        return None, 'stock shader read back already patched - unmount the override first (uninstall), then retry'
    with tempfile.TemporaryDirectory() as td:
        f = os.path.join(td, 'gles_gui_composite.frag')
        open(f, 'w').write(stock)
        p = subprocess.run(['patch', '--no-backup-if-mismatch', '-s', f, os.path.join(BOX, 'shaders', 'gles_gui_composite.linefix.patch')],
                           capture_output=True, text=True)
        if p.returncode != 0:
            return None, 'patch does not apply to this Kodi version:\n' + p.stdout + p.stderr
        text = open(f).read()
    sh = C.CFG['shader']; W = C.CFG['line'].get('panel_width', 3840)
    text = re.sub(r'#define LF_COL_MIN [0-9.]+', f'#define LF_COL_MIN {float(sh["col_min"]):.1f}', text)
    text = re.sub(r'#define LF_COL_MAX [0-9.]+', f'#define LF_COL_MAX {float(sh["col_max"]):.1f}', text)
    text = re.sub(r'#define LF_PANEL_W [0-9.]+', f'#define LF_PANEL_W {float(W):.1f}', text)
    import hashlib
    return text, hashlib.md5(stock.encode()).hexdigest()


def install(args):
    C.ssh(f'mkdir -p {C.D} {UNITS}', check=True)
    set_4k_gui()
    os.makedirs(C.STAGE, exist_ok=True)
    rj = os.path.join(C.STAGE, 'relay.json'); json.dump(C.CFG['relay'], open(rj, 'w'), indent=1)
    C.scp([os.path.join(BOX, 'relay.py'), rj, os.path.join(BOX, 'shader-mount.sh')], C.D + '/')
    C.scp([os.path.join(BOX, 'linefix-relay.service'), os.path.join(BOX, 'linefix-shaders.service')], UNITS + '/')
    C.ssh('systemctl daemon-reload; systemctl enable linefix-relay; systemctl restart linefix-relay', check=True)
    print('relay installed and running (curl http://<BOX_IP>:%d/p from an allowed address)' % C.CFG['relay'].get('port', 8790))
    if args.no_shader:
        C.ssh('systemctl disable linefix-shaders 2>/dev/null; true'); print('HDR shader: skipped (--no-shader)'); return
    text, md5 = build_shader()
    if text is None:
        print('HDR shader NOT installed:', md5); return
    f = os.path.join(C.STAGE, 'gles_gui_composite.linefix.frag'); open(f, 'w').write(text)
    m = os.path.join(C.STAGE, 'shader-orig.md5'); open(m, 'w').write(md5 + '\n')
    C.scp([f, m], C.D + '/')
    C.ssh('systemctl daemon-reload; systemctl enable linefix-shaders', check=True)
    print(f'HDR shader installed (guard md5 {md5}); active after the next Kodi start')
    if args.restart_kodi:
        C.ssh('systemctl stop kodi; systemctl restart linefix-shaders; systemctl start kodi', timeout=90)
        print('Kodi restarted; mount status:', C.ssh(f'cat {C.D}/shader-mount.status').strip())


def status(_):
    print(C.ssh(f'echo "relay:   $(systemctl is-active linefix-relay)"; echo "shaders: $(systemctl is-active linefix-shaders)"; '
                f'echo "mount:   $(cat {C.D}/shader-mount.status 2>/dev/null)"; '
                f'echo "profiles: $(cat {C.D}/profiles.json 2>/dev/null)"; '
                f'test -f {C.D}/on && echo "layer flag: on" || echo "layer flag: off"; '
                f'test -f {C.D}/profile.lock && echo "CALIBRATION LOCK present"; '
                f'echo "output: $(cat /sys/class/display/mode)"; '
                f'grep -o "disableguiscaling\\">[a-z]*" /storage/.kodi/userdata/guisettings.xml; '
                f'echo; curl -s -m 2 127.0.0.1:{C.CFG["relay"].get("port", 8790)}/p'))


def uninstall(_):
    from linefix_skin import skin_file
    C.ssh(f'rm -f {C.D}/on; kodi-send --action="ClearProperty(linefix_on,Home)" >/dev/null; '
          f'systemctl disable --now linefix-relay linefix-shaders; umount /usr/share/kodi/system/shaders 2>/dev/null; '
          f'rm -f {UNITS}/linefix-relay.service {UNITS}/linefix-shaders.service {skin_file()}; systemctl daemon-reload; '
          f'rm -rf {C.D}', timeout=60)
    print('removed. Restart Kodi (systemctl restart kodi) to drop the shader override and the skin dialog from memory.\n'
          'Optional: set Settings > System > Display GUI scaling back (coreelec.amlogic.disableguiscaling=false).')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['install', 'status', 'uninstall'])
    ap.add_argument('--no-shader', action='store_true', help='SDR only; do not install the HDR shader override')
    ap.add_argument('--restart-kodi', action='store_true', help='restart Kodi so the shader override takes effect now')
    a = ap.parse_args()
    {'install': install, 'status': status, 'uninstall': uninstall}[a.cmd](a)
