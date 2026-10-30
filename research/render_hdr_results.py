"""Render the published HDR ratio ranges; no image editing or device access."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    root = Path(__file__).resolve().parents[1]
    data = json.loads((root / "docs/assets/hdr-result-ranges.json").read_text())
    rows = data["results"]
    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=180)
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#ffffff")
    ax.axvspan(0.9, 1.1, color="#e4f3ed", zorder=0)
    ax.axvline(1, color="#374151", linewidth=1.2, linestyle="--")
    for y, row in enumerate(rows):
        low, high = row["low"], row["high"]
        ax.plot([low, high], [y, y], color="#087f8c", linewidth=6, solid_capstyle="round")
        ax.text(high + 0.025, y, f"{low:.2f}–{high:.2f}×", va="center", fontsize=11, color="#143c45")
        if "uncorrected_approx" in row:
            value = row["uncorrected_approx"]
            ax.scatter(value, y, marker="x", s=60, color="#b45335", zorder=3)
            ax.annotate("Before ≈0.02×", (value, y), (0.14, y - 0.28), fontsize=10, color="#9a452a")
    ax.set_yticks(range(len(rows)), [f"{r['target_nits']:g} nits" for r in rows])
    ax.set_ylim(len(rows) - 0.5, -0.6)
    ax.set_xlim(0, 1.5)
    ax.set_xlabel("Damaged / healthy column luminance   ·   1.00× = equal measured brightness", labelpad=12)
    ax.set_title("Line correction from near black to brighter HDR", loc="left", fontsize=16, weight="bold", pad=30)
    ax.text(0, 1.045, "Final Kodi HDR v2 · nominal test targets · measured core-column ranges", transform=ax.transAxes, fontsize=10, color="#52616b")
    ax.grid(axis="x", color="#e5e7eb", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.tick_params(axis="both", length=0, labelsize=10, pad=8)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.text(0.125, 0.015, "Green band: ±10% reference. Ranges are not confidence intervals. No final measurements above 100 nits shown.", fontsize=9, color="#52616b")
    fig.subplots_adjust(top=0.76, bottom=0.2, right=0.95)
    fig.savefig(root / "docs/assets/hdr-result-ranges.png", facecolor=fig.get_facecolor())
    plt.close(fig)


if __name__ == "__main__":
    main()
