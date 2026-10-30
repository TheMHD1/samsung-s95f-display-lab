# Unexplored directions

Ordered roughly by expected value. None of these were finished.

## 1. Exact per-column LUT on a mini PC with mpv / libplacebo
The affine map is an approximation; the exact correction is a per-column, per-channel 1-D curve
`f(P) = PQ(G(PQ^-1(P)))` (METHOD.md). A GPU shader that sees the decoded VIDEO can apply it exactly, including
below 1 nit and in highlights. Kodi on Amlogic cannot (hardware video plane, no GL access to frames).
Sketch: a small x86 PC with mpv `--vo=gpu-next`, a custom user shader hooked at OUTPUT/PREOUTPUT with a small LUT
texture for the damaged columns, `//!PARAM shift` marked DYNAMIC and updated over mpv's IPC for Pixel Shift,
`--target-colorspace-hint` so the TV gets HDR10 with metadata, and a media-server front end (e.g. Jellyfin MPV Shim).
Output 4K 23.976 RGB 10/12-bit. Cost a few hundred dollars. Commercial video processors (madVR Envy, Lumagen) had no
per-pixel spatial correction feature; an FPGA in the HDMI chain is impractical (HDCP, effort).

## 2. Alternating-row correction ("smooth max of two lines")
A per-column affine map cannot follow the curved correction at both ends. Using two different (a, L) pairs on
alternating rows (or a 2x2 dither of rows) gives the eye the average of two lines, i.e. a piecewise shape, and also
half-code steps for the tiny lifts needed at 0.5-2 nits. Needs the v2 parameter block extended to per-row parameters.
Risk: visible row structure close up.

## 3. Scene-adaptive correction
Choose (a, L) per frame from the average picture level, or blend between a "dark" and a "bright" profile, to fix the
< 1 nit and > 300 nits ends and ABL scenes. In Kodi this could be a profile switch driven by a cheap luminance
estimate; on an mpv box it is a shader parameter. Needs hysteresis to avoid pumping.

## 4. Chroma pre-compensation
The TV low-passes chroma over ~+-2 columns, so colour lifts put into one column spread to its neighbours. In principle
the colour correction could be deconvolved (pre-sharpened chroma around the line). We advised ourselves against it
for now: noise and overshoot on saturated content, and the luma/sum approach already gets luma within 0.92-1.05. A
measured chroma kernel (single-colour impulse clips) would be the first step.

## 5. Dolby Vision profile 5 path
With DV P5 the box's DV engine composites the GUI and remaps it, so the raw-PQ strip lands at 0.4-0.7. Options:
(a) a separate P5 profile with its own calibration, selected when the source is P5 (Kodi reports only the output
type, so detection has to come from the file/stream info); (b) CoreELEC's DV graphics brightness parameter (GUI nits
when the DV core composes); (c) avoid P5 (replace with HDR10 releases), which is what we did.

## 6. Smaller items
- Dedicated `hdr422` profile for 50/60 Hz HDR (we used one HDR profile for all rates).
- Better dark HDR fit with a 0.5-nit anchor, or a 2-segment trick (two strips per column, one active only near black).
- A test with 4000-nit mastering metadata clips (tone mapping differs).
- CoreELEC's SDR->HDR OSD gain table (`oo_y_lut_sdr_hdr`) to shape GUI brightness in HDR without touching the shader.
- Pixel Shift: a source of the shift value that does not need device access (e.g. a camera watching a corner of the
  screen, or predicting the TV's orbit pattern after observing it).
- Monthly automatic camera drift check; a remote button in Kodi to toggle the layer.
- 4:4:4 at 60 Hz through a PC-mode input (if the HDMI chain allows) to avoid the 4:2:2 profile.
