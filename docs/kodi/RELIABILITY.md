# Reliability: self-heal, enforcement, lessons

A correction that is wrong for a few seconds is worse than none (a bright or dark stripe draws the eye). The design
goal was: in every state the screen is either correctly corrected or completely stock.

## 1. Layers of defence

| what | where | handles |
|---|---|---|
| profile switching every 0.2 s | relay (box) | SDR/HDR/refresh-rate changes, DV/HLG/non-2160p -> no strip |
| enforcement every 0.5 s | relay | Kodi restart, lost EventServer packets: re-sends `linefix_on/strip/hdr/x` that differ |
| ordering of property changes | relay | transitions never brighter or darker than either end state |
| self-heal on HDMI re-plug / mode change | relay | stale texture/GUI state after an HDMI reset (see 2) |
| optional reboot after re-plug | relay | display chain left in a bad HDR state (see 2) |
| md5-guarded shader mount | shader-mount.sh | CoreELEC/Kodi update with a changed shader -> stock GUI, no HDR strip |
| keeper (every few s) | computer | skin update deleted the XML, 4K GUI turned off, profiles out of date, stale locks |
| locks with expiry | both | `profile.lock` ignored after 2 h, `keeper.hold` after 4 h: a crashed calibration cannot freeze things |

## 2. The HDMI re-plug incident

Rebooting the soundbar between box and TV caused two HDMI re-plugs on the box (bar restart, then the eARC handshake;
Kodi logged that a hot-plug mode switch was ignored while the HDMI connector was not ready). Afterwards the strip
stopped correcting in SDR and HDR although every Kodi property looked right. Re-applying everything fixed SDR ->
stale strip texture / GUI state. Fix 1: the relay watches `/sys/class/amhdmitx/amhdmitx0/hpd_state` (0 -> 1: re-apply
after 4 s) and output-mode changes (re-apply after 2 s), and shows the strip through a **freshly named copy**
(`/storage/linefix/rt/...-rN.png`) so Kodi must load a new texture.
Later the same night HDR correction still failed for ALL HDR content (camera: dim applied, lift missing) while SDR
worked; a Kodi restart did not help, a **reboot of the box** did. Fix 2: after a re-plug the relay reboots the box
once at a quiet moment (no video for 20 s, uptime > 5 min, at most every 30 min), saving diagnostics first. Disable
with `touch /storage/linefix/no-auto-reboot` or `auto_reboot_after_replug: false`.

## 3. Pitfalls and lessons

Kodi / JSON-RPC
- `Player.Open`'s `repeat` option is ignored; send `Player.SetRepeat` after opening.
- Some Matroska Dolby Vision test files are rejected by JSON-RPC `Player.Open`; the built-in `PlayMedia()` plays them.
- JSON-RPC replies over raw TCP (port 9090) can arrive in several chunks: read until the JSON closes.
- After starting a clip Kodi shows a "now playing" pop-up for a few seconds - wait before measuring.
- A changed skin XML needs `ReloadSkin()`; a reused texture path may be served from cache - use new file names.
- Keep heavy remote actions to a minimum during recovery; a picture action fired while Kodi was recovering froze it once.
- EventServer clients are dropped when silent; the relay pings every 30 s.
- Kodi reports the OUTPUT HDR type: DV profile 8.1 files play as hdr10/hdr10plus (HDR10 base layer) and get the strip;
  profile 5 goes through the DV engine and is not corrected. Our final player settings: Dolby Vision disabled in
  CoreELEC, allowed HDR formats = HDR10+ (DV ignored).

CoreELEC / box
- **Never read `/sys/class/amvecm/*`** (e.g. help/white-balance nodes): it crashed and rebooted the box.
- Memory: after ~70 play/stop test cycles Kodi was OOM-killed once (RSS 2.3 GB, no swap). Enabling a 1 GB swap file
  (CoreELEC swap config, swappiness 10) fixed it. Watch Kodi restarts / OOM kills in a health check.
- No `timeout` binary on CoreELEC; scripts must not rely on it.
- Don't force colour space or depth: the 444/422 profiles rely on the automatic choice (4:4:4 at 24-30 Hz, 4:2:2 at
  50/60 Hz over HDMI 2.0). Forcing RGB or 4:4:4 at 2160p60 still ended in 4:2:2 (link bandwidth) and cost two Kodi
  restarts.
- Updates: a CoreELEC update can change the shader (guard handles it), reset settings (keeper reports 4K GUI off),
  and a skin update removes the custom XML (keeper re-installs). Re-check after every update; keep the box-side files
  in version control (a nightly snapshot of `/storage/linefix`, the units and the relevant Kodi settings helped).

Your computer / scripts
- Don't stage files in `/tmp` if a service re-installs them later: it may be gone after a reboot.
- Never `pgrep -f <script>` from a shell whose own command line contains that name (it finds itself).
- Calibration scripts must restore state on ANY exit (`atexit`): once a test left the fix half-off.
- Treat "box unreachable" differently from "box not ready": a Wi-Fi hiccup must not switch the layer off and on.
- Missing values from a status probe keep their last value; one timeout must never flip SDR/HDR.

## 4. Turning it off

| scope | how |
|---|---|
| layer, instantly | `python3 linefix_skin.py off` (removes the flag, clears `linefix_on`) |
| keeper | stop it, or `touch code/keeper.pause` (also switches the layer off) |
| HDR shader | on the box: `systemctl disable --now linefix-shaders && systemctl restart kodi` |
| everything | `python3 install_box.py uninstall`, restart Kodi |
