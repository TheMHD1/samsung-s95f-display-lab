# Calibrating damaged QD-OLED columns through the TV's own compensation scan: step by step

This guide is for the owner of **one** damaged TV who wants to repeat the method of
[the write-up](../../docs/advanced/tv-calibration/WRITEUP.md) on their own set with the scripts in this folder. Read the
write-up first: it explains *why* each step exists. This page explains *how*.

> **Worked example values.** Every address, lane, column, word and threshold quoted below comes from **one Samsung S95F
> 77-inch on one firmware**. They are marked *S95F example*. They are not facts about your TV. Verify each one on your own
> set (step 5) before any tool writes anything.

Everything here is independent owner-device research, not affiliated with Samsung, with no warranty. You can damage your
TV. Nothing in this folder is a one-click fix.

---

## 0. Does this method apply to your panel?

The method fixes one specific failure: damaged columns whose **stored power-off sensing result reads far too HIGH**
(hundreds of counts above healthy columns). The TV's compensation only adds drive for readings below a neutral point, so
such columns get no compensation and look dim. Lowering the scan's sensing gain on those columns makes the TV's own scan
store a reading below neutral, and the TV then drives them itself.

It does **not** apply when:

| You see | Why the method cannot help |
|---|---|
| The damaged columns' stored reading (step 7) is **normal or low** (close to, or below, healthy columns) | The TV's compensation already treats them as normal or already adds drive. The dimness has another cause. Faking a lower reading would over-drive them in a way we never tested. Do not use this kit for it. |
| The columns are **electrically dead**: no light at all, even at full white, or the stored reading does not move when the gain changes | No compensation can drive a sub-pixel that does not conduct. |
| Only one colour is affected and the others read normally | The sensing gain is common to red, green and blue. You would over-drive the healthy colours. |
| The damage is a horizontal line, a single pixel, or a large area | The gain is per sense lane (two columns). The kit only handles a narrow vertical band. |

Even when it applies, expect a colour floor. On our panel blue stays short in dark greys (write-up section 10).

---

## 1. Prerequisites

You need all of these before step 2.

1. **A working root shell on your TV** that a script on another computer can run non-interactively. It must return
   the command's stdout and its exit status, as `ssh root@TV 'cmd'` does. Use the [root verification guide](https://github.com/TheMHD1/samsung-s95f-root-access/blob/main/docs/VERIFY-ROOT.md)
   to check your existing TV session. Stop here if you cannot verify root access.
2. **.NET on the TV.** The helpers are small C# programs run with `/usr/bin/dotnet`. They target net6.0. Check with
   `dotnet --list-runtimes` in your root shell.
3. **The panel controller (TCON) USB link**, visible to the TV's kernel. *S95F example:* USB device `04e8:2001` at
   `/sys/bus/usb/devices/7-1` (bus 7), interface 2, bulk endpoints OUT `0x02` / IN `0x82`. Check, read-only:
   `cat /sys/bus/usb/devices/7-1/idVendor /sys/bus/usb/devices/7-1/idProduct` should print `04e8` and `2001`.
   If yours differs, every helper needs changes (section 16). Do not guess.
4. **A camera** that saves RAW, on a tripod, close enough that one panel column spans at least 4 camera pixels (we used
   about 13). It needs a command-line capture (e.g. `gphoto2`) on the computer that runs the kit.
5. **A media player** that plays the test clips full screen and can be scripted. The kit talks to **Kodi's JSON-RPC**
   through a shell on the player (`kodi-send`, `nc`). Other players need `measure/optical.py` adapted.
6. **An always-on Linux computer** with `python3` (3.10+), `numpy`, `Pillow`, `pytest`, optionally `rawpy` (RAW
   decoding), `ffmpeg` (clips), `docker` (helper build) and `systemd --user` (services).
7. Your TV's **TCON package** file (`F_RSM1_*_COMMON.bin` on the S95F) from its own firmware. The backup tool only reads
   its storage map. Firmware images are not part of this kit.
8. **Firmware auto-update OFF** on the TV. An update can remove the access, the calibration and everything else.

---

## 2. Install and configure (no TV contact)

1. Copy the configuration and edit it. Every value in the example is a placeholder.
   ```sh
   cd tools/tcon-calibration
   cp config.example.json config.json
   ```

   | Key | Meaning |
   |---|---|
   | `work_dir` | Where captures, backups, logs and service state go (default `./work`). Keep it backed up. |
   | `tv.shell` | argv template that runs `{cmd}` as root on the TV and returns its stdout and exit code. Without `{cmd}` the command goes to stdin. |
   | `tv.forward` / `tv.forward_remove` | Optional `{port}` forward for faster dump fetches. Default: base64 over `tv.shell`. |
   | `tv.timezone` | The TV's local time: an IANA zone name or a fixed offset like `+01:00`. `null` = this computer's zone. |
   | `tv.bake_window` | On-demand calibration runs (one TV scan with your gains set; §9) are allowed only inside this TV-local window. *S95F example:* `10:30`–`01:15` (see 14.1). |
   | `tv.key_cmd` | Optional `{key}` remote-key command, used only to dismiss the TV screensaver before photos. |
   | `tv.player_input` | TV source name of the player's input (*S95F example:* `SOURCE_TYPE_HDMI3`). |
   | `watcher.enabled` / `watcher.dir` | Only if you run an external blackout lane-mask watcher that uses the same pause/state files. Default off. |
   | `player.shell`, `player.clip_dir`, `player.jsonrpc_port` | Shell on the player (`{cmd}`), where the clips are, and Kodi's JSON-RPC TCP port. |
   | `camera.capture` | Takes ONE photo to `{out}.<ext>` and prints the file path. It may also print `SHUTTER=1/50` (the dark-screen guard uses it). `{shutter}` is the requested exposure or `auto`. |
   | `camera.raw_cmd` / `camera.jpeg_cmd` | Optional commands that switch the camera's image format. |
   | `camera.keep_photos` | Keep the photos after analysis (default: delete, like the original). |
   | `camera.analysis` | Bar geometry for `colratio.py`: `first_column` 1100, `bar_columns` 320, `rows` (fraction of photo height), optional `unmix` (step 6.5). |
   | `alert.url` / `alert.token_file` | Optional HTTP POST endpoint for service alerts (Bearer token read from the file at run time). |

2. Check the settings: `python3 -B config.py show`.
3. Run the offline tests. They never contact a device.
   ```sh
   TCON_KIT_WORK=/tmp/tcon-test python3 -m pytest -q offline measure services
   ```
4. First TV contact, read-only: check identity, controller presence and power state through your configured shell.
   ```sh
   python3 -B -c "import config as C; print(C.tv_root('id -u; cat /proc/sys/kernel/random/boot_id; \
   cat /sys/bus/usb/devices/7-1/idVendor /sys/bus/usb/devices/7-1/idProduct /sys/bus/usb/devices/7-1/devnum; \
   /usr/bin/dotnet --list-runtimes'))"
   ```
   Expect `0`, a boot id, `04e8`, `2001`, a device number and a .NET runtime line.

---

## 3. Build the helpers (source only, no binaries ship)

Three variants of one C# helper, `TconDump`:

| Folder | Used by | Writes |
|---|---|---|
| `tcon/helpers/read-poke/` | `tvdump.py` (bulk reads), `tvtool.py` (`--poke`/`--watch`/`--restore`), `bake_now.py` (`--armwait`) | RAM only: words of lanes 600–660 in the three gain arrays (S0, S1, third array `0x58698800`) and 12 enable words (0/1), bounded |
| `tcon/helpers/scan-arm/` | `services/s0-nightly` (`--armwait` with SIGTERM cancel and restore on abnormal exit) | RAM only, as above |
| `tcon/helpers/runtime/` | `tcon/rt_tool.py` (`--rt audit/apply/apply-s1/restore`) | RAM only: S1 lanes 627–630 and the weight pairs, hard-coded addresses and stock words |

`NuGet.Config` clears all online package sources on purpose (builds are offline and reproducible). The SDK 10 image still
needs the .NET 6 targeting pack once, so fill a local package cache first:

```sh
cd tools/tcon-calibration/tcon/helpers
mkdir -p ~/.cache/tcon-nuget
# once, online: restore into the cache (--source overrides the cleared NuGet.Config sources for this one call)
docker run --rm --user $(id -u):$(id -g) -e HOME=/tmp -e DOTNET_CLI_TELEMETRY_OPTOUT=1 -e NUGET_PACKAGES=/cache \
  -v $PWD/read-poke:/w -v ~/.cache/tcon-nuget:/cache mcr.microsoft.com/dotnet/sdk:10.0 \
  dotnet restore /w/TconDump.csproj --source https://api.nuget.org/v3/index.json
# every build, offline from the cache
for h in read-poke scan-arm runtime; do
  docker run --rm --user $(id -u):$(id -g) -e HOME=/tmp -e DOTNET_CLI_TELEMETRY_OPTOUT=1 -e NUGET_PACKAGES=/cache \
    -v $PWD/$h:/w -v ~/.cache/tcon-nuget:/cache mcr.microsoft.com/dotnet/sdk:10.0 \
    dotnet build /w/TconDump.csproj -c Release -o /w/bin
done
```

Each `bin/` must contain `TconDump.dll`, `TconDump.runtimeconfig.json` and `TconDump.deps.json`. Read the source before
you run it. The bounds are in `CheckAddr`, `CheckVal`, `CheckPoke`, `Clean` and (runtime) `RtParse`.

The services refuse an unpinned helper. Pin your build (after review) whenever you rebuild:
`python3 -B tcon/pin_helper.py scan-arm <work>/s0svc/plan.json` and
`python3 -B tcon/pin_helper.py runtime <work>/rtsvc/rt_plan.json` (create the plans first, steps 11–12).

---

## 4. Safety rules and the backup

Every tool enforces these rules. Do not weaken them:

1. **Read before write.** A full hash-checked backup of controller storage comes before any write of any kind.
2. **First write ever = identity write**: the current value written back, then read back and compared (step 5.3).
3. **RAM only.** Each write is verified by read-back. The restore path does not depend on the current value. The
   controller clears everything at every power-down.
4. **Hard bounds.** S0 halves ×0.65–1.00 of stock (`0x2A1C`–`0x40CA`). S1 never above stock, at least 9900, and at most
   8000 below stock. Blue weight 205–820. At most 8000 counts per poke step. Small steps near neutral.
5. **Stop on any non-Clean controller state.** The helpers check the status block (*S95F example:* `0x47012400`) before
   and during every claim. Clean = stop 0, fault 0, gate 1, limit 40 (gate may read 0 during off-sensing).
6. **On-demand calibration runs only inside `tv.bake_window`**, only on a boot that looks healthy, with exactly one reboot as the
   dark-screen remedy, then stop (14.1).
7. **No static test pictures on the OLED.** The tools blank the player after every batch. Keep batches short (≤ 10 min).
8. **Never run a live-capable command "to test argument parsing".** Use the offline tests. Have every change to a tool
   reviewed by someone else before it touches the TV.
9. **One variable per calibration run.** Predict each result first, then compare with the prediction before the next step.

Backup (read-only, 19 storage items, resumable, writes `<work>/backup/` + `MANIFEST.json` with sha256):

```sh
python3 -B tcon/backup_items.py /path/to/your/F_RSM1_..._COMMON.bin
```

Copy `<work>/backup/` somewhere safe, off the computer. `d4store.py` needs its `MANIFEST.json`, so nothing later works
without this step.

---

## 5. Verify the layout on your TV (read-only, then one identity write)

1. Dump the S0 and S1 arrays and the weights (one helper run, read-only):
   ```sh
   python3 -B tcon/tvdump.py --name verify --ranges 58691000:a00,58694c00:a00,586026f8:c
   python3 -c "import numpy as np, sys; sys.path.insert(0,'.'); import config as C; \
   d=np.fromfile(C.CAPTURES/'verify'/'dump.bin','<u4'); L=range(624,634); \
   print('S0', [hex(d[i]) for i in L]); print('S1', [hex(d[640+i]) for i in L]); print('RGB weights', list(d[1280:1283]))"
   ```
   *S95F example:* S0 is `0x40CA40CA` on every lane. S1 differs per lane (627–630: `0x40AA40AE 0x40A340A6 0x409B409F
   0x40944098`). The weights are `205 205 205`. If your values differ, the hard-coded stocks in the tools are wrong for
   your TV (section 16). Stop and adapt before any write.
2. Map lanes to columns. Lane L covers panel columns 2L (low 16 bits of the word) and 2L+1 (high 16 bits).
   `offline/s0words.py decode s0 628 0x32E03055` shows this.
3. Identity write, once, on a lane inside your band (writes the stock value back and reads it back):
   ```sh
   python3 -B tcon/tvtool.py --poke 586919d4:40ca40ca:40ca40ca
   ```
   The JSON result must have `writes` `["586919d4:40ca40ca->40ca40ca"]`, and the `before`/`after` states must be Clean.

---

## 6. Measure the line

1. Make the test clips: 320-column bars at exact codes, panel columns 1100–1419, black elsewhere, SDR BT.709, 60 s.
   If your band is not inside 1100–1419, change the column range in `measure/mkclip.py` and `camera.analysis.first_column`.
   ```sh
   python3 measure/mkclip.py <work>/clips grey4:4:4:4 grey8:8:8:8 grey13:13:13:13 grey26:26:26:26 grey51:51:51:51 \
     grey77:77:77:77 grey128:128:128:128 grey204:204:204:204 grey255:255:255:255 xred153:153:0:0 xgreen153:0:153:0 xblue153:0:0:153
   ```
   Copy `<work>/clips/*.mp4` to `player.clip_dir` on the player.
2. Set up the TV: SDR, one fixed picture mode (we used Movie), energy saving and automatic brightness off, the same
   settings for every session. The room should be dark and stable.
3. Set up the camera: tripod, RAW, manual focus on the column grid, manual white balance. Frame the band with at least 50
   healthy columns on each side. The bar must be the only light in the frame.
4. One measurement (plays the clip, checks the TV shows the player, takes one photo, prints ratios, blanks the player):
   ```sh
   python3 -B measure/optical.py grey51 auto base-grey51
   ```
   Or analyse a photo you took yourself, fully offline:
   ```sh
   python3 measure/colratio.py photo.ARW --first-column 1100 --json base-grey51.json
   ```
   The output lists, per panel column, R/G/B and luminance divided by the median of healthy columns 14–45 columns away
   on both sides **in the same photo**. 1.00 means as bright as the neighbours. Check that `period` matches your
   framing, that the darkest window sits on your band, and that `saturated` is 0.
5. Sub-pixel unmixing (recommended). Camera channels overlap: on our panel the camera's green saw about 20 % blue light.
   Shoot `xred153`, `xgreen153` and `xblue153` with the same settings, then:
   ```sh
   python3 measure/colratio.py mixmatrix red.ARW green.ARW blue.ARW --out <work>/unmix.json
   ```
   Copy the `unmix` matrix into `camera.analysis.unmix`. Without it, missing blue hides inside the camera's green.
6. `colratio.py` is a deliberately simple starting point (it is not the analysis behind the published numbers). It
   assumes vertical columns, a linear image and a resolved column grid. Validate it against your own eye and a second
   photo before you trust a step on it.

---

## 7. Diagnose: does the stored reading of the damaged columns read HIGH?

```sh
python3 -B tcon/d4store.py live d4-base > <work>/captures/d4-base.json
```

This reads the stored power-off sensing result ("D4") of both banks. For each colour it prints the healthy reference
(median of columns 1200–1249) and each listed column minus that reference. The listed columns are the *S95F example*
1254–1261 and 1278–1282. Edit the tuple in `report()` for your band. `gen` is the scan generation of each bank. The
newer bank is the one in use.

- Damaged columns **hundreds of counts above** the reference (ours: R/G +100…+300, B more): the method applies.
- Normal or below: stop (section 0).

---

## 8. Baseline before the first calibration run

`after_now.sh TAG PREV` compares a calibration run with the captures of the previous tag: `d4-PREV`, `c1-ddr-PREV` and the photo set
`post-PREV`. Make the baseline set `base` now, with the TV on and showing the player:

```sh
R=$(python3 -c "print(','.join(f'{0x755b8000+n*0x388400:x}:fe000' for n in range(12)))")   # live C1 in DDR, S95F example
python3 -B tcon/tvdump.py --name c1-ddr-base --chunk 4096 --budget-ms 15000 --ranges $R
python3 -B -c "import sys; sys.path.insert(0, 'tcon'); import bake_eval as E; c = E.read_c1('c1-ddr-base'); \
d = E.read_d4('d4-base'); print('C1 row 0 == stored D4 - 2047:', bool((c == d.row0[:, E.C1_COLUMNS] - E.D4_TO_C1).all()))"
python3 -B measure/postbake.py post-base
```

The C1 line must print `True` (the live correction table was rebuilt from the stored scan, as the night audit expects).

`d4-base` comes from step 7. `postbake.py` shoots grey 128/77/204, the three primaries and grey 4/8/13 (the original set
also had a `split32` clip that `mkclip.py` cannot make: `--split32` is opt-in).

---

## 9. First calibration run

A "calibration run" sets the S0 sensing gain in controller RAM at the moment the TV's own power-off scan starts. The scan then stores
its result, and the TV saves it to flash itself. The kit uses the TV's own on-demand scan (*Screen Optimization*, "Start
Now"; TV off for about 12 minutes, then back on by itself).

1. Stop anything else that talks to the TV (`systemctl --user stop s0-nightly s95f-rt s95f-bake11-guard` if installed).
   The TV must be on, showing a blank player, inside `tv.bake_window`.
2. Compute the words. Start with both halves of the worst lanes at ×0.80:
   ```sh
   python3 -B offline/s0words.py s0 628=0.80 629=0.80
   ```
   It prints the `pokes` string `ADDR:OLD:NEW,...` and refuses anything outside the tools' bounds.
3. Calibration run, then evaluate:
   ```sh
   python3 -B tcon/bake_now.py <pokes>          # --dry first: stages and starts the TV-side monitors only, no request
   bash tcon/after_now.sh bake1 base
   ```
   `bake_now.py` refuses outside the window, refuses if another arming tool runs, and checks every poke (S0 lanes only,
   stock pre-value, floor ×0.65). It writes only when the controller powers back up for the scan. If the controller never
   power-cycles, nothing is written. `after_now.sh` then reads D4 and C1, runs `bake_eval.py`
   (`<work>/captures/eval-bake1.txt`) and photographs (`<work>/after_bake1.log`).
4. What to expect. A small first step can store a lower reading and change **nothing** on screen, because the reading is
   still above neutral (our ×0.85 calibration run). That is not a failure. Our ×0.80 calibration run closed about 75 % of the red/green gap.
5. **Rollback is always one unarmed scan away**: any scan that runs without the kit stores the stock result again.

---

## 10. Iterate per column

1. Change one or two lanes per calibration run, in steps of ≤ 0.05 of gain near the point where the light starts to respond.
   Overshoot is strongly non-linear: our run 5 made two columns glow 11–29× too bright near black.
2. **Look at near-black (grey 13 and 26) after every calibration run**, not only at mid grey. Overshoot shows at 2–5 % grey first.
3. Use per-column halves once lanes respond: `s0words.py s0 628=0x3055,0x32E0` (even, odd). The tools allow unequal halves
   only on band lanes 626–632 (*S95F example*; edit `bake_now.py` and `s0_nightly.py` for your band, with review).
4. Model the firmware's **vertical-line repair**. After the scan, a stored column that differs from both neighbours by
   more than about 40–45 counts is replaced by the mean of the three largest of its four nearest neighbours. Columns in a
   damaged band therefore inherit their neighbours' readings, and lanes couple. Without this, per-lane results make no
   sense.
5. A repeat calibration run of the same words reproduces the stored result to about one count (our run 6). Use that to separate
   drift from effect.
6. Keep a log per calibration run: words, prediction, stored result, photos. `tcon/check_bake11.py` shows how we checked our final
   calibration run against its prediction. Its expected values are *S95F example* only.

---

## 11. Runtime trims (S1) and the blue weight

After the calibration runs, two RAM-only settings act on top. Both clear at every controller boot:

- **S1 runtime gain** per lane (used by the real-time correction loop while the TV is on): acts like a brightness gain on
  the band, about +5–6 % light per −25 % gain, equal in R/G/B.
- **Blue runtime weight** (pair `0x58602700`/`0x58622700`, stock 205, bound 205–820): scales the blue compensation, mostly
  on the band. The healthy panel's blue drops about 1 % per +100.

1. Create the plan from the example and edit the NEW words:
   ```sh
   cp examples/rt_plan-bake11.json <work>/rtsvc/rt_plan.json
   python3 -B offline/s0words.py s1 628:0x40A340A6=0.67,0.67      # S1 word from the lane's STOCK word
   python3 -B tcon/pin_helper.py runtime <work>/rtsvc/rt_plan.json
   ```
   The lanes (627–630) and their stock words are hard-coded in `tcon/rt_tool.py` (`LANES`) **and** in the runtime helper
   (`RtS1`/`RtStock`). For another band, change both, rebuild, and have it reviewed.

   The runtime helper also refuses to write until it knows YOUR gain block (`CaRefSha`, `CaS1Ref` are placeholders).
   Right after a normal power-on, before any trim:
   ```sh
   python3 -B tcon/tvdump.py --name ca-ref --ranges 58691000:16800
   python3 -B offline/ca_ref.py <work>/captures/ca-ref/dump.bin   # prints the two C# lines
   ```
   Paste them over the placeholders in `tcon/helpers/runtime/Program.cs`, rebuild, re-pin (`pin_helper.py`).
   Optional red/green weights in a plan are bounded 205–430; blue 205–820.
2. Audit, apply, audit, and undo if needed:
   ```sh
   python3 -B tcon/rt_tool.py audit      # expect s1_state stock, blue_state stock, weights 205 x6
   python3 -B tcon/rt_tool.py apply      # waits for a bank flip (<= 100 s), writes S1, ramps blue in steps <= 64
   python3 -B tcon/rt_tool.py audit      # expect plan / plan
   python3 -B tcon/rt_tool.py restore    # back to stock at any time
   ```
3. Photograph after each change (step 6.4, or `postbake.py`). Fit S1 for bright greys and blue for colour balance. Then
   re-tune the scan-time gain if low greys are over-driven (our final calibration).

---

## 12. Automation (reference implementations: adapt before use)

The stored calibration lasts until the next scan without the kit. The trims last until the next controller boot. Three services keep
both in place. They are the code that ran on our TV, with the private parts moved to `config.py`. They carry our
thresholds, lanes and final calibration words. Read each one, adapt it, and run its offline tests (`pytest -q services/...`)
before you enable it.

1. **Night service** `services/s0-nightly/` arms the S0 words for every standby scan that the TV announces ("off sensing
   required before power off" in the kernel log). It accepts the controller wake 11–21 min after standby (*S95F example*
   timing), audits the stored result once the TV has been on ≥ 5 min (`morning_audit.py`), and **latches off** on a bad
   result (`--status`, `--reset`).
   ```sh
   cp examples/s0-plan-bake11.json <work>/s0svc/plan.json
   python3 -B tcon/pin_helper.py scan-arm <work>/s0svc/plan.json
   bash services/s0-nightly/deploy.sh 627=0x408A40CA,628=0x32E03055,629=0x339A2CB4,630=0x40CA3904 d4-bake11
   ```
   The reference capture (here `d4-bake11`) must be the D4 of an on-demand calibration run with exactly these words.
2. **Runtime service** `services/s95f-rt/` re-applies the plan after each new controller boot (at most 3 applies per
   boot, audits at +90 s, +10 min, then every 30 min). It never runs a helper unless the TV reports `lcdon` and the
   controller is present.
   ```sh
   bash services/install_unit.sh s95f-rt && systemctl --user enable --now s95f-rt
   touch <work>/rtsvc/rt.disable          # kill switch (the service idles while it exists)
   ```
3. **Guard** `services/bake11-guard/` reads the stored calibration at each controller boot and every 12 h. If it is gone,
   it switches the trims off at once, repeats the calibration run at a quiet moment inside the window (at most twice per 24 h), and stops
   after two failures. Adapt `WORDS`, `POKES`, `REF`, `BAND` and the signatures in `compare()` in `restore_bake11.py`, and
   copy your plan to `<work>/rtsvc/rt_plan-bake11.json`. Its "quiet" test needs Kodi and `tv.player_input`. The `--l2`
   and `--probe` research modes are not part of this kit and are refused.
   ```sh
   python3 -B services/bake11-guard/restore_bake11.py --check     # read-only: ok / drift / foreign
   bash services/install_unit.sh s95f-bake11-guard && systemctl --user enable --now s95f-bake11-guard
   ```
4. Not covered by any service: firmware updates, factory resets and loss of the computer.

---

## 13. Verify on real content

Calibration photos are not the finish line:

1. Watch dark scenes (5–20 % grey content, night skies, dim interiors), bright scenes, flat-colour fields and moving
   pans, at your normal viewing distance, from both the player and the TV's own apps (the fix is TV-side).
2. Re-measure after the first nights under automation. The stored readings of the damaged columns can drift (ours by
   0.6–0.9 % in a few days, about ±5–7 % of band light at 10 % grey).
3. Anything that looks wrong: take the photo set again (`postbake.py`) before you change words.

---

## 14. Recovery

1. **Dark screen after an on-demand calibration run** (TV reports `lcdon`, the controller USB device is absent, the kernel log repeats
   `tcon power(0)`). Twice on our TV, both when the restart after the scan fell after 02:00 TV local, hence the window.
   Run **one** root `reboot` of the TV. If it is still dark, unplug the TV at the wall for 10 s. Do not try other
   remedies. `restore_bake11.py` does the single reboot automatically, saves read-only diagnostics and then stops.
2. **Lost calibration** (a scan ran without the kit, a menu Screen Optimization, a computer outage): switch the trims off
   (`touch <work>/rtsvc/rt.disable; python3 -B tcon/rt_tool.py restore`), then repeat the calibration run with your words (step 9) or let the
   guard do it.
3. **Undo everything**: stop the services, `python3 -B tcon/rt_tool.py restore`, then let one standby scan run unarmed or
   start Screen Optimization from the menu. The stock result is stored again. A power cycle clears all RAM settings.
4. **Controller not Clean / helper refuses**: do nothing more. Put the TV in standby, wait for it to come back on, and run
   the read-only `rt_tool.py audit` or `tvdump.py`. Never force past a refusal.
5. **Blackout** (picture black, sound continues) is a different fault and this kit does not address it. See
   [BLACKOUT-MITIGATION.md](../../docs/advanced/BLACKOUT-MITIGATION.md). If you run such a watcher, set
   `watcher.enabled` so the tools pause it around helper runs.
6. **`s0-nightly` LATCHED**: read `<work>/s0svc/s0_nightly.log`, fix the cause, then
   `python3 -B services/s0-nightly/s0_nightly.py --reset`.

---

## 15. What NOT to write

| Never write | Why |
|---|---|
| Stored compensation, demura data, controller flash (storage), TV eMMC, boot areas, factory data | A bad write can brick the panel. The stored result changes only through the TV's own scan and save. The helpers have no storage-write path. |
| Panel curve tables (*S95F example:* B3 `0x58614000`, C3 `0x58615000`) | They act panel-wide, not per column. One test write made our controller report a fault and restart itself. |
| The BE block (*S95F example:* `0x58650000`) | Read-only in the helpers' allowlist. Leave it so. |
| Bulk edits of the scan's raw sensing plane during the scan | It worked where applied, but a full run is about 6,500 writes and the debug channel lost about 1 write in 3,600. Dropped. Not in this kit. |
| Compensation enable/gate words as an experiment | No visible effect in 30–50 s tests. The helpers allow only 0/1 on them, for restore. |
| Anything outside the helpers' allowlists, or new bounds without review | The bounds are the safety case. |

Not used, for reference: `0x58698800` is a third gain array, and the mode-3 offset array is `0x5869C400` (stock
`0x11401140`). The tools never write either for calibration.

---

## 16. Adapting to another TV: where the S95F values live

| Item (*S95F example*) | Where |
|---|---|
| USB path `7-1`, bus 7, ids `04e8:2001`, interface 2, endpoints `0x02`/`0x82` | `tcon/helpers/*/Program.cs` (`Usb`, `Claimed`, `Xfer`), the power/USB probes in the Python tools |
| Status block `0x47012400` and the Clean signature | `R()` / `Clean()` in every helper |
| S0 `0x58691000`, S1 `0x58694C00`, lanes 600–660, halves 8000–26000 | helpers `CaBase`, `CheckAddr`, `Half`; `offline/s0words.py` |
| Your gain-block reference (`CaRefSha`, `CaS1Ref`; placeholders, apply refuses until set) | `tcon/helpers/runtime/Program.cs`; generate with `offline/ca_ref.py` (section 11) |
| On-demand lanes 600–679, per-column halves 626–632, lane-640 rider, floor `0x2A1C` | `tcon/bake_now.py` |
| Night-service lanes, per-column lanes, wake window 11–21 min | `services/s0-nightly/s0_nightly.py` |
| S1 lanes 627–630 + stock words, blue pair, bounds | `tcon/rt_tool.py` `LANES`; runtime helper `RtS1`/`RtStock` |
| D4 plane 1920×2160 pitch 2880, healthy columns 1200–1250, report columns | `tcon/d4store.py`, `tcon/bake_eval.py`, `tcon/rowaudit.py` |
| Live C1 in DDR `0x755B8000 + n×0x388400` | `tcon/after_now.sh`, `services/s0-nightly/s0_nightly.py` |
| Audit tolerances and band | `services/s0-nightly/morning_audit.py` (`SKIP`, `BAND`, `BAND_TOL`) |
| Approved calibration, expected deltas, signatures | `services/bake11-guard/restore_bake11.py`, `tcon/check_bake11.py` |
| Test bar columns 1100–1419 | `measure/mkclip.py`, `camera.analysis` |
| Pre-photo screen check (Tizen `buxton2ctl` source, `enlightenment_info` OSD dump, screensaver process) | `measure/screencheck.py` |
| Power state / scan request (`deviced` D-Bus `GetPowerState`, `RequestOffSensing`), kernel log lines | `tcon/bake_now.py`, `tcon/rt_tool.py`, `services/*` |

Every change there changes a safety bound. Have it reviewed, and test offline before the TV sees it.

---

## 17. Worked example: the S95F 77-inch final state (this firmware only; verify on your own TV)

| Layer | Values |
|---|---|
| Damaged columns | 1255–1260 (lanes 627–630) |
| S0 words of the final calibration | 627 `0x408A40CA`, 628 `0x32E03055`, 629 `0x339A2CB4`, 630 `0x40CA3904` (`examples/s0-plan-bake11.json`) |
| S1 runtime words | 627 `0x3A333A36`, 628 `0x2B4E2B50`, 629 `0x26C326C6`, 630 `0x325F3262` (`examples/rt_plan-bake11.json`) |
| Blue weight | 820 on `0x58602700` + `0x58622700` (R/G stay 205) |
| Result (camera, band vs. panel) | luminance within 1–2 % from 30 % grey to white, +3 % at 20 %, +6 % at 10 %; blue short in dark greys |

These words fit one panel's damage. Copied to another TV they will at best do nothing and at worst over-drive healthy
or damaged columns.
