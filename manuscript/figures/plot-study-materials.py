"""Render the AeBAD-S sample gallery and allocation schema at 160 mm.

The illustration uses original dataset files and validates membership in
the frozen score manifests. This script never writes to experiment outputs.
"""

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from matplotlib import pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle
from PIL import Image


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ENGLISH = HERE.parent / "arxiv" / "figures"
DATASET = ROOT / "week3/data/aebad/AeBAD/AeBAD_S"
WIDTH_MM = 160
DPI = 600
INK = "#17232C"
GRAY = "#64727B"
RULE = "#A4AEB5"
BLUE = "#23688B"

SAMPLES = {
    "background": ("IMG_7728", "IMG_9382", "IMG_9255"),
    "same": ("IMG_7683", "IMG_9405", "IMG_9003"),
}
KINDS = ("good", "fracture", "breakdown")
SCORE_FILES = {
    "background": ROOT / "week7/outputs/background-448-r1/scores.csv",
    "same": ROOT / "week9/outputs/same-448-r1/scores.csv",
}


def get_records(pool):
    with SCORE_FILES[pool].open(encoding="utf-8", newline="") as file:
        return {row["relative_path"]: row for row in csv.DictReader(file)}


def get_study_sizes():
    background = get_records("background")
    same = get_records("same")
    arms = json.loads((ROOT / "week8/acceptance/stage8-arms-2026-11-06/arms-plan.json")
                      .read_text(encoding="utf-8"))["arms"]
    same_plan = json.loads((ROOT / "week9/acceptance/stage9b-plan-2026-11-18-r2/pool-plan.json")
                           .read_text(encoding="utf-8"))
    anchor = set(arms["I0"]["image_keys"]) - set(arms["I1"]["image_keys"])
    assert any(set(unit) == anchor for unit in arms["G0"]["units"])
    assert len(anchor) == 18
    assert len(same_plan["roles"]["Z"]) == 129
    assert len(same_plan["roles"]["D"]) == 459
    assert len(arms["G0"]["units"]) == 66 and len(same_plan["groups"]) == 87
    for records in (background, same):
        roles = [row["role"] for row in records.values()]
        assert roles.count("reference") == 8
        assert roles.count("calibration") == 61 and roles.count("eval_normal") == 32
    assert sum(row["role"] == "eval_defect" for row in background.values()) == 212
    assert sum(row["role"] == "eval_defect" for row in same.values()) == 459


def canvas(height_mm):
    fig = plt.figure(figsize=(WIDTH_MM / 25.4, height_mm / 25.4), facecolor="white")
    ax = fig.add_axes((0, 0, 1, 1), xlim=(0, WIDTH_MM), ylim=(0, height_mm))
    ax.set_axis_off()
    return fig, ax


def label(ax, x, y, text, *, size=9, bold=False, color=INK, align="left"):
    ax.text(x, y, text, fontsize=size, fontweight="bold" if bold else "normal",
            color=color, ha=align, va="center")


def horizontal_line(ax, x0, x1, y, *, color=RULE, width=0.55):
    ax.plot((x0, x1), (y, y), color=color, lw=width, solid_capstyle="butt")


def save(fig, base, *, vector=False):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for ax in fig.axes:
        labels = [item.get_window_extent(renderer) for item in ax.texts]
        for index, extent in enumerate(labels):
            assert fig.bbox.contains(extent.x0, extent.y0)
            assert fig.bbox.contains(extent.x1, extent.y1)
            assert not any(extent.overlaps(other) for other in labels[:index])
    target = base.with_suffix(".png")
    fig.savefig(target, dpi=DPI)
    with Image.open(target) as png:
        image = png.convert("RGB")
    image.save(target, dpi=(DPI, DPI), optimize=True)
    if vector:
        fig.savefig(base.with_suffix(".svg"), metadata={"Date": None})
    plt.close(fig)


def examples(zh):
    fig, ax = canvas(94)
    labels = ("正常", "断裂", "异物损伤") if zh else ("Normal", "Fracture", "Breakdown")
    conditions = ("背景偏移", "无偏移") if zh else ("Background shift", "No shift")
    cols = (36.5, 78.3, 120.1)
    side = 37
    for x, name in zip(cols, labels):
        label(ax, x + side / 2, 90.7, name, size=9.5, bold=True, align="center")
    horizontal_line(ax, 3, 157.1, 44.1, color="#D4DADE", width=0.55)
    for index, ((pool, ids), condition) in enumerate(zip(SAMPLES.items(), conditions)):
        records = get_records(pool)
        bottom = (49.5, 5.1)[index]
        label(ax, 3, bottom + 26, f"({chr(97 + index)})", size=9.5, bold=True)
        label(ax, 3, bottom + 20, pool, size=9.4, bold=True)
        label(ax, 3, bottom + 14.4, condition, size=8.5, color=GRAY)
        for x, kind, stem in zip(cols, KINDS, ids):
            relative = f"test/{kind}/{pool}/{stem}.png"
            row = records[relative]
            assert row["anomaly_type"] == kind
            assert (row["role"] in {"calibration", "eval_normal"} if kind == "good"
                    else row["role"] == "eval_defect")
            with Image.open(DATASET / relative) as source:
                image = source.convert("RGB")
            # Fit within the square without changing the field of view.
            scale = side / max(image.size)
            w, h = image.width * scale, image.height * scale
            left, lower = x + (side - w) / 2, bottom + (side - h) / 2
            ax.imshow(image, extent=(left, left + w, lower, lower + h),
                      interpolation="antialiased", aspect="auto")
            ax.add_patch(Rectangle((left, lower), w, h, facecolor="none",
                                   edgecolor=RULE, lw=0.45))
            label(ax, x + side / 2, bottom - 2.5, stem, size=8.5, color=GRAY,
                  align="center")
    dest = HERE / "figure-1-aebad-examples" if zh else ENGLISH / "figure-1-examples-en"
    save(fig, dest)


def group_sample(ax, y, *, grouped):
    groups = ((43, 48, 53), (63, 68), (78,))
    selected = {63, 68} if grouped else {48, 63}
    for positions in groups:
        filled = selected.issuperset(positions)
        left, right = positions[0] - 3.1, positions[-1] + 3.1
        ax.add_patch(Rectangle((left, y - 3.5), right - left, 7,
                               facecolor="#EAF3F7" if filled else "white",
                               edgecolor=BLUE if filled else GRAY, lw=0.85))
        for x in positions:
            allocation_marker(ax, x, y, selected=x in selected)


def allocation_marker(ax, x, y, *, selected):
    ax.plot(x, y, marker="o", markersize=5.4, color=BLUE if selected else "white",
            markeredgecolor=INK, markeredgewidth=0.7, zorder=4)


def protocol(zh):
    fig, ax = canvas(82)
    amber = "#A65D22"
    label(ax, 3, 77.4, "(a) 两池的图像角色" if zh else "(a) Image roles in each pool",
          size=10, bold=True)
    headings = ("子集", "固定参考图（8 张）", "活动正常图（93 张）", "评价缺陷图") if zh else (
        "Test subset", "Fixed references (8)", "Active normals (93)", "All defects")
    for x, name in zip((5, 36, 81, 140), headings):
        label(ax, x, 68.7, name, bold=True, align="center" if x == 140 else "left")
    for y, name, path, groups, defects in (
        (59.4, "background", "train/good/background", 66, 212),
        (49.1, "same", "test/good/same (R1)", 87, 459),
    ):
        ax.add_patch(Rectangle((77.5, y - 3.9), 48, 7.8, facecolor="#EAF3F7",
                               edgecolor="none"))
        label(ax, 5, y, name, bold=True)
        label(ax, 36, y, path, size=8.7)
        label(ax, 81, y, f"{groups} 组" if zh else f"{groups} groups")
        label(ax, 140, y, str(defects), bold=True, align="center")
    label(ax, 120, 59.4, "A · 18", size=8.5, color=amber, bold=True, align="right")
    horizontal_line(ax, 3, 157, 64.6)
    horizontal_line(ax, 3, 157, 43.6, color="#CAD2D7")

    label(ax, 3, 38.5, "(b) 活动正常图的划分" if zh else "(b) Allocation of active normals",
          size=10, bold=True)
    label(ax, 113, 36.7, "每个划分的配额" if zh else "Per-split quotas", size=8.7,
          color=GRAY, align="left")
    allocation_rows = (28.1, 17.5)
    for y, grouped in zip(allocation_rows, (False, True)):
        if grouped:
            name = "整组划分 G" if zh else "Whole-group (G)"
        else:
            name = "逐图划分 I" if zh else "Image-wise (I)"
        label(ax, 5, y, name, bold=True)
        group_sample(ax, y, grouped=grouped)
    ax.plot((83.3, 89.5, 89.5, 83.3), (28.1, 28.1, 17.5, 17.5),
            color=GRAY, lw=0.85)
    ax.add_patch(FancyArrowPatch((89.5, 22.8), (105, 22.8), arrowstyle="-|>",
                                 color=GRAY, linewidth=0.85, mutation_scale=8))
    ax.add_patch(Rectangle((105, 13.45), 52, 9.35, facecolor="#EAF3F7", edgecolor="none"))
    ax.add_patch(Rectangle((105, 13.45), 52, 18.7, facecolor="none",
                           edgecolor="#B1BFC8", lw=0.65))
    horizontal_line(ax, 105, 157, 22.8, color="#B1BFC8", width=0.65)
    for y, name, count, selected in (
        (28.1, "校准正常图" if zh else "Calibration normals", 61, False),
        (17.5, "评价正常图" if zh else "Evaluation normals", 32, True),
    ):
        allocation_marker(ax, 109.4, y, selected=selected)
        label(ax, 113, y, name, bold=True)
        label(ax, 153.5, y, str(count), bold=True, align="right")
    label(ax, 40, 9.7, "边框表示组，实心点表示选入评价侧。" if zh
          else "Boxes mark groups. Filled dots enter evaluation.", size=8.5, color=GRAY)
    label(ax, 5, 4.7, "锚定臂 I1、G1（background）将 A 的 18 张图固定在校准侧。" if zh
          else "Anchored arms I1 and G1 (background) keep all 18 images in A in calibration.",
          size=8.5, color=amber)
    dest = HERE / "figure-2-allocation-protocol" if zh else ENGLISH / "figure-2-protocol-en"
    with matplotlib.rc_context({"svg.fonttype": "none"}):
        save(fig, dest, vector=True)


def main():
    get_study_sizes()
    matplotlib.rcParams.update({
        "font.family": ["Arial", "Microsoft YaHei"],
        "svg.fonttype": "path",
        "svg.hashsalt": "aebad-samples-and-allocation",
    })
    for chinese in (False, True):
        examples(chinese)
        protocol(chinese)


if __name__ == "__main__":
    main()

