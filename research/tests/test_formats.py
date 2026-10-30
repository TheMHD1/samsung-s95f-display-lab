"""Synthetic known-answer cases; no firmware, keys, devices or network."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from formats import (Header, inspect_metadata, saved_regions, v5_body_checksum,
                     crc8_d5, inspect_mks, unpack_u12_fields, REGIONS, REGION_BYTES, STRIDE)


class FormatTests(unittest.TestCase):
    def test_fixed_mask_header(self):
        h = Header.parse(bytes.fromhex("0101000038040147f4000000"))
        self.assertEqual((h.opcode, h.address, h.length), (0x101, 0x47010438, 244))
        self.assertEqual((h.family, h.operation, h.direction), (1, 1, "IN / memory"))

    def test_id_header_and_normalization(self):
        h = Header.parse(struct.pack("<III", 0x13, 6, 512))
        self.assertEqual(h.operation, 3)
        self.assertEqual(h.address, 6)

    def test_malformed_header(self):
        for data in (b"", bytes(11), bytes(13), struct.pack("<III", 1, 6, 0)):
            with self.assertRaises(ValueError):
                Header.parse(data)

    def test_family2_boundary_and_overflow(self):
        self.assertTrue(Header(0x203, 0, 512).family2_range_valid())
        self.assertFalse(Header(0x203, 0xFFFF00, 256).family2_range_valid())
        self.assertFalse(Header(0x203, 1, 0xFFFFFFFF).family2_range_valid())
        self.assertFalse(Header(0x203, 0x1842BA00, 512).family2_range_valid())
        self.assertFalse(Header(0x101, 0, 512).family2_range_valid())

    def test_metadata_mutation_and_commit_flags(self):
        data = bytearray(512)
        struct.pack_into("<H", data, 6, 0xA080)
        struct.pack_into("<I", data, 8, 2)
        words = struct.unpack("<127I", data[4:])
        struct.pack_into("<I", data, 0, (~sum(words)) & 0xFFFFFFFF)
        m = inspect_metadata(data)
        self.assertTrue(m["checksum_valid"])
        self.assertEqual((m["item_type_code"], m["sequence"]), (0xA080, 2))
        self.assertFalse(m["fresh_storage_read_proved"])
        data[0x20] ^= 1
        self.assertFalse(inspect_metadata(data)["checksum_valid"])
        data[5] = 1
        self.assertFalse(inspect_metadata(data)["commit_flag_zero"])
        with self.assertRaises(ValueError):
            inspect_metadata(bytes(511))

    def test_strided_layout(self):
        rows = saved_regions("comp2", 0)
        self.assertEqual(len(rows), 12)
        self.assertEqual(rows[0]["storage_start"], 0x1842BC00)
        self.assertEqual(rows[-1]["ram_start"] + rows[-1]["bytes"], 0x7801B000 + 0xC57E00)
        self.assertEqual(REGIONS * REGION_BYTES, 0xBDD800)
        self.assertEqual(REGIONS * STRIDE, 0xC63000)
        self.assertEqual(saved_regions("comp6", 1)[0]["storage_start"], 0x32802400)
        for item, slot in (("other", 0), ("comp2", 2)):
            with self.assertRaises(ValueError):
                saved_regions(item, slot)

    def test_v5_unsigned_word_sum(self):
        data = bytes(512) + struct.pack("<III", 0xFFFFFFFF, 0x10, 3)
        self.assertEqual(v5_body_checksum(data, len(data)), (-0x12) & 0xFFFFFFFF)
        for n in (0, 511, len(data) - 1, len(data) + 4):
            with self.assertRaises(ValueError):
                v5_body_checksum(data, n)

    def test_mks_crc_known_answer_and_corruption(self):
        self.assertEqual(crc8_d5(b"123456789"), 0xBC)
        data = bytearray(0x10 + 5)
        struct.pack_into("<I", data, 8, 5)
        data[0x10:] = b"model"
        data[0xC] = crc8_d5(data[0x10:])
        data[0xE] = crc8_d5(data[:0xE])
        self.assertTrue(inspect_mks(data)["data_crc_valid"])
        self.assertTrue(inspect_mks(data)["header_crc_valid"])
        data[-1] ^= 1
        self.assertFalse(inspect_mks(data)["data_crc_valid"])
        with self.assertRaises(ValueError):
            inspect_mks(data[:-1])

    def test_nonuniform_positive_packing(self):
        fields = [0x123, 0x456, 0x789, 0xABC, 0xDEF, 0x135, 0x246, 0x357]
        packed = sum(x << (12 * i) for i, x in enumerate(fields)).to_bytes(12, "little")
        self.assertEqual(unpack_u12_fields(packed), fields)


if __name__ == "__main__":
    unittest.main()
