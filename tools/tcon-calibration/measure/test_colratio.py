"""Offline test of colratio.py on a synthetic photo of the test bar (no camera, no TV). pytest -q measure/test_colratio.py"""
import pathlib, sys
import numpy as np, pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import colratio as CR

N, FIRST = 320, 1100
DAMAGE = {155: 0.30, 156: 0.05, 157: 0.50, 158: 0.80, 159: 0.65, 160: 0.90}   # column index in the bar -> relative light


def synth(period=7.3, x0=412.6, width=3200, height=300, gains=(1.0, 0.8, 0.6), damage=DAMAGE, noise=0.002, seed=1):
    """Each panel column = a Gaussian stripe (sigma 0.18 * period) with dark gaps between columns; linear values."""
    rng = np.random.default_rng(seed); x = np.arange(width) + 0.5
    prof = np.zeros((3, width))
    for k in range(N):
        c = x0 + (k + 0.5) * period; f = damage.get(k, 1.0)
        stripe = np.exp(-0.5 * ((x - c) / (0.18 * period)) ** 2)
        for ch in range(3): prof[ch] += gains[ch] * f * stripe
    img = np.repeat(prof.T[None], height, axis=0) * 20000.0
    return img + rng.normal(0, noise * 20000.0, img.shape).clip(0)


def test_period_and_ratios():
    r = CR.analyse(synth(), FIRST, N, white=65535.0)
    assert r['period'] == pytest.approx(7.3, rel=2e-3)
    assert r['line_col_idx'] in range(153, 158)                    # darkest 6-column window found on the band
    for k, f in DAMAGE.items():
        for c in 'RGB': assert r['ratios'][c][k] == pytest.approx(f, abs=0.03), (k, c)
    healthy = [i for i in range(110, 140)] + [i for i in range(175, 205)]
    for c in 'RGB': assert np.allclose([r['ratios'][c][i] for i in healthy], 1.0, atol=0.02)
    assert r['panel_columns'][156] == FIRST + 156 and r['sat'] == 0.0


def test_other_period_and_offset():
    r = CR.analyse(synth(period=12.9, x0=88.2, width=4300), FIRST, N, white=65535.0)
    assert r['period'] == pytest.approx(12.9, rel=2e-3) and r['ratios']['G'][156] == pytest.approx(0.05, abs=0.02)


def test_unmix_identity_and_matrix():
    img = synth(gains=(1.0, 1.0, 1.0))
    a = CR.analyse(img, FIRST, N, white=65535.0, unmix=np.eye(3))
    assert a['ratios']['B'][157] == pytest.approx(0.5, abs=0.03)
    red = synth(gains=(1.0, 0.2, 0.05), damage={}); green = synth(gains=(0.1, 1.0, 0.2), damage={}); blue = synth(gains=(0.02, 0.15, 1.0), damage={})
    M, U = CR.mixmatrix(red, green, blue, first_column=FIRST, bar_columns=N, white=65535.0)
    assert M[1, 0] == pytest.approx(0.2, abs=0.01) and M[1, 2] == pytest.approx(0.15, abs=0.01)
    assert np.allclose(M @ U, np.eye(3), atol=1e-9)


def test_png_roundtrip(tmp_path):
    from PIL import Image
    v = np.clip(synth(noise=0.0) / 65535.0 * 2.5, 0, 1)
    s = np.where(v <= 0.0031308, 12.92 * v, 1.055 * v ** (1 / 2.4) - 0.055)          # encode linear -> sRGB 8-bit
    Image.fromarray((s * 255 + 0.5).astype(np.uint8)).save(tmp_path / 'bar.png')
    r = CR.analyse(tmp_path / 'bar.png', FIRST, N)
    assert r['kind'] == 'srgb8' and r['ratios']['G'][157] == pytest.approx(0.5, abs=0.05)


def test_no_bar_is_an_error():
    with pytest.raises(ValueError): CR.analyse(np.zeros((50, 400, 3)) + 1.0, FIRST, N)
