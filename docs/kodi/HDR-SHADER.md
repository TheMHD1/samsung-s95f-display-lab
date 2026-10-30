# HDR: the GUI composite shader patch

Files: `code/box/shaders/gles_gui_composite.linefix.patch` (apply to your stock shader),
`gles_gui_composite.linefix.frag` (patched result for the version we used), `code/box/shader-mount.sh`,
`code/box/linefix-shaders.service`. Derived from Kodi: GPL-2.0-or-later.

## 1. Why a shader patch

On Amlogic CoreELEC the GUI (OSD plane) and the video plane are separate and blended by the display hardware. In HDR
output Kodi renders the GUI into an sRGB framebuffer and then runs `GLES/2.0/gles_gui_composite.frag` once more to
convert it for the OSD plane: sRGB -> linear (LUT) -> BT.709 to BT.2020 -> PQ (LUT with the GUI peak baked in) (or HLG).
The hardware then blends `out = GUI_PQ * a + (1 - a) * VIDEO_PQ` in PQ code. GL cannot touch the hardware-decoded
video. So the only place where a per-column correction can be expressed in the PQ signal domain is this shader:
it decides the colour and alpha that the hardware blends over the video.

## 2. Parameter block (no visible pixels)

The HDR strip carries per-column parameters in the top 4 rows of its column, fully opaque, red channel = magic:

| row | R (magic) | G, B |
|---|---|---|
| 0 | 165 | alpha `a`, 16-bit (hi, lo) |
| 1 | 90 | lift `L_R`, 16-bit |
| 2 | 60 | lift `L_G`, 16-bit |
| 3 | 195 | lift `L_B`, 16-bit |

Values are `round(v/255 * 65535)` where `v` is the profile number (0..255 scale), so `a` and `L` are 0..1 with
16-bit precision (8-bit GUI code steps would be too coarse in PQ near black). All four magic values must match within
0.6 code and alpha must be ~1, so ordinary GUI content cannot trigger it by accident.

## 3. What the patched shader does

For every fragment whose column lies in `[LF_COL_MIN, LF_COL_MAX]` (a window around the line, wide enough for Pixel
Shift - `install_box.py` writes it from config):
1. read the 4 parameter pixels of THIS column from the GUI texture (row 0..3; it tries top-down and bottom-up because
   the framebuffer orientation was not known - whichever matches the magic wins);
2. if they match: `lfOn`, decode `a` and `L`; if this fragment IS one of the 4 parameter pixels, treat its GUI
   colour as transparent (never shown);
3. fragments with no GUI content are normally `discard`ed; on corrected columns they are processed too
   (otherwise the video under an empty GUI would not be corrected);
4. convert the GUI colour as stock (sRGB -> linear -> BT.2020 -> PQ), giving `g` with GUI alpha `ga`;
5. composite so the hardware blend yields the corrected result:

```
   final = L + (1 - a) * ( g * ga + (1 - ga) * video )          (PQ signal domain)
   written as   outA  = 1 - (1 - a)(1 - ga)
                colour = (L + (1 - a) * g * ga) / outA          -> hardware: colour*outA + (1-outA)*video
```
So everything on those columns - video, menus, subtitles - gets the same physical correction, and menus/subtitles
over the line are still composited correctly.
6. HLG output (`u_ootfGamma > 0`): correction off (calibrated for PQ only).
7. `precision highp float` (stock: mediump) so row/column addressing and 16-bit decoding are exact.

Earlier version (v1) marked strip rows with a magenta colour key and passed only keyed pixels through as raw PQ.
Problems: a **purple line** when opening Kodi's home screen during HDR playback, and subtitles over the line broke the
keying. v2 (above) fixed both.

## 4. Installation and the md5 guard

`install_box.py install`:
1. reads the box's OWN stock `gles_gui_composite.frag` (even if an override is mounted),
2. applies `gles_gui_composite.linefix.patch` with `patch`; if it does not apply cleanly, HDR is skipped (SDR still works),
3. sets the column window, uploads the result and the **md5 of the stock file** (`shader-orig.md5`).
At boot `linefix-shaders.service` runs `shader-mount.sh` before Kodi: it copies the stock shader tree to
`/storage/linefix/shaders`, replaces the composite shader and **bind-mounts** the copy over
`/usr/share/kodi/system/shaders`. Only if the stock shader still has the recorded md5. After a CoreELEC/Kodi update that
changes the shader, nothing is mounted (status in `/storage/linefix/shader-mount.status`), the GUI is 100 % stock and the
relay shows no HDR strip (it checks for the `LINEFIX v2` marker in the active shader every 20 s). Re-run
`install_box.py install` to re-patch against the new version.

## 5. Safety properties

- The system image is never modified; undo = `umount /usr/share/kodi/system/shaders` + restart Kodi, or disable the unit.
- No shader -> no HDR strip -> no correction, but also no wrong picture.
- DV / HLG / non-2160p -> no strip.
- If the strip ever shows without the shader: 4 tiny dots at the top edge per column.
- If the parameters are wrong the damage is limited to the configured columns: `a` <= 0.6 and `L` <= 0.92 a are
  enforced by the calibration scripts; keep `L` below the level at which the dead columns start to light, so black
  never glows (METHOD.md section 4).

## 6. Related knobs found (not needed by the fix)

- Kodi "GUI peak luminance in HDR PQ mode" (default 40 %) - irrelevant for the parameter block (it bypasses the LUT).
- CoreELEC's OSD SDR->HDR gain table (`oo_y_lut_sdr_hdr` module parameter in the amvecm driver) scales GUI brightness
  in HDR. Do not read or write `/sys/class/amvecm/*` nodes - reading some of them crashed and rebooted our box.
- Dolby Vision output composites the GUI inside the DV engine and remaps it, so the raw-PQ strip does not hold there
  (line only 0.4-0.7 on a P5 test) - see IDEAS.md.
