"""Rebuild the bilingual outcome and layout figures from frozen records."""

import json
from fractions import Fraction
from pathlib import Path
from runpy import run_path

import matplotlib

matplotlib.use("Agg")

from matplotlib import pyplot as plt
from matplotlib.lines import Line2D
from PIL import Image


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ENGLISH = HERE.parent / "arxiv" / "figures"
BACKGROUND = ROOT / "week8/acceptance/stage8-arms-2026-11-06"
SAME = ROOT / "week9/acceptance/stage9b-eval-2026-11-18"
BLUE = "#23688B"
AMBER = "#A65D22"
INK = "#20272C"
RULE = "#D6DBDF"


def exact_contrasts():
    background = json.loads((BACKGROUND / "exact-audit-v1.json").read_text(
        encoding="utf-8"))["arms"]
    same = json.loads((SAME / "exact-states.json").read_text(encoding="utf-8"))
    names = ("both_over_budget", "budget_gain", "mid_over_budget")
    bg_values = []
    same_values = []
    for name in names:
        bg = [Fraction(background[arm]["exact_states"][name]["exact"])
              for arm in ("G0", "I0")]
        sm = [Fraction(same[arm]["probabilities"][name]) for arm in ("G", "I")]
        bg_values.append(100 * (bg[0] - bg[1]))
        same_values.append(100 * (sm[0] - sm[1]))
        assert same_values[-1] == 100 * Fraction(same["differences"][name])
    return bg_values, same_values


def signed(value):
    return f"{float(value):+.3f}".replace("-", "−")


def probability_label(value):
    return f"{float(value):.3f}"


def save(fig, base):
    png = base.with_suffix(".png")
    fig.savefig(base.with_suffix(".svg"), metadata={"Date": None})
    fig.savefig(png, dpi=600, facecolor="white")
    with Image.open(png) as image:
        rgb = image.convert("RGB")
    rgb.save(png, dpi=(600, 600), optimize=True)
    plt.close(fig)


def style_axis(ax):
    ax.tick_params(axis="y", length=0, pad=7)
    ax.tick_params(axis="x", length=3, pad=3)
    for name in ("left", "top", "right"):
        ax.spines[name].set_visible(False)
    ax.spines["bottom"].set_color("#6E7880")
    ax.spines["bottom"].set_linewidth(.7)


def draw_contrasts(bg, sm, english):
    fig, ax = plt.subplots(figsize=(160 / 25.4, 57 / 25.4))
    fig.subplots_adjust(left=.273 if english else .226, right=.98, bottom=.238, top=.83)
    labels = (
        ("Joint exceedance", "Within-budget gain", "MID12-only exceedance")
        if english else ("双超预算", "预算内增益", "仅 MID12 超预算")
    )
    style_axis(ax)
    ax.set_xlabel("Change in probability (percentage points)"
                  if english else "概率变化（百分点）", labelpad=5)
    ax.set(xlim=(-3.45, 11.35), ylim=(-.48, 2.48), xticks=(-2, 0, 2, 4, 6, 8, 10),
           yticks=(2, 1, 0), yticklabels=labels)
    for boundary in (.5, 1.5):
        ax.axhline(boundary, color=RULE, linewidth=.5, zorder=1)
    ax.axvline(0, color=INK, linewidth=.85, zorder=2)
    handles = []
    for values, offset, color, marker, fill, label in (
        (bg, .155, BLUE, "o", BLUE, "background: G0 − I0"),
        (sm, -.155, AMBER, "s", "white", "same: G − I"),
    ):
        handles.append(Line2D([], [], markeredgecolor=color, markerfacecolor=fill,
                              marker=marker, linestyle="None", markersize=5.2, label=label))
        for row, change in zip((2, 1, 0), values):
            x, y = float(change), row + offset
            ax.scatter(x, y, s=29, facecolors=fill, marker=marker, edgecolors=color,
                       linewidths=1.15, zorder=4)
            direction = 1 if x >= 0 else -1
            ax.annotate(signed(change), (x, y), xytext=(direction * 5, 0),
                        textcoords="offset points", ha="left" if x >= 0 else "right",
                        va="center", color=INK)
    ax.legend(handles=handles, loc="lower center", frameon=False,
              bbox_to_anchor=(.5, 1.035), ncols=2, handletextpad=.4, columnspacing=1.55)
    save(fig, (ENGLISH / "figure-3-contrasts-en") if english else
         (HERE / "figure-3-outcome-contrasts"))


def layout_data():
    # Reuse the exact coefficient and partition enumeration in the original figure.
    calculation = run_path(str(HERE / "figure-2-layout-enumeration.py"))
    probability = calculation["probability"]
    enumerate_layouts = calculation["layouts"]
    observed = [(name, multi, row) for name, multi, row, _ in
                calculation["observed_layouts"]()]
    rows = []
    for name, multi, row in observed:
        capacity = sum(multi)
        values = sorted(100 * probability(parts) for parts in enumerate_layouts(capacity))
        rows.append((name, capacity, values, 100 * probability(multi), row))
    assert {capacity: len(values) for _, capacity, values, _, _ in rows} == {11: 14, 32: 1507}
    return rows


def plot_layout_rows(ax, rows, annotate_full_range):
    for name, capacity, values, observed, row in rows:
        color = BLUE if capacity == 32 else AMBER
        low, high = float(values[0]), float(values[-1])
        span_style = (0, (4, 2)) if capacity == 32 else (0, (1, 1.5))
        ax.hlines(row + .21, low, high, color=color, linewidth=.9,
                  linestyles=span_style, zorder=2)
        ax.vlines([low, high], row + .13, row + .28, color=color,
                  linewidth=.9, zorder=2)
        jitter = [.24 * ((i * .61803398875) % 1 - .5) for i in range(len(values))]
        dense_row = capacity == 32 and annotate_full_range
        ax.scatter([float(p) for p in values], [row + offset for offset in jitter],
                   marker="s" if capacity == 11 else "o",
                   s=4 if dense_row else 8, color=color,
                   alpha=.72 if dense_row else .91, linewidths=0, zorder=3)
        ax.scatter(float(observed), row, marker="D", s=31, facecolor="white",
                   edgecolor=color, linewidth=1.25, zorder=4)
        if annotate_full_range:
            for bound in (low, high):
                ax.annotate(probability_label(bound), (bound, row + .28), xytext=(0, 2),
                            textcoords="offset points", ha="center", va="bottom")
            ax.annotate(f"{name}  {probability_label(observed)}%", (float(observed), row),
                        xytext=(0, -6), textcoords="offset points",
                        ha="center" if capacity == 32 else "left", va="top", color=INK)


def draw_layouts(rows, english):
    fig, (overview, zoom) = plt.subplots(2, 1, figsize=(160 / 25.4, 87 / 25.4),
                                         height_ratios=(1.15, 1))
    fig.subplots_adjust(left=.196 if english else .18, right=.973,
                        bottom=.155, top=.89, hspace=.59)
    overlap = max(values[0] for _, _, values, _, _ in rows), min(
        values[-1] for _, _, values, _, _ in rows)
    assert overlap[0] < overlap[1]
    for ax in (overview, zoom):
        style_axis(ax)
        ax.set(ylim=(-.45, 1.68), yticks=[row for _, _, _, _, row in rows])
        ax.axvspan(*map(float, overlap), color="#E3E7EB", zorder=1)
    overview.set(xlim=(12, 28), xticks=range(12, 29, 2))
    overview.set_title("a   All layouts" if english else "a   全部布局",
                       loc="left", fontsize=9.5, fontweight="bold", pad=4)
    overview.set_yticklabels([
        f"{capacity} images\n{len(values):,} layouts" if english else
        f"{capacity} 张图像\n{len(values):,} 种布局"
        for _, capacity, values, _, _ in rows
    ])
    zoom.set(xlim=(14, 15.4), xticks=(14, 14.4, 14.8, 15.2))
    zoom.set_title("b   Detail of the lower end" if english else "b   低概率端局部放大",
                   loc="left", fontsize=9.5, fontweight="bold", pad=4)
    zoom.set_yticklabels([f"{capacity} images" if english else f"{capacity} 张图像"
                         for _, capacity, _, _, _ in rows])
    zoom.set_xlabel("Probability of joint exceedance (%)"
                    if english else "双超预算概率（%）", labelpad=5)
    zoom.text(float(sum(overlap) / 2), 1.46,
              "–".join(probability_label(value) for value in overlap) + "%",
              ha="center", va="center")
    plot_layout_rows(overview, rows, annotate_full_range=True)
    plot_layout_rows(zoom, rows, annotate_full_range=False)
    save(fig, (ENGLISH / "figure-4-layout-en") if english else
         (HERE / "figure-4-layout-sensitivity"))


def main():
    style = {
        "font.family": ["Arial", "Microsoft YaHei", "DejaVu Sans"],
        "font.size": 9,
        "text.color": INK,
        "axes.labelcolor": INK,
        "xtick.color": INK,
        "ytick.color": INK,
        "svg.fonttype": "path",
        "svg.hashsalt": "aebad-result-figures",
    }
    bg, same = exact_contrasts()
    print("Outcome contrasts (pp):", [signed(x) for x in bg], [signed(x) for x in same])
    rows = layout_data()
    for name, capacity, values, observed, _ in rows:
        print(name, capacity, len(values), *(f"{float(p):.6f}%" for p in
                                            (values[0], values[-1], observed)))
    with plt.rc_context(style):
        for english in (False, True):
            draw_contrasts(bg, same, english)
            draw_layouts(rows, english)


if __name__ == "__main__":
    main()
