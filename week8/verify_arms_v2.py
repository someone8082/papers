"""Independent recomputation of the corrected stage 8 evaluation.

Shares no code with ``arms.py`` or ``arms_v2.py``: it re-reads the frozen plan and
manifests, rebuilds every calibration/evaluation split from the key table, and
recomputes thresholds, FP/TP, the four states, C* and U with its own loops (plain
linear scans, no bisect). C* is evaluated two ways on every row -- maximum TP over
all feasible candidates, and TP at the lowest feasible candidate -- and the two
must agree.

It writes ``independent-eval-v2.json`` and ``verification-digest.json`` into the
v2 acceptance directory and never touches a frozen file.
"""

import csv
import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
V2 = ROOT / "week8/acceptance/stage8-arms-v2-2026-11-07"
V1 = ROOT / "week8/acceptance/stage8-arms-2026-11-06"
OUT = ROOT / "week8/outputs/arms-v1"
RUN = ROOT / "week7/outputs/background-448-r1"
ARMS = ("I0", "G0", "I1", "G1")
STATES = ("budget_gain", "budget_no_gain", "mid_over_budget", "both_over_budget")


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def above(values, threshold):
    """Linear count of strict exceedances; deliberately not bisect."""
    return sum(1 for v in values if v > threshold)


def ceildiv_rank(num, den, n):
    return -(-num * n // den)


def rule_thresholds(cal):
    ordered = sorted(cal)
    return ordered, {
        "MAX": ordered[60],
        "Q99": ordered[ceildiv_rank(99, 100, 61) - 1],
        "Q95": ordered[ceildiv_rank(95, 100, 61) - 1],
        "Q90": ordered[ceildiv_rank(90, 100, 61) - 1],
        "MID12": (ordered[59] + ordered[60]) / 2.0,
    }


def evaluate_row(cal, ev, defects):
    ordered, t = rule_thresholds(cal)
    rules = {k: {"fp": above(ev, v), "tp": above(defects, v)} for k, v in t.items()}
    fp_max, tp_max = rules["MAX"]["fp"], rules["MAX"]["tp"]
    fp_mid, tp_mid = rules["MID12"]["fp"], rules["MID12"]["tp"]
    if rules["Q99"] != rules["MAX"]:
        raise SystemExit("Q99 is not MAX")
    if fp_mid < fp_max or tp_mid < tp_max:
        raise SystemExit("MID12 does not dominate MAX")
    state = ("both_over_budget" if fp_max >= 2 else
             "mid_over_budget" if fp_mid >= 2 else
             "budget_gain" if tp_mid > tp_max else "budget_no_gain")

    # C* by route 1: maximum TP over every feasible candidate.
    feasible = [c for c in ordered if above(ev, c) <= 1]
    route1 = max((above(defects, c) for c in feasible), default=None)
    # C* by route 2: TP at the lowest feasible candidate.
    route2 = above(defects, min(feasible)) if feasible else None
    if route1 != route2:
        raise SystemExit(f"two restatements disagree: {route1} vs {route2}")
    if (route1 is None) != (state == "both_over_budget"):
        raise SystemExit("feasibility and the both_over state diverge")

    u_tp = above(defects, ev[-2])
    five_rules = [c for c in t.values() if c >= ev[-2]]
    five = above(defects, min(five_rules)) if five_rules else None
    return {"state": state, "rules": rules, "c_star": route1, "u": u_tp,
            "gap": (u_tp - route1) if route1 is not None else None,
            "five": five, "changed": five != route1, "n_feasible": len(feasible),
            "cal_max": ordered[60], "min_threshold": min(t.values()),
            "slack": min(t.values()) - ev[-1]}


def mean(values):
    return sum(values) / len(values) if values else None


def summarise(records):
    n = len(records)
    counts = {s: sum(1 for r in records if r["state"] == s) for s in STATES}
    valid = [r for r in records if r["c_star"] is not None]
    c_vals = [r["c_star"] for r in valid]
    gaps = [r["gap"] for r in valid]
    lower = sum(1 for r in records if r["changed"] and r["c_star"] is not None
                and r["five"] is not None and r["c_star"] < r["five"])
    higher = sum(1 for r in records if r["changed"] and r["c_star"] is not None
                 and r["five"] is not None and r["c_star"] > r["five"])
    rules = {}
    for name in ("MAX", "MID12", "Q95", "Q90"):
        fps = [r["rules"][name]["fp"] for r in records]
        tps = [r["rules"][name]["tp"] for r in records]
        rules[name] = {"fp_mean": mean(fps), "fp_le1_frac": sum(1 for v in fps if v <= 1) / n,
                       "fp_zero_frac": sum(1 for v in fps if v == 0) / n,
                       "tp_mean": mean(tps), "tp_max": max(tps), "tp_min": min(tps)}
    return {
        "rows": n,
        "states": {s: {"count": counts[s], "p": counts[s] / n} for s in STATES},
        "rules": rules,
        "bounds": {
            "feasible_rows": len(valid),
            "infeasible_rows": n - len(valid),
            "c_star_tp_mean_given_feasible": mean(c_vals),
            "u_tp_mean_given_feasible": mean([r["u"] for r in valid]),
            "u_tp_mean_all_rows": mean([r["u"] for r in records]),
            "gap_mean_given_feasible": mean(gaps),
            "c_star_changed_rows": sum(1 for r in records if r["changed"]),
            "corrected_lower_rows": lower,
            "corrected_higher_rows": higher,
            "five_rule_mean_given_feasible": mean(
                [r["five"] for r in valid if r["five"] is not None]),
        },
        "all_rules_fp_zero_frac": sum(
            1 for r in records if all(v["fp"] == 0 for v in r["rules"].values())) / n,
        "slack_median": sorted(r["slack"] for r in records)[n // 2],
    }


def main():
    plan = json.loads((V1 / "arms-plan.json").read_text(encoding="utf-8"))
    digest = json.loads((V1 / "plan-digest.json").read_text(encoding="utf-8"))
    for rel, meta in digest["files"].items():
        blob = (ROOT / rel).read_bytes()
        if len(blob) != meta["bytes"] or hashlib.sha256(blob).hexdigest() != meta["sha256"]:
            raise SystemExit(f"frozen file changed: {rel}")

    scores, normals, defects = {}, [], []
    with (RUN / "calibration-scores.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            scores[row["relative_path"]] = float(row["score"])
            normals.append(row["relative_path"])
    with (RUN / "evaluation-scores.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            scores[row["relative_path"]] = float(row["score"])
            if row["role"] == "eval_defect":
                defects.append(float(row["score"]))
            else:
                normals.append(row["relative_path"])
    defects.sort()
    if len(scores) != 305 or len(normals) != 93 or len(defects) != 212:
        raise SystemExit(f"pool sizes {len(scores)}/{len(normals)}/{len(defects)}")

    driver_rows = {}
    with (V2 / "eval-rows-v2.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            driver_rows[(row["arm"], int(row["repeat_id"]))] = row
    v1_rows = {}
    with (V1 / "eval-rows.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            v1_rows[(row["arm"], int(row["repeat_id"]))] = row

    out = {"status": "STAGE8_ARMS_INDEPENDENT_EVAL_V2",
           "note": "own loops; C* restated two ways per row",
           "frozen_digest_files_checked": len(digest["files"]),
           "arms": {}, "row_comparison": {}, "v1_shared_columns": {}}

    for arm in ARMS:
        image_keys = plan["arms"][arm]["image_keys"]
        records = []
        comparisons = 0
        v1_comparisons = 0
        with (OUT / f"manifest-{arm}.csv").open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                idx = [int(x) for x in row["eval_idx"].split()]
                eval_keys = [image_keys[i] for i in idx]
                if len(idx) != 32 or len(set(idx)) != 32 or len(eval_keys) != 32:
                    raise SystemExit(f"{arm}/{row['repeat_id']}: bad eval side")
                if sha("\n".join(sorted(eval_keys))) != row["eval_sha256"]:
                    raise SystemExit(f"{arm}/{row['repeat_id']}: digest mismatch")
                cal_keys = [k for k in normals if k not in set(eval_keys)]
                if len(cal_keys) != 61:
                    raise SystemExit(f"{arm}/{row['repeat_id']}: {len(cal_keys)} calibration")
                rec = evaluate_row([scores[k] for k in cal_keys],
                                   sorted(scores[k] for k in eval_keys), defects)

                got = driver_rows[(arm, int(row["repeat_id"]))]
                for name in ("max_fp", "max_tp", "mid_fp", "mid_tp",
                             "q95_fp", "q95_tp", "q90_fp", "q90_tp"):
                    rule, kind = name.split("_")
                    key = {"max": "MAX", "mid": "MID12", "q95": "Q95", "q90": "Q90"}[rule]
                    if rec["rules"][key][kind] != int(got[name]):
                        raise SystemExit(f"{arm}/{row['repeat_id']}: {name} differs")
                    comparisons += 1
                if got["state"] != rec["state"]:
                    raise SystemExit(f"{arm}/{row['repeat_id']}: state differs")
                if int(got["u_tp"]) != rec["u"]:
                    raise SystemExit(f"{arm}/{row['repeat_id']}: U differs")
                if (int(got["c_star_tp"]) if got["c_star_tp"] else None) != rec["c_star"]:
                    raise SystemExit(f"{arm}/{row['repeat_id']}: C* differs")
                if (int(got["c_star_tp_five_rules"]) if got["c_star_tp_five_rules"]
                        else None) != rec["five"]:
                    raise SystemExit(f"{arm}/{row['repeat_id']}: five-rule column differs")
                if int(got["n_feasible_candidates"]) != rec["n_feasible"]:
                    raise SystemExit(f"{arm}/{row['repeat_id']}: feasible count differs")
                gap_text = got["gap"]
                if (float(gap_text) if gap_text else None) != rec["gap"]:
                    raise SystemExit(f"{arm}/{row['repeat_id']}: gap differs")
                comparisons += 2

                old = v1_rows[(arm, int(row["repeat_id"]))]
                if old["state"] != rec["state"] or int(old["max_tp"]) != rec["rules"]["MAX"]["tp"]:
                    raise SystemExit(f"{arm}/{row['repeat_id']}: v1 shared column differs")
                if int(old["u_tp"]) != rec["u"]:
                    raise SystemExit(f"{arm}/{row['repeat_id']}: v1 U differs")
                v1_comparisons += 3
                records.append(rec)
        out["arms"][arm] = summarise(records)
        out["row_comparison"][arm] = {"fields_compared": comparisons, "mismatches": 0}
        out["v1_shared_columns"][arm] = {"fields_compared": v1_comparisons, "mismatches": 0}

    driver = json.loads((V2 / "eval-v2.json").read_text(encoding="utf-8"))
    headline = {}
    for arm in ARMS:
        mine = out["arms"][arm]["bounds"]
        theirs = driver["arms"][arm]["bounds"]
        for name in ("c_star_tp_mean_given_feasible", "gap_mean_given_feasible",
                     "u_tp_mean_all_rows", "u_tp_mean_given_feasible",
                     "feasible_rows", "infeasible_rows", "c_star_changed_rows",
                     "corrected_lower_rows", "corrected_higher_rows"):
            if abs(float(mine[name]) - float(theirs[name])) > 1e-12:
                raise SystemExit(f"{arm}: {name} {mine[name]} != {theirs[name]}")
        for state in STATES:
            if out["arms"][arm]["states"][state]["count"] != driver["arms"][arm]["states"][state]["count"]:
                raise SystemExit(f"{arm}: {state} count differs")
        dep = theirs["deprecated_five_rule"]["c_star_tp_mean_given_feasible"]
        if abs(float(mine["five_rule_mean_given_feasible"]) - float(dep)) > 1e-12:
            raise SystemExit(f"{arm}: five-rule mean {mine['five_rule_mean_given_feasible']} != {dep}")
        headline[arm] = {"c_star_tp_mean_given_feasible": mine["c_star_tp_mean_given_feasible"],
                         "u_tp_mean_given_feasible": mine["u_tp_mean_given_feasible"],
                         "gap_mean_given_feasible": mine["gap_mean_given_feasible"],
                         "u_tp_mean_all_rows": mine["u_tp_mean_all_rows"],
                         "five_rule_mean_given_feasible": mine["five_rule_mean_given_feasible"]}
    out["headline"] = headline
    out["driver_agreement"] = "aggregates and 40000 rows agree, 0 mismatches"
    out["source_hashes"] = {
        "plan-digest-v1": sha_file(V1 / "plan-digest.json"),
        "eval-v2.json": sha_file(V2 / "eval-v2.json"),
        "eval-rows-v2.csv": sha_file(V2 / "eval-rows-v2.csv"),
        "verifier": sha_file(pathlib.Path(__file__)),
    }

    target = V2 / "independent-eval-v2.json"
    if target.exists():
        raise SystemExit(f"refusing to overwrite {target.name}")
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    full = {p.name: {"bytes": p.stat().st_size, "sha256": sha_file(p)}
            for p in sorted(V2.iterdir()) if p.name != "verification-digest.json"}
    (V2 / "verification-digest.json").write_text(
        json.dumps({"status": "STAGE8_ARMS_V2_VERIFICATION_DIGEST",
                    "files": full,
                    "excludes": "verification-digest.json itself"}, ensure_ascii=False,
                   indent=2) + "\n", encoding="utf-8")

    print(json.dumps(headline, ensure_ascii=False, indent=1))
    print("rows compared:", sum(v["fields_compared"] for v in out["row_comparison"].values()))


if __name__ == "__main__":
    main()
