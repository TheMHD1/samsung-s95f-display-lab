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

## Build the helpers

Same recipe as [GUIDE §3](../../GUIDE.md#3-build-the-helpers-source-only-no-binaries-ship), for the three folders
`lane-mask-read`, `lane-mask-write`, `lane-mask-firstscan` (output to `<folder>/bin`). Each has built-in self-tests
that need no TV:

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

On the S95F, a controller that had already faulted was brought back with two more tools: one that puts the TV on its
own Apps home screen (a clean picture state) and one stock controller power-cycle. They are not part of this kit. The
watcher calls them only if you configure them:

| Key | Contract |
| --- | --- |
| `apps_cmd` | argv list. Called with `--boot <boot_id> --output <dir>` (plus `--check` for a 0-key check). Must print JSON with `ok` (true when the TV is verified on its Apps home) and `keys` (list of keys sent) |
| `mode2_cmd` | argv list. Called with `--output <file>`. Exit code 0 = the controller power-cycle completed |

Without them the watcher **withholds recovery and alerts**; it never improvises. Budgets when configured: at most 3
power-cycles per rolling hour and 6 per day, spaced 0 / 90 / 600 s, and an owner acknowledgement (`budget_ack` file) once
the budget is used up.

## Safety

- RAM only; writes only the bit-0 skip flags inside the fixed 122-halfword window, only on a Clean controller, and
  verifies every write by reading it back. A first-scan write whose outcome is unclear holds all controller access on
  that controller instance, even across a watcher restart.
- Every controller access holds the TV-side lock (`/tmp/s95f-watcher.lock`) shared with the line-fix tools.
- Trade-off: the mask turns off that one sensing-consistency check for the masked lanes. It does not repair the damage
  and does not prove that driving the damaged area long-term is safe.
