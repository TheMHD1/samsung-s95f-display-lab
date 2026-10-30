# Research tools

These small offline tools preserve the useful protocol and storage-format discoveries. They do not bootstrap root, open devices, make network requests, decrypt firmware, dump calibration or write a panel. They inspect **local regular files** and synthetic inputs only.

From the repository root:

```sh
python3 -m unittest discover -s research/tests -v
python3 research/inspect_formats.py header 0101000038040147f4000000
python3 research/inspect_formats.py layout comp2 0
python3 research/inspect_formats.py metadata /path/to/private-512-byte-record.bin
python3 research/inspect_formats.py v5-checksum /path/to/local-v5-region.bin --length 0x110000
python3 research/inspect_formats.py mks /path/to/local-mks-block.bin
```

Use your own authorized local firmware/data. A checksum match does not prove payload integrity, freshness, compatibility or safe restoration. Do not commit unique calibration dumps or decryption keys.

The layout model lists the exact twelve strided regions from the selected firmware descriptor. It is not a complete backup specification. `unpack_u12_fields` reproduces a bounded positive 12-byte/eight-field model; it deliberately does not invent physical RGB/column mapping, signed range or comp2 encoding.

The [experimental TV overlay source](tv-overlay/README.md) is separate from these offline tools. It is an ordinary EFL/Wayland client, included for researchers continuing the working graphics experiment. The [archive-root runtime-discovery patch](root-access/README.md) preserves the actual S95F access compatibility delta that was absent from the base upstream commit. The default Kodi package still does not access the TV.
