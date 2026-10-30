# TV reverse engineering and future panel correction

The TV/controller track of [Samsung S95F Display Lab](../../README.md): root access, fault mitigation, graphics correction and the firmware evidence behind future panel calibration. Start with the result you want to understand, then follow its source and transport requirements.

The ordinary [Kodi installation](../kodi/README.md#quick-guide) needs no TV root. The TV experiments are model-specific; panel programming remains research rather than a tested procedure.

## Reading order

| Document | Contents |
| --- | --- |
| [Blackout/crash mitigation](BLACKOUT-MITIGATION.md) | Fault evidence, exact skip-bit direction/window, guarded RAM writes, watcher/recovery design and limits |
| [TV-side overview](TV-SIDE-OVERVIEW.md) | How the working overlay, controller fix and player correction fit together |
| [Root access](ROOT-ACCESS.md) | The actual SDK archive-root chain, prerequisites, public tooling, authenticated host controller, and its distinction from GPU exploits |
| [Controller communications](CONTROLLER-COMMUNICATIONS.md) | USB framing, address spaces, RAM/storage modes, lane masking, read freshness and transaction ownership |
| [Firmware and compensation](panel/FIRMWARE-AND-COMPENSATION.md) | Firmware coordinates, comp2/comp6 storage, persistence, checksums, EXCO/IP-LUT and internal demura |
| [Graphics and GPU research](GRAPHICS-AND-GPU.md) | EFL/HWC overlay, MGA register interface, captures, ABI findings, Kodi shader, and unproved memory-injection ideas |
| [TV graphics correction workflow](TV-LINE-CORRECTION.md) | Root/session setup, EFL geometry, paired gain, camera fitting and coupled cleanup; explains the public backend's remaining adaptation needs |
| [Photos and measurements](../PHOTO-GALLERY.md) | Original phone references, recovered Sony setup preview, measured after data and missing after-photo provenance |
| [Mobile Demura and panel flashing](panel/README.md) | Consolidated mobile app/flash chain, receiver framing, backup false-success cases, both-slot overwrite and missing phone/format/restore evidence |
| [Future panel-native dossier](panel/FUTURE-PANEL-CALIBRATION.md) | What is needed to build a real writer, candidate paths, backup/restore requirements, experiments and decision gates |
| [Evidence and chronology](EVIDENCE-AND-CHRONOLOGY.md) | Evidence levels, experiment sequence, corrected earlier claims and source-report index |
| [Future image-processing ideas](IDEAS.md) | Historical proposals for LUTs, row patterns, adaptive fitting and alternate playback paths |
| [Research tools](../../research/README.md) | Offline protocol/layout/checksum inspection and the experimental EFL overlay source |

## What worked, and what did not

| Finding | Evidence | Boundary |
| --- | --- | --- |
| Native-4K Kodi layer and raw-PQ HDR shader | Camera measured | Works for the tested Kodi/HDR10/HDR10+ path; not a panel repair |
| TV EFL overlay plus whole-picture MGA gain | Camera measured on one S95F | 1080p canvas/upscaling causes neighbour halos; depends on TV access and compositor state |
| Bounded controller lane-mask mitigation | Live target and owner observation | Reduced a damaged set's sensing-consistency blackouts; changes diagnostic coverage, not physical damage |
| SDK archive-root access | Live target | One locally guarded S95F deployment; not universal model support |
| Compensation RAM can be saved by stock firmware | Static original-code trace and host models | Establishes a persistence path, not proof that every byte is saved on every boot |
| Panel coefficient format and write/restore procedure | Unresolved | No compensation, calibration-storage or panel-flash write was attempted |
| GPU-memory correction injection / full-resolution HDMI capture loop | Unproved | Do not confuse root exploits, EFL composition or Kodi shader processing with this |

The earlier statement that “every path is a permanent write” was too broad: volatile display composition worked, and a future isolated hardware-consumer path remains a research possibility. The precise finding is that the investigated **shared compensation buffers are not proved isolated from persistent saves**, and the user-calibration mapping and reliable rollback are unresolved.

Conversely, “no risk to the TV” is too strong. The Kodi path avoids changing TV storage, but altered drive levels, bright patterns, heat and an already damaged panel still deserve attention. The lane mask also suppresses part of a consistency check. See [SAFETY.md](../../SAFETY.md).

No new TV operation was performed to produce this documentation. It preserves past findings and future plans. OEM firmware, extracted keys, raw calibration dumps, private identity/boot records and access credentials are not redistributed.
