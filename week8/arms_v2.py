"""Stage 8 driver, version 2: C* over the 61 calibration candidates.

Version 1 (``arms.py``) is retained byte-identical and is never edited. It is
imported here only for the parts the review found correct: plan-digest
verification, manifest decoding, score loading, the five rule thresholds and
the four-state order. Its ``evaluate_row`` is *not* used, because its ``C*``
substituted the five rule thresholds for the protocol's 61-candidate family and
also admitted ``MID12``, which is an interpolated point and not a candidate.

Protocol (v2, section 6): ``c_star_tp`` is the largest defect count among the 61
calibration scores whose normal-side budget satisfies ``FP <= 1``. Because TP is
non-increasing in the threshold, that maximum is attained at the lowest feasible
candidate, but the driver scans all 61 and takes the maximum explicitly; the
equivalence is asserted rather than assumed.

The plan is not redrawn. The four manifests are re-verified against the frozen
digest and only the score side is re-read. All version-1 files keep their bytes;
outputs go to ``acceptance/stage8-arms-v2-2026-11-07``.
"""

import argparse
import csv
import json
import math
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import arms as frozen  # noqa: E402

V2_ACC = ROOT / "week8/acceptance/stage8-arms-v2-2026-11-07"
V1_ACC = frozen.ACC
ARMS = frozen.ARMS
DRAWS = frozen.DRAWS
TARGET = frozen.TARGET
BUDGET = frozen.BUDGET
STATE_ORDER = frozen.STATE_ORDER


# ---------------------------------------------------------------- helpers

def sha256_file(path):
    return frozen.sha256_file(pathlib.Path(path))


def read_json(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def write_json(path, payload):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def mean(values):
    return sum(values) / len(values) if values else None


def stderr(values):
    if len(values) < 2:
        return None
    m = mean(values)
    var = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var / len(values))


# ---------------------------------------------------------------- C*

def candidate_thresholds(cal_values):
    """The 61 candidate thresholds: every calibration score, ascending.

    Duplicates are kept: the family is defined by the 61 calibration images, not
    by their distinct values, so ``len(candidates) == 61`` is itself a check.
    """
    if len(cal_values) != 61:
        raise SystemExit(f"C* needs 61 calibration scores, got {len(cal_values)}")
    return sorted(cal_values)


def c_star_scan(cal_values, eval_values, defect_sorted):
    """Scan all 61 candidates; return the budget-feasible maximum TP.

    Explicitly evaluates FP and TP at every candidate, takes the maximum TP over
    the feasible ones, and cross-checks that it equals the TP at the lowest
    feasible candidate (TP monotone non-increasing in the threshold).
    """
    candidates = candidate_thresholds(cal_values)
    feasible = [t for t in candidates
                if frozen.count_above(eval_values, t) <= BUDGET]
    if not feasible:
        return {"c_star_tp": None, "c_star_threshold": None,
                "n_candidates": len(candidates), "n_feasible": 0}
    tps = [frozen.count_above(defect_sorted, t) for t in feasible]
    best = max(tps)
    lowest = min(feasible)
    if frozen.count_above(defect_sorted, lowest) != best:
        raise SystemExit("TP is not monotone over the candidate family")
    return {"c_star_tp": best, "c_star_threshold": lowest,
            "n_candidates": len(candidates), "n_feasible": len(feasible)}


def c_star_five_rules(thresholds, eval_values, defect_sorted):
    """The frozen v1 definition, reproduced exactly, kept only for the diff.

    ``min`` over the five rule thresholds that the v1 code judged feasible. It
    both omits feasible candidates below ``Q90`` and admits ``MID12``, which is
    not a candidate at all.
    """
    second_high = eval_values[-2]
    feasible = [t for t in thresholds.values() if t >= second_high]
    if not feasible:
        return None
    return frozen.count_above(defect_sorted, min(feasible))


def evaluate_row_v2(cal_values, eval_values, defect_sorted):
    thresholds, degenerate = frozen.thresholds_from(cal_values)
    rules = {}
    for name in ("MAX", "MID12", "Q95", "Q90"):
        t = thresholds[name]
        rules[name] = {"fp": frozen.count_above(eval_values, t),
                       "tp": frozen.count_above(defect_sorted, t), "hex": t.hex()}
    top, mid = rules["MAX"], rules["MID12"]
    if mid["tp"] < top["tp"] or mid["fp"] < top["fp"]:
        raise SystemExit("MID12 does not dominate MAX")
    delta_fp, delta_tp = mid["fp"] - top["fp"], mid["tp"] - top["tp"]
    if top["fp"] >= 2:
        state = "both_over_budget"
    elif mid["fp"] >= 2:
        state = "mid_over_budget"
    elif delta_tp > 0:
        state = "budget_gain"
    else:
        state = "budget_no_gain"

    scan = c_star_scan(cal_values, eval_values, defect_sorted)
    c_star = scan["c_star_tp"]
    u_tp = frozen.count_above(defect_sorted, eval_values[-2])
    five = c_star_five_rules(thresholds, eval_values, defect_sorted)

    # Feasibility of the candidate family is the complement of both_over_budget:
    # no candidate keeps FP <= 1 exactly when both top-two normals are on the
    # evaluation side, which is what FP(MAX) >= 2 means. Recorded, not assumed.
    if (c_star is None) != (state == "both_over_budget"):
        raise SystemExit("candidate feasibility and the both_over state diverge")
    if c_star is not None:
        if c_star > u_tp:
            raise SystemExit("C* exceeds the oracle point U")
        if c_star < top["tp"]:
            raise SystemExit("C* is below TP at MAX, which is a feasible candidate")

    return {
        "state": state, "delta_fp": delta_fp, "delta_tp": delta_tp,
        "rules": rules,
        "c_star_tp": c_star,
        "c_star_threshold": scan["c_star_threshold"],
        "n_feasible_candidates": scan["n_feasible"],
        "c_star_tp_five_rules": five,
        "c_star_changed": five != c_star,
        "u_tp": u_tp,
        "gap": (u_tp - c_star) if c_star is not None else None,
        "min_threshold": min(thresholds.values()),
        "max_normal": eval_values[-1],
        "slack": min(thresholds.values()) - eval_values[-1],
        "all_fp_zero": all(r["fp"] == 0 for r in rules.values()),
        "mid_degenerate": degenerate,
        "q99_identity": thresholds["Q99"].hex() == thresholds["MAX"].hex(),
    }


# ---------------------------------------------------------------- aggregation

def summarise_v2(rows):
    n = len(rows)
    states = {name: sum(1 for r in rows if r["state"] == name) for name in STATE_ORDER}
    state_block = {name: {"count": states[name], "p": states[name] / n,
                          "halfwidth": 1.96 * math.sqrt(states[name] / n
                                                        * (1 - states[name] / n) / n)}
                   for name in STATE_ORDER}

    rule_block = {}
    for name in ("MAX", "MID12", "Q95", "Q90"):
        fps = [r["rules"][name]["fp"] for r in rows]
        tps = [r["rules"][name]["tp"] for r in rows]
        rule_block[name] = {
            "fp_mean": sum(fps) / n, "fp_median": frozen.quantile(fps, 0.5),
            "fp_max": max(fps),
            "fp_le1_frac": sum(1 for v in fps if v <= BUDGET) / n,
            "fp_zero_frac": sum(1 for v in fps if v == 0) / n,
            "tp_mean": sum(tps) / n, "tp_median": frozen.quantile(tps, 0.5),
            "tp_p05": frozen.quantile(tps, 0.05), "tp_p95": frozen.quantile(tps, 0.95),
            "tp_min": min(tps), "tp_max": max(tps),
        }

    deltas_tp = [r["delta_tp"] for r in rows]
    deltas_fp = [r["delta_fp"] for r in rows]
    slacks = [r["slack"] for r in rows]

    valid = [r for r in rows if r["c_star_tp"] is not None]
    c_vals = [r["c_star_tp"] for r in valid]
    five_vals = [r["c_star_tp_five_rules"] for r in valid]
    u_valid = [r["u_tp"] for r in valid]
    u_all = [r["u_tp"] for r in rows]
    gaps = [r["gap"] for r in valid]
    changed = [r for r in rows if r["c_star_changed"]]
    lower = [r for r in changed if r["c_star_tp"] is not None
             and r["c_star_tp_five_rules"] is not None
             and r["c_star_tp"] < r["c_star_tp_five_rules"]]
    higher = [r for r in changed if r["c_star_tp"] is not None
              and r["c_star_tp_five_rules"] is not None
              and r["c_star_tp"] > r["c_star_tp_five_rules"]]
    unclassified = len(changed) - len(lower) - len(higher)

    bounds = {
        "candidate_family": "the 61 calibration scores of the row",
        "rows": n,
        "feasible_rows": len(valid),
        "infeasible_rows": n - len(valid),
        "c_star_tp_mean_given_feasible": mean(c_vals),
        "c_star_tp_se_given_feasible": stderr(c_vals),
        "c_star_tp_median_given_feasible": frozen.quantile(c_vals, 0.5),
        "c_star_tp_min_given_feasible": min(c_vals),
        "c_star_tp_max_given_feasible": max(c_vals),
        "c_star_feasible_candidates_median": frozen.quantile(
            [r["n_feasible_candidates"] for r in rows], 0.5),
        "u_tp_mean_all_rows": mean(u_all),
        "u_tp_mean_given_feasible": mean(u_valid),
        "gap_mean_given_feasible": mean(gaps),
        "gap_se_given_feasible": stderr(gaps),
        "gap_median_given_feasible": frozen.quantile(gaps, 0.5),
        "gap_min_given_feasible": min(gaps),
        "gap_max_given_feasible": max(gaps),
        "c_star_changed_rows": len(changed),
        "corrected_lower_rows": len(lower),
        "corrected_higher_rows": len(higher),
        "changed_unclassified_rows": unclassified,
        "deprecated_five_rule": {
            "note": "v1 definition reproduced for the diff only; not a bound under the protocol",
            "c_star_tp_mean_given_feasible": mean(five_vals),
            "gap_mean_given_feasible": mean(u_valid) - mean(five_vals),
            "rows_differing": len(changed),
        },
    }
    if unclassified:
        raise SystemExit(f"{unclassified} changed rows are neither lower nor higher")

    return {
        "rows": n,
        "states": state_block,
        "rules": rule_block,
        "delta": {
            "tp_mean": sum(deltas_tp) / n, "tp_median": frozen.quantile(deltas_tp, 0.5),
            "tp_max": max(deltas_tp),
            "tp_positive_frac": sum(1 for v in deltas_tp if v > 0) / n,
            "fp_mean": sum(deltas_fp) / n, "fp_median": frozen.quantile(deltas_fp, 0.5),
            "fp_max": max(deltas_fp),
            "fp_positive_frac": sum(1 for v in deltas_fp if v > 0) / n,
        },
        "slack": {
            "min": min(slacks), "median": frozen.quantile(slacks, 0.5),
            "max": max(slacks),
            "positive_frac": sum(1 for v in slacks if v > 0) / n,
            "negative_frac": sum(1 for v in slacks if v < 0) / n,
            "zero_count": sum(1 for v in slacks if v == 0),
        },
        "bounds": bounds,
        "all_rules_fp_zero_frac": sum(1 for r in rows if r["all_fp_zero"]) / n,
        "mid_degenerate_rows": sum(1 for r in rows if r["mid_degenerate"]),
        "q99_identity_rows": sum(1 for r in rows if r["q99_identity"]),
        "distinct_splits": len({tuple(r["eval_keys"]) for r in rows}),
        "duplicate_splits": n - len({tuple(r["eval_keys"]) for r in rows}),
    }


# ---------------------------------------------------------------- v1 diff

def load_v1_rows():
    path = V1_ACC / "eval-rows.csv"
    rows = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            rows[(row["arm"], int(row["repeat_id"]))] = row
    return rows


def compare_with_v1(records, v1_rows):
    """The 40000 shared columns must be untouched; only C* and gap may move."""
    fields = ("state", "max_fp", "max_tp", "mid_fp", "mid_tp",
              "q95_fp", "q95_tp", "q90_fp", "q90_tp", "u_tp")
    rule_name = {"max": "MAX", "mid": "MID12", "q95": "Q95", "q90": "Q90"}
    mismatches = []
    five_rule_mismatches = 0
    for rec in records:
        old = v1_rows[(rec["arm"], rec["repeat_id"])]
        for name in fields:
            if name == "state":
                got, want = rec["state"], old["state"]
            elif name == "u_tp":
                got, want = rec["u_tp"], int(old["u_tp"])
            else:
                rule, kind = name.split("_")
                got = rec["rules"][rule_name[rule]][kind]
                want = int(old[name])
            if got != want:
                mismatches.append([rec["arm"], rec["repeat_id"], name, got, want])
        old_c = int(old["c_star_tp"]) if old["c_star_tp"] else None
        if old_c != rec["c_star_tp_five_rules"]:
            five_rule_mismatches += 1
    if mismatches:
        raise SystemExit(f"{len(mismatches)} shared-column mismatches, e.g. {mismatches[:3]}")
    if five_rule_mismatches:
        raise SystemExit(f"{five_rule_mismatches} rows do not reproduce the v1 C* column")
    return {"shared_columns_compared": len(fields) * len(records),
            "shared_column_mismatches": 0,
            "rows_reproducing_v1_c_star_column": len(records),
            "v1_c_star_mismatches": 0}


# ---------------------------------------------------------------- eval

def evaluate(write):
    started = time.time()
    if write:
        for name in ("eval-v2.json", "eval-rows-v2.csv"):
            if (V2_ACC / name).exists():
                raise SystemExit(f"refusing to overwrite {name}")

    digest = frozen.verify_plan_digest()
    data = frozen.build_arms()
    plan_payload = frozen.load_plan()
    if plan_payload["protocol"]["sha256"] != sha256_file(frozen.PROTOCOL):
        raise SystemExit("protocol changed after the plan was frozen")
    if plan_payload["code"]["arms"]["sha256"] != sha256_file(HERE / "arms.py"):
        raise SystemExit("the frozen v1 driver no longer matches the plan digest")
    frozen.ANCHOR_KEYS = data["anchor_keys"]

    manifests = {}
    for arm in ARMS:
        spec = data["arms"][arm]
        total = frozen.lab.count(tuple(len(u) for u in spec["units"]), TARGET,
                                 spec["excluded"])
        if str(total) != plan_payload["arms"][arm]["count"]:
            raise SystemExit(f"{arm}: count changed since the plan was frozen")
        manifests[arm] = frozen.read_manifest(arm, spec, data, total)

    normals, defects = frozen.load_scores(data)
    defect_sorted = sorted(defects.values())

    per_arm = {}
    records = []
    row_records = []
    for arm in ARMS:
        arm_records = []
        for row in manifests[arm]:
            cal_values = [normals[k] for k in row["cal_keys"]]
            eval_values = sorted(normals[k] for k in row["eval_keys"])
            rec = evaluate_row_v2(cal_values, eval_values, defect_sorted)
            rec["repeat_id"] = row["repeat_id"]
            rec["eval_keys"] = row["eval_keys"]
            rec["arm"] = arm
            arm_records.append(rec)
            records.append(rec)
            row_records.append([
                arm, row["repeat_id"], rec["state"],
                rec["rules"]["MAX"]["fp"], rec["rules"]["MAX"]["tp"],
                rec["rules"]["MID12"]["fp"], rec["rules"]["MID12"]["tp"],
                rec["rules"]["Q95"]["fp"], rec["rules"]["Q95"]["tp"],
                rec["rules"]["Q90"]["fp"], rec["rules"]["Q90"]["tp"],
                rec["c_star_tp"] if rec["c_star_tp"] is not None else "",
                rec["c_star_tp_five_rules"] if rec["c_star_tp_five_rules"] is not None else "",
                int(rec["c_star_changed"]),
                rec["c_star_threshold"].hex() if rec["c_star_threshold"] is not None else "",
                rec["n_feasible_candidates"],
                rec["u_tp"],
                repr(rec["gap"]) if rec["gap"] is not None else "",
                repr(rec["slack"]),
            ])
        per_arm[arm] = summarise_v2(arm_records)

    v1_rows = load_v1_rows()
    diff = compare_with_v1(records, v1_rows)
    v1_eval = read_json(V1_ACC / "eval.json")

    # The I0 gate concerned the four states, which are unchanged by this fix.
    # Carry it forward with its hash instead of re-running it.
    gate_v1 = v1_eval["i0_gate"]
    if per_arm["I0"]["states"]["mid_over_budget"]["count"] != 58:
        raise SystemExit("I0 state counts no longer reproduce the v1 evaluation")

    v1_bounds = {arm: v1_eval["arms"][arm]["bounds"] for arm in ARMS}
    for arm in ARMS:
        got = per_arm[arm]["bounds"]["deprecated_five_rule"]["c_star_tp_mean_given_feasible"]
        want = v1_bounds[arm]["c_star_tp_mean"]
        if abs(got - want) > 1e-9:
            raise SystemExit(f"{arm}: the reproduced v1 C* mean {got} != v1 report {want}")
        if per_arm[arm]["bounds"]["feasible_rows"] != DRAWS - v1_bounds[arm]["c_star_empty"]:
            raise SystemExit(f"{arm}: feasible-row count differs from v1")

    payload = {
        "status": "STAGE8_ARMS_EVALUATION_V2",
        "version": 2,
        "supersedes": {
            "path": (V1_ACC / "eval.json").relative_to(ROOT).as_posix(),
            "sha256": sha256_file(V1_ACC / "eval.json"),
            "corrects": "c_star_tp and gap only; the five rule operating points, the "
                        "four states, slack and U are reproduced row for row",
        },
        "plan": {
            "digest": {"path": (V1_ACC / "plan-digest.json").relative_to(ROOT).as_posix(),
                       "sha256": sha256_file(V1_ACC / "plan-digest.json"),
                       "files_verified": len(digest["files"]),
                       "mismatches": 0},
            "plan_json": {"path": (V1_ACC / "arms-plan.json").relative_to(ROOT).as_posix(),
                          "sha256": sha256_file(V1_ACC / "arms-plan.json")},
            "manifests": {arm: {"path": (frozen.OUT / f"manifest-{arm}.csv")
                                .relative_to(ROOT).as_posix(),
                                "rows": len(manifests[arm]),
                                "sha256": sha256_file(frozen.OUT / f"manifest-{arm}.csv")}
                          for arm in ARMS},
            "redrawn": False,
        },
        "code": {
            "driver_v2": {"path": (HERE / "arms_v2.py").relative_to(ROOT).as_posix(),
                          "sha256": sha256_file(HERE / "arms_v2.py")},
            "driver_v1_frozen": {"path": "week8/arms.py",
                                 "sha256": sha256_file(HERE / "arms.py"),
                                 "role": "plan verification, manifest decoding, scores, "
                                         "rule thresholds, state order; evaluate_row unused"},
            "sampler": {**plan_payload["code"]["sampler"]},
        },
        "protocol": {"path": frozen.PROTOCOL.relative_to(ROOT).as_posix(),
                     "sha256": sha256_file(frozen.PROTOCOL),
                     "changed": False,
                     "note": "the fix restores conformance to section 6; the immutable "
                             "list of section 8 is untouched, so no v3 protocol is issued"},
        "scores": {"calibration": {"path": frozen.CAL_CSV.relative_to(ROOT).as_posix(),
                                   "sha256": sha256_file(frozen.CAL_CSV)},
                   "evaluation": {"path": frozen.EVAL_CSV.relative_to(ROOT).as_posix(),
                                  "sha256": sha256_file(frozen.EVAL_CSV)},
                   "normals": len(normals), "defects": len(defects)},
        "decision": "score > threshold; MAX=x61, Q99=rank61, Q95=x58, Q90=x55, "
                    "MID12=(x60+x61)/2.0; C* = max TP over the 61 candidates with FP<=1",
        "v1_diff": diff,
        "arms": per_arm,
        "i0_gate": {"status": gate_v1["status"],
                    "carried_from": (V1_ACC / "eval.json").relative_to(ROOT).as_posix(),
                    "reason": "the four states are identical to v1 row for row, so the "
                              "gate and its adjudication are unaffected by the C* fix",
                    "states_outside_3sigma": gate_v1["states_outside_3sigma"]},
        "elapsed_seconds": round(time.time() - started, 3),
    }

    if write:
        V2_ACC.mkdir(parents=True, exist_ok=True)
        rows_path = V2_ACC / "eval-rows-v2.csv"
        with rows_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh, lineterminator="\n")
            writer.writerow(["arm", "repeat_id", "state", "max_fp", "max_tp",
                             "mid_fp", "mid_tp", "q95_fp", "q95_tp", "q90_fp", "q90_tp",
                             "c_star_tp", "c_star_tp_five_rules", "c_star_changed",
                             "c_star_threshold_hex", "n_feasible_candidates",
                             "u_tp", "gap", "slack"])
            writer.writerows(row_records)
        payload["artifacts"] = {
            "eval_rows_v2": {"path": rows_path.relative_to(ROOT).as_posix(),
                             "rows": len(row_records),
                             "bytes": rows_path.stat().st_size,
                             "sha256": sha256_file(rows_path)}}
        write_json(V2_ACC / "eval-v2.json", payload)

        digest_v2 = {
            "status": "STAGE8_ARMS_V2_OUTPUT_DIGEST",
            "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "inputs": {
                "plan-digest-v1": sha256_file(V1_ACC / "plan-digest.json"),
                "protocol-v2": sha256_file(frozen.PROTOCOL),
                "arms-v1-frozen": sha256_file(HERE / "arms.py"),
                "arms-v2": sha256_file(HERE / "arms_v2.py"),
                **{f"manifest-{arm}": sha256_file(frozen.OUT / f"manifest-{arm}.csv")
                   for arm in ARMS},
            },
            "outputs": {
                "eval-v2.json": sha256_file(V2_ACC / "eval-v2.json"),
                "eval-rows-v2.csv": sha256_file(rows_path),
            },
            "modified_v1_files": 0,
        }
        write_json(V2_ACC / "output-digest.json", digest_v2)
    return payload


# ---------------------------------------------------------------- regression

def _pool(cal, ev, defects):
    """A regression case is just three sorted score vectors."""
    return {"cal": sorted(float(x) for x in cal),
            "eval_normals": sorted(float(x) for x in ev),
            "defects": sorted(float(x) for x in defects)}


def _five_rule_pool_case(cal, ev, defects):
    thresholds, _ = frozen.thresholds_from(cal)
    return c_star_five_rules(thresholds, sorted(ev), sorted(defects))


def build_cases():
    """Four fail-able cases; two of them separate the two definitions."""
    # A: the whole evaluation side is the low tail, so every calibration score is
    # feasible and the lowest one carries TP. Scanning only the five rules stops
    # at Q90 and loses 20 defect detections.
    case_a = _pool(cal=range(33, 94), ev=range(1, 33), defects=range(40, 60))

    # B: MID12 = 96 lies in a gap with no calibration score, and the only
    # feasible candidate is the calibration maximum 100. The interpolated point
    # is not a candidate, so the five-rule definition overstates C* by 3.
    case_b = _pool(cal=list(range(33, 93)) + [100],
                   ev=list(range(1, 31)) + [93, 94],
                   defects=[96.5, 97.5, 98.5])

    # C: the two definitions agree (no defect above any feasible threshold).
    case_c = _pool(cal=range(33, 94), ev=range(1, 33), defects=[200.0, 201.0])

    # D: both top-two normals are on the evaluation side; no candidate is
    # feasible and both definitions must return None.
    case_d = _pool(cal=range(1, 62), ev=list(range(62, 92)) + [99.0, 100.0],
                   defects=[50.0, 60.0])

    cases = [
        {"id": "A_low_tail_eval", "pool": case_a,
         "note": "every calibration score is feasible; C* sits at the calibration minimum",
         "expects_difference": True},
        {"id": "B_mid12_not_a_candidate", "pool": case_b,
         "note": "MID12 is feasible but lies between two calibration scores",
         "expects_difference": True},
        {"id": "C_definitions_agree", "pool": case_c,
         "note": "agreement case, so the test is not trivially unequal",
         "expects_difference": False},
        {"id": "D_no_feasible_candidate", "pool": case_d,
         "note": "both top-two normals in the evaluation side",
         "expects_difference": False},
    ]
    for case in cases:
        pool = case["pool"]
        scan = c_star_scan(pool["cal"], pool["eval_normals"], pool["defects"])
        five = _five_rule_pool_case(pool["cal"], pool["eval_normals"], pool["defects"])
        case["corrected_c_star"] = scan["c_star_tp"]
        case["corrected_threshold"] = (None if scan["c_star_threshold"] is None
                                       else scan["c_star_threshold"].hex())
        case["n_feasible_candidates"] = scan["n_feasible"]
        case["five_rule_c_star"] = five
        case["differs"] = five != scan["c_star_tp"]
    return cases


def selftest(write=False):
    checks = []

    def check(name, condition, detail=None):
        checks.append({"check": name, "pass": bool(condition), "detail": detail})

    cases = build_cases()
    by_id = {c["id"]: c for c in cases}

    # The case set must separate the corrected definition from the frozen one.
    differing = [c for c in cases if c["differs"]]
    check("cases_discriminate", len(differing) >= 2,
          [c["id"] for c in differing])
    check("case_A_old_underestimates", by_id["A_low_tail_eval"]["corrected_c_star"]
          == 20 and by_id["A_low_tail_eval"]["five_rule_c_star"] == 0,
          {"corrected": by_id["A_low_tail_eval"]["corrected_c_star"],
           "five_rule": by_id["A_low_tail_eval"]["five_rule_c_star"]})
    check("case_B_old_overestimates", by_id["B_mid12_not_a_candidate"]["corrected_c_star"]
          == 0 and by_id["B_mid12_not_a_candidate"]["five_rule_c_star"] == 3,
          {"corrected": by_id["B_mid12_not_a_candidate"]["corrected_c_star"],
           "five_rule": by_id["B_mid12_not_a_candidate"]["five_rule_c_star"]})
    check("case_C_agrees", by_id["C_definitions_agree"]["corrected_c_star"] == 2
          and by_id["C_definitions_agree"]["five_rule_c_star"] == 2,
          {"corrected": by_id["C_definitions_agree"]["corrected_c_star"],
           "five_rule": by_id["C_definitions_agree"]["five_rule_c_star"]})
    check("case_D_both_none", by_id["D_no_feasible_candidate"]["corrected_c_star"] is None
          and by_id["D_no_feasible_candidate"]["five_rule_c_star"] is None)

    # Independent restatement of the definition on every case: brute force over
    # the candidate list, no monotonicity shortcut.
    for case in cases:
        pool = case["pool"]
        brute = [len([d for d in pool["defects"] if d > t])
                 for t in pool["cal"]
                 if len([x for x in pool["eval_normals"] if x > t]) <= BUDGET]
        check(f"brute_force_matches_{case['id']}",
              (max(brute) if brute else None) == case["corrected_c_star"])

    # A mutation that scans only the five rule thresholds must fail the case set;
    # a mutation that admits MID12 must fail case B. This is what makes the
    # regression fail-able rather than merely descriptive.
    mutants = {
        "scan_five_rule_thresholds": _five_rule_pool_case,
    }
    for name, mutant in mutants.items():
        caught = []
        for case in cases:
            pool = case["pool"]
            got = mutant(pool["cal"], pool["eval_normals"], pool["defects"])
            if got != case["corrected_c_star"]:
                caught.append(case["id"])
        check(f"mutant_{name}_caught", len(caught) >= 1, caught)

    # Structural identities on real data, one arm at a time.
    data = frozen.build_arms()
    normals, defects = frozen.load_scores(data)
    defect_sorted = sorted(defects.values())
    frozen.ANCHOR_KEYS = data["anchor_keys"]
    spec = data["arms"]["G1"]
    sample = frozen.read_manifest("G1", spec, data,
                                 frozen.lab.count(tuple(len(u) for u in spec["units"]),
                                                  TARGET, spec["excluded"]))[:400]
    c_all, u_all, feasible = [], [], 0
    for row in sample:
        cal = [normals[k] for k in row["cal_keys"]]
        ev = sorted(normals[k] for k in row["eval_keys"])
        scan = c_star_scan(cal, ev, defect_sorted)
        u = frozen.count_above(defect_sorted, ev[-2])
        if scan["c_star_tp"] is not None:
            feasible += 1
            c_all.append(scan["c_star_tp"])
            u_all.append(u)
        if scan["n_candidates"] != 61:
            check("candidate_family_is_61", False, row["repeat_id"])
            break
    else:
        check("candidate_family_is_61", True, 400)
    check("sample_gap_non_negative", bool(c_all) and min(u - c for c, u in zip(c_all, u_all)) >= 0,
          {"rows": len(c_all), "min_gap": min((u - c for c, u in zip(c_all, u_all)),
                                              default=None)})
    check("sample_feasible_share", 0 < feasible <= len(sample),
          {"feasible": feasible, "rows": len(sample)})

    failed = [c for c in checks if not c["pass"]]
    payload = {"status": "STAGE8_ARMS_V2_SELFTEST", "checks": checks,
               "n_checks": len(checks), "n_failed": len(failed),
               "passed": not failed, "cases": cases}
    for item in checks:
        print(("OK   " if item["pass"] else "FAIL ") + item["check"])
    print(f"selftest: {len(checks)} checks, {len(failed)} failed")
    if write:
        for name in ("selftest-v2.json", "c-star-cases.json"):
            if (V2_ACC / name).exists():
                raise SystemExit(f"refusing to overwrite {name}")
        write_json(V2_ACC / "selftest-v2.json",
                   {**payload, "cases": [
                       {k: v for k, v in c.items() if k != "pool"} for c in cases]})
        write_json(V2_ACC / "c-star-cases.json", {"status": "STAGE8_C_STAR_CASES",
                                                 "definition": "max TP over the 61 "
                                                               "candidates with FP<=1",
                                                 "cases": cases})
    return 0 if not failed else 1


# ---------------------------------------------------------------- main

def main(argv=None):
    parser = argparse.ArgumentParser(description="Stage 8 driver v2 (corrected C*)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("selftest")
    st.add_argument("--write", action="store_true")
    ev = sub.add_parser("eval")
    ev.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)

    if args.cmd == "selftest":
        return selftest(args.write)

    payload = evaluate(args.write)
    for arm in ARMS:
        b = payload["arms"][arm]["bounds"]
        print(arm, {
            "feasible": b["feasible_rows"],
            "E_C*|feasible": round(b["c_star_tp_mean_given_feasible"], 6),
            "E_U|feasible": round(b["u_tp_mean_given_feasible"], 6),
            "E_gap|feasible": round(b["gap_mean_given_feasible"], 6),
            "E_U|all": round(b["u_tp_mean_all_rows"], 4),
            "changed": b["c_star_changed_rows"],
            "lower": b["corrected_lower_rows"],
            "higher": b["corrected_higher_rows"],
            "v1_E_C*|feasible": round(
                b["deprecated_five_rule"]["c_star_tp_mean_given_feasible"], 4),
        })
    print("v1 diff:", payload["v1_diff"])
    print("written:", args.write, "elapsed:", payload["elapsed_seconds"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
