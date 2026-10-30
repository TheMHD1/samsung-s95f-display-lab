#!/usr/bin/env python3
"""Tethered RAW capture + per-TV-column, per-colour light measurement from the camera's Bayer (CFA) planes.

Runs on the computer the camera is connected to by USB (macOS or Linux). Needs: gphoto2, python3 with numpy + rawpy.
(macOS: `brew install gphoto2`; kill PTPCamera before capturing: `killall PTPCamera`.)

  measure.py --label grey51 --count 1 --shutter 1/4            capture + analyse, print JSON on stdout
  measure.py --label test --files a.ARW b.ARW                     analyse existing RAW files (no capture)

Camera setup (once): M mode, ISO 100, f/5.6-8, RAW only (lossless/uncompressed, 14-bit: NOT the silent/electronic
shutter if that drops the bit depth), stabiliser off, long-exposure NR off, autofocus once then manual focus,
image saved to the computer only. Camera on a tripod, square to the screen, centred on the line at mid-height,
TV columns running VERTICALLY in the image (use --transpose otherwise). Dark room.
Aim for >= 8 samples per TV column in each Bayer plane (we had ~10.4 with a 75 mm lens at ~30 cm).

Method (no demosaicing - it would blur neighbouring subpixels together):
  1. split the RAW into R, G (mean of G1/G2), B half-resolution planes, subtract the black level (and a dark frame);
  2. average the plane over the central rows -> one profile per colour along x;
  3. find the TV column period in G by FFT, then the exact lattice x0 + k*period by peak fitting;
  4. each colour's subpixel sits at its own offset inside a TV pixel (QD-OLED: R/G/B not co-located) -> per-colour
     phase in samples relative to G (--phase-r / --phase-b, measured once; the estimate is printed as phase_est);
  5. integrate each colour over one period centred on its own subpixel position -> light per TV column.
Output JSON: {"shutter", "dir", "frames": [{"cols": {"R": [...], "G": [...], "B": [...]}, "centres": [...],
             "line_col_idx": i, "period": p, "peak": {c: frac of white}, "sat": {c: frac of saturated px},
             "phase_est": {"R": ., "B": .}}]}
"centres" are G centres in plane samples; downstream code maps them to panel columns with a reference shot.
"""
import argparse, glob, json, os, subprocess, sys, time
import numpy as np


def capture(label, count, shutter, outdir):
    os.makedirs(outdir, exist_ok=True)
    if sys.platform == 'darwin':
        subprocess.run(['killall', 'PTPCamera'], capture_output=True)
    if shutter:
        subprocess.run(['gphoto2', '--set-config', f'shutterspeed={shutter}'], check=True, capture_output=True, timeout=60)
    files = []
    for n in range(count):
        base = os.path.join(outdir, f'{label}-{n}-{int(time.time())}')
        subprocess.run(['gphoto2', '--capture-image-and-download', '--force-overwrite', '--filename', base + '.%C'],
                       check=True, capture_output=True, timeout=120)
        files += [f for f in glob.glob(base + '.*') if not f.lower().endswith(('.jpg', '.jpeg'))]
    return files


def planes(path, transpose=False):
    import rawpy
    with rawpy.imread(path) as raw:
        img = raw.raw_image_visible.astype(np.float64)
        cfa = raw.raw_colors_visible
        desc = raw.color_desc.decode()                     # e.g. 'RGBG'
        black = np.array(raw.black_level_per_channel, float)
        white = float(raw.white_level)
    img = img - black[cfa]
    rng = white - black.mean()
    H, W = img.shape
    H2, W2 = H // 2 * 2, W // 2 * 2
    img, cfa = img[:H2, :W2], cfa[:H2, :W2]
    out = {}
    for name in 'RGB':
        idx = [i for i, ch in enumerate(desc) if ch == name]
        acc, n = np.zeros((H2 // 2, W2 // 2)), 0
        for dy in (0, 1):
            for dx in (0, 1):
                if cfa[dy, dx] in idx:
                    acc += img[dy::2, dx::2]; n += 1
        out[name] = acc / max(n, 1)
        if transpose:
            out[name] = out[name].T
    return out, rng


def smooth(x, k):
    k = max(1, int(k)); return np.convolve(x, np.ones(k) / k, 'same')


def fft_period(prof, lo=4.0, hi=40.0):
    x = prof - smooth(prof, 41)
    x = x * np.hanning(len(x))
    f = np.fft.rfftfreq(len(x)); a = np.abs(np.fft.rfft(x))
    ok = (f > 1 / hi) & (f < 1 / lo)
    return 1.0 / f[ok][np.argmax(a[ok])]


def lattice(prof, approx):
    """Fit peak positions x0 + n*step to a periodic profile (period ~approx)."""
    x = prof - smooth(prof, 3 * approx)
    s = smooth(x, max(3, approx // 8))
    peaks = [i for i in range(1, len(s) - 1) if s[i] >= s[i - 1] and s[i] > s[i + 1] and s[i] > 0]
    sel = []
    for i in peaks:
        if sel and i - sel[-1] < 0.6 * approx:
            if s[i] > s[sel[-1]]:
                sel[-1] = i
        else:
            sel.append(i)
    sel = np.array(sel, float)
    # sub-sample peak refinement (parabola through the 3 samples around each peak)
    ref = []
    for i in sel.astype(int):
        if 1 <= i < len(s) - 1:
            den = s[i - 1] - 2 * s[i] + s[i + 1]
            ref.append(i + (0.5 * (s[i - 1] - s[i + 1]) / den if den < 0 else 0.0))
    sel = np.array(ref)
    n = np.round((sel - sel[0]) / approx)
    A = np.vstack([np.ones_like(n), n]).T
    x0, step = np.linalg.lstsq(A, sel, rcond=None)[0]
    return float(x0), float(step)


def integrate(prof, centres, period):
    """Mean of the profile over [c - p/2, c + p/2] with fractional edges (via the cumulative sum)."""
    cum = np.concatenate([[0.0], np.cumsum(prof)])
    xs = np.arange(len(cum)) - 0.5                       # cum[i] = sum of samples < i - 0.5 + 1
    a = np.interp(np.asarray(centres) - period / 2, xs, cum)
    b = np.interp(np.asarray(centres) + period / 2, xs, cum)
    return (b - a) / period


def analyse(path, args):
    pl, rng = planes(path, args.transpose)
    H = pl['G'].shape[0]
    r0, r1 = int(H * args.rows[0]), int(H * args.rows[1])
    prof = {c: pl[c][r0:r1].mean(0) for c in 'RGB'}
    p0 = args.period or fft_period(prof['G'])
    x0, period = lattice(prof['G'], p0)
    m = int(np.ceil(period)) + 3
    k0 = int(np.ceil((m - x0) / period)); k1 = int(np.floor((len(prof['G']) - m - x0) / period))
    centres = x0 + period * np.arange(k0, k1 + 1)
    phase = {'R': args.phase_r, 'G': 0.0, 'B': args.phase_b}
    cols = {c: integrate(prof[c], centres + phase[c], period).tolist() for c in 'RGB'}
    est = {}
    for c in 'RB':                                        # phase estimate: own lattice of this colour vs G
        try:
            xc, _ = lattice(prof[c], period)
            d = (xc - x0) % period
            est[c] = float(d - period if d > period / 2 else d)
        except Exception:
            est[c] = None
    g = np.array(cols['G']); n = len(g)
    mid = slice(int(n * 0.2), int(n * 0.8))
    line_idx = int(np.argmin(g[mid]) + int(n * 0.2))     # darkest column near the image centre = the line
    roi = {c: pl[c][r0:r1] for c in 'RGB'}
    return {'cols': cols, 'centres': centres.tolist(), 'line_col_idx': line_idx, 'period': period,
            'peak': {c: float(np.percentile(roi[c], 99.99) / rng) for c in 'RGB'},
            'sat': {c: float(np.mean(roi[c] >= 0.98 * rng)) for c in 'RGB'},
            'phase_est': est, 'file': os.path.basename(path)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--label', default='shot')
    ap.add_argument('--count', type=int, default=1)
    ap.add_argument('--shutter', default=None, help="gphoto2 shutterspeed value, e.g. 1/4 or 25/10")
    ap.add_argument('--files', nargs='*', help='analyse these RAW files instead of capturing')
    ap.add_argument('--outdir', default=os.path.expanduser('~/linefix-raw'))
    ap.add_argument('--keep', type=int, default=0, help='1 = keep the RAW files (default: deleted after analysis)')
    ap.add_argument('--dark', default=None, help='RAW dark frame (same shutter, TV showing black) to subtract')
    ap.add_argument('--rows', type=float, nargs=2, default=(0.3, 0.7), help='row band (fractions) used for the profile')
    ap.add_argument('--period', type=float, default=None, help='TV column period in plane samples (default: FFT)')
    ap.add_argument('--phase-r', type=float, default=1.96)
    ap.add_argument('--phase-b', type=float, default=-1.49)
    ap.add_argument('--transpose', action='store_true', help='TV columns run horizontally in the image')
    args = ap.parse_args()
    try:
        files = args.files or capture(args.label, args.count, args.shutter, os.path.join(args.outdir, time.strftime('%Y%m%d')))
        dark = None
        if args.dark:                                     # dark frame: subtract its per-column values
            dpl, _ = planes(args.dark, args.transpose)
            H = dpl['G'].shape[0]
            dark = {c: dpl[c][int(H * args.rows[0]):int(H * args.rows[1])].mean(0) for c in 'RGB'}
        frames = []
        for f in files:
            fr = analyse(f, args)
            if dark:
                cen = np.array(fr['centres'])
                ph = {'R': args.phase_r, 'G': 0.0, 'B': args.phase_b}
                for c in 'RGB':
                    fr['cols'][c] = (np.array(fr['cols'][c]) - integrate(dark[c], cen + ph[c], fr['period'])).tolist()
            frames.append(fr)
        if not args.keep and not args.files:
            for f in files:
                os.remove(f)
        print(json.dumps({'shutter': args.shutter, 'dir': args.outdir, 'frames': frames}))
    except Exception as e:
        print(json.dumps({'error': f'{type(e).__name__}: {e}'}))


if __name__ == '__main__':
    main()
