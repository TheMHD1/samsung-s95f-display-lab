# Results and limits

All numbers: camera-measured ratio of a damaged column to its local healthy neighbours (1.00 = equal measured luminance), core
columns 1256-1259 of a 77-inch S95F; edge columns 1255/1260 were nearly healthy (0.94-0.97) before correction.

## Uncorrected

| level | per column R/G/B (1256 / 1257 / 1258 / 1259) |
|---|---|
| SDR grey 51 | .39/.36/.38 · .27/.23/.12 · .31/.28/.12 · .45/.41/.22 |
| SDR grey 13-102 | 0.05-0.36 (core, all levels) |
| HDR 2 nits | ~0.02 |
Model: fixed drive threshold ~14-23 code (R, G), ~25-40 code (B), slope 0.9-1.16 (METHOD.md).

## Kodi layer, SDR (profile 444, 24 Hz; calibrated with global dim B=60 + TV-side gain, see caveat in README)

| grey | 13 | 26 | 51 | 102 |
|---|---|---|---|---|
| core columns | 0.96-1.19 | ~1.0-1.1 | 0.98-1.09 | 0.96-1.05 |
After the chroma step: luma 0.92-1.05 per column. No halo: healthy neighbours unchanged except +10-25 % local lift
at grey 13. 4:2:2 (60 Hz) profile: same luma, colour lifts R x0.9, B x0.97.

## Kodi layer, HDR10 (patched shader, no global dim, no TV-side help)

| nits | 0.5 | 2 | 5 | 15 | 100 |
|---|---|---|---|---|---|
| v1 strips + shader v2 | - | 0.92-1.06 | - | 0.94-1.06 | 0.87-0.96 |
| v2 strips (final, 0.5-nit weighted) | 0.53-0.86 | 1.01-1.18 | 1.06-1.26 | 0.95-1.08 | 0.81-0.92 |
Blue is lower at 2 nits (0.5-0.75 with v1) because the TV smears colour sideways.

## For comparison: the measured TV-side overlay

See [TV graphics research](../advanced/GRAPHICS-AND-GPU.md) for the working compositor/gain mechanism, source and limitations.

| | result |
|---|---|
| SDR grey 13 / 51 / 102 | core 0.7-1.5 / 0.95-1.28 / 1.07-1.27; neighbour 1255 x2.1 at grey 13 |
| HDR 2 / 15 / 100 nits | core 0.75-1.22 / 0.93-1.14 / 1.05-1.17; neighbours up to ~2x at 2 nits |
| odd Pixel Shift phase | SDR grey 102 0.95-1.08, but grey 13/26 0.1-0.6 with 1255 at 2.5-5x |
The 2x-upscaled graphics plane blurs every correction over ~2.5 columns; the native-4K Kodi layer removed that limit.

## Limits

- **Only content through Kodi on the box.** TV apps and other HDMI inputs are not corrected. (Streaming add-ons
  inside Kodi are; DRM services that need the TV app are not.)
- **Dolby Vision** (profile 5 through the DV engine) and **HLG**: no correction (P5 test: line 0.4-0.7).
- **HDR below ~1 nit** under-corrects (0.5 nits 0.53-0.86) and above ~300 nits the affine shape under-corrects;
  bright full-field scenes are further affected by the TV's automatic brightness limiter.
- **Highlights**: the line can never exceed panel maximum; SDR without global gain (B = 0) cannot add gain > 1.
- **Colour**: one alpha per column for R, G, B together; the TV low-passes colour over ~+-2 columns, so very saturated
  dark colours on the line can show a slight tint.
- **Pixel Shift**: needs a source for the current shift; otherwise Pixel Shift must stay off.
- **Neighbours**: very dark scenes show a faint +10-25 % lift next to the line.
- **Not a repair**: the damaged columns are unchanged; if the damage changes, recalibrate.
- Visible for a moment on some transitions: profile switches are hidden inside the TV's HDMI re-sync, but a wrong
  state can last up to ~0.5 s after a Kodi restart before enforcement corrects it.
