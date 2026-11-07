"""Diagnosis of the I0 consistency gate, plus the structural check on MID12.

The frozen driver aborts because I0's sampled ``mid_over_budget`` rate sits
3.12 sigma below the stage 7 exact value. This script answers three questions
without touching any frozen artefact:

1. Is the deviation a pipeline error or a finite-sample fluctuation? Two
   independent replications (100,000 uniform subsets; 20,000 fresh lab-sampler
   draws) are compared with the exact probabilities.
2. How unlikely is the observed count under the exact model (exact binomial
   tail, not a normal approximation)?
3. Why is ``mid_over_budget`` empty in the three anchored arms while non-zero
   in I0? The joint distribution of (FP(MAX), FP(MID12)) and the score floor
   provided by the fixed 18-image group are recorded here.
"""

import bisect
import csv
import json
import math
import pathlib
import random
import sys
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAB = ROOT / "week8/grouped-split-lab"
sys.path.insert(0, str(LAB))
from src import sampler as lab  # noqa: E402

ACC = ROOT / "week8/acceptance/stage8-arms-2026-11-06"
OUT = ROOT / "week8/outputs/arms-v1"
RUN = ROOT / "week7/outputs/background-448-r1"
ARMS = ("I0", "G0", "I1", "G1")
STATES = ("budget_gain", "budget_no_gain", "mid_over_budget", "both_over_budget")


def above(values, threshold):
    return len(values) - bisect.bisect_right(values, threshold)


def load_scores():
    scores, cal, evn, defects = {}, [], [], []
    with (RUN / "calibration-scores.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            scores[row["relative_path"]] = float(row["score"])
            cal.append(row["relative_path"])
    with (RUN / "evaluation-scores.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            scores[row["relative_path"]] = float(row["score"])
            if row["role"] == "eval_normal":
                evn.append(row["relative_path"])
            else:
                defects.append(float(row["score"]))
    defects.sort()
    return scores, sorted(cal + evn), sorted(defects)


def state_of(cal, ev, defects):
    cal = sorted(cal)
    x61, x60 = cal[-1], cal[-2]
    mid = (x60 + x61) / 2.0
    fp_max, fp_mid = above(ev, x61), above(ev, mid)
    tp_max, tp_mid = above(defects, x61), above(defects, mid)
    if fp_max >= 2:
        return "both_over_budget", fp_max, fp_mid
    if fp_mid >= 2:
        return "mid_over_budget", fp_max, fp_mid
    return ("budget_gain" if tp_mid > tp_max else "budget_no_gain"), fp_max, fp_mid


def tally(states):
    return {s: states.count(s) / len(states) for s in STATES}


def binomial_tail(n, p_frac, k):
    """P(X <= k) under Binomial(n, p) with exact rational arithmetic."""
    total = Fraction(0)
    q = 1 - p_frac
    for i in range(k + 1):
        total += math.comb(n, i) * p_frac ** i * q ** (n - i)
    return total


def main():
    scores, universe, defects = load_scores()
    exact = json.loads((ROOT / "week7/acceptance/stage7-background-2026-11-05/"
                        "split-exact-enumeration.json").read_text(encoding="utf-8"))
    exact_p = {s: Fraction(exact["states"][s]["ways"], exact["total_splits"]) for s in STATES}
    plan = json.loads((ACC / "arms-plan.json").read_text(encoding="utf-8"))

    out = {
        "status": "STAGE8_I0_GATE_DIAGNOSIS",
        "exact": {s: float(exact_p[s]) for s in STATES},
        "gate": {"rule": "each state within 3 sigma of the exact value",
                 "sigma_basis": "sqrt(p(1-p)/10000)"},
    }

    # 1. frozen I0 manifest
    keys = plan["arms"]["I0"]["image_keys"]
    states, joints = [], {}
    for row in csv.DictReader((OUT / "manifest-I0.csv").open(encoding="utf-8", newline="")):
        idx = {int(x) for x in row["eval_idx"].split()}
        ev_keys = {keys[i] for i in idx}
        ev = sorted(scores[k] for k in ev_keys)
        cal = [scores[k] for k in universe if k not in ev_keys]
        state, fp_max, fp_mid = state_of(cal, ev, defects)
        states.append(state)
        joints[(fp_max, fp_mid)] = joints.get((fp_max, fp_mid), 0) + 1
    observed = tally(states)
    out["i0_manifest"] = {
        "rows": len(states),
        "observed": observed,
        "z": {s: (observed[s] - float(exact_p[s])) / math.sqrt(
            float(exact_p[s]) * (1 - float(exact_p[s])) / len(states)) for s in STATES},
        "counts": {s: states.count(s) for s in STATES},
    }
    k = states.count("mid_over_budget")
    tail = binomial_tail(len(states), exact_p["mid_over_budget"], k)
    out["i0_manifest"]["mid_over_tail"] = {
        "k": k, "expected": float(exact_p["mid_over_budget"]) * len(states),
        "p_X_le_k": float(tail), "log10": math.log10(float(tail))}

    # 2. independent replication A: 100,000 uniform subsets
    rng = random.Random(987654321)
    n_a = 100_000
    picks = []
    for _ in range(n_a):
        idx = set(rng.sample(range(len(universe)), 32))
        ev = sorted(scores[universe[i]] for i in idx)
        cal = [scores[universe[i]] for i in range(len(universe)) if i not in idx]
        picks.append(state_of(cal, ev, defects)[0])
    out["replication_A_random_sample"] = {"n": n_a, "p": tally(picks)}

    # 3. independent replication B: fresh lab decode
    n_b = 20_000
    rng = random.Random(2026110612)
    sizes = tuple([1] * len(universe))
    total = lab.count(sizes, 32)
    picks = []
    for _ in range(n_b):
        subset = lab.decode(sizes, 32, rng.randrange(total))
        idx = set(subset)
        ev = sorted(scores[universe[i]] for i in idx)
        cal = [scores[universe[i]] for i in range(len(universe)) if i not in idx]
        picks.append(state_of(cal, ev, defects)[0])
    out["replication_B_lab_decode"] = {"n": n_b, "p": tally(picks)}

    # 4. joint FP table per arm + anchored score floor
    joint_out = {}
    for arm in ARMS:
        image_keys = plan["arms"][arm]["image_keys"]
        table = {}
        for row in csv.DictReader((OUT / f"manifest-{arm}.csv").open(encoding="utf-8", newline="")):
            idx = {int(x) for x in row["eval_idx"].split()}
            ev_keys = {image_keys[i] for i in idx}
            ev = sorted(scores[k] for k in ev_keys)
            cal = [scores[k] for k in universe if k not in ev_keys]
            c = sorted(cal)
            x61, x60 = c[-1], c[-2]
            mid = (x60 + x61) / 2.0
            key = f"{above(ev, x61)},{above(ev, mid)}"
            table[key] = table.get(key, 0) + 1
        joint_out[arm] = dict(sorted(table.items(), key=lambda kv: tuple(map(int, kv[0].split(",")))))
    anchor = [u for u in plan["arms"]["G0"]["units"] if len(u) == 18][0]
    anchor_scores = sorted((scores[k] for k in anchor), reverse=True)
    eligible_scores = sorted((scores[k] for k in plan["arms"]["I1"]["image_keys"]), reverse=True)
    out["joint_fp_table"] = joint_out
    out["anchor_floor"] = {
        "anchor_top": anchor_scores[0],
        "anchor_second": anchor_scores[1],
        "eligible_top": eligible_scores[:4],
        "note": "the 18-image group stays on the calibration side in G0/I1/G1, so the "
                "second-highest calibration score can never fall below the group's "
                "second-highest score; MID12 therefore stays above the eligible tail "
                "whenever MAX is feasible, and no (FP_max=1, FP_mid=2) row occurs",
    }
    (ACC / "i0-gate-diagnosis.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in
                      ("i0_manifest", "replication_A_random_sample",
                       "replication_B_lab_decode", "anchor_floor")},
                     ensure_ascii=False, indent=1)[:2400])


if __name__ == "__main__":
    main()
