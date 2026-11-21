import unittest
import s0words as w

BAKE11_S0 = {627: 0x408A40CA, 628: 0x32E03055, 629: 0x339A2CB4, 630: 0x40CA3904}
BAKE11_S1 = {627: (0x40AA40AE, 0x3A333A36), 628: (0x40A340A6, 0x2B4E2B50),
             629: (0x409B409F, 0x26C326C6), 630: (0x40944098, 0x325F3262)}


class S0(unittest.TestCase):
    def test_bake11_words_round_trip(self):
        for lane, word in BAKE11_S0.items():
            lo, hi = w.halves(word)
            ad, old, new = w.s0_word(lane, lo / w.S0_STOCK_HALF, hi / w.S0_STOCK_HALF)
            self.assertEqual((ad, old, new), (0x58691000 + 4 * lane, 0x40CA40CA, word))

    def test_addresses_match_runbook(self):
        self.assertEqual([w.s0_word(l, 1, 1)[0] for l in (627, 628, 629, 630)],
                         [0x586919CC, 0x586919D0, 0x586919D4, 0x586919D8])

    def test_low_half_is_even_column(self):
        self.assertEqual(w.decode('s0', 628, 0x32E03055), {1256: 0.746, 1257: 0.7852})

    def test_hex_halves_reproduce_bake11(self):
        self.assertEqual(w.s0_word(628, *w._gains('0x3055,0x32E0'))[2], 0x32E03055)
        self.assertEqual(w.s0_word(629, *w._gains('0x2CB4,0x339A'))[2], 0x339A2CB4)

    def test_bounds(self):
        for bad in ((628, 0.64, 1.0), (628, 1.01, 1.0), (599, 1, 1), (661, 1, 1), (680, 1, 1), (640, 0.9, 0.8)):
            with self.assertRaises(ValueError):
                w.s0_word(*bad)
        w.s0_word(640, 0.9, 0.9)          # equal halves allowed outside the band

    def test_cli_pokes(self):
        self.assertEqual(w.main(['s0', '628=0.746,0.785']), 0)
        self.assertEqual(w.main(['s0', '628=0.5']), 1)


class S1(unittest.TestCase):
    def test_bake11_trims_round_trip(self):
        for lane, (stock, word) in BAKE11_S1.items():
            lo, hi = w.halves(word); slo, shi = w.halves(stock)
            ad, old, new = w.s1_word(lane, stock, lo / slo, hi / shi)
            self.assertEqual((ad, old, new), (0x58694C00 + 4 * lane, stock, word))

    def test_addresses_match_rt_tool(self):
        self.assertEqual([w.s1_word(l, s, 0.9, 0.9)[0] for l, (s, _) in BAKE11_S1.items()],
                         [0x586955CC, 0x586955D0, 0x586955D4, 0x586955D8])

    def test_bounds(self):
        with self.assertRaises(ValueError):
            w.s1_word(628, 0x40A340A6, 1.01, 1.0)       # above stock
        with self.assertRaises(ValueError):
            w.s1_word(628, 0x40A340A6, 0.5, 0.5)        # more than 8000 below stock
        with self.assertRaises(ValueError):
            w.s1_word(631, 0x40944098, 0.9, 0.9)        # lane not allowed
        with self.assertRaises(ValueError):
            w.s1_word(628, 0x40A340A7, 0.9, 0.9)        # wrong stock
        with self.assertRaises(ValueError):
            w.s1_word(628, 0x40A340A6, 1, 1)            # NEW == STOCK


if __name__ == '__main__':
    unittest.main()
