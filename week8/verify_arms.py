"""Independent recomputation of the four-arm evaluation.

Written after the frozen driver's I0 gate aborted, so it deliberately shares no
code with ``arms.py``: it re-reads the manifests, re-verifies their row digests
from the key table, recomputes thresholds, FP/TP and the four states with its own
implementation, and only then aggregates.

It never writes into the frozen plan and never changes a manifest.
"""

import bisect
import csv
import hashlib
import json
import math
import pathlib
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parents[1]
ACC = ROOT / "week8/acceptance/stage8-arms-2026-11-06"
OUT = ROOT / "week8/outputs/arms-v1"
RUN = ROOT / "week7/outputs/background-448-r1"
ARMS = ("I0", "G0", "I1", "G1")
STATES = ("budget_gain", "budget_no_gain", "mid_over_budget", "both_over_budget")


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def above(sorted_values, threshold):
    return len(sorted_values) - bisect.bisect_right(sorted_values, threshold)


def rank_ceiling(num, den, n):
    return (num * n + den - 1) // den


def arm_states(cal, ev, defects):
    """Own implementation: 61 calibration scores -> thresholds -> state."""
    cal = sorted(cal)
    x61, x60 = cal[-1], cal[-2]
    mid = (x60 + x61) / 2.0
    fp_max, fp_mid = above(ev, x61), above(ev, mid)
    tp_max, tp_mid = above(defects, x61), above(defects, mid)
    t = {
        "MAX": x61,
        "Q99": cal[rank_ceiling(99, 100, 61) - 1],
        "Q95": cal[rank_ceiling(95, 100, 61) - 1],
        "Q90": cal[rank_ceiling(90, 100, 61) - 1],
        "MID12": mid,
    }
    rules = {name: {"fp": above(ev, value), "tp": above(defects, value)}
             for name, value in t.items()}
    if rules["Q99"]["fp"] != fp_max or rules["Q99"]["tp"] != tp_max:
        raise SystemExit("Q99 identity broken")
    if rules["MID12"]["fp"] < fp_max or rules["MID12"]["tp"] < tp_max:
        raise SystemExit("MID12 does not dominate MAX")
    if fp_max >= 2:
        state = "both_over_budget"
    elif fp_mid >= 2:
        state = "mid_over_budget"
    elif tp_mid > tp_max:
        state = "budget_gain"
    else:
        state = "budget_no_gain"

    second_high = ev[-2]
    feasible = sorted(v for v in t.values() if v >= second_high)
    c_star = above(defects, feasible[0]) if feasible else None
    u_tp = above(defects, second_high)
    return {
        "state": state,
        "rules": rules,
        "delta_fp": fp_mid - fp_max,
        "delta_tp": tp_mid - tp_max,
        "c_star_tp": c_star,
        "u_tp": u_tp,
        "slack": min(t.values()) - ev[-1],
    }


def quantile(values, q):
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))]


def summarise(records, anchor_keys):
    n = len(records)
    states = {s: sum(1 for r in records if r["state"] == s) for s in STATES}
    state_block = {s: {"count": states[s], "p": states[s] / n,
                       "halfwidth": 1.96 * math.sqrt(states[s] / n * (1 - states[s] / n) / n)}
                   for s in STATES}
    rules = {}
    for name in ("MAX", "MID12", "Q95", "Q90"):
        fps = [r["rules"][name]["fp"] for r in records]
        tps = [r["rules"][name]["tp"] for r in records]
        rules[name] = {
            "fp_mean": sum(fps) / n, "fp_max": max(fps),
            "fp_le1_frac": sum(1 for v in fps if v <= 1) / n,
            "fp_zero_frac": sum(1 for v in fps if v == 0) / n,
            "tp_mean": sum(tps) / n, "tp_median": quantile(tps, 0.5),
            "tp_p05": quantile(tps, 0.05), "tp_p95": quantile(tps, 0.95),
            "tp_min": min(tps), "tp_max": max(tps),
        }
    dtp = [r["delta_tp"] for r in records]
    dfp = [r["delta_fp"] for r in records]
    slacks = [r["slack"] for r in records]
    c_valid = [r["c_star_tp"] for r in records if r["c_star_tp"] is not None]
    u_tp = [r["u_tp"] for r in records]
    gaps = [r["u_tp"] - r["c_star_tp"] for r in records if r["c_star_tp"] is not None]
    return {
        "rows": n,
        "states": state_block,
        "rules": rules,
        "delta": {"tp_mean": sum(dtp) / n, "tp_median": quantile(dtp, 0.5),
                  "tp_max": max(dtp), "tp_positive_frac": sum(1 for v in dtp if v > 0) / n,
                  "fp_mean": sum(dfp) / n, "fp_max": max(dfp),
                  "fp_positive_frac": sum(1 for v in dfp if v > 0) / n},
        "slack": {"min": min(slacks), "median": quantile(slacks, 0.5), "max": max(slacks),
                  "positive_frac": sum(1 for v in slacks if v > 0) / n},
        "bounds": {"c_star_tp_mean": sum(c_valid) / len(c_valid) if c_valid else None,
                   "c_star_tp_median": quantile(c_valid, 0.5) if c_valid else None,
                   "c_star_empty": n - len(c_valid),
                   "u_tp_mean": sum(u_tp) / n,
                   "gap_mean": sum(gaps) / len(gaps) if gaps else None,
                   "gap_median": quantile(gaps, 0.5) if gaps else None},
        "all_rules_fp_zero_frac": sum(1 for r in records
                                      if all(v["fp"] == 0 for v in r["rules"].values())) / n,
        "anchor_in_eval_rows": sum(1 for r in records
                                   if set(r["eval_keys"]) & anchor_keys),
        "distinct_splits": len({tuple(r["eval_keys"]) for r in records}),
    }


def main():
    plan = json.loads((ACC / "arms-plan.json").read_text(encoding="utf-8"))
    digest = json.loads((ACC / "plan-digest.json").read_text(encoding="utf-8"))

    scores = {}
    cal_keys_global = []
    normal_keys_global = []
    with (RUN / "calibration-scores.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            scores[row["relative_path"]] = float(row["score"])
            cal_keys_global.append(row["relative_path"])
    defects = []
    with (RUN / "evaluation-scores.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            scores[row["relative_path"]] = float(row["score"])
            if row["role"] == "eval_defect":
                defects.append(float(row["score"]))
            else:
                normal_keys_global.append(row["relative_path"])
    defects.sort()
    if len(scores) != 305 or len(defects) != 212:
        raise SystemExit(f"score pool {len(scores)}/{len(defects)}")
    universe = sorted(cal_keys_global + normal_keys_global)
    if len(universe) != 93:
        raise SystemExit(f"universe is {len(universe)}")

    anchor_keys = set(plan["arms"]["G0"]["units"][
        [i for i, u in enumerate(plan["arms"]["G0"]["units"])
         if len(u) == 18][0]])

    out = {"status": "STAGE8_ARMS_INDEPENDENT_EVAL",
           "note": "independent implementation; the frozen driver's I0 gate aborted",
           "plan_sha256": digest["files"]["week8/acceptance/stage8-arms-2026-11-06/arms-plan.json"]["sha256"],
           "arms": {}, "row_mismatches": {}}

    for arm in ARMS:
        image_keys = plan["arms"][arm]["image_keys"]
        records = []
        path = OUT / f"manifest-{arm}.csv"
        with path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                idx = [int(x) for x in row["eval_idx"].split()]
                if len(idx) != 32 or idx != sorted(idx) or len(set(idx)) != 32:
                    raise SystemExit(f"{arm}/{row['repeat_id']}: bad eval_idx")
                eval_keys = [image_keys[i] for i in idx]
                if sha("\n".join(sorted(eval_keys))) != row["eval_sha256"]:
                    raise SystemExit(f"{arm}/{row['repeat_id']}: row digest mismatch")
                if arm in ("I1", "G1") and set(eval_keys) & anchor_keys:
                    raise SystemExit(f"{arm}/{row['repeat_id']}: anchor in eval")
                cal_keys = [k for k in universe if k not in set(eval_keys)]
                if len(cal_keys) != 61:
                    raise SystemExit(f"{arm}/{row['repeat_id']}: {len(cal_keys)} calibration keys")
                ev = sorted(scores[k] for k in eval_keys)
                cal = [scores[k] for k in cal_keys]
                rec = arm_states(cal, ev, defects)
                rec["eval_keys"] = eval_keys
                records.append(rec)
        # calibration side is the complement inside the arm's own universe
        out["arms"][arm] = summarise(records, anchor_keys)

    exact = json.loads((ROOT / "week7/acceptance/stage7-background-2026-11-05/"
                        "split-exact-enumeration.json").read_text(encoding="utf-8"))
    out["i0_vs_exact"] = {}
    for s in STATES:
        ref = exact["states"][s]["p"]
        obs = out["arms"]["I0"]["states"][s]["p"]
        sigma = math.sqrt(ref * (1 - ref) / out["arms"]["I0"]["rows"])
        out["i0_vs_exact"][s] = {"exact": ref, "observed": obs,
                                 "z": (obs - ref) / sigma if sigma else 0.0,
                                 "sigma": sigma}
    (ACC / "independent-eval.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({arm: {s: round(v["p"] * 100, 3) for s, v in out["arms"][arm]["states"].items()}
                      for arm in ARMS}, ensure_ascii=False, indent=1))
    print(json.dumps({s: round(v["z"], 2) for s, v in out["i0_vs_exact"].items()}, indent=1))


if __name__ == "__main__":
    main()
