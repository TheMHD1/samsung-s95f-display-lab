#!/usr/bin/env python3
"""Evaluate an S0 bake using only saved D4 and optional C1 DDR captures."""

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config as C
from decode import unpack_plane

CAPTURES = C.CAPTURES
COLOURS = "RGB"
WIDTH, ROWS, PITCH = 1920, 2160, 2880
HEADER_SIZE = 512
PLANE_SIZE = ROWS * PITCH
D4_SIZES = [HEADER_SIZE] * 2 + [PLANE_SIZE] * 6
DDR_STRIDE = 0xFE000
C1_COLUMNS = np.arange(1250, 1291)
D4_TO_C1 = 2047
EXCLUDED = ((1250, 1266), (1276, 1285))
BAKE_WORDS = {629: 0x3712, 640: 0x3D8D}
STOCK = 0x40CA
THRESHOLD = 10
E_TOLERANCE = 0.03
COUNTS_PER_CODE = 6.7


@dataclass(frozen=True)
class D4Capture:
    name: str
    generations: tuple[int, int]
    bank: int
    medians: np.ndarray
    row0: np.ndarray

    def info(self):
        return dict(name=self.name, bank_generations=list(self.generations),
                    selected_bank=self.bank, generation=self.generations[self.bank])


def capture_name(value):
    if not value or value in (".", "..") or Path(value).name != value:
        raise argparse.ArgumentTypeError("use a capture directory name under captures/")
    return value


def read_capture(name, sizes):
    directory = CAPTURES / name
    meta, dump = ((directory / file).resolve(strict=True) for file in ("meta.json", "dump.bin"))
    if any(not path.is_relative_to(CAPTURES) or not path.is_file() for path in (meta, dump)):
        raise ValueError(f"{name} requires regular meta.json and dump.bin files under captures/")
    try:
        actual_sizes = [part["read"] for part in json.loads(meta.read_text())["result"]["ranges"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{name} has invalid capture metadata") from exc
    if actual_sizes != sizes or dump.stat().st_size != sum(sizes):
        raise ValueError(f"{name} has unexpected capture layout or dump length")
    return dump.read_bytes()


def d4_generations(blob):
    return tuple(int.from_bytes(blob[offset + 8:offset + 12], "little")
                 for offset in (0, HEADER_SIZE))


def read_d4(name):
    blob = memoryview(read_capture(name, D4_SIZES))
    generations = d4_generations(blob)
    bank = max(range(2), key=generations.__getitem__)
    medians = np.empty((len(COLOURS), WIDTH))
    row0 = np.empty((len(COLOURS), WIDTH), dtype=np.int32)
    for channel in range(len(COLOURS)):
        offset = 2 * HEADER_SIZE + (bank * len(COLOURS) + channel) * PLANE_SIZE
        plane = unpack_plane(blob[offset:offset + PLANE_SIZE], WIDTH, ROWS, PITCH)
        medians[channel] = np.median(plane, axis=0)
        row0[channel] = plane[0]
    return D4Capture(name, generations, bank, medians, row0)


def local_reference(medians):
    healthy = np.ones(WIDTH, dtype=bool)
    for first, last in EXCLUDED:
        healthy[first:last + 1] = False
    columns = np.flatnonzero(healthy)
    reference = np.empty_like(medians, dtype=float)
    for column in range(WIDTH):
        left, right = columns.searchsorted(column, side="left"), columns.searchsorted(column, side="right")
        neighbours = np.concatenate((columns[max(0, left - 10):left], columns[right:right + 10]))
        reference[:, column] = np.median(medians[:, neighbours], axis=1)
    return reference


def footprint(old, new):
    delta = new - old
    shift = np.median(delta, axis=1)
    centred = delta - shift[:, None]
    expected = {column for lane in BAKE_WORDS for column in (2 * lane, 2 * lane + 1)}
    points = []
    for column in np.flatnonzero(np.any(np.abs(centred) > THRESHOLD, axis=0)).tolist():
        values = centred[:, column]
        points.append(dict(column=column, centred_delta_counts=values.tolist(),
                           centred_delta_pct_of_old=[100 * float(delta / base) if base > 0 else None
                                                     for delta, base in zip(values, old[:, column])],
                           over_threshold=[colour for colour, value in zip(COLOURS, values)
                                           if abs(value) > THRESHOLD],
                           expected_column=column in expected))
    return dict(global_shift_counts=shift.tolist(), points=points,
                unexpected_columns=[point["column"] for point in points if not point["expected_column"]],
                possible_column_indices=[column for column in BAKE_WORDS
                                         if np.any(centred[:, column] < -THRESHOLD)],
                expected_drop_complete=bool(np.all(centred[:, sorted(expected)] < -THRESHOLD)))


def linearity(old, new, old_ref, new_ref):
    readings = []
    for lane, word in BAKE_WORDS.items():
        for column in (2 * lane, 2 * lane + 1):
            for channel, colour in enumerate(COLOURS):
                a, b = old[channel, column], new[channel, column]
                ref_a, ref_b = old_ref[channel, column], new_ref[channel, column]
                ratio = exponent = None
                if min(a, b, ref_a, ref_b) > 0:
                    ratio = float((b / ref_b) / (a / ref_a))
                    exponent = math.log(ratio) / math.log(word / STOCK)
                readings.append(dict(lane=lane, column=column, colour=colour, word=f"0x{word:04X}",
                                     ratio=ratio, exponent=exponent,
                                     accepted=exponent is not None and 0.97 <= exponent <= 1.03))
    return readings


def fit_calibration(scan, readings, old, new, old_ref, new_ref):
    if scan["possible_column_indices"] or not scan["expected_drop_complete"]:
        return dict(status="expected lane footprint is incomplete or column indexing is ambiguous")
    exponents = [reading["exponent"] for reading in readings]
    if any(value is None or value <= 0 for value in exponents):
        return dict(status="a positive exponent could not be measured for every baked sample")
    if all(reading["accepted"] for reading in readings):
        return dict(status="linear through zero", exponent=1.0)
    common = float(np.median(exponents))
    if all(abs(value - common) <= E_TOLERANCE for value in exponents):
        return dict(status="shared measured exponent", exponent=common)

    fits = []
    for reading in readings:
        lane, column = reading["lane"], reading["column"]
        channel = COLOURS.index(reading["colour"])
        stock_value = old[channel, column] / old_ref[channel, column] * new_ref[channel, column]
        slope = (new[channel, column] - stock_value) / (BAKE_WORDS[lane] - STOCK)
        fits.append(dict(column=column, colour=reading["colour"],
                         intercept_counts=float(stock_value - slope * STOCK),
                         slope_counts_per_word=float(slope)))
    return dict(status="exponents differ, using two-point affine fits on the new reference scale",
                affine_fits=fits, max_trim_before_second_bake_pct=15)


def suggested_words(new, reference, exponent):
    suggestions = []
    for lane in (628, 629):
        columns = [2 * lane, 2 * lane + 1]
        ref = reference[:, columns]
        applied = BAKE_WORDS.get(lane, STOCK) / STOCK
        untrimmed = new[:, columns] / applied**exponent
        index = int(np.argmin((untrimmed - ref)[:2].mean(axis=0)))
        target = float(ref[:2, index].mean() + 30)
        source = float(untrimmed[:2, index].mean())
        suggestion = dict(lane=lane, columns=columns, target_column=columns[index], target_counts=target,
                          untrimmed_d4_counts=untrimmed.tolist())
        if np.any(untrimmed < ref):
            suggestions.append(dict(suggestion, status="untrimmed D4 is already below reference"))
            continue
        requested = (target / source)**(1 / exponent)
        minimum = float(np.max((ref / untrimmed)**(1 / exponent)))
        gain = max(math.ceil(STOCK * max(0.78, minimum)), round(STOCK * min(1.0, requested)))
        gain = min(STOCK, gain)
        residual = untrimmed * (gain / STOCK)**exponent - ref
        suggestions.append(dict(suggestion, gain_ratio=gain / STOCK, requested_ratio=requested,
                                reference_floor_limited=minimum > max(0.78, min(1.0, requested)),
                                word=f"0x{gain * 0x10001:08X}",
                                predicted_residual_counts=residual.tolist(),
                                predicted_residual_codes=(residual / COUNTS_PER_CODE).tolist()))
    return suggestions


def read_c1(name):
    original_paths = sys.path[:]
    sys.path.insert(0, str(Path(__file__).resolve().parent))   # decode_c1.py
    try:
        from decode_c1 import LANE_WIDTH, TRANSFER_BYTES, decode_residuals, unscaled_prefix
    finally:
        sys.path[:] = original_paths

    data = read_capture(name, [DDR_STRIDE] * 12)
    row0 = np.empty((len(COLOURS), len(C1_COLUMNS)), dtype=np.int32)
    for channel, colour in enumerate(COLOURS):
        for parity in (0, 1):
            segment = channel * 4 + (0 if parity else 2)
            offset = segment * DDR_STRIDE
            mask = C1_COLUMNS % 2 == parity
            try:
                residuals, _, _ = decode_residuals(data[offset:offset + TRANSFER_BYTES])
            except ValueError as exc:
                raise ValueError(f"{name} C1 segment {segment} ({colour}): {exc}") from exc
            row0[channel, mask] = unscaled_prefix(residuals[:LANE_WIDTH])[C1_COLUMNS[mask] // 2]
    return row0


def compare_c1(old_name, new_name, new_d4):
    if not (old_name or new_name):
        return None
    old = read_c1(old_name) if old_name else None
    new = None
    if new_name:
        new = old if new_name == old_name else read_c1(new_name)
    expected = new_d4.row0[:, C1_COLUMNS] - D4_TO_C1
    return dict(columns=C1_COLUMNS.tolist(), old_capture=old_name, new_capture=new_name,
                old=old.tolist() if old is not None else None, new=new.tolist() if new is not None else None,
                old_to_new_delta=(new - old).tolist() if old is not None and new is not None else None,
                new_d4_row0_minus_2047=expected.tolist(),
                new_matches_d4=(new == expected).tolist() if new is not None else None)


def evaluate(old, new, c1):
    old_ref, new_ref = local_reference(old.medians), local_reference(new.medians)
    old_excess, new_excess = old.medians - old_ref, new.medians - new_ref
    delta_codes = (new_excess - old_excess) / COUNTS_PER_CODE
    scan = footprint(old.medians, new.medians)
    readings = linearity(old.medians, new.medians, old_ref, new_ref)
    model = fit_calibration(scan, readings, old.medians, new.medians, old_ref, new_ref)
    suggestions = suggested_words(new.medians, new_ref, model["exponent"]) if "exponent" in model else []
    return dict(old=old.info(), new=new.info(), colours=list(COLOURS), counts_per_code=COUNTS_PER_CODE,
                d4=dict(columns=list(range(WIDTH)), old_median_counts=old.medians.tolist(),
                        new_median_counts=new.medians.tolist(), old_reference_counts=old_ref.tolist(),
                        new_reference_counts=new_ref.tolist(), old_excess_counts=old_excess.tolist(),
                        new_excess_counts=new_excess.tolist(), delta_excess_codes=delta_codes.tolist(),
                        predicted_brightness_change_codes_if_case_d=(-delta_codes).tolist()),
                footprint=scan, linearity=readings, calibration=model, suggested_words=suggestions, c1=c1,
                verdict="D4/C1 evidence only. CONSULT-3 outcome requires photos.")


def rgb(values, spec="+.2f"):
    return "/".join(format(value, spec) for value in values)


def print_summary(report):
    for side in ("old", "new"):
        capture = report[side]
        print(f"D4 {side} {capture['name']}  generations {capture['bank_generations']}  "
              f"selected bank {capture['selected_bank']} (gen {capture['generation']})")
        if capture["bank_generations"][0] == capture["bank_generations"][1]:
            print("  Tied generations; selected bank 0.")
    if report["new"]["generation"] <= report["old"]["generation"]:
        print("D4 generation did not advance.")
    scan = report["footprint"]
    print(f"\nD4 footprint  R/G/B median shifts {rgb(scan['global_shift_counts'])} counts")
    print(f"{len(scan['points'])} columns exceed {THRESHOLD} counts in at least one colour "
          f"({len(scan['unexpected_columns'])} unexpected).")
    if scan["points"]:
        print("   col      centred delta R/G/B counts            % of old D4     colours over threshold")
    for point in scan["points"]:
        label = "expected column" if point["expected_column"] else "UNEXPECTED"
        pct = "/".join("n/a" if value is None else f"{value:+.2f}" for value in point["centred_delta_pct_of_old"])
        print(f"  {point['column']:4d}  {rgb(point['centred_delta_counts']):>30}  {pct:>22}  "
              f"{''.join(point['over_threshold'])}  {label}")
    if scan["possible_column_indices"]:
        print(f"  INDEX CAUTION: negative footprint at {scan['possible_column_indices']}. "
              "S0 may be indexed by panel column.")
    print("  Expected drops on 1258/1259 (~15%) and 1280/1281 (~5%) in all three colours: "
          f"{'yes' if scan['expected_drop_complete'] else 'no'}")

    print("\nLinearity  accepted e 0.97–1.03")
    print("  lane   col   colour     normalised r       e     pass")
    for reading in report["linearity"]:
        ratio = "n/a" if reading["ratio"] is None else f"{reading['ratio']:.6f}"
        exponent = "n/a" if reading["exponent"] is None else f"{reading['exponent']:.5f}"
        accepted = "yes" if reading["accepted"] else "no"
        print(f"  {reading['lane']:4d}  {reading['column']:4d}       {reading['colour']}"
              f"      {ratio:>11}  {exponent:>7}    {accepted}")

    print(f"\nS0 calibration  {report['calibration']['status']}")
    if "exponent" in report["calibration"]:
        print(f"  Model exponent {report['calibration']['exponent']:.5f}")
    for fit in report["calibration"].get("affine_fits", []):
        print(f"  {fit['column']} {fit['colour']}  D = {fit['intercept_counts']:.3f} "
              f"{fit['slope_counts_per_word']:+.6f} × w")
    if "affine_fits" in report["calibration"]:
        print("  CONSULT-6 caps trim at 15% pending a second bake.")
    if not report["suggested_words"]:
        print("  Suggested words unavailable.")
    for lane in report["suggested_words"]:
        if "word" not in lane:
            print(f"  Lane {lane['lane']}  {lane['status']}")
            continue
        print(f"  Lane {lane['lane']}  {lane['word']}  {lane['gain_ratio']:.3%} of stock  "
              f"target column {lane['target_column']}  target {lane['target_counts']:.2f} counts")
        if lane["reference_floor_limited"]:
            print("    The reference floor raised the gain above the target ratio.")
        for index, column in enumerate(lane["columns"]):
            counts = [values[index] for values in lane['predicted_residual_counts']]
            codes = [values[index] for values in lane['predicted_residual_codes']]
            print(f"    {column}  residual R/G/B {rgb(counts)} counts  {rgb(codes)} codes")

    evidence_columns = {1256, 1257, 1258, 1259, 1280, 1281}
    evidence_columns.update(point["column"] for point in scan["points"])
    print("\nD4 evidence  R/G/B")
    print("   col     old excess (counts)     new excess (counts)     Δexcess (codes)       brightness if (d) (codes)")
    for column in sorted(evidence_columns):
        fields = [rgb([values[column] for values in report["d4"][key]]) for key in (
            "old_excess_counts", "new_excess_counts", "delta_excess_codes",
            "predicted_brightness_change_codes_if_case_d")]
        print(f"  {column:4d}  " + "  ".join(f"{field:>22}" for field in fields))

    c1 = report["c1"]
    if c1 is None:
        print("\nC1 DDR  no captures selected")
    else:
        print(f"\nC1 DDR row 0  old {c1['old_capture'] or '—'}  new {c1['new_capture'] or '—'}")
        print("   col      old C1 R/G/B      new C1 R/G/B     new D4−2047 R/G/B     exact R/G/B")
        for index, column in enumerate(c1["columns"]):
            fields = [rgb([values[index] for values in c1[key]], "d") if c1[key] is not None else "—"
                      for key in ("old", "new", "new_d4_row0_minus_2047")]
            matches = c1["new_matches_d4"]
            match = "/".join("Y" if values[index] else "N" for values in matches) if matches is not None else "—"
            print(f"  {column:4d}  " + "  ".join(f"{field:>17}" for field in fields) + f"  {match:>13}")
        if c1["new_matches_d4"] is not None:
            exact = np.asarray(c1["new_matches_d4"])
            print(f"  New C1 equals new D4 row 0 minus 2047 on {np.count_nonzero(exact)}/{exact.size} samples.")
    print(f"\n{report['verdict']}")


def self_test():
    old = np.repeat([[1830.0], [1900.0], [1970.0]], WIDTH, axis=1)
    old[:, 1256:1260] += [360, 410, 466, 346]
    new = old.copy()
    new[:, 1258:1260] *= 0.85
    new[:, 1280:1282] *= 0.95
    scan = footprint(old, new)
    readings = linearity(old, new, local_reference(old), local_reference(new))
    found = [point["column"] for point in scan["points"]]
    if found != [1258, 1259, 1280, 1281] or not scan["expected_drop_complete"]:
        raise ValueError(f"synthetic footprint mismatch: {found}")
    if any(not reading["accepted"] or abs(reading["exponent"] - 1) > 0.002 for reading in readings):
        raise ValueError(f"synthetic exponent mismatch: {readings}")
    print("Synthetic self-test passed  footprint 1258/1259 and 1280/1281, all 12 exponents within 0.002 of 1.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=capture_name, default="d4-gen199", help="old D4 name (default d4-gen199)")
    parser.add_argument("--new", type=capture_name, help="new D4 name")
    parser.add_argument("--c1-old", type=capture_name, help="old C1 name (default c1-ddr-pre with --c1-new)")
    parser.add_argument("--c1-new", type=capture_name, help="new C1 name")
    parser.add_argument("--self-test", action="store_true", help="run only the in-memory check")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
            return
        if not args.new:
            parser.error("--new is required for capture evaluation")
        old = read_d4(args.old)
        new = old if args.old == args.new else read_d4(args.new)
        c1_old = args.c1_old or ("c1-ddr-pre" if args.c1_new else None)
        report = evaluate(old, new, compare_c1(c1_old, args.c1_new, new))
        print_summary(report)
        path = CAPTURES / f"{args.new}-eval.json"
        payload = json.dumps(report, indent=2, allow_nan=False) + "\n"
        try:
            with path.open("x", encoding="utf-8") as output:
                output.write(payload)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_text() != payload:
                raise ValueError(f"report already exists with different content: {path}") from None
        print(f"JSON report {path.relative_to(CAPTURES.parent)}")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"bake_eval.py: {exc}\n")


if __name__ == "__main__":
    main()
