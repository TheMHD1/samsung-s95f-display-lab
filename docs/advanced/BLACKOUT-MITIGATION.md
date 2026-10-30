# Blackout and crash investigation: the controller-RAM mitigation

This is the research and operating-design record for the damaged S95F's blackout problem. It is separate from the visible-line correction and future panel flashing. The owner reported that the lane-mask/watchdog deployment resolved the recurring blackout behavior on the tested set. That is an observed outcome, not a universal electrical repair or a guarantee against future faults.

## What the fault looked like

The panel could go completely black on sparse For You/Live pages and some dark/full-screen HDMI films while audio and the TV's Linux system continued. The same video behind the Ugoos home or a populated TV Apps page could remain visible. The owner called some incidents reboots; the retained symptom supports a panel/controller stop without establishing that every incident was a full TV reboot. A separate Ugoos crash from accessing `/sys/class/amvecm/*` was a different failure and must not be mixed into this diagnosis.

A retained accepted error-status query returned **`0x10`** with a matching QDF diagnostic. The selected AVE decoder names bit 4 **RT Protect**. That decodes a status word; it does not by itself identify a rail, temperature or physical cause. The host AVE recovery monitor uses a distinct ERR-GPIO fault predicate and history. A status label is not its reset condition. Direct GPIO getters may acquire/reconfigure GPIO ownership, so they are not passive status-memory reads.

Firmware analysis connected sensing/reference comparisons, damaged-region lane history, fault-score progression and a stop branch. All 24 historically noted faulting lanes fell within the damaged patch, approximately lanes 554–649; the most visible line was near lanes 626–631. The later mask deliberately covered a broader fixed window. Physical mapping came from owner measurement and operational correlation, not a recovered universal electrode/calibration map.

## The exact successful change

The bounded helper **sets bit 0 to 1** in the primary lane-table halfwords for **lanes 540–661 inclusive**. Bit 0 is the skip flag in the reviewed checking path. Clearing it removes the explicit mask. An earlier chat description saying the bypass cleared bit 0 was incorrect.

| Object | Selected controller CPU coordinate | Qualified bus view |
| --- | --- | --- |
| Primary table | `0x20010000 + 2*lane` | `0x47010000 + 2*lane` |
| Mask window | 122 halfwords / 244 bytes | `0x47010438` through last halfword `0x4701052a`; end exclusive `0x4701052c` |
| Secondary sticky flag | `0x2000c95c + lane` | Do not assume the primary-table alias formula |
| Counter | `0x2000ba4c + 2*lane` | Do not assume the primary-table alias formula |

The implementation computes mask target `old | 1` and unmask target `old & ~1`. Importantly, the deployed writer admits only stable **Clean** state with zero unexpected non-bit-0 content in the window. It refuses entries with counter-derived upper bits; it does not blindly overwrite arbitrary halfwords. It writes only changed two-byte entries, reads back the exact target window and verifies that the limit did not change. Its historical admission accepts limit 40 or 200; the retained settled configuration used **40**. This does not mean the old 200 service should be re-enabled.

This was a direct external-controller RAM change through the reviewed USB transport, **not GPU-memory injection**, a firmware patch or a panel-calibration flash. The owner confirmed that previously failing For You/Live pages stayed visible. Later work treated the blackout fix as operational while investigating the visible line.

## Why a one-time mask was insufficient

The primary table has stock writers. A proven publisher computes:

```text
primary_halfword = (secondary_byte + 2*counter_halfword) modulo 65536
```

Bit 0 mirrors the flag in that publisher; upper bits carry history. Controller restarts and stock publication can lose or replace the explicit mask. Reset behavior for all related primary/secondary/history state was not proved universal, so this is not a promise that reset restores every original byte.

The trainer uses `u16 CPU 0x200004a2 == 1`; an early lead confusing it with `0x200004aa` was corrected. Its band arithmetic uses a 32-bit wrapped product, shift by 8 and u16 bounds. Observations are outside only when strictly above the upper bound or strictly below the lower bound; equality stays inside. Outside observations increment the u16 counter, and a truncated count strictly greater than the threshold sets the secondary flag. There is no in-band counter reset in that routine. Nonconsecutive events can accumulate and 16-bit values can wrap. A zero primary entry is not proof of zero history.

The later fault-score producer audit retained a progression **0 → 38 → 44** with threshold 40 and a strict-greater-than fault branch. That score path and the trainer's counters must not be collapsed into a guessed physical unit or universal threshold interpretation.

## Watcher, recovery and source coordination

The server-side `s95f-lane-mask-watcher.service` runs the owner-specific controller helpers. The saved watcher probes TV boot identity, controller USB instance and active source, then uses read receipts to classify state. Its retained timing is ordinary polls every **15 seconds**, fast polls every **3 seconds**, and mask re-verification every **60 seconds**, with a 180-second fast window.

| State | Recorded watcher behavior |
| --- | --- |
| Clean, all 122 skip flags present | Record verified mask and continue monitoring |
| Clean, no skip flags present | Run guarded KB mask helper; require verified target readback |
| Quiescent | Allow controller startup/settling and recheck |
| Faulted | Attempt source-aware preparation and bounded reviewed recovery, then fast re-masking |
| Unexpected profile/partial mask/receipt failure | Record condition and recheck; no arbitrary widening of the write window |

For the configured Ugoos HDMI source, recovery attempts Kodi Home; for TV home it attempts Apps navigation. Other HDMI sources have no generic picture-control action. Navigation is an attempted preparation, not an established success prerequisite in every branch: the retained implementation can continue to reject checks even after navigation fails. It then requires the reviewed boot-agnostic public reject checks before exactly one reviewed stock controller **op 41 / MODE2** recovery call. This is a past recovery mechanism, not an unguarded command recipe.

The watcher records the attempt **before** calling recovery. It permits one attempt per controller instance and at most **three per hour**. A reused-instance fault or exhausted budget alerts and waits. Faults while the mask is already present are separately logged, with backoff after repeated occurrences. Failed/uncertain recovery is not automatically retried on the same instance. It does not prove MODE2 restores calibration, all controller RAM or every display fault.

The watcher and line-fix keeper share an access lock and retry lock contention. A `watcher.pause` file stops watcher actions; a busy flag participates in coordination. Manual controller work must use the same pause/ownership/reconciliation contract. Removing the pause without reconciling actual device/transport state is insufficient after an ambiguous operation. Never run an independent flasher against the same USB interface while this watcher can mutate or reset it.

## Earlier experiments and remaining limits

Raising a global controller limit from 40 to 200 helped in an earlier experiment. The temporary `s95f-temporary-limit200.service` was subsequently stopped/disabled and superseded by the lane mask. A recovery path selecting Apps before one stock MODE2 call was also tested. Apps-only home modifications were an early workaround, not the final controller mitigation.

INA238/current monitoring, PMIC/ELVDD control and defect-drive reduction were deliberately left untouched. That describes the scope of this modification; it does **not** mean all protection coverage is unchanged. Skipping damaged lanes suppresses that part of a sensing-consistency diagnostic. Heat at the damaged region also existed at stock settings; that observation cannot certify safe long-term drive after masking or correction.

The mask does not repair damaged conductors, restore lost emission, fix optical nonuniformity or identify Samsung demura coefficients. The approximate two-columns-per-lane relationship cannot be used to index comp2 or author a flash payload. Future panel calibration must retain the distinction between optical improvement and electrical/fault behavior.

## Files and evidence retained for the next session

| Local relative identifier | Role |
| --- | --- |
| `claude-20261028/tools/mask_watcher.py` | Saved watcher state machine, budgets, source handling and lock coordination |
| `claude-20261028/docs/HANDBOOK.md` | Owner-confirmed outcome, chronology, deployment references and incident history |
| `overnight/lane-mask-read-20261028ka` | KA reader and classifications |
| `overnight/lane-mask-write-20261028kb/Program.cs` | KB exact bit direction, window, admission and readback |
| `overnight/telemetry-read-20261028kd` | KD telemetry |
| `overnight/rtp-lane-table-writers-20261028ec/README.md` | Source-owned primary/secondary/counter lifetimes and corrected trainer gate |
| `overnight/firmware-rtp-producer-20261028df/README.md` | Later score/threshold/fault producer analysis |
| `tcon-research/rt-protect-host-recovery.md` | RT Protect status versus ERR-GPIO monitor boundary |
| `RECOVER-PANEL.md` and earlier recovery helper | Historical procedure; old boot pins require requalification |

Source hashes are in the [sanitized manifest](../../research/panel/sources.json); absolute locations and private runtime dependencies are in the local handoff. Public documentation includes the mechanism and exact evidence, not a generic live bypass installer. Owner-specific credentials, device identities, service units and raw receipts remain private. No service or TV setting was changed during this documentation update.
