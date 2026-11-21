import hashlib, struct, unittest
import ca_ref


class CaRef(unittest.TestCase):
    def test_lines(self):
        b = bytearray(ca_ref.CA_LEN)
        struct.pack_into('<I', b, ca_ref.S1_OFF + 4 * 600, 0x41ED41F6)
        struct.pack_into('<I', b, ca_ref.S1_OFF + 4 * 660, 0x40944098)
        sha, arr = ca_ref.ref_lines(bytes(b))
        self.assertIn(hashlib.sha256(bytes(b)).hexdigest(), sha)
        self.assertTrue(arr.split('{')[1].startswith('0x41ED41F6u,'))
        self.assertTrue(arr.endswith('0x40944098u};'))
        self.assertEqual(arr.count('u'), 61 + arr.count('uint'))

    def test_wrong_size(self):
        with self.assertRaises(ValueError):
            ca_ref.ref_lines(b'\0' * 100)


if __name__ == '__main__':
    unittest.main()
