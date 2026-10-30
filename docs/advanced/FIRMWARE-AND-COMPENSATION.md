# Firmware findings and compensation storage

All code coordinates in this chapter are **static facts about the retained selected package**, not attestation of every instruction currently executing on another TV. The package SHA256 was `bad60bca4d6064406f14e53da3528d46701ec9c81673f4323db1937f6a2017e0`. Obtain firmware from an authorized source; this repository does not redistribute OEM bytes, decryption keys or disassembly dumps.

## Coordinate conventions

| Domain | Example / translation | Do not confuse with |
| --- | --- | --- |
| Controller image0 VA | FILE offset = VA + `0x200` | Linux virtual/physical memory |
| Controller image1 VA | FILE offset = VA + `0x40200` | image0 VA |
| Controller CPU RAM | comp2 `0x7801b000` | Storage byte offset |
| Proved SRAM bus alias | CPU `0x20010000` ↔ bus `0x47010000` | A universal DRAM alias rule |
| Controller storage byte offset | comp2 data slot `0x1842bc00` | USB buffer ID or CPU pointer |
| SoC shared-memory reservation | DT `samsung,demura` region | External controller compensation RAM |
| FRC/hardware-bank register | MGA offset or `0x5870…` consumer field | A pixel buffer you can edit |

Record image, architecture, endianness, hash and coordinate convention before following any offset. Controller Thumb code, Linux ELF/PLT resolution, ARM32 userspace ABI and GPU surfaces require different analysis.

## The positive comp2/comp6 persistence result

Image0's storage-item table begins VA `0x3d7f8`, with 19 records of `0x20` bytes. Records include item ID, two metadata slots, sequence, optional callback and a data-descriptor pointer.

| Item | Descriptor VA | Working RAM | Metadata storage slots | Data storage slots |
| --- | --- | --- | --- | --- |
| 1, comp2 | `0x3d798` | `0x7801b000` | `0x1842ba00` / `0x2f675a00` | `0x1842bc00` / `0x2f675c00` |
| 2, comp6 | `0x3d7b0` | `0x7b1a7000` | `0x1b5b8200` / `0x32802200` | `0x1b5b8400` / `0x32802400` |

Each descriptor has **12 regions**, `0xfd200` bytes per region, stride `0x108400` in RAM and storage. Thus:

```text
copied RAM span:    12 × 0x108400 = 0xc63000
saved data bytes:   12 × 0x0fd200 = 0xbdd800
gap per stride:                    0x00b200
saved region i: RAM_base + i*stride ... + region_size
stored region i: selected_data_slot + i*stride ... + region_size
```

These are **storage-layout facts**, not RGB planes, optical coefficient semantics or a screen-coordinate mapping. Saved bytes happen to equal `3*1920*2160`; the copied span is larger. Neither equality proves plane order, signedness, grey-level knots or physical pixel indexing.

### Save chain

Under its normal-finish conditions, image0 `0x31650` reaches `0x315b4`; mode 4 queues items including **1 and 2** through `0x2f1d0` and schedules `finish_W_emmc`. The worker `0x2f2b0 → 0x2f4da → 0x2f3e4 → 0x2f2fc` selects sequence/slot, writes an incomplete metadata record, calls shared payload loop `0x2f000` in write mode, then commits metadata state.

The payload loop reaches `0x9ee4(device0, RAM_source, storage_byte_offset, bytes, 0)`. That routine checks 512-byte alignment and reaches storage-controller direction 2; the paired reader `0x9bd4` uses direction 1. It is a concrete write path, not a conclusion from an “EMMC” string. The host audit modeled both slots/directions/success and failure; it did not emulate real storage or establish current scheduler timing.

A still-present edit to a saved comp2/comp6 region can therefore reach persistent storage during ordinary firmware work. The opaque comp6→comp2 copy at `0x303b4..0x303c2` spans `0xc63000`, so comp6 is not independent of comp2.

### Reload is not rollback

The item loader `0x2ec24 → 0x2eb98 → 0x2ef04` selects valid metadata then uses `0x2f000` read mode. `exco_load_comp2_to_comp6` at `0x3216c` loads item 1 and copies comp2→comp6 without branching on the read return before copying. A failed load can copy stale RAM. Recovery at `0x37320` can load stored comp6, which need not be pristine factory data.

The available startup trace does not prove an unconditional full pristine reload on every reboot. Even a successful reload could select a newer saved edited slot. **RAM, reboot, bypass, reload and factory-labelled routines are not independently proved undo mechanisms.**

## Metadata and checksum grammar

The record is 512 bytes / 128 little-endian u32 words. Constructor `0x2ea5c` sets word 0 to the bitwise complement of the sum of words 1–127, modulo 2^32. Checker `0x2eb54` accepts a whole-record sum of `0xffffffff`.

Additional checks include byte `+5 == 0` and byte `+0x10 == 0`. The record has a u16 item/type code at `+6` and unsigned sequence at `+8`. Byte +5 is used as incomplete/committed transaction state. Slot selection compares valid sequences; rollover, ties and interrupted transactions require their own contract.

This is an **additive header checksum**, not an authenticated payload checksum or proof of original calibration. Two valid slots are not a permanent backup because future saves can reuse them. A real restore would require both raw metadata records, all strided payloads, device/firmware lineage and dependent item state, plus a verified transactional restore and power-loss recovery design. None was qualified.

## Packed sensing offsets are another format

The inspected packer at image0 `0x34138` loops three streams, two halves, 2160 rows and 1920 positions, packing eight 12-bit fields per 12 bytes: **2880 bytes per row**. The source aperture is `0x6bdd8000 + stream*0x32a0000 + half*0x1950000`.

Some loads are sign-extended, but a positive known-answer packing case does not prove valid negative range, saturation, optical sign or channel mapping. There is no grey-level input to that bounded packing loop. It is not a decoded comp2 optical-calibration format. A visible 480-wide loop in related work belongs to another family and cannot index comp2.

The `QfsOffsetEMMC` diagnostic's direct item selection is **17**, not comp2/comp6; its ordering alone does not prove a subsequent newly packed full array was saved. Distinguish that from the separate positive item-1/item-2 save proof above.

## Configuration package and hardware LUT consumer

The selected v5 package has a `0x200`-byte master header and `0x200`-strided subheaders. Master fields include count +0, size +4, version +8, marker `0xcfcfcfcf` +0x28, format version +0x5c and checksum +0x60. The checksum is negative sum of little-endian u32 body words from `0x200` to the selected region end. Header/data CRC-8 belong to the **separate Mks block**, using polynomial `0xd5`, MSB-first, init/xorout 0.

Subheaders describe IP register/LUT and MCU records, destination bases and source/destination/length copy lists. `Config_CopyData_To_IP_LUT` begins image0 VA **0x5a24**. The `0x1000` split is a **4-KiB transfer chunk limit**, not a 12-bit colour clamp. Descriptor stride is `0x18`. Packaged records reach staging, DMA and hardware banks in the `0x586…` ranges; compensation start-table programming also appears in `0x5870…` registers.

This proves transfer machinery, not coefficient meanings, a safe live insertion point, an atomic bank switch or persistence isolation. Generic staging at `0x20210000` is shared with stock state-machine ownership. It is not a free scratch texture or an admitted injection address.

## The internal SoC demura path is separate

The Linux `sdp_tcon` path maps a DT `samsung,demura` region, observed reservation `[0, 0x7fc00000, 0x200000]`, and communicates with internal uCom. The export container is **0x220 bytes of header plus at most 0x181000 payload bytes**. First-word byte order is handled by the driver; container size is not a decoded coefficient layout.

One fixed export attempt returned **2** and created no dump. A separate cached status read also yielded 2; these are different observations with undecoded meaning. Neither is a health verdict or successful export. The bounded search did not identify the internal receiver executable/contract.

The Linux library trace resolves `ave_api_update_mura_data` to upgrade/flash-associated functions, including `ave_tcon_api_upgrade_demura_data` variants. Earlier “update is RAM-only, upgrade is separate” advice was wrong for these bytes. The reload ioctl `0xc0146516` carries no new blob; following one wrapper without its indirect receiver cannot prove a volatile edited-profile load.

No compensation data, calibration storage, firmware/config flash or TCON demura was written in this project. See [the future dossier](FUTURE-PANEL-CALIBRATION.md) for the concrete steps still needed.
