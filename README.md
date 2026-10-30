# OLED dead/dim column line fix (Kodi / CoreELEC)

Hide a faint vertical line of damaged columns on an OLED TV by drawing a **pixel-exact, per-column, per-colour
correction** into the picture before it leaves a Kodi player box, calibrated with a RAW-capable camera.

Developed on a 77-inch Samsung S95F (QD-OLED) whose panel columns **1255-1260** (of 3840) had become dim after
physical damage, fed by a CoreELEC box (Ugoos AM9 Pro, Amlogic S905X5-J). Nothing on the TV is modified by this
package. Everything runs on the player box (files under `/storage`, removable) and on your computer.

> Not a repair. The damaged subpixels stay damaged; the picture sent to them is pre-distorted so the line blends in.
> It only works for content played **through Kodi on the box**. Read [SAFETY.md](SAFETY.md) first.

## Results (camera-measured, ratio of each damaged column to its healthy neighbours; 1.00 = invisible)

Uncorrected, the four core columns read **0.05-0.45** in SDR (grey 13-102; at grey 51 per column R/G/B:
0.39/0.36/0.38, 0.27/0.23/0.12, 0.31/0.28/0.12, 0.45/0.41/0.22, blue worst) and about **0.02** at 2 nits in HDR.

| Content | Corrected (core columns) |
|---|---|
| SDR grey 13/255 (very dark) | 0.96-1.19 |
| SDR grey 26 | ~1.0-1.1 |
| SDR grey 51 | 0.98-1.09 |
| SDR grey 102 | 0.96-1.05 |
| HDR10 0.5 nits | 0.53-0.86 (limit of the method) |
| HDR10 2 nits | 0.92-1.18 |
| HDR10 15 nits | 0.93-1.08 |
| HDR10 100 nits | 0.81-0.96 |

**Honest caveat for SDR:** these SDR numbers were measured with an optional full-screen dim (B=60) in the layer that
was cancelled by a whole-picture gain applied inside the TV, which needed device access and is NOT part of this
package. This package defaults to B=0 (lift + alpha only, the same form that produced the HDR results without any
TV-side help). Expect similar dark-scene results; bright highlights inside the line may stay slightly dim. The B=0
SDR variant was not separately camera-verified on our set.

Healthy neighbour columns stay at 1.00 (only a +10-25 % local lift at very dark grey 13). With Pixel Shift following
(optional, see docs) the result holds at any shift. Full numbers and limits: [docs/RESULTS-AND-LIMITS.md](docs/RESULTS-AND-LIMITS.md).

## How it works (one paragraph)
The damaged columns behave like healthy ones **minus a fixed drive threshold**: dark content vanishes, bright content
is almost normal. The correction per column and colour channel is therefore an affine map `out = lift + (1 - alpha) * in`
(mostly lift, a little dimming at high levels). Kodi's GUI is switched to native 4K so one GUI pixel = one panel
column; a skin dialog draws a thin strip texture over the line that does exactly this blend. In HDR, Kodi converts
the GUI to PQ inside a shader, so a small patch to that shader applies the same affine correction directly in the PQ
signal domain. A relay on the box switches between SDR 4:4:4, SDR 4:2:2 and HDR profiles automatically and self-heals
after HDMI resets. Details: [docs/METHOD.md](docs/METHOD.md).

## Requirements
- **CoreELEC box (Amlogic) able to run the Kodi GUI at native 4K** (`coreelec.amlogic.disableguiscaling`), output
  2160p to the TV. Tested: CoreELEC 22 nightly, kernel 5.15, Kodi with the GLES `gles_gui_composite.frag` HDR GUI shader.
  HDR correction needs that shader; SDR works without it.
- A Kodi skin you can add one XML file to (tested: Arctic Fuse 3; any skin works, set the path in the config).
- **A camera that shoots RAW and can be tethered with gphoto2** (tested: Sony a7 IV + 75 mm, ~25-40 cm from the
  screen, tripod). A phone camera is not enough (processed "RAW", 15-60 % shot-to-shot spread in our tests).
- A computer (Linux/macOS) with Python 3 + numpy, Pillow, rawpy, ffmpeg with libx265, ssh/scp, `patch`, gphoto2.
- A dark room, about half a day for the first calibration.

## Quick guide
All commands run from `code/` on your computer. Copy `config.example.json` to `config.json` and set `box.host`.

**0. Prepare.** CoreELEC: enable SSH and add your SSH key. Kodi: *Settings > Services > Control*: allow remote control
from applications on this system. *Settings > Player > Videos*: adjust display refresh rate = on start/stop, whitelist
only 2160p modes. Leave colour depth/subsampling on Auto. TV: **Pixel Shift OFF** (see docs/KODI-LAYER.md), picture size
"fit to screen" (no overscan), sharpness 0, the picture mode you will watch in. `pip install numpy pillow rawpy`.

**1. Find your columns.**
```
python3 install_box.py install --no-shader     # switches Kodi to the native 4K GUI, installs the relay
python3 calib/make_clips.py ruler              # ruler clip around line.ref_col (set a rough guess first)
```
Play `/storage/linefix/clips/ruler.mp4` in Kodi: ticks every 10 columns, numbers every 100 columns; read where the line is,
then confirm exact columns with `make_clips.py marker --col N` (a 1-pixel black column must sit exactly on the edge
of the line). Put the first/last damaged column into `line.c0` / `line.c1`, the darkest into `line.ref_col`, and set
`shader.col_min/col_max` to about `c0 - 55` / `c1 + 60`. Update `bg_left/bg_right/report_cols` (columns 10-40 away).

**2. Install the layer.**
```
python3 install_box.py install --restart-kodi  # relay + HDR shader override (md5-guarded, see docs/HDR-SHADER.md)
cp examples/starter-sdr.json my-sdr-444.json   # edit the column keys to your c0..c1
python3 linefix_skin.py install                # skin dialog + strips; the layer is now on (still uncorrected)
```

**3. Calibrate** (camera setup: [docs/CALIBRATION.md](docs/CALIBRATION.md)).
```
python3 calib/make_clips.py sdr && python3 calib/make_clips.py hdr
python3 calib/reference.py                     # locate the line in the camera image; prints 'before' ratios
python3 calib/sdr_round.py r1                  # repeat r2, r3 ... until all columns are 0.95-1.10
cp my-sdr-444.json my-sdr-422.json
python3 calib/sdr_chroma.py c1 0.9 0.97 --state my-sdr-422.json    # 50/60 Hz profile; tune by the 'sum' values
python3 calib/hdr_fit.py h0 2,15,100 && cp h0-hdr-initial.json my-hdr.json
python3 calib/hdr_round.py h1 0.6 0p5,2,15,100  # 2-3 rounds
python3 calib/verify.py final grey:13 grey:51 grey:102 hdr:2 hdr:100 --state my-hdr.json
python3 linefix_skin.py install                # install the final profiles; the relay picks them by output mode
```

**4. Keep it running (optional).** `python3 keeper.py` re-installs the layer after skin/CoreELEC updates and checks the
4K GUI, profiles and shader after HDMI resets ([docs/RELIABILITY.md](docs/RELIABILITY.md)).

**Turn off / remove.** `python3 linefix_skin.py off` (instant), `python3 install_box.py uninstall` (everything), then
restart Kodi. Nothing outside `/storage/linefix`, two unit files and one skin XML is ever written.

## Documentation
| | |
|---|---|
| [docs/METHOD.md](docs/METHOD.md) | physics of the defect, why dim+lift, chroma low-pass, PQ-domain correction, affine fit |
| [docs/KODI-LAYER.md](docs/KODI-LAYER.md) | native 4K GUI, skin dialog, strip textures, Pixel Shift following, profiles |
| [docs/HDR-SHADER.md](docs/HDR-SHADER.md) | the GUI composite shader patch, parameter block, compositing formula, guard |
| [docs/CALIBRATION.md](docs/CALIBRATION.md) | camera setup, RAW CFA planes, subpixel phase, rules, rounds, example numbers |
| [docs/RELIABILITY.md](docs/RELIABILITY.md) | self-heal, enforcement, pitfalls and lessons |
| [docs/RESULTS-AND-LIMITS.md](docs/RESULTS-AND-LIMITS.md) | all measured numbers, what it cannot do |
| [docs/IDEAS.md](docs/IDEAS.md) | unexplored directions |
| [docs/TV-SIDE-CONCEPTS.md](docs/TV-SIDE-CONCEPTS.md) | what was tried inside the TV (concepts only, out of scope) |

## Layout
```
code/  config.example.json  lfconfig.py  linefix_skin.py  install_box.py  keeper.py
       box/     relay.py, shader-mount.sh, systemd units, shaders/ (patched shader + .patch)
       calib/   make_clips.py, reference.py, sdr_round.py, sdr_chroma.py, hdr_fit.py, hdr_round.py, verify.py, lfcal.py
       camera/  measure.py (RAW CFA column extraction), camctl.py (ratios vs neighbours)
       examples/ S95F profiles and reference numbers, starter profile
```

## License
MIT ([LICENSE](LICENSE)), except `code/box/shaders/*`, which is derived from Kodi and stays GPL-2.0-or-later.
Not affiliated with Samsung, Kodi or CoreELEC. Use at your own risk.
