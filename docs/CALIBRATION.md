# Camera calibration

Code: `code/camera/measure.py` (capture + RAW analysis, runs where the camera is plugged in), `code/camera/camctl.py`
(ratios), `code/calib/*.py` (loops). All measurements are **ratios of a damaged column to its own healthy neighbours
in the same photo**, so exposure, camera response and TV brightness drift cancel out.

## 1. Why a camera, and which
- A spot meter reads a circle of ~2 cm; the line is a few mm wide and is diluted to ~14 %; near-black is below every
  meter's floor; it cannot separate columns. Factory panel compensation also uses imaging cameras.
- A phone "RAW" is demosaiced, multi-frame merged and smoothed: 15-60 % shot-to-shot spread in our first attempt.
- Use a real RAW camera with a fixed manual exposure. We used a Sony a7 IV (14-bit RAW) with a 75 mm lens at about
  25-40 cm, tethered by USB with gphoto2. Result: ~10.4 samples per TV column in each Bayer colour plane; individual
  subpixels resolved; repeated shots agree within about +-1 %.

## 2. Camera setup (once)
- M mode, ISO 100, f/5.6-8, RAW only (lossless/uncompressed 14-bit; avoid modes that drop to 12-bit, e.g. silent
  shutter on some bodies), stabiliser off, long-exposure noise reduction off, save to computer only, auto power-off
  longest. Autofocus once on the line, then manual focus and don't touch it.
- Tripod, sensor parallel to the screen, centred on the line at mid-height, TV columns vertical in the image.
- Dark room. TV: Pixel Shift OFF during calibration, the picture mode you watch in (we used Filmmaker mode, Peak
  Brightness off in SDR / high in HDR, static tone mapping, brightness optimisation off), sharpness 0.
- Shutter speeds per level are in `config.json` (`camera.shutter_*`); longer for dark levels. Our values: grey 13 at 4 s,
  grey 51 at 1/4 s, grey 102 at 1/20 s; HDR 2 nits 0.6 s, 100 nits 1/60 s.

## 3. RAW analysis (measure.py)
1. Read the RAW with rawpy; use `raw_image_visible` and the CFA colour map (no demosaicing - it mixes neighbouring
   subpixels); subtract the black level; build half-resolution R, G (mean of both greens), B planes.
2. Average the central rows of each plane -> one profile per colour along x.
3. Find the TV column period in the green profile by FFT, then fit the exact lattice `x0 + k * period` to the peaks.
4. **Per-colour subpixel phase**: on a QD-OLED the R, G, B subpixels of one pixel sit at different x positions. Each
   colour is integrated over one period centred on its OWN position: we measured R at +1.96 and B at -1.49 plane
   samples relative to G (`--phase-r/--phase-b`; measure.py prints its own estimate as `phase_est` - check it once).
5. Output: light per TV column per colour, the column centres, the darkest column (the line), peak level and
   saturated-pixel fraction (clipping check).

## 4. From camera columns to panel columns (camctl.py)
- `calib/reference.py` shoots the UNCORRECTED line at grey 51 and stores the camera position of the darkest column,
  which you identified as `line.ref_col` with the ruler/marker clips. Later frames use the column nearest that
  position (after correction there is no darkest column any more). Re-run it whenever the camera moves.
- Ratio per column = column value / a **local linear fit** of the healthy columns on both sides (`bg_left`, `bg_right`,
  ~10-40 columns away). The camera mapping drifts by about one TV column per 60-100 columns (lens, angle), so never
  compare against far-away columns.
- Validation: healthy columns must read 1.00 +- 0.02, repeated shots +-1 %. If not, fix the setup before calibrating.

## 5. Measurement rules (learned the hard way)
- Test clips are small windows around the line on black (`make_clips.py`), never full-screen bright fields.
- The pattern is on screen **only for the photo**: every measurement starts the clip, waits, shoots, stops playback.
- Wait until the clip really plays at the expected refresh rate (24 Hz clips -> 4:4:4 profile, `f60` clips -> 4:2:2),
  then 5 s more: Kodi shows a "now playing" pop-up for a few seconds after starting a clip.
- After the shot, check the clip is still playing (otherwise the photo shows the menu) - re-shoot if not.
- Clipping: a few saturated pixels -> one stop shorter and re-shoot; a frame much brighter than expected
  (peak >= 90 % of white) -> stop the whole run. Ignore frame edges when checking.
- A changed skin XML is only used after `ReloadSkin()` (the installer handles it).
- Pause anything that could change the layer while measuring (the scripts set `keeper.hold` and the box-side
  `profile.lock`, and remove both on any exit, including crashes).
- Delete RAWs after analysis (default); keep the per-shot numbers (`calib-data.jsonl`).

## 6. Rounds
**SDR (`sdr_round.py`, 24 Hz clips, profile 444).** Measure grey 13/26/51/102. Per column and channel, the lift is
updated from the dark levels: a light ratio `r` means the drive is off by `r^(-1/2)` (panel response ~ code^2), so
`d_lift = (lift + k*L) * (r^(-1/2) - 1)` averaged over 13 and 26, times a damping of 0.6. The column gain
`k = 1 - alpha/255` is updated from grey 102 (geometric mean of R, G, B). Blue uses a 3-column average. 3 rounds took
our columns from 0.05-0.36 to the final numbers; from zero expect 4-6.
Then **chroma** (`sdr_chroma.py`): scale R and B lifts until the `sum` of (ratio - 1) over the line on red/blue clips
is ~0; copy to a 4:2:2 profile and repeat with `f60` clips (our result: R x0.9, B x0.97).

**HDR (`hdr_fit.py`, then `hdr_round.py`).** Fit first: replace the core columns by constant PQ values C = P + 0.06 /
0.12 / 0.18 at 2, 15, 100 nits (one photo each), interpolate ln(ratio) to find C*, and least-squares fit
`dP = L - a*P` per column (one `a`, three `L`). Then refine: ratio errors -> PQ steps via the measured sensitivity
`S(P)`, refit, 2-3 rounds with damping 0.6. Weighted refits from logged data (`--refit TAG --weights 2,1,1,1`) cost no
photos; our final HDR profile was the midpoint of a plain refit and a refit weighted towards 0.5 nits.

## 7. Convergence and our numbers (S95F, columns 1255-1260)
| stage | result (core columns) |
|---|---|
| uncorrected, grey 51 (R/G/B) | 1256 .39/.36/.38, 1257 .27/.23/.12, 1258 .31/.28/.12, 1259 .45/.41/.22; edges 1255 ~.97, 1260 .94/.89/.72 |
| SDR after 3 rounds | 0.96-1.19 at 13, ~1.0-1.1 at 26, 0.98-1.09 at 51, 0.96-1.05 at 102 |
| SDR after chroma step | luma 0.92-1.05 per column |
| HDR fit | all anchors 2-100 nits within 0.008 PQ |
| HDR v1 (3 rounds) | 0.92-1.17 at 2 nits, 0.93-1.17 at 15, 0.86-0.96 at 100 (blue 0.5-0.75 at 2: colour smear) |
| HDR v1 + shader v2 | 0.92-1.06 at 2, 0.94-1.06 at 15, 0.87-0.96 at 100 |
| HDR v2 (0.5-nit weighted) | 0.53-0.86 at 0.5, 1.01-1.18 at 2, 1.06-1.26 at 5, 0.95-1.08 at 15, 0.81-0.92 at 100 |
Final strips: `code/examples/s95f-*.json`. Example (SDR 4:4:4, [alpha, R, G, B]): 1257 [62.7, 15.9, 24.2, 39.9];
HDR v2: 1257 [61.2, 38.2, 41.4, 52.3] (/255 = PQ).

## 8. Keep an eye on drift
Panels age and a damaged area can change. Re-run `verify.py` (a few minutes) every month or after anything changed
(firmware, picture mode). The reference shot must be redone whenever the camera moved.
