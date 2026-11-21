#!/usr/bin/env python3
"""Offline S0 / S1 word calculator for the S95F TCON sensing-gain arrays (no TV access, writes nothing).

A lane L drives panel columns 2L (even, LOW 16 bits of the word) and 2L+1 (odd, HIGH 16 bits).
S0 (scan-time gain, 0x58691000 + 4*L): stock half 0x40CA on every lane; gain = half / 0x40CA.
S1 (runtime gain,   0x58694C00 + 4*L): stock differs per lane; gain = half / that lane's stock half.
Bounds mirror the live tools: S0 halves in [0x2A1C (x0.65), 0x40CA], lanes 600..660 (TCON helper CheckAddr),
per-column halves only on 626..632 (bake_now.py); S1 only lanes 627..630 with their stored stock words, halves in
[9900, stock half], at most 8000 below stock, NEW != STOCK (rt_tool.py check_s1). Never above stock.
A gain may be given as a decimal (0.746) or as an exact 16-bit half in hex (0x3055) for exact reproduction.

usage:
  s0words.py s0 628=0.80 629=0.80                    -> pokes string for bake_now.py  (lane=gain or even,odd)
  s0words.py s0 628=0x3055,0x32E0 629=0x2CB4,0x339A  -> exact bake-11 words for lanes 628/629
  s0words.py s1 628:0x40A340A6=0.67,0.67              -> S1 word for lane 628 from its stock word
  s0words.py decode s0 628 0x32E03055                 -> per-column gains of a word
  s0words.py decode s1 628 0x2B4E2B50 0x40A340A6
"""
import sys

S0_BASE, S1_BASE = 0x58691000, 0x58694C00
S0_STOCK_HALF, S0_FLOOR = 0x40CA, 0x2A1C
S1_FLOOR, S1_STEP = 9900, 8000
S1_STOCK = {627: 0x40AA40AE, 628: 0x40A340A6, 629: 0x409B409F, 630: 0x40944098}   # stored stock words (rt_tool.LANES)


def halves(word):
    return word & 0xFFFF, word >> 16


def s0_word(lane, g_even, g_odd):
    """(address, stock word, new word) for an S0 lane; raises ValueError outside the live tools' bounds."""
    if not 600 <= lane <= 660:
        raise ValueError(f'lane {lane} outside 600..660')
    lo, hi = _half(g_even, S0_STOCK_HALF), _half(g_odd, S0_STOCK_HALF)
    for h in (lo, hi):
        if not S0_FLOOR <= h <= S0_STOCK_HALF:
            raise ValueError(f'lane {lane}: half 0x{h:04X} outside 0x{S0_FLOOR:04X}..0x{S0_STOCK_HALF:04X} (x0.65..x1.00)')
    if lo != hi and not 626 <= lane <= 632:
        raise ValueError(f'lane {lane}: per-column halves only on lanes 626..632')
    return S0_BASE + 4 * lane, (S0_STOCK_HALF << 16) | S0_STOCK_HALF, (hi << 16) | lo


def s1_word(lane, stock, g_even, g_odd):
    """(address, stock word, new word) for an S1 lane, gains relative to that lane's own stock halves."""
    if lane not in S1_STOCK:
        raise ValueError(f'lane {lane}: S1 only on lanes 627..630')
    if stock != S1_STOCK[lane]:
        raise ValueError(f'lane {lane}: stock 0x{stock:08X} is not the stored stock 0x{S1_STOCK[lane]:08X}')
    s_lo, s_hi = halves(stock)
    lo, hi = _half(g_even, s_lo), _half(g_odd, s_hi)
    for h, s in ((lo, s_lo), (hi, s_hi)):
        if not (S1_FLOOR <= h <= s and s - h <= S1_STEP):
            raise ValueError(f'lane {lane}: half {h} outside [{max(S1_FLOOR, s - S1_STEP)}, {s}]')
    new = (hi << 16) | lo
    if new == stock:
        raise ValueError(f'lane {lane}: NEW equals STOCK')
    return S1_BASE + 4 * lane, stock, new


def decode(kind, lane, word, stock=None):
    lo, hi = halves(word)
    if kind == 's0':
        s_lo = s_hi = S0_STOCK_HALF
    else:
        if stock is None:
            raise ValueError('decode s1 needs the lane stock word')
        s_lo, s_hi = halves(stock)
    return {2 * lane: round(lo / s_lo, 4), 2 * lane + 1: round(hi / s_hi, 4)}


class Half(int):
    """An exact 16-bit half given in hex on the command line (not a gain)."""


def _half(g, stock_half):
    """A gain -> rounded half; a Half is already exact."""
    return int(g) if isinstance(g, Half) else round(g * stock_half)


def _gains(txt):
    p = [Half(int(x, 16)) if x.strip().lower().startswith('0x') else float(x) for x in txt.split(',')]
    if len(p) == 1:
        p *= 2
    if len(p) != 2:
        raise ValueError(f'want even,odd gains, got {txt!r}')
    return p


def main(argv):
    if len(argv) < 2 or argv[0] in ('-h', '--help'):
        print(__doc__)
        return 0 if argv[:1] in (['-h'], ['--help']) else 2
    cmd, rest = argv[0], argv[1:]
    try:
        if cmd == 's0':
            pokes = []
            for item in rest:
                lane, g = item.split('=')
                ad, old, new = s0_word(int(lane), *_gains(g))
                print(f'lane {lane}: 0x{ad:08X}  stock 0x{old:08X} -> 0x{new:08X}  cols {decode("s0", int(lane), new)}')
                pokes.append(f'{ad:08x}:{old:08x}:{new:08x}')
            print('pokes:', ','.join(pokes))
        elif cmd == 's1':
            for item in rest:
                head, g = item.split('=')
                lane, stock = head.split(':')
                ad, old, new = s1_word(int(lane), int(stock, 16), *_gains(g))
                print(f'lane {lane}: 0x{ad:08X}  stock 0x{old:08X} -> 0x{new:08X}  cols {decode("s1", int(lane), new, old)}')
        elif cmd == 'decode':
            kind, lane, word = rest[0], int(rest[1]), int(rest[2], 16)
            stock = int(rest[3], 16) if len(rest) > 3 else None
            print(decode(kind, lane, word, stock))
        else:
            print(__doc__)
            return 2
    except (ValueError, IndexError) as e:
        print(f'refused: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
