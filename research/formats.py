"""Offline models of selected controller formats. No device or network I/O.

These are bounded format facts, not a calibration encoder or freshness check.
SPDX-License-Identifier: MIT
"""
from dataclasses import dataclass
import struct

U32 = 0xFFFFFFFF
REGIONS = 12
REGION_BYTES = 0xFD200
STRIDE = 0x108400
ITEMS = {
    "comp2": (0x7801B000, (0x1842BC00, 0x2F675C00)),
    "comp6": (0x7B1A7000, (0x1B5B8400, 0x32802400)),
}


@dataclass(frozen=True)
class Header:
    opcode: int
    address: int
    length: int

    @classmethod
    def parse(cls, data):
        if len(data) != 12:
            raise ValueError("header must be exactly 12 bytes")
        result = cls(*struct.unpack("<III", data))
        if result.length == 0:
            raise ValueError("zero length is not admitted")
        return result

    @property
    def family(self):
        return (self.opcode >> 8) & 0xFFFF

    @property
    def operation(self):
        return (self.opcode & 0xFF) & ~0x10

    @property
    def direction(self):
        return {1: "IN / memory", 2: "OUT / memory", 3: "IN / storage staging",
                4: "write-capable storage operation"}.get(self.operation, "unresolved")

    def family2_range_valid(self):
        """Stricter host guard: never allow source arithmetic to wrap."""
        end = self.address + self.length
        return (self.family == 2 and self.address < 0x1000000
                and end <= U32 and end < 0x1000000)


def inspect_metadata(data):
    if len(data) != 512:
        raise ValueError("metadata must be exactly 512 bytes")
    return {
        "checksum_valid": (sum(struct.unpack("<128I", data)) & U32) == U32,
        "commit_flag_zero": data[5] == 0,
        "extra_flag_zero": data[0x10] == 0,
        "item_type_code": struct.unpack_from("<H", data, 6)[0],
        "sequence": struct.unpack_from("<I", data, 8)[0],
        "fresh_storage_read_proved": False,
        "payload_integrity_proved": False,
    }


def saved_regions(item, slot):
    """Return the twelve source/storage intervals of the selected descriptor.

    These are static descriptor coordinates, not a device-read/write plan.
    """
    if item not in ITEMS or slot not in (0, 1):
        raise ValueError("choose comp2/comp6 and slot 0/1")
    ram, slots = ITEMS[item]
    return [dict(index=i, ram_start=ram + i * STRIDE,
                 storage_start=slots[slot] + i * STRIDE, bytes=REGION_BYTES)
            for i in range(REGIONS)]


def v5_body_checksum(data, region_length):
    if region_length < 0x200 or region_length > len(data) or region_length % 4:
        raise ValueError("region must include the header, fit input and be word-aligned")
    body = data[0x200:region_length]
    words = struct.unpack(f"<{len(body) // 4}I", body)
    return (-sum(words)) & U32


def crc8_d5(data):
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (((crc << 1) ^ 0xD5) if crc & 0x80 else (crc << 1)) & 0xFF
    return crc


def inspect_mks(data):
    if len(data) < 0x10:
        raise ValueError("Mks block is shorter than its header")
    size = struct.unpack_from("<I", data, 8)[0]
    if size > len(data) - 0x10:
        raise ValueError("Mks payload length exceeds input")
    return {"payload_bytes": size,
            "header_crc_valid": crc8_d5(data[:0xE]) == data[0xE],
            "data_crc_valid": crc8_d5(data[0x10:0x10 + size]) == data[0xC]}


def unpack_u12_fields(data):
    """Decode one little-endian 12-byte/8-field raw packing model.

    Negative range, physical channel/column and comp2 layout are NOT inferred.
    """
    if len(data) != 12:
        raise ValueError("exactly 12 bytes required for eight fields")
    packed = int.from_bytes(data, "little")
    return [(packed >> (12 * i)) & 0xFFF for i in range(8)]
