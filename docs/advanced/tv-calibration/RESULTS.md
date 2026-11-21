# TV-side calibration of the damaged columns: results tables

Companion to [WRITEUP.md](WRITEUP.md). Panel: 77-inch Samsung S95F QD-OLED, damaged columns **1255–1260** (worst
1256–1259). All measurements: SDR, the TV's Movie picture mode, narrow grey or colour bars on black played from a media
player, photographed with a RAW camera. **1.00 = the same as the healthy columns next to the band in the same photo.**


Two ways of reading a photo are used, and they are labelled everywhere:

- **Camera**: the camera's own R/G/B channels, column by column. Simple, but the camera's colour channels overlap
  (its green channel sees some blue light, and so on).
- **Sub-pixel**: the same photo after "unmixing" the camera's channel overlap with a 3×3 matrix measured on this panel
  (camera G ≈ .80 G + .20 B, camera R ≈ .93 R + .07 B, camera B ≈ .03 R + .21 G + .76 B). Luminance is then
  L = .25 R + .68 G + .07 B. This is the more honest number for colour.

## 1. Final state (bake 11 + runtime trims)

| Grey (8-bit code) | 100 % (255) | 50 % (128) | 30 % (77) | 20 % (51) | 10 % (26) | 5 % (13) |
|---|---|---|---|---|---|---|
| Luminance, sub-pixel, band mean | 0.987 | 0.987 | 0.998 | 1.030 | 1.061 | 1.144 |
| Luminance, sub-pixel, column range | 0.98–1.00 | 0.97–1.00 | 0.97–1.02 | 1.01–1.06 | 1.02–1.13 | 1.08–1.24 |
| Luminance, camera, band maximum | 1.01 | 1.01 | 1.02 | 1.02 | 1.01 | 1.11 |
| Red, camera, column range | 0.98–1.01 | 0.97–1.00 | 0.97–1.01 | 1.00–1.03 | 0.98–1.07 | 0.98–1.13 |
| Green, camera, column range | 0.99–1.01 | 0.98–1.01 | 0.98–1.02 | 0.99–1.02 | 0.94–1.04 | 0.99–1.19 |
| Blue ÷ mean(red, green), sub-pixel, band mean | 1.12 | 1.03 | 0.92 | 0.79 | 0.47 | 0.23 |
| Blue ÷ mean(red, green), camera, worst column | 1.00 | 0.99 | 0.89 | 0.77 | 0.52 | 0.45 |

Plain reading: brightness matches within 1–2 % from 30 % grey up and within about 3–6 % down to 10 % grey; red and green
match within about 3 % from 30 % grey up (unmixed green +5 % at 20 % grey). Blue is short below about 30 % grey, so dark greys on the band look slightly
yellow. Charts: [band luminance](../../assets/bake11-band-luminance.png), [blue balance](../../assets/bake11-blue-ratio.png).

## 2. Starting point: no correction at all

All earlier corrections switched off. Four worst columns, camera, range over columns and colours:

| Grey (code) | 51 | 77 | 102 | 128 | 153 | 204 | 255 |
|---|---|---|---|---|---|---|---|
| Light vs healthy | ~0.01 | 0.01–0.07 | 0.03–0.18 | 0.11–0.30 | 0.11–0.39 | 0.27–0.55 | 0.43–0.67 |

At 4 % grey the band was black (the 1–3 % measured is camera flare). Single-colour bars gave the same result per colour.
Expressed as drive, red and green lacked about 65–75 8-bit codes and blue somewhat more. A few weeks earlier the same
columns lacked 14–23 codes: **the damage grew about three-fold in a few weeks.**

## 3. Scan-time sensing gain: the bake series

A "bake" = lower the sensing gain of chosen lanes in controller RAM just before the TV's own compensation scan, let the
scan store its result, then measure. One sensing lane covers two panel columns (lane 628 = columns 1256/1257, lane 629 =
1258/1259, lane 630 = 1260/1261). Gains are given relative to the stock value.

**Stored scan reading** of the band, red, in counts above the healthy columns' level (columns 1256 / 1257 / 1258 /
1259 / 1260). Healthy columns read about 100–120 counts *below* the neutral point, and the hardware only adds drive to
readings below neutral. So a band column at +0 gets normal drive, and one at +120 or more gets none.

| Scan | Gain change | Stored reading, red | Light |
|---|---|---|---|
| Stock (no change) | none | +384 / +506 / +466 / +346 / +270 | Band dark (table 2) |
| Bake 1 | lane 629 ×0.85 | +258 / +218 / +207 / +163 / +123 | **No change**: still above neutral |
| Bake 2 | lanes 628, 629 ×0.80 | +55 / +67 / +61 / +64 / +41 | **First real fix** (table 4) |
| Bake 3 | ×0.78 | +28 / +36 / +43 / +48 / +30 | Same as bake 2 within noise |
| Bake 4 | ×0.75 | +3 / +2 / +23 / +30 / +17 | Best single shared gain, no glow |
| Bake 5 | 628 ×0.72, 629 ×0.68 | −50 / −157 / −178 / −33 / −14 | **Overshoot**: 1257/1258 at 1.23–1.37 (grey 128), 11–16× at grey 13 |
| Bake 6 | = bake 4 | +2 / +1 / +22 / +29 / +16 | Repeats bake 4 within about 1 count |
| Bake 7 | ×0.746 | −1 / −3 / +19 / +27 / +15 | No glow; first setting kept automatically |
| Bake 8 | + lane 630 ×0.966 | −2 / −4 / −2 / −4 / −4 | 1258/1259 near black fixed |
| Bakes 9–11 | per-lane (bake 9), per-column (bakes 10–11) | shaped by a few counts per column | see tables 4–6 |

Bake 11 gains (relative to stock), per column: 1255 ×0.996, 1256 ×0.746, 1257 ×0.785, 1258 ×0.690, 1259 ×0.796,
1260 ×0.880 (1254 and 1261 stock). Same gain for red, green and blue: the gain is per column, not per colour.

## 4. Progress at 50 % grey (128)

**Bakes 1–4**, camera, summed shortfall over the band's 10 columns (sum of 1 − column/healthy; 0 = perfect):

| State | Red | Green | Blue |
|---|---|---|---|
| No correction | 3.63 | 3.90 | 4.44 |
| Bake 1 | 3.64 | 3.82 | 4.72 |
| Bake 2 | 0.82 | 1.03 | 1.76 |
| Bake 3 | 0.90 | 1.12 | 1.99 |
| Bake 4 | 0.66 | 0.80 | 1.53 |

**Bakes 8–10 and the runtime layer**, camera, columns 1255 / 1256 / 1257 / 1258 / 1259 / 1260 (per-colour column labels
can be off by one):

| State | Red | Green | Blue |
|---|---|---|---|
| Bake 8 | .94 / .92 / .91 / .90 / .92 / .97 | .96 / .87 / .92 / .88 / .93 / .93 | .88 / .81 / .80 / .73 / .72 / .81 |
| Bake 9 | .94 / .92 / .93 / .92 / .95 / .99 | .94 / .88 / .93 / .89 / .94 / .95 | .86 / .81 / .82 / .74 / .72 / .84 |
| Bake 10 | .97 / .94 / .92 / .91 / .93 / .97 | .97 / .92 / .90 / .91 / .92 / .95 | .89 / .84 / .80 / .75 / .81 / .87 |
| Bake 10 + runtime trims + blue weight ×3 (range) | 1.00–1.03 | 0.99–1.02 | 0.94–0.99 |
| Bake 11 + runtime trims + blue weight ×4 (range) | 0.97–1.00 | 0.98–1.01 | 0.99–1.03 |

Bake 10 alone left bright scenes 6–9 % short (white: red .92, green .91, blue .85 at the worst column). The runtime layer
closed that.

## 5. Runtime layer (RAM only, re-applied after every controller boot)

| Test | Change | Result |
|---|---|---|
| Runtime gain, band lanes | −25 % | about +5–6 % light per band column at mid/high grey, +8 % near black, **equal in R/G/B** |
| Dose | −25 % / −40 % on four lanes | linear (about 0.9×), no clamp to −40 %; healthy field within ±1.5 % |
| Blue runtime weight (panel-wide) | stock → ×0, ×2, ×3 | scales the blue compensation strength exactly; R/G unchanged |
| Blue weight on the healthy panel | per +100 units (stock 205) | healthy blue about −1 % (the white gets slightly warmer) |

Blue weight 615 (×3) against 820 (×4), band blue ÷ mean(red, green), camera:

| Grey | 128 | 77 | 51 | 26 |
|---|---|---|---|---|
| ×3 (615) | 0.95 | 0.86 | 0.73 | 0.53 |
| ×4 (820), chosen | 1.00 | 0.91 | 0.81 | 0.57 |

The price is blue on the band at white (band blue against healthy blue, worst column): about 1.09 with bake 11 at
weight 820 (limit set at 1.10).

Final runtime gains (relative to the stock runtime value): lanes 627 / 628 / 629 / 630 = ×0.90 / ×0.67 / ×0.60 / ×0.78.

## 6. What bake 11 changed in dark greys

Bake 10 + runtime layer (blue ×4) left red/green over-driven at low grey (a reddish/yellow-green glow). Bake 11 raised
the stored readings of the band by 6–13 counts and deepened two runtime gains. Camera, band maximum:

| Grey | 255 | 128 | 77 | 51 | 26 | 13 |
|---|---|---|---|---|---|---|
| Luminance before bake 11 | 1.02 | 1.02 | 1.04 | 1.09 | 1.20 | 1.56 |
| Luminance with bake 11 | 1.01 | 1.01 | 1.02 | 1.02 | 1.01 | 1.11 |
| Blue ÷ red-green (worst column) before | 1.00 | 1.00 | 0.91 | 0.81 | 0.57 | 0.40 |
| Blue ÷ red-green (worst column) with bake 11 | 1.00 | 0.99 | 0.89 | 0.77 | 0.52 | 0.45 |

## 7. Why blue stays short: the floor

Stored blue minus red on the band after bake 11 (columns 1255–1260), against the lowest value any combination of
per-column gains can reach at a usable red level (40,000 random simulated gain sets):

| Column | 1255 | 1256 | 1257 | 1258 | 1259 | 1260 |
|---|---|---|---|---|---|---|
| Bake 11, counts | +34 | +54 | +73 | +86 | +52 | +46 |
| Floor, counts | +33 | +50 | +69 | +84 | +50 | +42 |

The damaged columns' own blue reads about 125–155 counts above their red at any usable gain, and the firmware's
vertical-line repair gives every band column at least one damaged neighbour's reading. Bake 11 sits on the floor.

## 8. Other levers measured

| Lever | Result |
|---|---|
| Runtime gain on the damaged core before any bake | No response (the core read above neutral) |
| Compensation enable and gate registers off for 30–50 s | No change in band or healthy field |
| Panel curve tables (one field at a time) | Band blue moved at most +0.03 where +0.5 was needed; the tables act on the whole panel; one table write made the controller report a fault and restart |
| Editing the blue part of the scan's raw measurement | Stored blue became equal to red on the band and blue on photos was 0.93–1.07 at grey 26; but bulk writes over the controller's debug channel proved unreliable, so that method was dropped. A result would also last only until the next nightly scan |
| Red/green runtime weights | Act like the blue weight (gain-like, only 1.8× stronger at grey 26 than at white); alone they cannot flatten the low-grey excess; with a small re-bake about 3 points better at grey 26 (not needed by the owner) |

## 9. Reliability

| Item | Result |
|---|---|
| Scan-to-scan repeat of the stored band, same gains | about 1 count (healthy columns sd 0.5) |
| Day-to-day drift of the damaged columns' own readings | 0.6–0.9 % over a few days (about ±5–7 % light at grey 26 with fixed gains); tracking not built yet |
| Blackout mask, controller boots since the last watcher fix | 24 of 24 clean, 0 blackouts |
| On-demand scans, TV back to normal | 14 of 14 whose TV restart fell between 10:39 and 01:43 TV local; the 2 whose restart fell after 02:00 came back with a dark screen (one restart fixed each; cause unknown, so only a time-window rule) |
| Natural standby scans | Do not restart the TV; first one under the final automation still to be verified |
