# Evidence, chronology and superseded claims

This is a sanitized account of local research, not a dump of the working directory. The original raw reports contain private device/session data and OEM material and remain local. Important report names are retained below so the owner can locate the evidence next time; the substantive conclusions and bounds are published in this handbook.

## Evidence vocabulary

- **Camera measured:** light recorded at damaged and reference columns under stated patterns/settings. Relative ratios are not certified absolute nits or colour accuracy.
- **Target observed:** a selected device returned data or an owner observed behaviour. It does not alone establish optical output, freshness or firmware equivalence.
- **Static source fact:** a byte-identified function/descriptor from a pinned image with an explicit address convention.
- **Host-model result:** original instructions or a mathematical model run with declared hardware stubs. Real storage, DMA, scheduling and optics remain outside the model.
- **Hypothesis:** a candidate link requiring a discriminating test.

## Chronology

| Stage | Finding | Later consequence |
| --- | --- | --- |
| Early controller diagnostics | Damaged region correlated with sensing-consistency faults | Led to bounded lane-eligibility experiment, not calibration decoding |
| Lane-mask mitigation | Owner observed blackout improvement; watcher reconciled volatile state | Preserve baseline and transport ownership during other work |
| Initial demura proposals | Suggested comp2 edits / update+reload as temporary | Superseded by concrete persistence and library-entry traces |
| Compensation audits | Exact strided save/load path; RAM→storage possible | Reboot cannot serve as verified undo |
| Early EFL/capture probes | Owned UI drawing/capture; black HDMI sample | Did not prove physical 4K video access |
| Later TV overlay | HWC change made EFL visible over HDMI; global MGA pairing camera-verified | Real TV-side mitigation, but 1080p blur limited |
| Native-4K Kodi correction | Per-column strip on the player | Better alignment without TV-root dependency |
| HDR shader v2 | Raw-PQ correction includes GUI/subtitles | Avoid stock-shader mismatches and VS10 remapping assumptions |
| Pixel Shift / HDMI incident work | Following verified; odd TV-overlay phase limited; full player reboot needed after one HDR failure | Calibration and reliability must be evaluated together |
| Public expansion, 2026-10-30 | Root, controller, GPU and future compensation research organized | No new device operation or panel write |

## Corrections future contributors should not lose

| Old inference | Corrected finding |
| --- | --- |
| S95F root was the Mali/GPU exploit | Current S95F controller used SDK archive-root; the upstream GPU route is separate |
| RAM edit resets on reboot | Comp2/comp6 have a positive stock save path; restoration is unproved |
| update_mura_data is harmless RAM staging | The selected library resolves it into upgrade-associated paths |
| 0x1000 is a 12-bit coefficient clamp | It is a DMA transfer chunk limit in the inspected routine |
| Copied buffer size proves RGB planes | Strided saved regions and copied span differ; optical layout unresolved |
| Lane i means compensation entries for columns 2i,2i+1 | Spatial correlation is not the coefficient consumer/index formula |
| USB complete + checksum valid means fresh backup | Storage read return can be ignored; stale staging can look valid |
| Early marker/capture failure rules out TV overlay | Later HWC-aware EFL overlay worked and was measured |
| TV GPU-memory injection worked | No such correction path was demonstrated; EFL and Kodi source shaders are different |
| No TV writes happened | Bounded lane-mask and MGA/display-state changes happened; compensation/flash writes did not |
| Pixel Shift was simply disabled | Later following worked; odd TV-overlay phases remained blur-limited |
| Shader/relay running means the line is corrected | A known HDMI incident broke HDR correction despite apparently correct state |
| Player-side correction has no physical risk | It avoids TV-storage edits; bright drive and pre-existing panel damage still matter |

## Original local report index

These are descriptive relative identifiers, not published raw reports or paths that expose an owner's account:

| Local research identifier | Topic now covered publicly |
| --- | --- |
| root-access/source and host controller source | [ROOT-ACCESS](ROOT-ACCESS.md) |
| rtp-lane-table-writers-20261028ec; firmware-rtp-producer-20261028df | [CONTROLLER-COMMUNICATIONS](CONTROLLER-COMMUNICATIONS.md) |
| tcon-path; tcon-persistence; comp-layout | [FIRMWARE-AND-COMPENSATION](FIRMWARE-AND-COMPENSATION.md) |
| comp-hardware-decoder; comp-indexing-followup; ip-lut-consumer; ip-lut-apply | Firmware consumer findings and [future dossier](FUTURE-PANEL-CALIBRATION.md) |
| soc-path; receiver-storage; boot-analysis; boot-counterpart | Internal receiver/export and firmware acquisition gaps |
| deep-dive-20261029/userspace-functions/REPORT; notes/sdm-il | Mobile Demura TV app, managed mobile receiver/write handlers and native TCON flash chain; companion phone app unverified |
| overlay-observation; canvas-position-observation; efl-oneframe-live; screenshot-server; capture-strip | [GRAPHICS-AND-GPU](GRAPHICS-AND-GPU.md) |
| gapfix/LINE-FIX-REPORT sections 2, 7–11; PLAN MGA tests | Later successful overlay, shader, Pixel Shift and reliability work |
| agent-demura-path and early agent-demura-format recommendations | Historical claims; later concrete traces take precedence |

## What is intentionally absent

There are no credentials, private network addresses, serials, boot/session identities, raw root-controller status, OEM binaries/keys, proprietary disassembly dumps or unique calibration backups. Static software addresses, protocol fields, package hash and negative findings are included because they are essential research facts. No panel writer is fabricated to fill the missing coefficient/restore contract.
