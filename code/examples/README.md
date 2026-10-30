# Original S95F profiles and starter data

These files document the original damaged panel. Calibrate your own columns and final HDMI path using the [guide](../../docs/kodi/README.md); copying these values is not a generic repair.

| File | Meaning |
| --- | --- |
| `starter-sdr.json` | B=0 starter for a new SDR calibration |
| `s95f-sdr-444.json` | Measured original SDR 4:4:4 reference; B=60 assumes the separate paired TV gain |
| `s95f-sdr-422.json` | Original chroma-adjusted SDR reference |
| `s95f-hdr.json` | Final original HDR fit |
| `s95f-hdr-v1.json`, `s95f-hdr-direct-fit.json` | Earlier/intermediate HDR fitting references |
| `s95f-tv-overlay-reference.json` | Historical 1080p TV-overlay values; requires the separate TV graphics/gain deployment |

Read each file's notes and [results/limits](../../docs/kodi/RESULTS-AND-LIMITS.md). The default Kodi setup does not install the TV gain controller, and B=60 without matching gain dims the whole picture.
