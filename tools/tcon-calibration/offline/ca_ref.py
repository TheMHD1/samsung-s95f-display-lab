#!/usr/bin/env python3
"""Offline: turn a dump of YOUR TV's gain block into the reference values the runtime helper pins (writes nothing).

The runtime helper (tcon/helpers/runtime/Program.cs) refuses to write unless the live gain block equals a reference
taken from your own TV: CaRefSha (SHA-256 of the whole block 0x58691000..0x586A77FF) and CaS1Ref (S1 words of lanes
600..660). Take the dump right after a normal TV power-on, before any runtime trim is applied:

  python3 -B tcon/tvdump.py --name ca-ref --ranges 58691000:16800
  python3 -B offline/ca_ref.py <work>/captures/ca-ref/dump.bin

Paste the two printed lines over the placeholders in Program.cs, rebuild the helper, and have the change reviewed.
"""
import hashlib, struct, sys

CA_LEN, S1_OFF, LANES = 0x16800, 0x3C00, range(600, 661)


def ref_lines(block):
    if len(block) != CA_LEN:
        raise ValueError(f'dump is {len(block)} bytes, want {CA_LEN} (range 58691000:16800)')
    sha = hashlib.sha256(block).hexdigest()
    words = [struct.unpack_from('<I', block, S1_OFF + 4 * L)[0] for L in LANES]
    return (f'  const string CaRefSha="{sha}";',
            '  static readonly uint[] CaS1Ref={' + ','.join(f'0x{v:08X}u' for v in words) + '};')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(__doc__); sys.exit(2)
    try:
        for line in ref_lines(open(sys.argv[1], 'rb').read()):
            print(line)
    except (OSError, ValueError) as e:
        print(f'refused: {e}', file=sys.stderr); sys.exit(1)
