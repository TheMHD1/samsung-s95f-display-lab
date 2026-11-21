#!/usr/bin/env python3
"""Decode the two saved C1 banks and export the region of interest."""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT.parent))
import config as C
from decode import unpack_plane

DENSE_BYTES = 0xCDA00
TRANSFER_BYTES = 0xFD200
ROWS = 2160
LANE_WIDTH = 960
COLUMNS = np.arange(1240, 1281)
GENERATIONS = (198, 197)
COLOURS = ("R", "G", "B")
BYTE_BITS = tuple(f"{byte:08b}" for byte in range(256))


def read_segment(table, bank, segment):
    path = C.BACKUP / table / f"bank{bank}_seg{segment:02}.bin"
    return path.read_bytes()


def decode_residuals(raw):
    """Return signed residuals, exact logical bit boundaries, and group orders."""
    if len(raw) != TRANSFER_BYTES:
        raise ValueError("Unexpected C1 segment length")
    words = np.frombuffer(raw[:DENSE_BYTES], dtype=np.uint8).reshape(-1, 16)
    bits = "".join(map(BYTE_BITS.__getitem__, words[:, ::-1].tobytes()))
    count = ROWS * LANE_WIDTH
    values = np.empty(count, dtype=np.int16)
    starts = np.empty(count + 1, dtype=np.int32)
    orders = np.empty(count // 4, dtype=np.uint8)
    position = order = 0
    for group_start in range(0, count, 4):
        orders[group_start // 4] = order
        smallest = 1 << 16
        largest = 0
        for sample in range(group_start, group_start + 4):
            starts[sample] = position
            one = bits.find("1", position)
            suffix = 2 * one - position + 1
            end = suffix + order
            if one < 0 or end > len(bits):
                raise ValueError(f"Incomplete sample {sample} at logical bit {position}")
            unsigned = (int(bits[one:suffix], 2) - 1) << order
            if order:
                unsigned |= int(bits[suffix:end], 2)
            if unsigned >= 1 << 16:
                raise ValueError(f"Residual exceeds 16-bit signed range at sample {sample}")
            values[sample] = -(unsigned // 2 + 1) if unsigned & 1 else unsigned // 2
            smallest = min(smallest, unsigned)
            largest = max(largest, unsigned)
            position = end
        if smallest >= 1 << order:
            order += 1
        elif order and largest < 1 << (order - 1):
            order -= 1

    starts[-1] = position
    end_word = (position + 127) // 128
    if "0" in bits[position:end_word * 128]:
        raise ValueError("Expected one bits after the last sample")
    for word in range(end_word, len(words)):
        if not (np.array_equal(words[word], words[word - 1])
                or np.array_equal(words[word], words[word - 384])):
            raise ValueError(f"Unexpected post-stream word at byte {16 * word:#x}")
    return values, starts, orders


def stored_bit(logical_bit):
    """Convert to the original segment's (byte offset, LSB-numbered bit)."""
    word, offset = divmod(int(logical_bit), 128)
    return 16 * word + 15 - offset // 8, 7 - offset % 8


def unscaled_prefix(residuals):
    """Integrate the three x-3 chains from their zero initial states."""
    absolute = residuals.astype(np.int32).copy()
    for lane in range(3):
        absolute[lane::3] = np.cumsum(absolute[lane::3])
    return absolute


def gradient_checks(residuals, d4):
    """Compare to D4 horizontal gradients using power-of-two scales."""
    gradient = d4[1:, COLUMNS].astype(np.int32) - d4[1:, COLUMNS - 6]
    strong = np.abs(gradient) >= 120
    coded = residuals[1:][strong].astype(np.int32)
    reference = gradient[strong]
    candidate_scales = 1 << np.arange(8)
    errors = np.abs(coded[:, None] * candidate_scales - reference[:, None])
    best = np.argmin(errors, axis=1)
    return coded, reference, candidate_scales[best], errors[np.arange(len(best)), best]


def main():
    shape = len(GENERATIONS), len(COLOURS), ROWS, len(COLUMNS)
    residual_roi = np.empty(shape, dtype=np.int16)
    bit_starts = np.empty(shape, dtype=np.int32)
    bit_lengths = np.empty(shape, dtype=np.uint8)
    orders = np.empty(shape, dtype=np.uint8)
    row0 = np.empty(shape[:2] + shape[-1:], dtype=np.int16)
    ends = np.empty((2, 12), dtype=np.int32)
    exact_prefix = np.empty((2, 12), dtype=np.uint16)
    for bank, generation in enumerate(GENERATIONS):
        for channel, colour in enumerate(COLOURS):
            planes = []
            for half in range(2):
                d4_raw = read_segment("06_D4", bank, channel * 2 + half)
                planes.append(unpack_plane(d4_raw, 1920, ROWS, 2880))
            for half in range(2):
                for parity in range(2):
                    segment = channel * 4 + half + (0 if parity else 2)
                    raw = read_segment("00_C1", bank, segment)
                    res, starts, k = decode_residuals(raw)
                    ends[bank, segment] = starts[-1]
                    prefix = unscaled_prefix(res[:LANE_WIDTH])
                    expected = planes[half][0, parity::2].astype(np.int32) - 2047
                    mismatches = np.flatnonzero(prefix != expected)
                    matched = int(mismatches[0]) if mismatches.size else LANE_WIDTH
                    exact_prefix[bank, segment] = matched
                    print(f"{generation} {colour} half {half} parity {parity} segment {segment:02}"
                          f" end bit {starts[-1]} final stored bit {stored_bit(starts[-1] - 1)}"
                          f" exact row 0 prefix {matched}", flush=True)
                    if half:
                        continue
                    column_mask = COLUMNS % 2 == parity
                    lane_x = COLUMNS[column_mask] // 2
                    indices = np.arange(ROWS)[:, None] * LANE_WIDTH + lane_x
                    if matched <= lane_x[-1]:
                        raise ValueError("Unscaled prefix does not reach the ROI")
                    residual_roi[bank, channel][:, column_mask] = res[indices]
                    bit_starts[bank, channel][:, column_mask] = starts[indices]
                    bit_lengths[bank, channel][:, column_mask] = starts[indices + 1] - starts[indices]
                    orders[bank, channel][:, column_mask] = k[indices // 4]
                    row0[bank, channel, column_mask] = prefix[lane_x]
            coded, ref, scale, err = gradient_checks(residual_roi[bank, channel], planes[0])
            scales, counts = np.unique(scale, return_counts=True)
            print(f"{generation} {colour} strong gradients {len(coded)}"
                  f" same sign {np.count_nonzero(np.sign(coded) == np.sign(ref))}"
                  f" scales {dict(zip(scales.tolist(), counts.tolist()))}"
                  f" within 8 / 16 counts {np.count_nonzero(err <= 8)} / {np.count_nonzero(err <= 16)}"
                  f" max error {err.max()}", flush=True)

    np.savez_compressed(
        C.CAPTURES / "c1-roi.npz",
        columns=COLUMNS, generations=GENERATIONS, colours=COLOURS,
        residuals=residual_roi, logical_bit_start=bit_starts, bit_length=bit_lengths,
        golomb_order=orders, row0_values=row0, stream_end_bit=ends,
        exact_row0_prefix_samples=exact_prefix,
    )
    report_mask = (COLUMNS >= 1250) & (COLUMNS <= 1265)
    print("column   198 R/G/B   197 R/G/B")
    for index in np.flatnonzero(report_mask):
        print(COLUMNS[index], *row0[:, :, index].tolist())
    print("Example codeword start/end (exclusive) and stored start")
    for bank, generation in enumerate(GENERATIONS):
        for y in (0, 100, 1000):
            for x in (1255, 1256, 1257):
                offset = x - COLUMNS[0]
                start = int(bit_starts[bank, 0, y, offset])
                end = start + int(bit_lengths[bank, 0, y, offset])
                byte, bit = stored_bit(start)
                residual = residual_roi[bank, 0, y, offset]
                print(f"{generation} R y={y} x={x} [{start},{end}) byte {byte:#x} bit {bit}"
                      f" residual {residual}")


if __name__ == "__main__":
    main()
