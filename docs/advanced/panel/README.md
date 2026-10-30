# Mobile Demura and future panel flashing: consolidated research

Saved 2026-10-30 for continuing the S95F investigation. This dossier connects the mobile service app, firmware write paths, backup research and missing calibration knowledge. It preserves **research, not a completed flashing procedure**. No Mobile Demura launch, phone pairing, compensation upload or panel-calibration write was performed in this project. Documentation work did not contact the TV.

Use this as the entry point alongside [firmware/storage details](FIRMWARE-AND-COMPENSATION.md), [controller transport](../CONTROLLER-COMMUNICATIONS.md) and the [ordered future research plan](FUTURE-PANEL-CALIBRATION.md). The optical Kodi/TV-overlay correction and the [blackout mitigation](../BLACKOUT-MITIGATION.md) solve different problems; neither decodes Samsung calibration coefficients.

## What “flash the panel” can mean here

| Operation | Evidence and scope |
| --- | --- |
| Mobile Demura table update | TV-side app and native TCON flash-update chain identified statically; authoring, compatibility and restore unresolved |
| External controller compensation-storage edit | comp2/comp6 save/load descriptors and persistence paths identified; optical coefficient grammar unresolved |
| Internal SoC demura load/update | Separate Linux driver/shared-memory/mailbox route; required receiver/loader unresolved |
| TCON firmware or configuration upgrade | Packaged firmware/configuration transfer mechanisms identified; this is not the same as replacing an individual panel's optical calibration |
| Pixel Refresh/electrical sensing | Stock sensing/generation/storage work; not a demonstrated way to import the camera-derived line correction |
| EFL overlay, MGA gain or Kodi shader | Working image/display-state corrections; no panel-calibration flash involved |

No evidence proves that Mobile Demura's `Data.bin`, external comp2/comp6 storage and the internal SoC export container share a format or target. Keep those paths separate until an actual producer/consumer edge connects them. A common firmware image is not a backup of this individual panel.

## Samsung Mobile Demura: identity and evidence

The saved userspace report names **Mobile Demura**, TV package **`com.samsung.tv.sdm`**, and factory item **“Mobile Demura Launch.”** The retained managed analysis is of `sdm.dll`, with `SPDeviceManager` namespaces and SmartView/MSF communication. This identifies the **TV component**, not a verified Android/iOS companion app.

The factory launch and native coordinates below are recorded leads from the original userspace report. They require matching module hashes and coordinate/Thumb-mode conventions before further use; they are not universal live addresses. Managed tokens are assembly-specific metadata identifiers.

| Recorded anchor | Coordinate/type | Meaning |
| --- | --- | --- |
| `LaunchMobileDemuraApp` | factory module `0x4a1cd` | Launch entry named by the retained factory analysis |
| `ReloadDemuraData` | managed token `0x06000023` | App reload handler |
| `WriteDemuraLUT` | managed token `0x06000024` | App native-write handler |
| `EraseDemuraLUT` | managed token `0x06000025` | App erase handler |
| `Parse22DEMURA` | managed token `0x0600003d` | Incoming table-fragment receiver |
| `writeTconDemuraData` | impl-sec module `0x5f75` | Native display-panel implementation lead |
| `ave_api_update_total_mura` | libave module `0x24e9f1` | Native update lead; report records ioctls `0xc0106514/15` |
| `TCON_UpgradeTotalDemura` | recorded native coordinate `0xb600` | Upgrade wrapper lead; re-establish containing module |
| `QDFTcon_UpgradeTotalDemura` | recorded native coordinate `0x5308` | QDF upgrade lead; re-establish containing module |
| `m_total_demura_upgrade` | recorded native coordinate `0x4e20` | Report associates it with `MURA_WRITE_DATA` and TCON flash update |

The separately pinned controller package SHA256 is `bad60bca4d6064406f14e53da3528d46701ec9c81673f4323db1937f6a2017e0`. That hash does **not** pin every Linux library or the managed assembly. A future analysis must inventory those dependencies independently.

### Mobile transport and file assembly

The retained managed trace establishes these static behaviors:

1. The TV uses SmartView's local service, a channel for `com.samsung.tv.sdm`, and message topic `/sec/tv/appdata/sdm`. Connection code includes bounded retry handling, recorded as up to 100 tries with 300-ms delays. This is not proof of a reachable raw TCP endpoint or a known phone pairing workflow.
2. The message dispatcher handles JSON commands and a separate `*22DEMURA`-identified message form.
3. For the latter, the first **1024 .NET string characters**, not a demonstrated byte-level network header, are split on `/`. Subsequent fields are parsed as chunk index, total size and chunk size. The substring after character 1024 is Base64-decoded.
4. Index zero removes an existing `/opt/data/com.samsung.tv.sdm/Data.bin`; decoded chunks are appended to that file. The inspected parser compares the index with integer `total_size / chunk_size` and sends `demuraUpdate` progress. This comparison is not an independently qualified completion or integrity contract.
5. The receiver assembles bytes; the separate write-command handler invokes the native calibration update. Receiving the last fragment does not itself establish a successful panel write.

This documents the receiver's observed implementation, not a validated packet generator. Ordering, duplicates, truncation, exact size units, last-chunk rules, sender behavior, native validation and cryptographic checks remain to be traced. Do not infer a valid LUT from a syntactically accepted Base64 payload. No sample calibration file is included.

### Native write chain and misleading acknowledgements

```text
mobile client (exact software/tool identity not recovered)
  → SmartView/MSF receiver in the TV app
  → /opt/data/com.samsung.tv.sdm/Data.bin
  → WriteDemuraLUT
  → DisplayPanelControl.writeTconDemuraData
  → libdisplay-panel.so: capi_write_tcon_demura_data
  → impl-sec: writeTconDemuraData
  → libave: ave_api_update_total_mura(0, path)
  → TCON_UpgradeTotalDemura
  → QDFTcon_UpgradeTotalDemura
  → m_total_demura_upgrade / flash-update machinery
```

The inspected `WriteDemuraLUT` invokes the native write when its argument contains `end`. It discards the native return value and sends `writeDemuraLUT: ok`. Reload and erase handlers likewise discard their native return values before sending their acknowledgements. Thus **an app `ok`, progress completion or existing Data.bin is not a write-success or readback receipt**. Validation could exist deeper in native code; the managed handler does not prove that it happened or succeeded.

The early report says any client can write/erase without authentication. The app-handler evidence alone does not establish SmartView's full authorization boundary or reachability. Retain this as an unresolved access-control concern. No live service was exposed to test it.

### The phone/tool and camera algorithm are still missing

The earlier narrative describes a Samsung service phone sending a camera-derived table. The TV app's mobile-channel machinery supports the mobile-client part. It does not identify an exact companion APK, iOS bundle, specialized service handset, external jig, supported camera, technician credential, calibration target sequence or optical fitting algorithm. No authorized tool distribution or current technician procedure has been verified.

A web check on 2026-10-30 for the exact Mobile Demura name and TV package did not locate an authoritative public companion-app procedure. That search result is bounded; it does not prove no service documentation exists.

Samsung separately documents **Smart Calibration through SmartThings**, using a phone camera to adjust picture quality in Movie mode and offering a picture-settings reset. That support article is not evidence of Mobile Demura access, per-column repair or TCON table flashing. See [Samsung's Smart Calibration guide](https://www.samsung.com/uk/support/tv-audio-video/how-to-use-smart-calibration-on-samsung-smart-tv/). Its listed model compatibility must not be extrapolated into an S95F service-tool contract.

## External compensation storage and the candidate backup

The detailed [firmware chapter](FIRMWARE-AND-COMPENSATION.md) preserves image0/image1 coordinate rules, working buffers, slots, save/load routines, header checksum and LUT-consumer facts. The later backup reports add several essential qualifications.

### Exact configured extent

| Item/code | Metadata slots, storage byte offsets | Payload starts, storage byte offsets | Working RAM |
| --- | --- | --- | --- |
| 1 / `0xa080` (comp2) | `0x1842ba00`, `0x2f675a00` | `0x1842bc00`, `0x2f675c00` | `0x7801b000` |
| 2 / `0xa0c0` (comp6) | `0x1b5b8200`, `0x32802200` | `0x1b5b8400`, `0x32802400` | `0x7b1a7000` |

Each slot has a 512-byte metadata record and **12 payload regions**, each `0xfd200` bytes at stride `0x108400`. All four headers and all four sets of saved regions total **49,768,448 bytes**. That is the selected descriptors' logical data total, not an implemented or verified backup archive. It excludes unknown dependent state and is not a single contiguous read. The working copy span `0xc63000` includes gaps that the saved payload sum `0xbdd800` does not.

The metadata checksum is the additive sum of 128 little-endian u32 words, accepted when it equals `0xffffffff`. Required marker bytes are +5 and +0x10, both zero. Item code is u16 +6, sequence u32 +8. This checks the header, not the payload.

The stock selector does not independently check that the header code matches the requested item. A future decoder must require `0xa080` or `0xa0c0` explicitly. It selects the greatest unsigned sequence; a tie selects slot 0. `0xffffffff` beats zero. Sequence rollover semantics are not established. Valid metadata does not prove pristine factory provenance or current active calibration.

### A wider storage-read branch exists, but freshness is unresolved

The later `comp-backup-contract` audit identifies opcode **`0x103`**, normalized to storage-read operation 3. Family 1 preserves a full configured 32-bit offset; the first-16-MiB guard belongs to family 2 (`0x203`). This is a source-derived fixed-offset candidate, not an argument-wraparound technique. No general reader or new live acquisition was implemented for this dossier.

Its direct read calls image0 `0x9bd4` and drops the return before scheduling USB IN; the continuation repeats that problem. A complete response can contain stale or partial staging. The shared pending word at CPU `0x2000d2c0 + 8` can be zero after both success and failure and is also used by asynchronous work. No durable, request-identifiable completion witness was found in that traced closure.

The earlier fixed metadata acquisition completed its transport replay and yielded a 512-byte header matching item 1, sequence 2, checksum and markers. This is **one candidate metadata record**, not a qualified owner backup. No complete, qualified owner calibration backup/restore is established.

Storage selector zero does not actively restore a default after all earlier selection/error histories. The bounded backend does not qualify physical capacity against the requested extent. External controller storage and Linux eMMC/boot0 have not been proved identical. Firmware naming and configured offsets do not close topology, selection or capacity.

### Stock success and alternating slots do not guarantee recovery

Original-instruction host models found that the shared payload loop retries failing region passes, but its read/save callers compare only `r0 == 1`. Other nonzero failure counts can be treated as success.

| Saved host-model case | Modeled payload calls | Observed wrapper consequence |
| --- | --- | --- |
| All 12 regions fail on all three passes | 36 | Read/save wrapper can return 0; save can commit metadata despite failed payload operations |
| Mode-4 save wrapper, both slots, all payload calls fail | 72 | Both slots receive metadata transitions and wrapper still returns 0 |

These are finite source-code counterexamples with storage intercepted on the host. They are not evidence that actual writes failed on this TV. They show why terminal zero, an operation bit or committed metadata is insufficient to qualify a backup or inverse.

Mode 4 can reset sequence and save twice, slot 1 then slot 0, in one wrapper invocation. The alternate slot is therefore not a protected original even through one qualifying save. The named AP abort byte at +0x26 is not checked by the queued save drainer before its write call. Clearing queues, observing an empty pending marker or changing that byte does not establish a global persistence barrier.

The mapper's comp3/4/5 banks are not saved-data bases in the inspected 19-entry table, but comp4 has an explicit stock temporary-work owner. Absence from that table does not establish an independently owned shadow buffer or exclude later copy-back into comp2/6.

## Other firmware leads that must stay separate

- **Internal SoC demura:** DT reservation `[0, 0x7fc00000, 0x200000]`; retained analysis records mailbox channel 3 / command 6. The export container is `0x220` header plus at most `0x181000` payload. A fixed attempt returned 2 with no output file. `demura_ctrl`, rather than `statinfo`, is the relevant result-getter surface in the saved driver analysis. Neither result 2 nor a cached status value is decoded as success or health. The receiver executable/loader remains missing.
- **Update versus reload:** selected `ave_api_update_mura_data` traces enter upgrade-associated machinery. Reload ioctl `0xc0146516` carries no new blob. Its unresolved receiver effects do not establish a harmless edited-table loader or rollback.
- **External USB writes:** `0x102` completion can advance shared upgrade state. A raw working-memory write is not an isolated calibration API. USB phase/ownership rules remain those in the controller chapter.
- **EXCO/IP-LUT consumer:** state 5 reloads; state 6 consumes queued words and applies them. S0/S1 banks exist, but active/shadow semantics and full restore remain unqualified. The argument-zero partial restore has no demonstrated complete-LUT restore contract. Staging `0x20210000` has a stock owner.
- **Boot acquisition:** the saved 4-MiB boot0 review found CRC32 grammar at offset `0x8100` over `0x8104..0x81ff`; this is not a recovered receiver or panel backup. The configured `onboot.bin` was absent from nine retained SWU sections. Its relationship to the missing receiver was not established.
- **Firmware decryption:** root-access and SWU research can help obtain analyzable software from an authorized source. Decrypted firmware does not by itself contain unique owner calibration, a phone-side algorithm or a verified restoration route. Keys and OEM bytes remain private.

## What a future flashing implementation must establish

The unresolved work is concrete:

1. Pin the actual TV/controller lineage and each app/native/receiver image; resolve module-specific coordinates and firmware applicability.
2. Recover the authorized phone/tool workflow, its camera model/patterns, pairing contract and generated table. Determine whether the format targets this panel and whether it preserves or replaces existing factory compensation.
3. Decode coefficients: physical x/y, subpixel/channel order, grey knots, signedness, quantization, compression, units, saturation, validation and active hardware consumer. A transport header and numerical buffer-size coincidence cannot provide these meanings.
4. Qualify complete acquisition with current topology/selection/capacity and independent per-operation freshness/completion. Retain originals privately outside alternating storage slots, including all relevant dependent state.
5. Establish a tested restore/transaction/power-loss recovery design independent of app `ok` and buggy stock wrapper success. Reset, reload, bypass, abort, an older slot and factory labels are not qualified undo mechanisms.
6. Build a bounded offline planner that rejects incompatible inputs and reports exact proposed optical/coefficient changes. Only then design an execution/readback path that preserves unrelated data, owns the transport and reconciles existing watchers.
7. Measure final light output for damaged/reference columns across grey levels, RGB/white, SDR/HDR, refresh rates, temperature/load, Pixel Shift and standby/sensing transitions. Include black level, clipping, neighbour artifacts and successful restoration.

At present there is no validated coefficient writer or native-calibration conversion from the existing Kodi RGB profile. We cannot promise a physical crack, lost emission or unstable conductor is recoverable by additional drive. Maximum useful correction and electrical/thermal behavior require measurement. The [future plan](FUTURE-PANEL-CALIBRATION.md) retains the ordered investigation; this dossier supplies the mobile and flashing evidence behind it.

## Evidence and next-session handoff

The sanitized [source manifest](../../../research/panel/sources.json) records hashes and relative identifiers of retained reports. Raw reports, managed/native traces, actual receipts, OEM binaries and unique calibration remain local; private provenance maps are saved with the local dossier. Report hashes identify evidence used here, not independent attestation of every inference in it.

Priority sources are `deep-dive-20261029/userspace-functions/{REPORT.md,notes/sdm-il.txt}`, `comp-backup-contract/REPORT.md`, its `persistence-followup/REPORT.md`, `storage-metadata-reader/post-acquisition-review/REPORT.md`, and the earlier controller/SoC/LUT reports listed in the manifest. Earlier “all paths permanently write,” “any client,” “RAM-only update,” “old slot is safe,” “abort stops saves” and “ok proves success” claims must be evaluated against these later bounded traces.

A new session should read this dossier and its linked chapters, then inspect the private source manifest before doing device work. The publication did not deploy a flasher, expose a service or change the running correction/watchers.
