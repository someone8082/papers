"""第八阶段第 1 步：background 正常图的分组依据与整组划分可行性。

只用图像身份（文件名帧号、文件字节）与图像内容（64 位 dHash），不读任何
模型分数、FP 或 TP。连通分量与分配计数调用刚验收通过的
week8/grouped-split-lab（提交 abc474f），不另写一份。

    E:/yingyong/an/envs/pytorch-lab/python.exe -B week8/grouping_evidence.py
"""

from __future__ import annotations

import hashlib
import itertools
import json
import pathlib
import re
import subprocess
import sys
from collections import Counter

import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "week3/data/aebad/AeBAD/AeBAD_S"
ROLES = ROOT / "week7/acceptance/stage7-background-2026-11-05/roles-background-v1.json"
LAB = ROOT / "week8/grouped-split-lab"
OUT_DIR = ROOT / "week8/acceptance/stage8-grouping-2026-11-06"

sys.path.insert(0, str(LAB))
from src.grouping import group_components  # noqa: E402
from src.counting import count_allocations  # noqa: E402

TARGET = 32
SIZES_GRID = [1, 2, 3]
DHASH_GRID = [4, 6, 8, 10, 12]


def dhash(path: pathlib.Path, size: int = 8) -> int:
    img = Image.open(path).convert("L").resize((size + 1, size), Image.BILINEAR)
    arr = np.asarray(img, dtype=np.int16)
    bits = (arr[:, 1:] > arr[:, :-1]).flatten()
    out = 0
    for bit in bits:
        out = (out << 1) | int(bit)
    return out


def ham(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def frame_id(key: str) -> int:
    return int(re.search(r"IMG_(\d+)", key).group(1))


def main() -> int:
    roles = json.loads(ROLES.read_text(encoding="utf-8"))
    pools = roles["pools"]
    reference = sorted(pools["reference"])
    cal = sorted(pools["calibration"])
    ev = sorted(pools["eval_normal"])
    test_normals = sorted(cal + ev)

    lab_commit = subprocess.run(
        ["git", "-C", str(LAB), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    # ---------------- 图像侧事实 ----------------
    meta = {}
    exif_tag_counts = Counter()
    mtimes = []
    for key in reference + test_normals:
        path = DATA / key
        with Image.open(path) as im:
            tags = len(im.getexif())
            size = im.size
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        exif_tag_counts[tags] += 1
        mtimes.append(round(path.stat().st_mtime))
        meta[key] = {"id": frame_id(key), "dhash": dhash(path), "sha256": digest,
                     "bytes": path.stat().st_size, "size": size, "exif_tags": tags}

    ids = sorted(meta[k]["id"] for k in test_normals)
    span = ids[-1] - ids[0] + 1
    gaps = Counter(b - a for a, b in zip(ids, ids[1:]))

    exif_facts = {
        "images_examined": len(meta),
        "images_with_zero_exif_tags": exif_tag_counts[0],
        "distinct_exif_tag_counts": dict(exif_tag_counts),
        "distinct_mtime_values": len(set(mtimes)),
        "mtime_first": min(mtimes),
        "mtime_last": max(mtimes),
        "mtime_span_seconds": max(mtimes) - min(mtimes),
        "note": "EXIF 已剥离、mtime 为数据集解包时间，均不含采集时刻或批次标识",
    }

    id_facts = {
        "n_test_normals": len(test_normals),
        "id_min": ids[0], "id_max": ids[-1], "id_span": span,
        "density": round(len(ids) / span, 4),
        "gap_histogram": {str(k): v for k, v in sorted(gaps.items())},
        "distinct_content_sha256": len({meta[k]["sha256"] for k in test_normals}),
        "same_content_pairs": [],
    }
    by_sha: dict[str, list[str]] = {}
    for k in test_normals:
        by_sha.setdefault(meta[k]["sha256"], []).append(k)
    id_facts["same_content_pairs"] = [v for v in by_sha.values() if len(v) > 1]

    # ---------------- 候选边规则 ----------------
    dh = {k: meta[k]["dhash"] for k in meta}
    fid = {k: meta[k]["id"] for k in meta}

    def build(keys):
        pairs = []
        for a, b in itertools.combinations(sorted(keys), 2):
            pairs.append((a, b))
        return pairs

    all_pairs = build(test_normals)

    # ---------------- dHash 阈值的图像侧依据 ----------------
    # 只用帧号把配对分成"近帧"与"远帧"，再看内容距离：这是选择阈值时唯一
    # 可用的、与模型分数无关的判据。远帧组给出同池的随机基线。
    near_pairs = [(a, b) for a, b in all_pairs if abs(fid[a] - fid[b]) <= 2]
    far_pairs = [(a, b) for a, b in all_pairs if abs(fid[a] - fid[b]) > 50]
    separation = {}
    for h in DHASH_GRID:
        near_frac = sum(1 for a, b in near_pairs if ham(dh[a], dh[b]) <= h) / len(near_pairs)
        far_frac = sum(1 for a, b in far_pairs if ham(dh[a], dh[b]) <= h) / len(far_pairs)
        separation[str(h)] = {
            "near_frac": round(near_frac, 4),
            "far_frac": round(far_frac, 4),
            "lift": round(near_frac / far_frac, 2) if far_frac else None,
        }

    descriptors = []

    def add_rule(name, pred, rationale):
        descriptors.append({"name": name, "pred": pred, "rationale": rationale})

    for s in SIZES_GRID:
        add_rule(f"id_le{s}",
                 lambda a, b, s=s: abs(fid[a] - fid[b]) <= s,
                 f"帧号相差不超过 {s}：同一连拍或相邻两拍，允许中间帧被其他条件占用")
    for h in DHASH_GRID:
        add_rule(f"dh_le{h}",
                 lambda a, b, h=h: ham(dh[a], dh[b]) <= h,
                 f"dHash 海明距离不超过 {h}：内容近似重复（随机配对基线 2% 在 ≤4）")
    add_rule("id_le3_and_dh_le12",
             lambda a, b: abs(fid[a] - fid[b]) <= 3 and ham(dh[a], dh[b]) <= 12,
             "帧号相邻且内容接近：避免把背靠背拍摄的不同场景并成一组")

    rules_out = {}
    for desc in descriptors:
        name, pred = desc["name"], desc["pred"]
        edges = [(a, b) for a, b in all_pairs if pred(a, b)]
        groups = group_components(test_normals, edges)
        sizes = [len(g) for g in groups]
        allocations = count_allocations(sizes, TARGET)

        # 现有 week7 逐图划分是否切开组
        cal_set = set(cal)
        straddling, straddle_images = [], []
        for g in groups:
            n_cal = sum(1 for k in g if k in cal_set)
            if 0 < n_cal < len(g):
                straddling.append({"size": len(g), "members": g})
                straddle_images.extend(g)
        # 现划分里评价侧有多少张与校准侧同组
        ev_contaminated = [g for g in groups
                           if any(k in cal_set for k in g) and any(k not in cal_set for k in g)]
        ev_in_bad = sum(1 for g in ev_contaminated for k in g if k not in cal_set)

        # 参考库跨池近邻
        ref_pairs = [(r, k) for r in reference for k in test_normals if pred(r, k)]
        eval_with_ref_neighbour = sorted({k for _, k in ref_pairs if k in set(ev)})
        ref_neighbour_keys = {k for _, k in ref_pairs}

        # 组内 dHash 直径：边阈值很小而直径很大说明是链式粘连，不是同一场景
        diameters = []
        for g in groups:
            if len(g) > 1:
                diameters.append(max(ham(dh[a], dh[b]) for a, b in itertools.combinations(g, 2)))
        # 三向隔离：与 8 张参考图有边相连的组不得进入评价侧
        eligible = [g for g in groups if not (set(g) & ref_neighbour_keys)]
        eligible_total = sum(len(g) for g in eligible)
        ref_iso_alloc = (count_allocations([len(g) for g in eligible], TARGET)
                         if eligible_total >= TARGET else 0)

        rules_out[name] = {
            "rationale": desc["rationale"],
            "n_edges": len(edges),
            "n_groups": len(groups),
            "max_group": max(sizes),
            "max_group_dhash_diameter": max(diameters) if diameters else 0,
            "size_histogram": {str(s): sizes.count(s) for s in sorted(set(sizes))},
            "target": TARGET,
            "allocations": allocations,
            "feasible": allocations > 0,
            "with_reference_isolation": {
                "eligible_groups": len(eligible),
                "eligible_images": eligible_total,
                "allocations": ref_iso_alloc,
                "feasible": ref_iso_alloc > 0,
            },
            "groups": [{"size": len(g), "members": g} for g in groups],
            "current_split": {
                "straddling_groups": len(straddling),
                "images_in_straddling_groups": len(straddle_images),
                "eval_images_sharing_group_with_calibration": ev_in_bad,
                "examples": [s["members"][:4] for s in straddling[:3]],
            },
            "reference_leakage": {
                "cross_pool_pairs": len(ref_pairs),
                "reference_images_with_test_neighbour": len({r for r, _ in ref_pairs}),
                "eval_images_with_reference_neighbour": len(eval_with_ref_neighbour),
                "example_pairs": [[r, k] for r, k in ref_pairs[:3]],
            },
        }

    payload = {
        "status": "STAGE8_GROUPING_EVIDENCE",
        "pool": "test/good/background",
        "target": TARGET,
        "roles_file": {"path": ROLES.relative_to(ROOT).as_posix(),
                       "sha256": hashlib.sha256(ROLES.read_bytes()).hexdigest()},
        "counts": {"reference": len(reference), "calibration": len(cal),
                   "eval_normal": len(ev)},
        "lab": {"commit": lab_commit, "used": ["src.grouping.group_components",
                                               "src.counting.count_allocations"]},
        "exif": exif_facts,
        "frame_ids": id_facts,
        "hash_separation": {
            "near_pairs_id_le2": len(near_pairs),
            "far_pairs_id_gt50": len(far_pairs),
            "by_threshold": separation,
            "note": "近帧组与远帧组的差值给出 dHash 阈值的图像侧依据；不涉及任何模型分数",
        },
        "rules": rules_out,
        "scoring_inputs": [],
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "grouping-evidence.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 主要候选的逐组清单，便于人工核对与后续划分抽样
    csv_path = OUT_DIR / "groups-dh4.csv"
    with csv_path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("group_id,size,members,eval_eligible\n")
        for index, group in enumerate(rules_out["dh_le4"]["groups"], start=1):
            keys = group["members"]
            eligible = not (set(keys) & {k for _, k in
                            [(r, k) for r in reference for k in test_normals
                             if ham(dh[r], dh[k]) <= 4]})
            fh.write(f"{index},{group['size']},\"{' '.join(keys)}\",{int(eligible)}\n")

    print(f"images={len(meta)} exif_zero={exif_facts['images_with_zero_exif_tags']} "
          f"mtime_distinct={exif_facts['distinct_mtime_values']}")
    print(f"ids {ids[0]}..{ids[-1]} span={span} density={id_facts['density']}")
    print(f"{'rule':22s} {'edges':>6s} {'groups':>7s} {'max':>4s} "
          f"{'alloc':>10s} {'straddle':>9s} {'ev_contam':>9s}")
    for name, r in rules_out.items():
        print(f"{name:22s} {r['n_edges']:6d} {r['n_groups']:7d} {r['max_group']:4d} "
              f"{str(r['allocations']):>10s} "
              f"{r['current_split']['straddling_groups']:9d} "
              f"{r['current_split']['eval_images_sharing_group_with_calibration']:9d}")
    print("wrote", out.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
