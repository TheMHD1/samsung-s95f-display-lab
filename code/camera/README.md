# Camera measurements

`camctl.py` coordinates camera captures and ratios; `measure.py` extracts measurements from RAW colour-filter-array data. They support the [calibration scripts](../calib/README.md), rather than measuring arbitrary screenshots as panel light output.

The retained setup used a tethered RAW-capable Sony a7 IV, tripod and fixed geometry. Phone captures were not repeatable enough in the original tests. See [camera setup and analysis](../../docs/kodi/CALIBRATION.md) for exposure, focus, CFA/subpixel phase, reference columns and measurement pitfalls. Public ratios are relative measurements, not a certified absolute luminance/colorimeter calibration.
