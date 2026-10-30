# Future panel-native calibration dossier

This document is saved for a future attempt. It records how to continue the investigation, including firmware findings that were omitted from the original public package. It is **not** a working panel-programming procedure, and no panel-calibration write was attempted while preparing it.

Read the [Mobile Demura and panel-flashing dossier](README.md) first for the mobile receiver/native chain, later backup failure cases and source manifest. This page gives the ordered programme; it does not establish that Mobile Demura, external comp2/6 and internal SoC demura share a format.

## Objective and candidate paths

The desired result is an input-dependent, per-column/per-colour correction inside the display, covering HDMI and TV apps with known HDR behaviour, Pixel Shift alignment and a verified removal path. A genuine panel-calibration method must connect:

```text
physical x, y, colour, input level
  → intended optical correction
  → coefficient representation and address
  → active hardware consumer
  → application/commit sequence
  → independently verified restore
```

None of the investigated panel paths closes that entire chain today.

| Candidate | Known | Missing |
| --- | --- | --- |
| External controller comp2/comp6 | Exact working bases, strided storage descriptors, save/load paths | Optical format/index/sign, complete current backup, isolated apply and restore |
| Internal SoC optical-demura blob | Linux export/shared-memory/mailbox path, bounded container | Successful useful dump, receiver executable/contract, coefficient grammar and loader semantics |
| EXCO/IP-LUT hardware consumer | Staging/DMA/bank/start-table paths | Optical entry meanings, active/shadow-bank behaviour, cache ownership and persistence isolation |
| Factory/service package path | Write-capable configuration/upgrade machinery | Valid per-panel calibration authoring, service equivalence and verified recovery |
| Samsung Mobile Demura | TV app `com.samsung.tv.sdm`, mobile-channel receiver and traced TCON flash-write chain | Exact phone/tool identity and access, optical algorithm, table grammar, authorization and verified restore |
| Independent post-generation shadow buffer | Plausible design | Existence/ownership, source-pointer switch, no save/copy-back alias and deterministic teardown |

The companion [firmware chapter](FIRMWARE-AND-COMPENSATION.md) contains the exact static addresses, storage descriptors and checksum rules. Preserve those details as research leads, not guessed write targets.

## What a real backup would need

A common firmware package, a Linux boot-area dump, a small comp2 prefix or one checksum-valid metadata record is **not** an individual panel-calibration backup.

Before any compensation mutation, establish a repeatable acquisition of both item-1 and item-2 metadata slots and all associated strided payload regions. Retain raw bytes, exact storage device/offsets, firmware identity, sequences/validity flags, acquisition status, whole-file hashes and relevant dependent item/callback state. Keep unique calibration backups private.

The fixed storage-read path can emit stale staging after a lower-level read failure. Backup qualification therefore needs independent evidence of a fresh successful read, repeated consistent data under understood stock activity, complete region coverage and a way to distinguish active and alternate slots. A checksum only validates its stated grammar.

Most importantly, prove restoration **before** relying on the backup: transaction ordering, sequence handling, slot selection, header/payload checks, readback, interrupted-write recovery and a recovery channel independent of the system being modified. An older slot can be overwritten by ordinary sensing work. No complete backup/restore procedure is currently established.

## Ordered research programme

### 1. Freeze and reproduce the source evidence offline

Preserve the working Kodi correction and an independently recoverable player card. Hash the firmware inputs; identify image0/image1 coordinates and architecture. Reproduce descriptors, save/load lineage, packet parsing and checksum models without the TV. The included [offline research tools](../../../research/README.md) cover small format facts; they are not substitutes for reproducing the original-code traces.

Do not rederive comp2 layout from `3*1920*2160`, a 480-wide loop, the two-columns-per-lane observation or a function name. Those shortcuts were specifically not proved.

For **Mobile Demura**, preserve and hash the matching TV app assembly/manifest and native dependencies privately. Reproduce the receiver-to-file-to-native-write trace described in the [firmware chapter](FIRMWARE-AND-COMPENSATION.md#samsung-mobile-demura-service-app). Identify the companion mobile software through authorized service documentation or package evidence; recover its camera calibration, table authoring, model admission and pairing contracts separately. A mobile transport/parser is not a decoded optical-calibration format. Establish what validates data and what reports actual native completion; the inspected app's `ok` response does not check the native write result. Resolve channel authorization without exposing a live write/erase service, and qualify complete backup/restore before any factory-app launch or calibration upload. No working phone app, external technician device or service workflow was validated here.

### 2. Qualify useful read-only acquisitions

For internal demura, success must mean a **new regular output file**, expected bounded size, a meaningful reported length, whole-file hash and retained request/return evidence. The past result 2/no file is failure. A debugfs write byte count is not a successful data export.

For external storage, close the ignored-read-return/freshness problem before calling captured bytes a backup. Keep fixed opcodes/IDs/ranges and a transport phase contract; a larger arbitrary dump is not a substitute for a qualified small read. Reads can still alter controller staging/protocol state and compete with sensing.

### 3. Recover the missing consumer

Trace the internal-uCom receiver or recover its command contract from matching source/package evidence. Separately trace external compensation DMA destinations, bank selectors and reset/load transitions. Determine which exact table consumes a value, when it becomes active and whether it is subsequently copied or saved.

The current hardware-bank evidence proves data movement, not the coefficient encoding. The source aperture `0x60000000 + descriptor.u8(+2)*0x1950000 + descriptor.s16(+6)*0xc00` and ring at `0x20253002` are selected image-1 producer facts; they do not establish physical units, cadence or an injection surface.

### 4. Recover coefficient semantics

Identify record size, compression/packing, endianness, signedness, channel and left/right ordering, x/y mapping, grey knots, optical domain and saturation. Use nonuniform synthetic fields and independently checked decoders so a uniform/zero sample cannot falsely validate a mapping.

Relate coefficient changes to expected light output through a model and, only with a separately qualified reversible insertion point, a bounded camera experiment. Do not assume EXCO voltage/sensing offsets are an optical RGB correction curve. The saved user RGB profile is an image-space calibration, not Samsung-native coefficients.

### 5. Prove isolation or commit to an explicitly persistent design

A volatile experiment needs positive proof that the chosen buffer/table has **no stock-save alias or copy-back**, a deterministic source/bank switch, known synchronization/cache behaviour, and a complete restore on stop/reset/reload. Applying “after generation” in the same comp2 buffer does not establish isolation: a later save can still sample it.

If the only viable method is persistent, call it persistent and establish a verified service-grade write/restore/recovery process. Do not relabel it RAM-only. Disabling save callbacks or bypassing sensing is a different modification with its own unclosed effects, not a demonstrated rollback strategy.

### 6. Design a writer only after those facts are established

Minimum properties of a future implementation:

- Exact firmware/device/ABI admission; no arbitrary opcode/address options in the ordinary workflow.
- Proven complete private backup and restore, including interrupted-write handling.
- One bounded record/region, non-target bits/bytes preserved, one transport owner and explicit synchronization with existing keepers/watchers.
- Separate plan and execute modes, exact preflight/readback, bounded receipts and no automatic retry after an ambiguous result.
- A camera test proving local improvement, unchanged neighbours/background, correct black/HDR behaviour and then successful restoration.
- Thermal/physical observations, realistic behaviour across standby/reboot/sensing and a defined stop condition.

These are requirements for future work, not conditions this project has already met. There is no writer in this package because selecting its coefficients and guaranteeing recovery would currently be guesswork.

## Firmware acquisition and decryption research to retain

The research used selected extracted OEM package images and Linux libraries/modules, then correlated source paths with small bounded observations. Public upstream Samsung TV Root also documents SWU key-recovery tooling. Firmware acquisition/decryption is a separate activity from knowing how to program a panel: decrypting a package does not recover unique panel calibration or a hardware receiver missing from that package.

For future work, record authorized package origin, complete package hash, extraction/tool revision, each extracted image's hash, virtual/file offsets, architecture and matched runtime applicability. Keep recovered keys and private payloads outside the repository. Do not infer encryption solely from entropy or force a file into a guessed decoder.

A 4-MiB boot0 acquisition was reviewed; a word at offset `0x8100` matched CRC32 over `0x8104..0x81ff`. That is a record-grammar clue, not proof that the boot bytes contain the missing compensation receiver or a restorable panel image. The bounded search did not identify the needed internal-uCom consumer.

## Decision log and alternatives

Panel flashing/calibration-storage editing was **researched, not attempted**. The reason is a missing format/consumer/restore chain, strengthened by a positive comp2/comp6 persistence trace. This is not a claim that panel programming is impossible, nor a permanent instruction to discard the research.

Continue the panel route only when a specific new source fact or qualified read closes one of the gaps above. Meanwhile, better camera fitting, row-dither/two-segment profiles and a decoded-video per-column LUT on mpv/libplacebo can improve the image without needing native panel storage. None should be advertised as exact until measured through the final output path.
