#!/usr/bin/env python3
"""Per-column brightness ratios from ONE photo of a narrow test bar (offline; reads a file, contacts nothing).

A STARTING POINT, not the analysis that produced the published numbers (that ran elsewhere and is not part of this kit).
It assumes:
  * the photo shows the bar from measure/mkclip.py (BAR_COLUMNS panel columns wide, starting at panel column
    FIRST_COLUMN, black elsewhere), with the panel columns roughly vertical in the image (rotate/crop first if not);
  * the camera resolves the panel's column grid: at least ~4 camera pixels per panel column (we used ~13);
  * a linear image: camera RAW (read with rawpy, no gamma, no auto-brightness, no white balance) or a 16-bit linear TIFF.
    8-bit PNG/JPEG are linearised with the sRGB curve, which is only an approximation of what the camera did.
Method:
  1 crop a horizontal strip (ROWS = fraction of the image height) and sum it over rows -> one profile per camera channel;
  2 find the lit bar (first / last pixel above half of the 99th percentile) -> first estimate of the column period;
  3 refine period and offset so the column borders fall on the dark gaps between panel columns (least light on the borders);
  4 integrate each channel over every column cell (fractional pixel edges) -> one value per panel column and channel;
  5 optional 3x3 unmixing (camera RGB -> panel sub-pixel RGB, from single-primary photos, see `mixmatrix`);
  6 locate the darkest 6-column window in G, then ratio = value / median of the healthy columns 14..45 columns away on
    BOTH sides of it (same rule as optical.table). 1.00 = as bright as the healthy neighbours in the same photo.
usage: colratio.py PHOTO [--first-column 1100] [--bar-columns 320] [--rows 0.40,0.60] [--unmix M.json] [--json OUT]
       colratio.py mixmatrix RED_PHOTO GREEN_PHOTO BLUE_PHOTO [--out M.json]   (photos of the xred/xgreen/xblue bars)
"""
import argparse, json, pathlib, sys
import numpy as np

RAW_EXT = {'.arw', '.cr2', '.cr3', '.nef', '.nrw', '.dng', '.raf', '.orf', '.rw2', '.pef', '.srw', '.3fr', '.iiq'}
HEALTHY_GAP = (14, 45)                      # healthy reference: columns 14..45 away from the darkest 6-column window


def load_image(path):
    """-> (H x W x 3 float64 linear image, white level, kind)."""
    path = pathlib.Path(path)
    if path.suffix.lower() in RAW_EXT:
        try: import rawpy
        except ImportError: raise SystemExit('RAW file given but rawpy is not installed (pip install rawpy), or convert to a 16-bit linear TIFF')
        with rawpy.imread(str(path)) as r:
            a = r.postprocess(gamma=(1, 1), no_auto_bright=True, output_bps=16, use_camera_wb=False, use_auto_wb=False,
                              user_wb=[1.0, 1.0, 1.0, 1.0], output_color=rawpy.ColorSpace.raw, user_flip=0)
        return a.astype(np.float64), 65535.0, 'raw'
    from PIL import Image
    im = Image.open(path)
    a = np.asarray(im)
    if a.ndim == 2: a = np.repeat(a[..., None], 3, axis=2)
    a = a[..., :3]
    if a.dtype == np.uint16: return a.astype(np.float64), 65535.0, 'linear16'
    if a.dtype == np.uint8:
        v = a.astype(np.float64) / 255.0
        lin = np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)        # sRGB -> linear (approximation)
        return lin * 65535.0, 65535.0, 'srgb8'
    return a.astype(np.float64), float(np.max(a)) or 1.0, 'float'


def _cum(profile):
    c = np.concatenate([[0.0], np.cumsum(profile)])
    return lambda x: np.interp(x, np.arange(len(c)), c)        # integral of the profile from pixel 0 to x (fractional)


def fit_grid(total, n_cols):
    """-> (offset, period) of the column grid in a 1-D profile of the bar."""
    thr = 0.5 * np.percentile(total, 99)
    lit = np.flatnonzero(total > thr)
    if len(lit) < 2 * n_cols: raise ValueError('bar not found or the camera does not resolve the columns (< 2 px per column)')
    x0, x1 = float(lit[0]), float(lit[-1] + 1)
    p0 = (x1 - x0) / n_cols
    xs = np.arange(len(total), dtype=np.float64)
    best = None
    for p in np.linspace(p0 * 0.98, p0 * 1.02, 81):
        for o in np.linspace(x0 - 0.5 * p, x0 + 0.5 * p, 41):
            edges = o + p * np.arange(1, n_cols)                    # inner borders only (outer ones are on black anyway)
            cost = float(np.interp(edges, xs, total).sum())
            if best is None or cost < best[0]: best = (cost, o, p)
    _, o, p = best
    for p in np.linspace(p * 0.998, p * 1.002, 21):                 # fine pass on the period around the best offset
        for o2 in np.linspace(o - 0.1 * p, o + 0.1 * p, 21):
            edges = o2 + p * np.arange(1, n_cols)
            cost = float(np.interp(edges, xs, total).sum())
            if cost < best[0]: best = (cost, o2, p)
    return best[1], best[2]


def darkest_window(v, width=6, margin=50):
    """Start index of the darkest WIDTH-column window, at least MARGIN columns from both bar ends."""
    n = len(v); lo, hi = min(margin, n // 4), max(min(margin, n // 4) + 1, n - margin - width)
    s = [v[i:i + width].sum() for i in range(lo, hi)]
    return lo + int(np.argmin(s))


def healthy_ref(v, start, width=6, gap=HEALTHY_GAP):
    idx = np.r_[max(0, start - gap[1]):max(0, start - gap[0]), start + width + gap[0]:min(len(v), start + width + gap[1])]
    return float(np.median(v[idx]))


def analyse(img, first_column=1100, bar_columns=320, rows=(0.40, 0.60), unmix=None, white=None):
    """IMG = path or H x W x 3 linear array -> dict with per-column values, ratios and the fitted grid.
    Keys line_col_idx / period / sat / peak / phase_off / centres / cols match what measure/optical.py expects."""
    kind = 'array'
    if not isinstance(img, np.ndarray): img, white, kind = load_image(img)
    white = white or float(np.max(img)) or 1.0
    h = img.shape[0]; r0, r1 = int(rows[0] * h), max(int(rows[0] * h) + 1, int(rows[1] * h))
    crop = img[r0:r1].astype(np.float64)
    prof = crop.sum(axis=0)                                         # W x 3
    o, p = fit_grid(prof.sum(axis=1), bar_columns)
    edges = o + p * np.arange(bar_columns + 1)
    cols = np.empty((3, bar_columns))
    for ch in range(3):
        F = _cum(prof[:, ch]); cols[ch] = np.diff(F(edges))
    if unmix is not None: cols = np.asarray(unmix, float) @ cols     # camera RGB -> panel sub-pixel RGB
    bar = crop[:, max(0, int(edges[0])):int(np.ceil(edges[-1]))]
    s = darkest_window(cols[1])
    ratios = {c: (cols[i] / healthy_ref(cols[i], s)).tolist() for i, c in enumerate('RGB')}
    lum = 0.25 * cols[0] + 0.68 * cols[1] + 0.07 * cols[2]
    return dict(kind=kind, period=float(p), offset=float(o), phase_off=float((o - edges[0]) % p),
                centres=(o + p * (np.arange(bar_columns) + 0.5)).tolist(), first_column=first_column,
                panel_columns=list(range(first_column, first_column + bar_columns)), line_col_idx=int(s),
                line_panel_column=first_column + int(s), sat=float(np.mean(bar >= 0.98 * white)), peak=float(bar.max() / white),
                cols={c: cols[i].tolist() for i, c in enumerate('RGB')}, ratios=ratios,
                lum_ratio=(lum / healthy_ref(lum, s)).tolist())


def mixmatrix(red, green, blue, **kw):
    """Column j = camera R/G/B response to panel primary j on healthy columns (normalised to its own channel) ->
    (mix, unmix = inverse). Use photos of the xred153 / xgreen153 / xblue153 bars at the same exposure settings."""
    M = np.empty((3, 3))
    for j, ph in enumerate((red, green, blue)):
        a = analyse(ph, **kw); c = np.array([a['cols'][k] for k in 'RGB']); s = a['line_col_idx']
        v = np.array([healthy_ref(c[i], s) for i in range(3)]); M[:, j] = v / v[j]
    return M, np.linalg.inv(M)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ['mixmatrix']:
        ap = argparse.ArgumentParser(prog='colratio.py mixmatrix'); ap.add_argument('red'); ap.add_argument('green'); ap.add_argument('blue')
        ap.add_argument('--out'); ap.add_argument('--first-column', type=int, default=1100); ap.add_argument('--bar-columns', type=int, default=320)
        a = ap.parse_args(argv[1:])
        M, U = mixmatrix(a.red, a.green, a.blue, first_column=a.first_column, bar_columns=a.bar_columns)
        out = dict(mix=M.round(4).tolist(), unmix=U.round(5).tolist()); print(json.dumps(out, indent=1))
        if a.out: pathlib.Path(a.out).write_text(json.dumps(out, indent=1))
        return 0
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0]); ap.add_argument('photo')
    ap.add_argument('--first-column', type=int, default=1100); ap.add_argument('--bar-columns', type=int, default=320)
    ap.add_argument('--rows', default='0.40,0.60'); ap.add_argument('--unmix', help='JSON file with "unmix" (from mixmatrix)')
    ap.add_argument('--json', help='write the full result here'); ap.add_argument('--around', type=int, default=8)
    a = ap.parse_args(argv)
    U = json.loads(pathlib.Path(a.unmix).read_text())['unmix'] if a.unmix else None
    r = analyse(a.photo, a.first_column, a.bar_columns, tuple(float(x) for x in a.rows.split(',')), U)
    if a.json: pathlib.Path(a.json).write_text(json.dumps(r))
    s = r['line_col_idx']
    print(f"{r['kind']}  period {r['period']:.3f} px/column  darkest 6-column window starts at panel column {r['line_panel_column']}"
          f"  saturated {100 * r['sat']:.2f} %  peak {r['peak']:.2f}")
    print('panel col     R      G      B    lum')
    for i in range(max(0, s - a.around), min(a.bar_columns, s + 6 + a.around)):
        print(f"{r['panel_columns'][i]:8d}  " + ' '.join(f"{r['ratios'][c][i]:5.2f} " for c in 'RGB') + f" {r['lum_ratio'][i]:5.2f}")
    if r['sat'] > 0.001: print('WARNING: saturated pixels in the bar: shorten the exposure')
    return 0


if __name__ == '__main__':
    sys.exit(main())
