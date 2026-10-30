# Calibration workflow

Run these scripts from `code/` after filling in the private config and installing the player layer. The [complete guide](../../docs/kodi/README.md#quick-guide) supplies commands; [camera calibration](../../docs/kodi/CALIBRATION.md) explains measurements and fitting.

| Order | Tool | Purpose |
| --- | --- | --- |
| 1 | `make_clips.py` | Ruler, one-column markers and bounded SDR/HDR test windows |
| 2 | `reference.py` | Locate the damaged columns in the camera image and establish baseline ratios |
| 3 | `sdr_round.py` | Iterate the SDR per-column lift/alpha fit |
| 4 | `sdr_chroma.py` | Fit the separate 4:2:2/chroma profile |
| 5 | `hdr_fit.py`, `hdr_round.py` | Initialize and refine the matching raw-PQ HDR profile |
| 6 | `verify.py` | Measure the final profile at selected levels and inspect neighbours |
| Shared | `lfcal.py` | Common configuration, measurement and calibration operations |

Keep the final HDMI path, refresh/chroma mode and Pixel Shift alignment fixed or explicitly followed. Use bounded patterns and stop playback after each shot. Near-black and highlight limits are recorded in [results](../../docs/kodi/RESULTS-AND-LIMITS.md).
