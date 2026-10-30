# Controller communications and the lane-mask experiment

This chapter records selected-firmware protocol facts and the past bounded experiment. It is not a general-purpose live controller writer. Firmware coordinates and address domains are defined in [the firmware chapter](FIRMWARE-AND-COMPENSATION.md).

## Two transports, not one

The external controller path used Linux **usbfs**, opening a selected `/dev/bus/usb/...` node, claiming interface **2**, sending headers/data on bulk OUT **0x02**, and receiving bulk IN **0x82**. The reviewed ARM32 helper used `USBDEVFS_CLAIMINTERFACE=0x8004550f`, release `0x80045510`, and bulk `0xc0105502`.

Its ARM32 bulk structure is 16 bytes: `u32 endpoint, u32 length, u32 timeout_ms, u32 data_pointer`. Pointer width/alignment matters; copying that ioctl/structure unchanged into an AArch64 process is not an ABI port.

The internal Linux `/dev/tztv_tcon`/driver ioctls and internal-uCom mailbox are **another path**. Do not confuse their operation records with the external USB 12-byte controller header.

## External wire framing

The header is exactly three little-endian 32-bit words:

```text
offset 0: opcode
offset 4: address OR buffer ID, according to family/mode
offset 8: nonzero byte length
```

Header OUT is followed by its exact-length IN or OUT partner. A client must model `ReadyForHeader → AwaitingPayload → ReadyForHeader`; after a short transfer or timeout the phase is **unknown**. A new header is not a safe retry. One process owns the interface and all transfer partners until release/close.

Selected source normalizes the low opcode byte with bit 4 cleared and separately handles its family. Examples:

| Header fields | Selected-source interpretation |
| --- | --- |
| `0x101, bus_address, length` | Direct-address RAM read |
| `0x102, bus_address, length` | Direct-address RAM write; completion can also advance upgrade state |
| `0x1, 6, length` | Buffer-ID RAM read starting at comp2 base |
| `0x2, 6, length` | Buffer-ID RAM write; not an isolated volatile-calibration API |
| `0x3, 6, 0x200` | Storage metadata read through ID mapping and staging |
| `0x201, 0, 0x200` | Direct-memory IN from address 0; **not** a storage backup |
| `0x203, offset, length` | Storage-read branch subject to a first-16-MiB family guard |

The family-2 guard uses 32-bit start/end arithmetic and a `0x01000000` boundary. A portable host validator must also reject integer overflow; never exploit wraparound or aliases to get past it. The calibration slots described later are outside this family window.

ID **6 is an ID, not an offset**. `6 + n` does not mean comp2+n. With the RAM mapper, ID `6+n`, for n=0..4, selects the buffer starting at `0x7801b000 + n*0xc63000`. With storage mode, ID 6 selects the item-1 metadata slot at storage offset `0x1842ba00`. A caller must not interchange these domains.

## A complete response can still be stale

For the fixed `0x3 / ID6 / 512` read, the source calls the storage reader and then queues USB IN **without checking the reader's return**. Both success and failed-storage host models reached the same staging address/count. A full-size response, even with a valid metadata checksum, is not proof of a fresh storage acquisition.

One past fixed metadata acquisition produced a checksum-valid header matching item 1 and sequence 2, with the surrounding state/mask unchanged. It did **not** qualify active-slot selection, payload integrity or a restorable calibration backup. Preserve this distinction for future read-tool design.

The new [offline inspector](../../research/README.md) decodes supplied headers and metadata. It opens no USB node and cannot turn a transport-complete packet into a freshness claim.

## Lane-table facts and the actual mitigation

The image-1 analysis found a sensing-consistency eligibility table:

| Object | Controller CPU coordinate | Bus coordinate where established |
| --- | --- | --- |
| Primary table, 1920 u16 entries | `0x20010000 + 2*i` | `0x47010000 + 2*i` |
| Sticky secondary byte | `0x2000c95c + i` | Not assumed from arithmetic alone |
| Counter halfword | `0x2000ba4c + 2*i` | Not assumed from arithmetic alone |

The publisher computes primary word = `secondary + 2*counter (mod 2^16)`. Bit 0 is the known eligibility flag; upper bits are counter-derived and must not be replaced wholesale. History/secondary state can later republish the table. Zero in a primary entry does not prove all history was cleared.

The tested helper changed only bit 0 for **lanes 540–661 inclusive**, a 122-entry/244-byte window at bus `0x47010438`. Fixed read windows included R `0x47012400:256`, M `0x470004a0:68`, C `0x47000bc0:16`, and that mask window. It retained the existing limits/gates and required exact pre/post readback. A watcher reconciled state after standby/reset.

The owner observed improved blackout behaviour. This changes the eligibility of damaged lanes in a **sensing-consistency check**; it is not a physical repair or proof against every shutdown. Current-monitor/PMIC protections were separate and were not deliberately changed. Suppressing a diagnostic still reduces protection/diagnostic coverage in that path; “all protections intact” would overstate the result. The damaged region's heat was pre-existing and content-dependent.

The measured spatial correlation suggested two image columns per lane on this panel, but that does **not** establish comp2 coefficient indexing or a universal electrode map. Do not derive a panel writer by dividing a screen column by two.

## Reusable transaction requirements

The useful part to carry forward is the guard design: selected device and boot identity, exact source/build/profile, one claimed interface, fixed operation/length/range, full state preflight, non-target bits preserved, readback, bounded receipt, and explicit terminal phase. Pause/reconcile the watcher rather than racing it. A partial transfer is an ambiguous outcome: no automatic new header, reset, repeated mutation or success claim.

A past helper also had a receipt-size failure after completed writes. Subsequent independent readback established what happened. A host reporting failure is not proof that the device was unchanged. Capture data-plane outcome separately from log/receipt delivery.
