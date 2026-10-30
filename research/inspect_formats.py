#!/usr/bin/env python3
"""Inspect local inputs only. Never imports transport or opens device nodes."""
import argparse
import hashlib
import json
import os
import stat
from pathlib import Path

from formats import Header, inspect_metadata, saved_regions, v5_body_checksum, inspect_mks


def read_local(path, limit):
    p = Path(path)
    if not p.is_file():
        raise ValueError("only regular local files are accepted")
    with p.open("rb") as f:
        mode = os.fstat(f.fileno()).st_mode
        if not stat.S_ISREG(mode):
            raise ValueError("only regular local files are accepted")
        data = f.read(limit + 1)
    if len(data) > limit:
        raise ValueError("input exceeds the bounded inspection limit")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    head = subs.add_parser("header")
    head.add_argument("hex_bytes")
    meta = subs.add_parser("metadata")
    meta.add_argument("file")
    layout = subs.add_parser("layout")
    layout.add_argument("item", choices=("comp2", "comp6"))
    layout.add_argument("slot", type=int, choices=(0, 1))
    cfg = subs.add_parser("v5-checksum")
    cfg.add_argument("file", help="local region starting at its v5 master header")
    cfg.add_argument("--length", type=lambda x: int(x, 0), required=True)
    mks = subs.add_parser("mks")
    mks.add_argument("file", help="local block starting at its Mks header")
    args = parser.parse_args()
    try:
        if args.command == "header":
            h = Header.parse(bytes.fromhex(args.hex_bytes))
            result = dict(opcode=hex(h.opcode), address_or_id=hex(h.address), length=h.length,
                          family=h.family, normalized_operation=h.operation,
                          direction=h.direction, family2_host_range_valid=h.family2_range_valid(),
                          warning="Decoded structure only; no transport or safety qualification")
        elif args.command == "layout":
            result = saved_regions(args.item, args.slot)
        elif args.command == "metadata":
            result = inspect_metadata(read_local(args.file, 512))
        else:
            data = read_local(args.file, 32 * 1024 * 1024)
            if args.command == "mks":
                result = inspect_mks(data)
            else:
                if len(data) < 0x64:
                    raise ValueError("v5 header too short")
                stored = int.from_bytes(data[0x60:0x64], "little")
                computed = v5_body_checksum(data, args.length)
                result = dict(stored=hex(stored), computed=hex(computed), matches=stored == computed)
            result["input_sha256"] = hashlib.sha256(data).hexdigest()
        print(json.dumps(result, indent=2))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
