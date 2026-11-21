# RT-SPEC: power-on runtime service (Claude, from design note CONSULT-14 §5–§6)

> Public kit note: this is the original build spec, kept for the reasoning. Paths now come from `config.py`:
> `rtsvc/` = `<work>/rtsvc/` (state) with the code in `tcon/rt_tool.py` and `services/s95f-rt/`; `TconDump-rt/` =
> `tcon/helpers/runtime/`; the watcher files are in `watcher.dir` and only used when `watcher.enabled` is true; alerts go to
> the optional `alert.url`. Addresses and stock words are the S95F 77-inch values (this firmware only; verify on your TV).

Goal: at every TV power-on (controller boot), re-apply the runtime S1 gains on lanes 627–630 and the blue runtime weight,
because both are RAM-only and clear at each controller boot. (CONSULT-14 is an internal design note, not included.) New files go in `rtsvc/` and `TconDump-rt/`.
Existing files must keep working unchanged: the blackout watcher, `tvtool.py`, `tvdump.py`, the read/poke helper, `s0svc/*`.

## 1. Helper `TconDump-rt/` (C#; copy of `TconDump-e2/`, add one command)

Build: `docker run --rm --user $(id -u):$(id -g) -e HOME=/tmp -e DOTNET_CLI_TELEMETRY_OPTOUT=1 -e NUGET_PACKAGES=/cache -v $PWD/TconDump-rt:/w -v <nuget cache>:/cache mcr.microsoft.com/dotnet/sdk:10.0 dotnet build /w/TconDump.csproj -c Release -o /w/bin`

New command `--rt` (dispatched through `Tool()` exactly like `--wpoke`; `Tool()` already claims the device and checks
Clean before and after). Arguments after the standard four: `MODE PLAN` where MODE is `audit`, `apply`, `apply-s1`,
`restore`, and PLAN is `S1A:STOCK:NEW,S1B:STOCK:NEW,S1C:STOCK:NEW,S1D:STOCK:NEW,BLUE` (hex words, BLUE decimal 205..820; CONSULT-15).

Hard bounds in C# (refuse the whole call if any fails, before any write):
- S1 addresses exactly `0x586955CC, 0x586955D0, 0x586955D4, 0x586955D8` (lanes 627..630), each once.
- STOCK per address must equal the stored stock word: `40AA40AE, 40A340A6, 409B409F, 40944098` (hard-coded).
- NEW: each 16-bit half in `[9900, that half of STOCK]` (never above stock); |STOCK half − NEW half| ≤ 8000.
- Weights: blue `0x58602700` + twin `0x58622700`, always as a pair, BLUE in `[205, 820]` (CONSULT-15). Red/green
  `0x586026F8/FC` + twins `0x586226F8/FC` stay 205 unless a plan sets them (optional, `[205, 430]`, as pairs).
- Nothing else is ever written.

Modes:
- `audit` (read-only): output `s1` (4 hex words), `s1_state` = `stock` | `plan` | `other` (all four equal STOCK / all
  four equal NEW / anything else), `weights` (six decimals in the order 26F8, 26FC, 2700, twins), `blue_state` = `stock`
  (pair 205) | `plan` (pair BLUE) | `other`, `rec` (0x450158A8), state tuple. rc 0 when the reads succeed.
- `apply` / `apply-s1`:
  1. Record `rec & 0xFFFF == 0x0803` on three reads 1 s apart.
  2. S1 words: each must be STOCK or NEW, else refuse (`S1 not stock/plan`).
  3. Weights: R/G four read 205; blue pair equal and 205 (or BLUE if all S1 are NEW = "blue rewritten" case). Otherwise refuse.
  4. If all S1 are NEW and (mode is `apply-s1` or the blue pair == BLUE): rc 0, `already`, no writes.
  5. `WaitFlip` (existing); refuse if `flip_ms == -1`.
  6. All six weights unchanged for 5 s after the flip (existing `--wpoke` logic).
  7. Writes: each S1 word that is STOCK → NEW: re-read == STOCK right before the write (OLD check), write, read back == NEW.
     Then (mode `apply` only) blue ramp from 205 to BLUE in steps of at most 64 (205, 269, 333, …, BLUE): per step write
     `0x58602700` then `0x58622700`, read back each, 300 ms between steps.
  8. Any failure after the first write: undo in reverse order — blue pair to 205 (write + read back), then every S1 word
     written in this call back to STOCK (write + read back). If a `Write32` transfer itself throws, do no further USB
     traffic (same rule as `--wpoke`'s `inW`).
  9. Output `writes` log, final `s1`, `weights`.
- `restore`: blue pair: if not 205 and within 0..820 → write 205 to both, read back. Then each S1 word ≠ STOCK whose
  halves are within 8000..26000 → write STOCK, read back; a word outside that range is reported and left (refuse).
  No WaitFlip, no 5 s wait. Weights first, then S1.

## 2. `rtsvc/rt_tool.py` (Python, like `tvtool_e2.py`)

Same as `tvtool_e2.py` (pauses the watcher, holds the TV lock, stages the helper, runs it, always unpauses) but
`BIN = TconDump-rt/bin` and `TconDump.dll --rt MODE PLAN`. Prints the JSON result. Pin the helper files' sha256 in
`rtsvc/rt_plan.json` and refuse if they differ (as `s0svc/s0_nightly.load_plan` does).

## 3. `rtsvc/rt_plan.json`

```json
{"s1": {"627": ["0x40AA40AE", "0x3A333A36"], "628": ["0x40A340A6", "0x2E8A2E8C"],
        "629": ["0x409B409F", "0x280E2811"], "630": ["0x40944098", "0x325F3262"]},
 "blue": 615, "helper_sha256": {...}}
```
Values = CONSULT-14 §0 table. Python validates the same bounds as the C# before calling.

## 4. `rtsvc/rt_service.py` + `rtsvc/s95f-rt.service` (systemd --user)

Loop every 15 s:
- **Power state** with the same dbus call as `s0svc/s0_nightly.state()` (import it or copy it). Never call the helper
  when the TV is in standby/lowpower or the TCON USB device is absent.
- **Controller boot identity** = TV `/proc/sys/kernel/random/boot_id` + `/sys/bus/usb/devices/7-1/devnum` (read over
  the same root channel tvdump uses). A new identity = a new controller boot → reset per-boot counters.
- **Ready** when: TV on; watcher state MASKED (watcher state file `watcher-v3-state.json` or the last
  `-> MASKED` line in `watcher-v3.log`, both in `watcher.dir`; skipped when no watcher is configured) for ≥ 20 s since the boot; no kill-switch file
  `rtsvc/rt.disable`; none of these running: `bake_now.py`, `arm_wake`, `s0_nightly.py` (unit s0-nightly is allowed to
  be active, but skip while its log's last line says it is arming/baking), `e1.py`..`e4.py`, `tvtool`, `brightset.py`,
  `after_now.sh`, `postbake.py`. The TV lock in tvtool serialises the rest.
- **Apply** (`rt_tool.py apply`) once ready. At most 3 apply calls per controller boot, ≥ 2 min apart.
- **Audits** (`rt_tool.py audit`, read-only) at +90 s and +10 min after a successful apply, then every 30 min.
- **Audit → action** (CONSULT-14 §6 table):
  | audit | action |
  |---|---|
  | s1 plan, blue plan | ok |
  | s1 stock, blue stock | controller rebooted without identity change?: full apply (counts toward the 3) |
  | s1 plan, blue stock | apply once more; if it happens twice within 10 min: `apply-s1` only for the rest of this boot, log |
  | s1 stock, blue plan | `restore`, then `apply` |
  | s1 other, or blue other | `restore`, stop for this boot, notify |
  | helper refuses: not Clean / limit ≠ 40 / record not mode 8 | `restore` if reachable, stop for this boot, notify |
- **Notify**: POST a one-line text to the configured `alert.url`, best effort, no secrets.
- Log `rtsvc/rt_service.log` (timestamped lines), status `rtsvc/rt_status.json` (boot identity, applies, last audit).
- Unit: `Restart=on-failure`, `RestartSec=60`, `StartLimitIntervalSec=3600`, `StartLimitBurst=5`,
  `SuccessExitStatus=143 129`, `WorkingDirectory=rtsvc`. Do NOT install or start it; leave that to Claude.

## 5. Tests `rtsvc/test_rt_service.py` (pytest, no TV)

Mock the helper / power state / watcher. Cover: no call in standby; waits for MASKED ≥ 20 s; new boot identity resets
counters; ≤ 3 applies per boot, 2 min apart; each audit row of the table; kill switch; other-tool guard; plan bound
validation (bad address, NEW above stock, below 9900, step > 8000, blue 721, blue 204); helper sha mismatch refused.

## 6. Done means

Helper builds with 0 errors; `pytest -q rtsvc/test_rt_service.py` passes; a short `rtsvc/README.md` (what it does,
how to disable: `touch rtsvc/rt.disable` or `systemctl --user stop s95f-rt`, how to restore by hand:
`python3 -B rtsvc/rt_tool.py restore`). No TV contact at all while building (no tvtool/tvdump/rt_tool runs, no ssh).
