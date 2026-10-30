# TV graphics line correction: setup and calibration workflow

[Project](../../README.md) · [Root access](ROOT-ACCESS.md) · [Graphics internals](GRAPHICS-AND-GPU.md) · [Kodi alternative](../kodi/README.md)

This is the reproduction workflow for the measured **TV-side overlay plus MGA gain** experiment. It explains how the parts fit together and where firmware-specific adaptation is still required. The public EFL client is included; a generalized TV HWC/gain controller and installer are not. The ordinary Kodi installer cannot deploy this TV backend.

## 1. Establish the matching root session

Follow the [root guide](ROOT-ACCESS.md#reproduction-entry-points): select the authorized TV, match source/payload revision, apply the S95F runtime-discovery patch where needed and verify UID/EUID. The tested root session still had SMACK label `User`. Host-assisted reacquisition is separate from installing a TV boot service.

Coordinate with the existing blackout watcher, keeper and manual tools. Record firmware/ABI, current source/picture/HDR mode, Pixel Shift state and the existing compositor/gain settings before any change. The access lock and watcher pause/reconciliation contract are described in the [blackout chapter](BLACKOUT-MITIGATION.md).

## 2. Build the overlay and verify its geometry

Build the [EFL client](../../research/tv-overlay/README.md) using a compatible .NET SDK:

```sh
dotnet build research/tv-overlay/GapOverlay.csproj -c Release
```

Stage its managed files through your authenticated TV session into a private run directory. Use the documented disabled `params.example` and finite default lifetime. The client needs the target's matched native EFL libraries; a successful host build does not qualify their ABI.

The tested launch used `XDG_RUNTIME_DIR=/run` and an effective **1920×1080** canvas. An enabled marker/owned surface must be observed at the final screen. Determine orientation, offset and the 2× canvas-to-panel scale on the target before assigning damaged columns. A nominal 4K window request did not produce a native-4K TV canvas.

In the original environment the layer appeared over HDMI after `enlightenment_info -hwc 0` changed compositor HWC state. Restore the recorded prior state on exit; do not infer it was always 1. This is a target-specific display-stack change, not a default installation command. Starting an empty full-size window before content could also produce an effectively 1×1 surface; the published client preserves the later content/show ordering.

## 3. Pair background dimming with the matched display gain

The working idea is:

```text
black overlay away from the line → background transmission (1 − B/255)
paired whole-picture gain       → approximately 1 / (1 − B/255)
different strip alpha/lift       → relative correction at damaged columns
```

MGA is a global RGB tone curve, not a per-column GPU register. The selected driver exposes the FRC debugfs register interface with grammar `map address MASK VALUE`. The [graphics chapter](GRAPHICS-AND-GPU.md#the-measured-global-gain-trick) records the 102-word layout, neutral value, inspected gain limits, readbacks and corrected argument order.

Use a matched controller that captures/restores the complete baseline, checks every intended word and serializes operations. The EFL client does not perform those writes. The published register coordinates and reference profiles are research inputs; no universal gain setter is bundled here. Do not transplant a register sequence into a different firmware or assume a flat gain fits every brightness level.

First qualify healthy-region brightness against an original/no-correction reference. The retained coupled test reached **1.000 ± 0.2% at SDR grey 51**. That single result does not prove matching at all levels or HDR modes.

## 4. Fit and measure the damaged strip

Use the [RAW-camera method](../kodi/CALIBRATION.md) for exposure discipline, geometry, colour-filter-array analysis and healthy-column references. Those measurement principles transfer to the TV experiment; the Kodi fitting commands themselves are not a TV controller backend.

The TV client's premultiplied strip parameters need their own profile. In the later measured orientation, image column `c` initially mapped to `floor(c/2)` on the canvas; verify it with a marker rather than assuming it. Include RGB/white, dark levels, mid-tones, brighter samples, black and neighbours. Keep the final source/HDR mode and healthy-region baseline in the record.

The scaled TV graphics impulse affects neighbouring columns. Pixel Shift following must start from an actual recorded shift and requires separate odd/even fits. The saved experiment improved a followed sample from roughly **0.43–0.59× to 1.02–1.09×**, but odd-phase dark tests could brighten neighbours to **2.5–5×**. That blur is why the native-4K Kodi correction is the more precise published playback solution.

## 5. Verify lifetime, cleanup and operating limits

Test bounded start/stop and verify that the owned surface disappears. Restore **overlay, MGA gain and compositor state together**: removing only the overlay can leave a boosted picture; resetting gain while dimming remains can leave the picture dark. A process exit or root-command success is not final optical verification.

Record behavior through the tested standby, source, HDMI and Pixel Shift transitions. Keep blackout recovery and optical correction as separate state machines. No full-resolution video capture/modify/reinject loop, direct TV GPU-memory picture injection or calibration flash is part of this method.

The original panel remains physically damaged. Use the bounded patterns and limits in [SAFETY.md](../../SAFETY.md). [Full results](../kodi/RESULTS-AND-LIMITS.md) distinguish this TV experiment from the sharper player correction and its near-black/highlight limits.
