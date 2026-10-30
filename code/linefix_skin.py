"""Kodi correction layer: skin dialog XML + strip textures (SDR and HDR v2 parameter block) + installer.

How the layer works (details: docs/KODI-LAYER.md)
- Kodi's GUI must run at native 4K (CoreELEC setting coreelec.amlogic.disableguiscaling = true), so one GUI pixel
  is one panel column. The skin works in 1920x1080 units, so one panel column = 0.5 skin units.
- A dialog window (Custom_<id>_LineFix.xml, no focusable controls -> never takes remote input) is visible while the
  Home window property `linefix_on` is set. It holds:
    * optional full-screen dim rectangles (alpha B) left and right of the line - only if you have a matching global gain
      elsewhere (see docs/METHOD.md; default B = 0),
    * one image = the strip texture over columns C0..C1, path taken from Home property `linefix_strip`.
- Pixel Shift: the whole group slides by `linefix_x` panel columns via instant conditional slide animations.
- HDR: Home property `linefix_hdr` hides the dim rectangles; the HDR strip is a parameter block read by the patched
  GUI composite shader (code/box/shaders/), never shown as pixels.

Profile/state file format (examples/*.json):
  {"B": dim alpha 0..255, "strips": {"<col>": [alpha, R, G, B]}, "hdr": true|absent}
  SDR: alpha 0..255 = how much the video in that column is darkened, R/G/B = PREMULTIPLIED lift (<= alpha), 0..255.
       Result in the column: out = lift + (1 - alpha/255) * video   (8-bit GUI code domain, then Kodi's normal output).
  HDR: same numbers /255 interpreted in the raw PQ signal domain by the shader: out = L + (1 - a) * video.
"""
import hashlib, io, json, os, sys
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lfconfig as C

MAGIC = (165, 90, 60, 195)  # HDR v2 parameter block: red channel of rows 0..3 (must match the shader)


def cols():
    return C.CFG['line']['c0'], C.CFG['line']['c1']


def skin_file():
    s = C.CFG['skin']
    return f"{s['addon_dir']}/{s['xml_dir']}/Custom_{s['window_id']}_LineFix.xml"


def skin_xml(B):
    c0, c1 = cols()
    sh = C.CFG['relay'].get('pixel_shift_max', 30)
    a = f'{B:02X}000000'
    left = c0 / 2; width = (c1 - c0 + 1) / 2; right = (c1 + 1) / 2
    margin = sh / 2 + 10      # dim rectangles extend past the screen edge so a slide never uncovers an edge
    # B == 0: NO dim rectangles at all. Careful: colordiffuse "00000000" is read by Kodi as "no tint" = a WHITE screen.
    dim = (lambda l, w: f'''            <control type="image">
                <visible>String.IsEmpty(Window(Home).Property(linefix_hdr))</visible>
                <left>{l:g}</left><top>0</top><width>{w:g}</width><height>1080</height>
                <aspectratio>stretch</aspectratio><texture colordiffuse="{a}">{C.D}/white.png</texture>
            </control>
''') if B > 0 else (lambda l, w: '')
    anims = '\n'.join(
        f'            <animation effect="slide" end="{x / 2:g},0" time="0" '
        f'condition="String.IsEqual(Window(Home).Property(linefix_x),{x})">Conditional</animation>'
        for x in range(-sh, sh + 1) if x != 0)
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!-- OLED line-fix correction layer. Visible while Home property linefix_on is set.
     Strip texture over panel columns {c0}-{c1} (Home property linefix_strip); optional dim B={B} elsewhere.
     Pixel Shift: Home property linefix_x slides the group by x panel columns, instantly (time=0).
     No focusable controls (never takes remote input). Delete this file to remove the feature. -->
<window type="dialog" id="{C.CFG['skin']['window_id']}">
    <visible>!String.IsEmpty(Window(Home).Property(linefix_on))</visible>
    <zorder>99</zorder>
    <controls>
        <control type="group">
{anims}
{dim(-margin, left + margin)}            <control type="image">
                <left>{left:g}</left><top>0</top><width>{width:g}</width><height>1080</height>
                <aspectratio>stretch</aspectratio><texture>$INFO[Window(Home).Property(linefix_strip)]</texture>
            </control>
{dim(right, 1920 + margin - right)}        </control>
    </controls>
</window>
'''


def strip_png(B, strips):
    """SDR strip: (C1-C0+1) x 4 RGBA, stretched to full height by the skin. Columns without an entry get alpha B
    (= same dim as the rest of the screen). PNG stores STRAIGHT colour, so premultiplied lift is divided by alpha."""
    c0, c1 = cols(); w = c1 - c0 + 1
    img = np.zeros((4, w, 4), np.uint8); img[..., 3] = B
    for c, (a, r, g, b) in strips.items():
        c = int(c)
        if c0 <= c <= c1:
            a = int(round(max(0, min(255, a))))
            img[:, c - c0, :3] = [int(round(min(v, a) * 255 / a)) if a else 0 for v in (r, g, b)]
            img[:, c - c0, 3] = a
    bb = io.BytesIO(); Image.fromarray(img, 'RGBA').save(bb, 'PNG'); return bb.getvalue()


def strip_png_hdr(strips, rows=2160):
    """HDR strip v2 for the patched shader: (C1-C0+1) x 2160 RGBA, fully transparent except the top 4 rows of each
    corrected column, which carry its parameters (opaque):
        row0 (165, a_hi, a_lo)  row1 (90, LR_hi, LR_lo)  row2 (60, LG_hi, LG_lo)  row3 (195, LB_hi, LB_lo)
    16-bit values; a = dim of the video, L = raw PQ lift (both 0..1, stored as value/255 in the profile).
    The shader hides these 4 pixels and corrects the whole column. If this strip is ever shown WITHOUT the shader,
    you only see 4 tiny dots per column at the top edge."""
    c0, c1 = cols(); w = c1 - c0 + 1
    img = np.zeros((rows, w, 4), np.uint8)
    for c, (a, r, g, b) in strips.items():
        c = int(c)
        if not (c0 <= c <= c1) or a <= 0:
            continue
        vals = [a] + [min(v, a) for v in (r, g, b)]
        for k, (m, v) in enumerate(zip(MAGIC, vals)):
            q = int(round(max(0.0, min(255.0, v)) / 255.0 * 65535))
            img[k, c - c0] = (m, q >> 8, q & 255, 255)
    bb = io.BytesIO(); Image.fromarray(img, 'RGBA').save(bb, 'PNG'); return bb.getvalue()


def strip_bytes(st, B=None):
    return strip_png_hdr(st['strips']) if st.get('hdr') else strip_png(int(st['B'] if B is None else B), st['strips'])


def strip_name(png):
    return f"{C.D}/strip-{hashlib.md5(png).hexdigest()[:10]}.png"


def _white():
    os.makedirs(C.STAGE, exist_ok=True)
    p = C.STAGE + '/white.png'
    Image.new('RGBA', (4, 4), (255, 255, 255, 255)).save(p, 'PNG')
    return p


def _upload_skin(xml):
    os.makedirs(C.STAGE, exist_ok=True)
    p = C.STAGE + '/skin.xml'
    open(p, 'w').write(xml)
    C.put_atomic(p, skin_file())
    C.scp(_white(), f'{C.D}/white.png')


def remote_skin_matches(xml):
    return hashlib.md5(xml.encode()).hexdigest() in C.ssh(f'md5sum {skin_file()} 2>/dev/null')


def install(st, reload=None):
    """Calibration install of ONE state: uploads skin + strip, shows it and sets the calibration lock so the relay
    stops switching profiles. reload=None: ReloadSkin only if the XML on the box differs.
    LESSON: a changed skin XML is NOT used by Kodi until ReloadSkin(); a stale in-memory XML silently invalidated
    a whole series of measurements once."""
    B = 0 if st.get('hdr') else int(st['B'])
    xml = skin_xml(B)
    if reload is None:
        reload = not remote_skin_matches(xml)
    png = strip_bytes(st, B); name = strip_name(png)
    os.makedirs(C.STAGE, exist_ok=True)
    p = C.STAGE + '/strip.png'; open(p, 'wb').write(png)
    _upload_skin(xml)
    C.scp(p, name)
    cmd = (f'touch {C.D}/profile.lock; '
           f'kodi-send --action="SetProperty(linefix_strip,{name},Home)" >/dev/null; '
           f'kodi-send --action="{"SetProperty(linefix_hdr,1,Home)" if st.get("hdr") else "ClearProperty(linefix_hdr,Home)"}" >/dev/null; '
           f'keep=$(cat {C.D}/profiles.json 2>/dev/null); for f in {C.D}/strip-*.png; do '
           f'case "$keep" in *"$f"*) ;; *) [ "$f" = {name} ] || rm -f "$f";; esac; done')
    if reload:
        cmd = 'kodi-send --action="ReloadSkin()" >/dev/null; sleep 4; ' + cmd
    C.ssh(cmd, timeout=60)
    return name


def install_profiles(profiles, reload=None):
    """Final install: profiles = {'444': state, '422': state, 'hdr': state (optional)}; all SDR profiles share one B.
    Uploads skin XML + one strip per profile, writes <linefix_dir>/profiles.json and removes the calibration lock;
    the relay on the box then picks the strip by HDMI output format. Returns {name: strip path}."""
    Bs = {int(st['B']) for st in profiles.values() if not st.get('hdr')}
    assert len(Bs) <= 1, f'all SDR profiles need the same B, got {Bs}'
    B = Bs.pop() if Bs else 0
    xml = skin_xml(B)
    if reload is None:
        reload = not remote_skin_matches(xml)
    _upload_skin(xml)
    files, paths = [], {}
    for name, st in profiles.items():
        png = strip_bytes(st, B); path = strip_name(png)
        f = C.STAGE + '/' + os.path.basename(path); open(f, 'wb').write(png); files.append(f)
        paths[name] = path
    pj = C.STAGE + '/profiles.json'; open(pj, 'w').write(json.dumps(paths, sort_keys=True))
    C.scp(files, C.D + '/')
    C.scp(pj, f'{C.D}/profiles.json.tmp')
    keep = ' '.join(paths.values())
    cmd = (f'mv {C.D}/profiles.json.tmp {C.D}/profiles.json; rm -f {C.D}/profile.lock; '
           f'for f in {C.D}/strip-*.png; do case " {keep} " in *" $f "*) ;; *) rm -f "$f";; esac; done')
    if reload:
        cmd = 'kodi-send --action="ReloadSkin()" >/dev/null; sleep 4; ' + cmd
    C.ssh(cmd, timeout=60)
    return paths


def load_profiles():
    base = C.HERE
    return {k: json.load(open(v if os.path.isabs(v) else os.path.join(base, v)))
            for k, v in C.CFG['profiles'].items()
            if not k.startswith('_') and os.path.exists(v if os.path.isabs(v) else os.path.join(base, v))}


def layer_on():
    C.ssh(f'touch {C.D}/on; kodi-send --action="SetProperty(linefix_on,1,Home)" >/dev/null')


def layer_off():
    C.ssh(f'rm -f {C.D}/on; kodi-send --action="ClearProperty(linefix_on,Home)" >/dev/null')


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Install / switch the Kodi line-fix layer')
    ap.add_argument('cmd', choices=['install', 'on', 'off', 'xml'],
                    help='install = upload all profiles from config + turn on; on/off = toggle; xml = print skin XML')
    a = ap.parse_args()
    if a.cmd == 'xml':
        profs = load_profiles()
        print(skin_xml(next((int(s['B']) for s in profs.values() if not s.get('hdr')), 0)))
    elif a.cmd == 'install':
        print(install_profiles(load_profiles())); layer_on()
    elif a.cmd == 'on':
        layer_on()
    else:
        layer_off()
