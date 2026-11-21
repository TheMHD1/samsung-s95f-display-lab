# Lane-mask watcher: the blackout fix

The damaged lanes kept failing a per-lane sensing check in the panel controller, which switched the picture off and was
reset by the TV in a loop (at worst every 46–51 s). The fix sets the controller's own per-lane **skip flag** (bit 0 of
the primary lane table) for **lanes 540–661**: 122 halfwords at `0x47010438`–`0x4701052A` in controller RAM. RAM clears at
every controller power-up, so this watcher re-applies the flags whenever the controller comes back.
Background and evidence: [BLACKOUT-MITIGATION.md](../../../../docs/advanced/BLACKOUT-MITIGATION.md) ·
how the tools talk to the controller: [HOW-THE-TOOLS-WORK.md](../../../../docs/advanced/tv-calibration/HOW-THE-TOOLS-WORK.md).

**Reference implementation from one S95F 77-inch on one firmware. Read it and adapt it before use.** The lane window,
addresses and controller states are this panel's; verify them on your TV read-only first.

## Files

| File | What |
| --- | --- |
| `mask_watcher.py` | The watcher (state machine, budgets, TV-side lock, alerts) |
| `run_on_tv.py` | Copies one helper build to the TV, runs it once with `dotnet`, fetches its receipt, cleans up |
| `lane-mask-watcher.service` | systemd `--user` unit template (`services/install_unit.sh lane-mask-watcher`) |
| `test_mask_watcher.py` | Offline checks (no TV) |
| `../../tcon/helpers/lane-mask-read/` | C# helper: reads the status block, context and the 122-entry window; classifies the controller (no writes) |
| `../../tcon/helpers/lane-mask-write/` | C# helper: writes the skip bits on a Clean, settled controller; exact read-back |
| `../../tcon/helpers/lane-mask-firstscan/` | C# helper: same flags during the first scan after power-on; ignores the six free-running scan-counter bytes when comparing two reads |
| `recovery/`, `test_recovery.py` | Optional recovery tools for an already-faulted controller (below) and their offline tests |

## Build the helpers

Same recipe as [GUIDE §3](../../GUIDE.md#3-build-the-helpers-source-only-no-binaries-ship), for the folders
`lane-mask-read`, `lane-mask-write`, `lane-mask-firstscan` and, for the optional recovery, `tcon-power-cycle` (output to
`<folder>/bin`). The power-cycle helper refuses to run anywhere but the TV's 32-bit ARM (`REFUSED_ARCH_ABI`). The lane-mask helpers have built-in
self-tests that need no TV:

```sh
dotnet lane-mask-read/bin/LaneMaskRead.dll --self-test                 # selfTestsPassed 662
dotnet lane-mask-write/bin/LaneMaskWrite.dll --self-test               # selfTestsPassed 662
dotnet lane-mask-firstscan/bin/LaneMaskWrite.dll --startup-mask-self-test
```

(Set `DOTNET_ROLL_FORWARD=Major` to run the net6.0 builds on a newer runtime.)

## Configure and run

1. Kit config (`config.json`): `tv.shell` (your TV root-shell template), `watcher.enabled: true`, `watcher.dir`, and
   optionally `alert.url` / `alert.token_file`. The line-fix tools then pause the watcher around their own helper runs.
2. Optional watcher config `<watcher.dir>/watcher.json` (or `$S95F_WATCHER_CONFIG`); every key is optional, see
   `DEFAULTS` in `mask_watcher.py`. Leave `role` at `primary`.
3. Offline checks: `python3 -m pytest -q services/lane-mask-watcher`.
4. Install and start: `services/install_unit.sh lane-mask-watcher`, then `systemctl --user enable --now lane-mask-watcher`.
5. Watch `<watcher.dir>/watcher-v3.log`: after each controller boot you should see the phase reach `MASKED`.
   Pause at any time with `touch <watcher.dir>/watcher.pause` (remove the file to resume).

## Recovery of a faulted controller (optional, off by default)

A controller that has already faulted (picture off) needs more than the mask. On the S95F two steps brought it back,
and both are included as optional tools in `recovery/`:

| Tool | What it does | Watcher key |
| --- | --- | --- |
| `recovery/tv_apps_home.py` | Puts the TV on its own **Apps home screen** with stock key presses (one Home, then at most 8 Right/Up along observed paths), checking after every key that the home screen still has focus. On the S95F, a faulted controller on the media-player HDMI input kept resetting until the TV showed its own Apps screen. `--check` only looks (0 keys). | `apps_cmd` |
| `recovery/tcon_power_cycle.py` + `tcon/helpers/tcon-power-cycle/` | **One stock controller power cycle**: the helper sends the TV driver's own normal off-then-on request (`/dev/tztv_tcon`, ioctl `0xc010749f`, payload 41, 2, 0, 0). No arguments, no retries, no flash. Dry unless `--run`. | `mode2_cmd` |

Turn them on in `<watcher.dir>/watcher.json` (replace `<kit>` with the kit folder):

```json
{
  "apps_cmd": ["python3", "-B", "<kit>/services/lane-mask-watcher/recovery/tv_apps_home.py"],
  "mode2_cmd": ["python3", "-B", "<kit>/services/lane-mask-watcher/recovery/tcon_power_cycle.py", "--run"]
}
```

Try each by hand first, with the TV on and the watcher paused: `tv_apps_home.py --boot <boot_id> --output /tmp/apps-1
--check` (looks only), then without `--check`; `tcon_power_cycle.py` (dry plan), then once with
`--run --output /tmp/pc-1.json` while you watch the screen. A zero return from the driver is not proof of recovery; the
watcher decides from its next controller read.

Without them the watcher **withholds recovery and alerts**; it never improvises. Order when configured: Apps home
first (and a 0-key check right before the power cycle), then the power cycle. Budgets: at most 3 power cycles per
rolling hour and 6 per day, spaced 0 / 90 / 600 s, and an owner acknowledgement (`budget_ack` file) once the budget is
used up. Both tools are S95F / Tizen specific (home UI `com.samsung.tv.csfs`, tab names, the driver request): verify on
your TV. `TV_INPUT_KEYEVENT_SHA256` can pin the TV's key tool by hash.

## Safety

- RAM only; writes only the bit-0 skip flags inside the fixed 122-halfword window, only on a Clean controller, and
  verifies every write by reading it back. A first-scan write whose outcome is unclear holds all controller access on
  that controller instance, even across a watcher restart.
- Every controller access holds the TV-side lock (`/tmp/s95f-watcher.lock`) shared with the line-fix tools.
- Trade-off: the mask turns off that one sensing-consistency check for the masked lanes. It does not repair the damage
  and does not prove that driving the damaged area long-term is safe.
