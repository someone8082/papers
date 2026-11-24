"""Enumerate the layouts in manuscript §6.1 and render Figure 2."""

import json
from fractions import Fraction
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from matplotlib import pyplot as plt
from matplotlib.ticker import MultipleLocator


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BACKGROUND = ROOT / "week8/acceptance/stage8-arms-2026-11-06"
SAME = ROOT / "week9/acceptance"
NORMALS, EVALUATION = 93, 32


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def layouts(capacity, minimum=2):
    """Yield each nondecreasing partition with all parts at least two."""
    for size in range(minimum, capacity // 2 + 1):
        for rest in layouts(capacity - size, size):
            yield (size, *rest)
    if capacity >= minimum:
        yield (capacity,)


def coefficient(sizes, degree):
    values = [1] + [0] * degree
    for size in sizes:
        for k in range(degree, size - 1, -1):
            values[k] += values[k - size]
    return values[degree]


def probability(non_singletons):
    """Conditional on the two highest-scoring normals being singleton groups."""
    sizes = non_singletons + (1,) * (NORMALS - sum(non_singletons))
    assert sizes[-2:] == (1, 1)
    return Fraction(coefficient(sizes[:-2], EVALUATION - 2),
                    coefficient(sizes, EVALUATION))


def observed_layouts():
    old_plan = read_json(BACKGROUND / "arms-plan.json")["arms"]["G0"]
    new_plan = read_json(SAME / "stage9b-plan-2026-11-18-r2/pool-plan.json")
    old_audit = read_json(BACKGROUND / "exact-audit-v1.json")["arms"]["G0"]
    new_audit = read_json(SAME / "stage9b-eval-2026-11-18/exact-states.json")["G"]
    state = "both_over_budget"
    assert old_plan["target"] == new_plan["target"] == EVALUATION
    for name, plan, exact, row, color in (
        ("same G", new_plan["arms"]["G"], new_audit["probabilities"][state], 1, "#805419"),
        ("background G0", old_plan, old_audit["exact_states"][state]["exact"], 0, "#146A78"),
    ):
        sizes = [len(group) for group in plan["units"]]
        assert sum(sizes) == NORMALS
        multi = tuple(sorted(size for size in sizes if size > 1))
        assert probability(multi) == Fraction(exact)
        yield name, multi, row, color


def main():
    matplotlib.rcParams.update({
        "font.family": ["Microsoft YaHei", "DejaVu Sans"],
        "font.size": 9.5,
        "svg.fonttype": "path",
        "svg.hashsalt": "figure-2-layout-enumeration",
    })
    observed = list(observed_layouts())
    by_capacity = {
        sum(multi): {parts: probability(parts) for parts in layouts(sum(multi))}
        for _, multi, _, _ in observed
    }
    assert {capacity: len(values) for capacity, values in by_capacity.items()} == {11: 14, 32: 1507}
    ranges = {capacity: (min(values.values()), max(values.values()))
              for capacity, values in by_capacity.items()}
    overlap_left = max(low for low, _ in ranges.values()) * 100
    overlap_right = min(high for _, high in ranges.values()) * 100
    assert overlap_left < overlap_right

    fig, ax = plt.subplots(figsize=(16 / 2.54, 7.2 / 2.54))
    fig.subplots_adjust(left=.195, right=.972, bottom=.205, top=.945)
    ax.set(xlim=(11.75, 28), ylim=(-.48, 1.61), xlabel="双超预算概率（%）")
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["32 张 / 1507 种", "11 张 / 14 种"])
    ax.xaxis.set_major_locator(MultipleLocator(2))
    ax.tick_params(axis="y", length=0, pad=7, colors="#182A39")
    ax.tick_params(axis="x", length=3, pad=4, colors="#182A39")
    ax.grid(axis="x", color="#DFE5E9", linewidth=.55)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#8B98A2")

    ax.axvspan(float(overlap_left), float(overlap_right), color="#DEE4EC", zorder=1)
    mid = float(overlap_left + overlap_right) / 2
    ax.annotate("极值区间重叠", xy=(mid, 1.32), xytext=(mid, 1.52),
                ha="center", va="center", color="#465967",
                arrowprops={"arrowstyle": "-", "linewidth": .65, "color": "#71818E"})

    for name, multi, row, color in observed:
        values = by_capacity[sum(multi)]
        low, high = (100 * float(p) for p in ranges[sum(multi)])
        x = sorted(100 * float(p) for p in values.values())
        spread = [.27 * ((i * .61803398875) % 1 - .5) for i in range(len(x))]
        ax.hlines(row, low, high, color=color, alpha=.56, linewidth=.8, zorder=2)
        ax.vlines([low, high], row - .17, row + .17, color=color, linewidth=.8, zorder=2)
        ax.scatter(x, [row + offset for offset in spread], s=9 if row else 5,
                   color=color, alpha=.48, linewidths=0, zorder=3)
        actual = 100 * float(values[multi])
        ax.scatter(actual, row, marker="D", s=39, color=color, edgecolor="white",
                   linewidth=.9, zorder=4)
        ax.annotate(f"{name}  {actual:.3f}%", xy=(actual, row - .065),
                    xytext=(actual, row - .29), ha="center", va="center",
                    fontweight="bold", color=color,
                    arrowprops={"arrowstyle": "-", "linewidth": .65, "color": color})
        print(f"{sum(multi)} images: {len(values)} layouts, {low:.6f}% to {high:.6f}%,"
              f" {name} {actual:.9f}%")

    output = HERE / "figure-2-layout-enumeration"
    fig.savefig(output.with_suffix(".svg"), metadata={"Date": None})
    fig.savefig(output.with_suffix(".png"), dpi=300)
    plt.close(fig)


if __name__ == "__main__":
    main()
