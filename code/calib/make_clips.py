#!/usr/bin/env python3
"""Make the calibration test clips (4K HEVC 10-bit, static, looped by Kodi) and upload them to the box.

  make_clips.py sdr          grey 8..102 at 24 fps + grey 26/51 at 60 fps (f60) + red/green/blue 26/51/102
  make_clips.py hdr          HDR10 (PQ, BT.2020) grey at 0.5/2/5/15/50/100/200 nits
  make_clips.py ruler        column ruler around the line, to find C0..C1 (see README step 1)
  make_clips.py marker --col N   one 1-pixel black column at panel column N in a dim grey window
  options: --no-upload, --seconds S

SAFETY: every clip is a WINDOW around the line on a black screen (config clips.window_half_width / window_rows),
never a bright full-screen field; the brightest SDR level used for calibration is 102/255 and HDR 200 nits.
Levels are 8-bit full-range codes as you would pick in an image editor (grey 51 = 20 %), encoded as limited-range
10-bit video (Y = 64 + 876 * code/255). HDR levels are absolute luminance through the PQ curve.
"""
import argparse, os, subprocess, sys
import numpy as np
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lfconfig as C
from lfcal import pq

W, H = 3840, 2160
OUT = os.path.join(HERE, 'clips')


def ycbcr10(rgb, matrix):
    """R'G'B' 0..1 -> limited-range 10-bit Y, Cb, Cr."""
    kr, kb = (0.2126, 0.0722) if matrix == 'bt709' else (0.2627, 0.0593)
    r, g, b = rgb; y = kr * r + (1 - kr - kb) * g + kb * b
    cb = (b - y) / (2 * (1 - kb)); cr = (r - y) / (2 * (1 - kr))
    return round(64 + 876 * y), round(512 + 896 * cb), round(512 + 896 * cr)


def frame(rgb, matrix, ruler=False, marker=None):
    ln = C.CFG['line']; cl = C.CFG['clips']
    ref = ln['ref_col']; hw = cl['window_half_width']; r0, r1 = cl['window_rows']
    x0, x1 = (ref - hw) // 2 * 2, (ref + hw) // 2 * 2         # even edges (4:2:0 chroma)
    Y = np.full((H, W), 64, np.uint16); U = np.full((H // 2, W // 2), 512, np.uint16); V = U.copy()
    y, cb, cr = ycbcr10(rgb, matrix)
    Y[r0:r1, x0:x1] = y; U[r0 // 2:r1 // 2, x0 // 2:x1 // 2] = cb; V[r0 // 2:r1 // 2, x0 // 2:x1 // 2] = cr
    if ruler:                                                  # black tick every 10 columns, longer every 50 / 100
        for c in range(x0 - x0 % 10 + 10, x1, 10):
            top = r0 + (0 if c % 100 == 0 else 120 if c % 50 == 0 else 240)
            Y[top:r1 - (0 if c % 100 == 0 else 120 if c % 50 == 0 else 240), c] = 64
        _labels(Y, x0, x1, r0)
    if marker is not None:
        Y[r0:r1, marker] = 64
    return Y.tobytes() + U.tobytes() + V.tobytes()


def _labels(Y, x0, x1, r0):
    """Column numbers above every 100-column tick (needs Pillow; skipped if unavailable)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        try:
            font = ImageFont.load_default(size=36)
        except TypeError:
            font = ImageFont.load_default()
        for c in range(x0 - x0 % 100 + 100, x1, 100):
            im = Image.new('L', (120, 44), 0); ImageDraw.Draw(im).text((2, 2), str(c), fill=255, font=font)
            m = np.array(im) > 128
            ys, xs = slice(r0 - 50, r0 - 6), slice(c - 4, c + 116)
            Y[ys, xs][m[:, :Y[ys, xs].shape[1]]] = 64 + 876 * 60 // 255
    except ImportError:
        pass


def encode(name, data, fps, hdr, seconds, upload):
    os.makedirs(OUT, exist_ok=True)
    raw = os.path.join(OUT, name + '.yuv'); open(raw, 'wb').write(data)
    if hdr:
        xp = ('colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:range=limited:hdr10=1:repeat-headers=1:'
              'master-display=G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1):max-cll=1000,400')
        tags = ['-color_primaries', 'bt2020', '-color_trc', 'smpte2084', '-colorspace', 'bt2020nc']
    else:
        xp = 'colorprim=bt709:transfer=bt709:colormatrix=bt709:range=limited:repeat-headers=1'
        tags = ['-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709']
    out = os.path.join(OUT, name + '.mp4')
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'yuv420p10le',
                    '-s', f'{W}x{H}', '-r', str(fps), '-stream_loop', '-1', '-i', raw, '-t', str(seconds),
                    '-c:v', 'libx265', '-preset', 'ultrafast', '-x265-params', f'lossless=1:keyint={fps * 10}:log-level=error:{xp}',
                    '-pix_fmt', 'yuv420p10le', '-color_range', 'tv', *tags, '-tag:v', 'hvc1', out], check=True)
    os.remove(raw)
    if upload:
        C.ssh(f"mkdir -p {C.CFG['clips']['box_dir']}")
        C.scp(out, C.CFG['clips']['box_dir'] + '/')
    print(out, flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('set', choices=['sdr', 'hdr', 'ruler', 'marker'])
    ap.add_argument('--col', type=int, help='marker column')
    ap.add_argument('--seconds', type=int, default=None)
    ap.add_argument('--no-upload', action='store_true')
    a = ap.parse_args()
    sec = a.seconds or C.CFG['clips'].get('seconds', 30); up = not a.no_upload
    if a.set == 'sdr':
        for L in (8, 13, 20, 26, 32, 51, 77, 102):
            encode(f'grey{L}', frame((L / 255,) * 3, 'bt709'), 24, False, sec, up)
        for L in (26, 51):
            encode(f'grey{L}f60', frame((L / 255,) * 3, 'bt709'), 60, False, sec, up)
        for fam, k in (('red', 0), ('green', 1), ('blue', 2)):
            for L in (26, 51, 102):
                rgb = [0.0, 0.0, 0.0]; rgb[k] = L / 255
                encode(f'{fam}{L}', frame(rgb, 'bt709'), 24, False, sec, up)
    elif a.set == 'hdr':
        for tag, n in (('0p5', 0.5), ('2', 2), ('5', 5), ('15', 15), ('50', 50), ('100', 100), ('200', 200)):
            encode(f'hdr{tag}', frame((pq(n),) * 3, 'bt2020'), 24, True, sec, up)
    elif a.set == 'ruler':
        encode('ruler', frame((26 / 255,) * 3, 'bt709', ruler=True), 24, False, sec, up)
    else:
        if a.col is None:
            ap.error('marker needs --col')
        encode(f'marker{a.col}', frame((26 / 255,) * 3, 'bt709', marker=a.col), 24, False, sec, up)


if __name__ == '__main__':
    main()
