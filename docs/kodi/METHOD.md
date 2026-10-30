# Method

## 1. The defect is a threshold, not a gain

Camera measurements (RAW, per column and per colour, see CALIBRATION.md) of the uncorrected line at several grey
levels were fitted with a simple model per column/channel:

    light_damaged(d) = s * light_healthy(d - t)          d = drive code, t = threshold, s = slope

Fit quality ~6 % rms. Found on our panel:
- threshold **t ~ 14-23 code** (8-bit) for red and green, **~25-40 code for blue** (blue worst),
- slope **s ~ 0.9-1.16**, i.e. near normal.

So a damaged column is almost a healthy column whose input is shifted down by a constant. Consequences:
- near black the column is (almost) dark: ratio ~0.05 at grey 13, ~0.02 at 2 nits HDR;
- at bright levels it is nearly normal (ratio approaches 1);
- the ideal correction is mostly an **offset (lift) on the drive signal**, not a gain. An earlier per-level
  "eye" calibration had suggested a gain-type need (+15-22 % at mid levels, +100-170 % at levels 5-10); that is
  exactly what a threshold looks like when expressed as gains.

Our line was 6 columns wide: two edge columns nearly healthy (0.94-0.97), four core columns at 0.12-0.45 (grey 51).

## 2. The correction primitive: alpha compositing = per-column affine map

An overlay pixel with alpha `a` and premultiplied colour `C` (C <= a) composited over video `V` gives

    out = C + (1 - a) * V

per channel. That is an affine map with offset `C >= 0` and gain `1 - a <= 1`. Per column and channel we can choose
the offset freely (up to `a`) and the gain once per column (alpha is shared by R, G, B).

Why alpha as well as lift: the threshold is constant in the panel's DRIVE domain, but the signal we edit is not
exactly that domain. In SDR (gamma-encoded code, close to the drive domain) the measured need was almost a pure lift:
our final SDR strips have alpha about equal to the global dim and lifts of 10-46 code. In HDR the TV tone-maps the PQ
signal before the panel, and the needed PQ lift falls with level (section 4); the dimming term `a * P` makes the
correction fade out towards bright content. The fitted HDR alphas are about 0.18-0.24.

Why "dim + lift" (global dim B): if the damaged column also needs a gain **above** 1 (slope < 1), an overlay alone
cannot provide it. The trick is to dim the WHOLE picture by B (dim rectangles everywhere except over the line) and
give the whole picture back a gain of 1/(1 - B/255) somewhere downstream; the line columns, dimmed less, then end up
with a net gain > 1. We did this with a whole-picture gain inside the TV (see [TV graphics research](../advanced/GRAPHICS-AND-GPU.md)).
Without such a gain keep **B = 0**; the threshold model says the remaining error is small (slope ~1).

## 3. Columns are not independent in colour: the chroma low-pass finding

- At 50/60 Hz the box sends 2160p as **YCbCr 4:2:2** over the HDMI 2.0 link (24/25/30 Hz go out as 4:4:4), so
  red/blue corrections are effectively per column PAIR at 60 Hz -> separate 444 and 422 profiles, chosen by the relay.
- Even at 4:4:4 the TV **low-passes colour over about +-2 columns**. On single-colour clips the per-column colour ratios
  are smeared, so judging colour column by column over-corrects. Rule adopted: luma per column, colour balance by the
  **sum of (ratio - 1) over the line area** on single-colour clips (`sdr_chroma.py`). Result: luma per column 0.92-1.05.
- Blue light also spreads into neighbours in the measurement, so blue is evaluated on a 3-column average.
- On our set the 60 Hz profile = 4:4:4 profile with R x0.9 and B x0.97.

## 4. HDR: correct in the PQ signal domain

In HDR output Kodi converts the GUI (sRGB) inside its composite shader: sRGB -> linear -> BT.2020 -> PQ with a "GUI peak"
(e.g. 40 % setting). Consequences seen with the SDR strips: the correction was weak, and the dim layer darkened HDR
video non-uniformly (0.81 at 2 nits ... 0.53 at 100 nits), because the blend happens in PQ code after conversion.

The box's display hardware blends the GUI over the video as `out = OSD_PQ * a + (1 - a) * V_PQ` in PQ code (no
linear-light blend). So the natural correction is affine **in the PQ signal**:

    P_out = L + (1 - a) * P          i.e.   dP = P_out - P = L - a * P

and the shader patch (HDR-SHADER.md) passes `a` and `L` through untouched by the sRGB->PQ conversion.

Exact correction for a threshold defect (model `Y = Ymax * max(0, d - t)^g` in linear drive):

    f(P) = PQ( G( PQ^-1(P) ) ),   G(Y) = Ymax * ((Y/Ymax)^(1/g) + t)^g

The needed PQ lift **falls with level**. Example for t = 0.05: dP 0.127 at 0.5 nit, 0.114 at 1, 0.082 at 5, 0.069 at 10,
0.042 at 50, 0.033 at 100, 0.026 at 200, 0.018 at 500 nits. A straight line `L - a*P` fits this well over a limited
range: t = 0.05 -> 5-200 nits within +-5-8 % (a ~0.17, L ~0.124), 1-300 nits within +-15 %; 0.5-500 nits +-20-25 %.
A blue-like t = 0.10 needs a ~0.35, L ~0.245 (+-35 % over the full range). Affine in linear light is the worst choice.

Rules of thumb from that analysis:
- `L ~ 0.8 * P_th`, where P_th is the PQ level at which the damaged column starts to light. **Keep L < P_th** so
  black never glows (with an affine map, video black gets exactly `L`).
- `a ~ 3.5-4.2 * t`.
- Choose the line through two anchor levels where you want it exact (we used ~2 nits and ~100 nits):
  `a = (D1 - D2) / (P2 - P1)`, `L = D1 + a * P1`, with D = needed dP at each anchor.

## 5. Our measured affine fit

`hdr_fit.py` replaced the core columns by constant PQ values and found, per column/channel, the PQ output that matches
the neighbours at 2/5/15/100 nits. One alpha per column + one lift per channel fitted all anchors within **0.008 PQ**:

| column | a | L (R, G, B) in PQ |
|---|---|---|
| 1256 | 0.221 | 0.140, 0.146, 0.161 |
| 1257 | 0.227 | 0.150, 0.159, 0.185 |
| 1258 | 0.200 | 0.132, 0.142, 0.176 |
| 1259 | 0.175 | 0.111, 0.116, 0.141 |

Refinement rounds convert each remaining ratio error to a PQ step through the measured sensitivity of the damaged
columns, `S(P) = d ln(light) / dP` (about 30 at P = 0.12 falling to 11 at P = 0.58), and refit (hdr_round.py).
Where it fails: below ~1 nit (the needed lift rises faster than a line can follow) and above ~300 nits.

## 6. Per-column alpha and lift, nothing else

The whole correction is 4 numbers per column (alpha + R/G/B lift) per profile. That is small enough to calibrate
with a camera in a few hours, robust (no per-level tables), and cheap to apply in the GPU. A per-column 1-D LUT per
channel would be exact; see IDEAS.md for where that could run.
