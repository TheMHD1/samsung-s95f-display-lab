# TV-side concepts (high level only)

Before the Kodi layer existed, the line was corrected **inside the TV**. Those techniques required privileged device
access to the TV, which is **out of scope for this project**: no access method, commands, register addresses,
firmware details or code are published here, and none are needed for the Kodi method. This page only records the
ideas and what they achieved, because they explain some design choices.

## 1. Graphics overlay on the TV
A full-screen layer on the TV's own graphics plane: black with a small alpha everywhere (a uniform dim) and per-pixel
RGBA strips over the line (premultiplied: colour = lift, alpha = dimming), updated live during calibration.
Findings:
- The TV composes graphics at **1920x1080 and upscales 2x in fixed hardware** after mixing, with a blur that cannot be
  switched to nearest-neighbour. One graphics pixel p covers panel columns 2p, 2p+1 and part of 2p-1; odd panel columns
  get the average of two graphics pixels. So the lift needed by the damaged columns inevitably leaks half-strength into
  the neighbours (1255/1261), most visible in dark scenes. A native 4K graphics canvas was not available.
- The overlay had to be composited in a way that is visible over HDMI inputs, and it moves with the TV's Pixel
  Shift, so odd/even shift phases needed separate parameter sets.
- Results (RESULTS-AND-LIMITS.md): good at mid/bright levels, blur-limited near black.
This limitation is the reason for the native-4K Kodi layer.

## 2. Whole-picture gain via a SoC tone-curve stage
The dim part of the overlay was cancelled by raising the gain of the entire picture by 1/(1 - dim) in a per-level,
per-channel tone-curve stage of the TV's video processor that sits after graphics mixing. Net effect: background
unchanged (camera: 1.000 +- 0.2 % at grey 51), the line columns (dimmed less) relatively brighter, i.e. an effective
gain above 1 on the line. Changes were RAM-only and needed re-applying after standby/reboot. The same stage behaves as
a gain-vs-level curve after HDR tone mapping. The SDR numbers of the Kodi layer were measured with such a gain
cancelling a Kodi-side dim of B = 60; this package defaults to B = 0 instead.

## 3. Video-plane dimming boxes (idea, not tested)
Some TV video pipelines offer a few rectangular alpha boxes on the video plane, pixel-exact at 4K. Combined with a
whole-picture gain they could give a blur-free per-column GAIN (no offsets) for all sources including TV apps.

## 4. Panel compensation (demura / TCON) - researched, deliberately NOT attempted
OLED panels carry factory per-pixel compensation data applied by the timing controller. Correcting the line there
would cover every source. It was researched and **deliberately not attempted**: every path found writes persistent
storage (the compensation data or controller flash), with no trustworthy backup/restore and a real risk of an
unrecoverable panel. A reboot would not undo a mistake. No instructions are given, and we recommend against it.

## 5. What a TV-side solution would still need
Blur-free 4K overlay or exact video-plane access, a persistent way to re-apply after standby, Pixel Shift following,
and coverage of TV apps and HDR. None of that is required for the Kodi method, which runs entirely on the player box.
