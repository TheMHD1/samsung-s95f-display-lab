# TCON calibration kit: damaged QD-OLED columns, fixed by the TV's own compensation scan

These are the tools that calibrated a damaged band of columns on a Samsung S95F 77-inch **inside the TV**. They lower the
panel controller's sensing gain on the damaged columns in RAM, just before the TV's own power-off scan. The scan then
stores a compensation that drives those columns properly, and the TV saves it itself. Two RAM-only runtime trims go on
top. The method and results are in the [write-up](../../docs/advanced/tv-calibration/WRITEUP.md). The step-by-step is in
**[GUIDE.md](GUIDE.md)**.

**Prerequisite, not provided:** a working root shell on your own TV ([GUIDE §1](GUIDE.md#1-prerequisites)). The kit
does not obtain, explain or link root access.

**Applies only** when the damaged columns' stored sensing result reads far too high
([GUIDE §0](GUIDE.md#0-does-this-method-apply-to-your-panel), [§7](GUIDE.md#7-diagnose-does-the-stored-reading-of-the-damaged-columns-read-high)).
All addresses and words are **S95F 77-inch, one firmware: worked examples to verify on your TV** ([§5](GUIDE.md#5-verify-the-layout-on-your-tv-read-only-then-one-identity-write), [§16](GUIDE.md#16-adapting-to-another-tv-where-the-s95f-values-live)).

| Folder | Stage | What |
|---|---|---|
| `config.py`, `config.example.json` | setup | Every machine-specific item: TV root-shell template, work dir, player, camera hook, alerts, TV time zone, calibration window ([§2](GUIDE.md#2-install-and-configure-no-tv-contact)) |
| `tcon/helpers/` | build | C# TCON USB helpers, source only ([§3](GUIDE.md#3-build-the-helpers-source-only-no-binaries-ship)) |
| `tcon/` | read / poke / calibration run / runtime | `backup_items.py`, `tvdump.py`, `tvtool.py`, `d4store.py`, `bake_now.py`, `after_now.sh`, `bake_eval.py`, `rt_tool.py`, `pin_helper.py` ([§4](GUIDE.md#4-safety-rules-and-the-backup)–[§11](GUIDE.md#11-runtime-trims-s1-and-the-blue-weight)) |
| `measure/` | measure | Test clips, player + camera capture, `colratio.py` (offline per-column ratios from one photo) ([§6](GUIDE.md#6-measure-the-line)) |
| `offline/` | plan | `s0words.py`: gain to word calculator with the tools' bounds |
| `services/` | automate | Nightly calibration run, runtime re-apply, calibration guard: **reference implementations, adapt before use** ([§12](GUIDE.md#12-automation-reference-implementations-adapt-before-use)) |
| `examples/` | reference | The S95F final calibration plans (worked example, helper pins removed) |

Safety in one line: read-only backup first, identity write first, RAM only with read-back, hard bounds, stop on any
non-Clean controller state, no static pictures, and never write stored compensation, flash, curve tables or the BE block
([§4](GUIDE.md#4-safety-rules-and-the-backup), [§15](GUIDE.md#15-what-not-to-write)). Recovery: [§14](GUIDE.md#14-recovery).

Offline tests (no device contact): `TCON_KIT_WORK=/tmp/tcon-test python3 -m pytest -q offline measure services`.

Notes: comments that cite `CONSULT-n`, `RUN-BAKE11` or `FINDINGS` refer to internal design notes that are not published.
The camera analysis behind the published numbers ran on another machine. `measure/colratio.py` is a simpler, documented
starting point. Independent owner-device research, not affiliated with Samsung, no warranty.
