# Graphics, GPU and compositor research

There were three different graphics questions: drawing an ordinary TV overlay, accessing/correcting the real video image, and applying correction in Kodi before HDMI. Their results should not be combined into a claim that TV GPU-memory injection worked.

## Early client/capture probes

Ordinary EFL/Wayland clients could draw and remove owned surfaces. Early markers requested as 96×96 appeared 16×16 in a 320×180 screenshot; a canvas move to (192,192) appeared at (32,32). This measured a **six-to-one screenshot reduction**, not physical panel coordinates. Window move and canvas-object move were also distinct operations.

The normal EFL/TBM screenshot route produced a valid mapped XR24 buffer. An HDMI-source sample was black; an Apps UI sample contained the UI. In the examined path, software capture could zero-fill and ignore a composite failure, then still send a completion event. This means neither “API returned success” nor “HDMI was black” establishes a universal capability policy. A populated UI buffer does not establish independent video-plane capture, freshness, HDR colour correctness or a 4K physical scanout buffer.

ABI review mattered: one borrowed capture declaration had four parameters while the local ARM32 implementation read six, including stack pointers. The matched TBM map routine cleared **148 bytes** while an external declaration allocated **136**. Callback signature alone did not qualify structure size or lifetime. Copying pixels within a callback does not grant ownership of the returned surface.

No full-resolution HDMI capture/modify/reinject loop, DMA-BUF import into the compositor, arbitrary video texture access or compositor-memory patch was qualified. The `libgfx-video-output` wrapper also invokes secure GPU modes `0x301/0x302` and hides some return values; finalizing it is not proof of restoring every display state.

## Later success: TV EFL overlay and HWC

Later work superseded the early “no useful overlay” conclusion. A root-run C#/EFL client using **wayland_shm** created a small window, installed content, then showed it. Showing an empty full-size window first could produce an effectively 1×1 surface. The tested client set alpha, focus-skip, an empty input rectangle and layer 6, then drew premultiplied full-height per-canvas-column rectangles.

Initially the layer was not visible over HDMI. Disabling compositor HWC through **`enlightenment_info -hwc 0`** made the software-composited overlay visible in the tested environment. This changes compositor behaviour; it is not a portable command to run without recording/recovering the previous state and display environment. The experiments launched the client with `XDG_RUNTIME_DIR=/run` on that target.

The effective canvas remained **1920×1080**, with fixed 2× scaling into the 3840-column picture. In the later non-mirrored measured setup, image column c initially mapped to canvas `floor(c/2)`; earlier notes used a mirrored mapping. Determine orientation, offset and scale with a marker on each target rather than treating that formula as portable. A canvas impulse also affected neighbouring panel columns. The later overlay really did affect the tested HDMI chain and was camera-calibrated, but this scaling prevents a pixel-exact narrow correction. HWC/compositor version, source and picture mode, orientation and Pixel Shift profile are calibration inputs; other sources/apps/HDR modes need their own acceptance.

The adapted [GapOverlay source](../../research/tv-overlay/README.md) is included as an experimental ordinary EFL client. It does not acquire root, disable HWC, change registers or install a TV service.

## The measured global-gain trick

The TV's MGA stage is a **global RGB tone curve**, with no column coordinates. A black overlay dims the background by `(1-B/255)`; a paired whole-picture gain of approximately `1/(1-B/255)` cancels that dimming away from the strip. Different alpha/lift at the defect creates a relative local correction.

The tested FRC debugfs interface was:

```text
/sys/kernel/debug/frc/frctest/regwrite
grammar: map address MASK VALUE
```

For the retained model/driver, the experiment used 102 four-byte words across offsets **0x54200..0x54394**: three 34-word channels, starting R `0x54200`, G `0x54288`, B `0x54310`. Neutral was `0x200`; a later controller constrained gain values to `0x200..0x300` and checked all 102 readbacks. The argument order was MASK before VALUE; an old VALUE/MASK interpretation was wrong.

The controlled A/B changed red-channel gain above unity and restored the captured baseline. It showed gain was honoured and the tested graphics mix-mode 11 passed through the effective MGA path. A later coupled overlay/gain calibration measured background correction/original **1.000 ± 0.2% at grey 51**. This is experimental evidence for that chain, not proof of universal block ordering or a calibrated absolute nit scale.

These addresses are now documented for future source work. They are firmware-specific register offsets, not generic settings or an unguarded write recipe. Restoring neutral gain alone is not sufficient if a dimming overlay remains active; removing only the overlay can also leave a boosted image. Treat overlay, tone curve, keeper and compositor mode as coupled state.

## Pixel Shift and the blur limit

The TV graphics plane was later observed to move with Pixel Shift. The follower parsed kernel records of the form `BLACK PIXELSHIFT [on:1](x,y)`, waited for an actual record rather than inventing a starting shift, and moved profiles accordingly. Odd shifts place the line halfway across a 1080p canvas pixel and need separate fits.

Following improved a sample at x=6 from roughly 0.43–0.59 to 1.02–1.09. Odd-phase dark TV-app correction still had severe limitations: neighbours could reach 2.5–5× their local reference at low grey. This is a physical blur/approximation limit, not something root access alone solves.

## Why the Kodi path is better

Kodi's native-4K GUI can address one output column directly. In HDR, the patched GLES GUI-composite shader carries parameter pixels in the strip texture and performs correction in raw PQ at the blend output, including GUI/subtitles. Its conceptual premultiplied/blend-domain final-v2 form is:

```text
final = lift + (1-alpha) * (gui*gui_alpha + (1-gui_alpha)*video)
```

The existing [HDR shader documentation](../HDR-SHADER.md) and GPL-derived patch describe the implementation. This is deliberate source-controlled shader processing on the player, **not** TV memory injection. HLG is excluded from this shader path. Profile 5 VS10 remapped the GUI and invalidated calibration; other Dolby-processing paths need new tests.

After a soundbar HDMI reset, a fresh texture name and mode-change reload fixed some stale GUI cases. A later all-HDR failure required a **full player reboot**, not just Kodi restart. Correct settings and an active process were insufficient proof of correct output. The relay's idle reboot policy must be explicit rather than hidden inside a “self-healing” claim.

## Remaining GPU/plane ideas

- Video-plane alpha boxes might provide exact 4K dimming rectangles; combined global gain could offer local gain, but not arbitrary nonlinear offsets. No accepted all-source implementation exists.
- A native TV 4K graphics canvas was not achieved. The inspected display plane/memory constraints made it a boot/display-stack research task, not a window-size change.
- An independently owned post-transform buffer/consumer could be useful only after proving colour domain, coordinates, ownership, synchronization, protected-content boundaries and restoration. Root or a GPU physical-address primitive does not supply those contracts.
- A PC player with decoded video in mpv/libplacebo is a more direct research target for a nonlinear per-column LUT. It still needs output/cadence/HDR calibration and is a future alternative, not an implemented feature here.
