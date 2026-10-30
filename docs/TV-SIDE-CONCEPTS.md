# TV-side experiments: overview

The original release kept TV-side work at a high level. Detailed mechanisms, addresses, firmware findings and future
research are now preserved in the [advanced handbook](advanced/README.md). The normal Kodi method still requires no
TV access. This page is a short map of the alternatives.

## Working TV overlay, with limits

A root-run EFL/Wayland client drew premultiplied RGBA strips and whole-screen black alpha. Disabling compositor HWC
made the layer visible over the tested HDMI input. The effective TV canvas remained 1920×1080 and was scaled 2×,
spreading correction into neighbouring panel columns. Later Pixel Shift following worked, but odd phases remained
blur-limited. This was a real camera-measured mitigation on the retained test chain. Other sources, picture/HDR modes,
compositor versions and canvas orientation/offsets need their own calibration and acceptance.

A global MGA tone-curve gain compensated whole-screen dimming away from the line. Camera-measured background ratio
was 1.000 ± 0.2% at grey 51 under the test conditions. MGA is global, not a per-column register block. Overlay, gain
and compositor state form a coupled correction and removal procedure. [Graphics details and source](advanced/GRAPHICS-AND-GPU.md)

## Native-4K Kodi layer

The better practical correction places the strip in the player's native-4K GUI and applies HDR correction in the
raw-PQ blend shader. It can align to individual output columns without the TV graphics-plane blur. It covers Kodi
content, not every TV app/input, and Dolby/VS10 composition changes require a separate calibration.

## Root, controller and firmware work

The S95F used SDK archive-root access, not the separate Mali/GPU exploit. The external controller used a stateful USB
protocol; a bounded lane mask reduced the damaged set's sensing-consistency blackouts. Neither is a panel calibration.
The detailed [root chain](advanced/ROOT-ACCESS.md) and [communications](advanced/CONTROLLER-COMMUNICATIONS.md) are documented.

## Panel compensation: researched, not attempted

Firmware analysis found comp2/comp6 working buffers, exact strided storage descriptors, save/load code, checksum
grammar, hardware-consumer leads and a separate internal SoC demura path. It also disproved a proposed guarantee
that editing the working RAM would reset harmlessly on reboot: the stock firmware can save those regions.

No reliable coefficient mapping, isolated application point or complete backup/restore method was established. No
compensation/calibration-storage/flash edit was attempted. This does not prove a future method impossible. The
[firmware chapter](advanced/FIRMWARE-AND-COMPENSATION.md) and [future dossier](advanced/FUTURE-PANEL-CALIBRATION.md)
preserve the actual evidence and the work needed before developing a writer.

## GPU and video-plane ideas

Ordinary EFL capture worked for UI, but a sampled HDMI image was black. No full-resolution video capture/reinjection,
DMA-BUF compositor import or GPU-memory correction injection was demonstrated. Video-plane alpha boxes and a future
independent post-transform consumer remain research leads. A PC player shader with a nonlinear per-column LUT is an
alternative when decoded video is directly available. [Experiments and limits](advanced/GRAPHICS-AND-GPU.md)
