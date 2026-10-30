# Safety

A damaged OLED panel needs care. These rules come from real incidents during this project.

## The panel
- **Never show bright full-screen patterns for long.** A full-screen grey 128 test frame was immediately "too
  bright, hurts the panel" on a damaged set. All clips here are small windows around the line on black; the brightest
  calibration levels are SDR 102/255 and HDR 200 nits, on screen only for the photo.
- Static patterns cause image retention: stop playback after every shot (the scripts do), don't leave a paused test
  clip on screen.
- The damaged area of our panel got warm depending on content (also before any correction). Don't leave a long
  calibration run unattended, and stop if anything smells, flickers or the panel switches itself off.
- Keep the HDR lift `L` below the level where the dead columns start to light (`L < P_th`, METHOD.md): otherwise black
  areas glow on the line. Watch a black screen and letterbox bars after calibrating.
- Pixel Shift OFF (needed unless you can follow it) slightly increases burn-in risk for static content. Consider
  turning it back on when you are not using the box.

## The TV and advanced research
- The ordinary `code/` Kodi installer does not access the TV. The separately documented root tools and experimental
  `research/tv-overlay` source are for deliberate owner-device research and are not invoked by that installer.
- Past TV-side work did change volatile display/compositor/MGA state and a bounded controller lane mask. The mask
  suppresses part of a sensing-consistency check; it is not a physical repair or proof of unchanged protection coverage.
- No compensation-buffer, calibration-storage or firmware/config-flash write was attempted. Firmware analysis found a
  real stock save path from comp2/comp6 RAM to storage: reboot is not a verified undo. A common firmware file is not a
  backup of unique panel calibration. See the [firmware findings](docs/advanced/panel/FIRMWARE-AND-COMPENSATION.md).
- Future panel programming requires a recovered format/consumer and verified backup, restore and power-loss recovery.
  The [future dossier](docs/advanced/panel/FUTURE-PANEL-CALIBRATION.md) records those gaps and the research sequence; no
  guessed panel writer is included. Do not interpret documented addresses as a ready-to-run repair procedure.
- TV overlay dimming, MGA gain and compositor state must be restored together. Stopping only one can leave the
  picture globally dimmed or boosted. Root UID alone does not supply a safe graphics ABI or controller contract.

## The box (CoreELEC)
- All changes are files under `/storage` (removable) plus one skin XML; the system image is never modified. The
  shader override is a bind mount that is only made when the stock shader matches the md5 it was patched against.
- **Never read or write `/sys/class/amvecm/*`** - reading some nodes crashed and rebooted our box.
- Don't force colour space/depth for this fix; keep a backup of `guisettings.xml` before changing Kodi settings.
- The relay may reboot the box once after an HDMI re-plug (only when idle). Disable with
  `touch /storage/linefix/no-auto-reboot` or `auto_reboot_after_replug: false`.

## Rollback
| scope | command |
|---|---|
| layer off now | `python3 code/linefix_skin.py off` |
| HDR shader off | on the box: `systemctl disable --now linefix-shaders && systemctl restart kodi` |
| everything | `python3 code/install_box.py uninstall`, then restart Kodi; optionally re-enable GUI scaling |
After uninstall the box is stock apart from the 4K GUI setting (and a swap file if you added one).
