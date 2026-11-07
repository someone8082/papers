"""Stage 8 four-arm driver.

Two strictly ordered phases, per ``stage8-arms-protocol-2026-11-06.md``:

``plan`` builds the four arm definitions, verifies the three external counts,
computes exact inclusion probabilities and draws the 10,000 whole-group (or
whole-image) allocations per arm. It never opens a score file; an audit hook
records every repository path opened inside the window.

``eval`` re-verifies the frozen plan digest, re-decodes every manifest row, and
only then loads the archived scores to compute thresholds, FP/TP, the four
states and the post-hoc bounds.

Nothing here trains, scores or selects images by their scores.
"""

import argparse
import bisect
import csv
import hashlib
import json
import math
import pathlib
import random
import sys
import time
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAB = ROOT / "week8/grouped-split-lab"
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from src import sampler as lab  # noqa: E402

ROLES = ROOT / "week7/acceptance/stage7-background-2026-11-05/roles-background-v1.json"
GROUPS = ROOT / "week8/acceptance/stage8-grouping-2026-11-06/groups-dh4.csv"
DECISION = ROOT / "week8/acceptance/stage8-grouping-2026-11-06/decision-check.json"
CAL_CSV = ROOT / "week7/outputs/background-448-r1/calibration-scores.csv"
EVAL_CSV = ROOT / "week7/outputs/background-448-r1/evaluation-scores.csv"
EXACT = ROOT / "week7/acceptance/stage7-background-2026-11-05/split-exact-enumeration.json"

PROTOCOL = ROOT / "week8/stage8-arms-protocol-v2-2026-11-06.md"
PROTOCOL_V1 = ROOT / "week8/stage8-arms-protocol-2026-11-06.md"
OUT = ROOT / "week8/outputs/arms-v1"
ACC = ROOT / "week8/acceptance/stage8-arms-2026-11-06"

ARMS = ("I0", "G0", "I1", "G1")
MAIN_ARM = "G1"
TARGET = 32
DRAWS = 10_000
BUDGET = 1
RULES = ("MAX", "Q99", "Q95", "Q90", "MID12")
STATE_ORDER = ("budget_gain", "budget_no_gain", "mid_over_budget", "both_over_budget")
SEED_TEMPLATE = "stage8-grouped-v1|20261106|"
ADJUDICATION_DRAWS = 100_000
ADJUDICATION_SEED_TEXT = "stage8-adjudication|20261106"


# ---------------------------------------------------------------- utilities

def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def rank_of(num: int, den: int, n: int) -> int:
    """Ascending nearest-rank index: ceil(num*n/den) in integer arithmetic."""
    return (num * n + den - 1) // den


def seed_of(arm: str) -> int:
    return int.from_bytes(sha256_bytes((SEED_TEMPLATE + arm).encode("utf-8")), "big")


def sha256_bytes(payload: bytes) -> bytes:
    return hashlib.sha256(payload).digest()


class Audit:
    """Records every repository path opened inside the window."""

    def __init__(self, root: pathlib.Path) -> None:
        self.root = str(root)
        self.paths: list[str] = []
        self.active = False

    def start(self) -> None:
        self.active = True
        sys.addaudithook(self._hook)

    def stop(self) -> None:
        self.active = False

    def _hook(self, event: str, args: tuple) -> None:
        if not self.active or event != "open":
            return
        raw = args[0] if args else None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        elif not isinstance(raw, str):
            return
        try:
            resolved = pathlib.Path(raw).resolve()
        except OSError:
            return
        text = str(resolved)
        if not text.startswith(self.root):
            return
        rel = text[len(self.root) + 1:].replace("\\", "/")
        if rel not in self.paths:
            self.paths.append(rel)


# ---------------------------------------------------------------- inputs

def load_groups() -> list[dict]:
    rows = []
    with GROUPS.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            members = tuple(row["members"].split())
            if len(members) != int(row["size"]):
                raise SystemExit(f"group {row['group_id']}: size mismatch")
            rows.append({"group_id": int(row["group_id"]), "members": members,
                         "size": len(members), "eval_eligible": row["eval_eligible"]})
    if [g["members"][0] for g in rows] != sorted(g["members"][0] for g in rows):
        raise SystemExit("groups are not ordered by their smallest key")
    return rows


def build_arms() -> dict:
    roles = read_json(ROLES)
    pools = roles["pools"]
    universe = sorted(pools["calibration"] + pools["eval_normal"])
    if len(universe) != 93 or len(set(universe)) != 93:
        raise SystemExit("universe is not 93 distinct test normals")

    groups = load_groups()
    if len(groups) != 66:
        raise SystemExit(f"expected 66 groups, got {len(groups)}")
    flat = [k for g in groups for k in g["members"]]
    if sorted(flat) != universe:
        raise SystemExit("group members do not partition the 93 test normals")

    anchored_groups = [g for g in groups if g["eval_eligible"] != "1"]
    if len(anchored_groups) != 1 or anchored_groups[0]["size"] != 18:
        raise SystemExit("expected exactly one 18-image anchored group")
    anchor = anchored_groups[0]
    anchor_keys = set(anchor["members"])
    eligible = [k for k in universe if k not in anchor_keys]
    if len(eligible) != 75:
        raise SystemExit(f"expected 75 eligible images, got {len(eligible)}")

    group_units = [g["members"] for g in groups]
    eligible_units = [g["members"] for g in groups if g is not anchor]

    return {
        "universe": universe,
        "eligible": eligible,
        "anchor": anchor,
        "anchor_keys": anchor_keys,
        "groups": groups,
        "arms": {
            "I0": {"units": [(k,) for k in universe], "image_keys": universe,
                   "excluded": (), "kind": "image"},
            "G0": {"units": group_units, "image_keys": universe,
                   "excluded": (), "kind": "group"},
            "I1": {"units": [(k,) for k in eligible], "image_keys": eligible,
                   "excluded": (), "kind": "image"},
            "G1": {"units": eligible_units, "image_keys": eligible,
                   "excluded": (), "kind": "group"},
        },
    }


def expected_counts(data: dict) -> dict:
    decision = read_json(DECISION)
    return {
        "I0": math.comb(93, TARGET),
        "G0": int(decision["grouped_allocations"]),
        "I1": math.comb(75, TARGET),
        "G1": int(decision["anchored_allocations"]),
    }


# ---------------------------------------------------------------- plan

def fraction_record(value: Fraction) -> dict:
    return {"value": repr(float(value)), "numerator": str(value.numerator),
            "denominator": str(value.denominator)}


def draw_arm(arm: str, spec: dict, total: int) -> list[tuple[int, int, tuple]]:
    sizes = tuple(len(u) for u in spec["units"])
    rng = random.Random(seed_of(arm))
    rows = []
    for repeat in range(DRAWS):
        rank = rng.randrange(total)
        subset = lab.decode(sizes, TARGET, rank, spec["excluded"])
        rows.append((repeat, rank, subset))
    return rows


def expand(units: list[tuple], subset: tuple) -> list[str]:
    keys: list[str] = []
    for index in subset:
        keys.extend(units[index])
    return sorted(keys)


def plan(write: bool) -> dict:
    audit = Audit(ROOT)
    audit.start()
    started = time.time()

    data = build_arms()
    anchors = expected_counts(data)
    arms_out = {}
    manifests = {}

    for arm in ARMS:
        spec = data["arms"][arm]
        sizes = tuple(len(u) for u in spec["units"])
        total = lab.count(sizes, TARGET, spec["excluded"])
        if total != anchors[arm]:
            raise SystemExit(f"{arm}: count {total} != external anchor {anchors[arm]}")
        probabilities = lab.inclusion_probabilities(sizes, TARGET, spec["excluded"])
        weighted = sum(size * p for size, p in zip(sizes, probabilities))
        if weighted != TARGET:
            raise SystemExit(f"{arm}: weighted inclusion {weighted} != {TARGET}")

        rows = draw_arm(arm, spec, total)
        positions = {key: i for i, key in enumerate(spec["image_keys"])}

        manifest_rows = []
        seen: dict[str, int] = {}
        for repeat, rank, subset in rows:
            eval_keys = expand(spec["units"], subset)
            if len(eval_keys) != TARGET:
                raise SystemExit(f"{arm}/{repeat}: {len(eval_keys)} eval images")
            # Only the anchored arms keep the reference-adjacent group on the
            # calibration side. I0 and G0 are unrestricted baselines.
            if arm in ("I1", "G1") and data["anchor_keys"] & set(eval_keys):
                raise SystemExit(f"{arm}/{repeat}: anchored image entered the eval side")
            cal_keys = sorted(k for k in data["universe"] if k not in set(eval_keys))
            if len(cal_keys) != 61:
                raise SystemExit(f"{arm}/{repeat}: {len(cal_keys)} calibration images")
            digest = sha256_text("\n".join(eval_keys))
            # Repeated splits are allowed by the protocol: counted, never dropped.
            seen.setdefault(digest, repeat)
            idx = " ".join(str(positions[k]) for k in eval_keys)
            manifest_rows.append([arm, repeat, str(rank), idx, len(eval_keys), digest,
                                  len(cal_keys)])

        manifests[arm] = manifest_rows
        arms_out[arm] = {
            "kind": spec["kind"],
            "units": [list(u) for u in spec["units"]],
            "unit_sizes": list(sizes),
            "image_keys": spec["image_keys"],
            "target": TARGET,
            "count": str(total),
            "count_anchor": str(anchors[arm]),
            "count_matches_anchor": True,
            "draws": DRAWS,
            "seed": str(seed_of(arm)),
            "seed_hex": format(seed_of(arm), "x"),
            "inclusion": [{"unit": i, "size": sizes[i], **fraction_record(p)}
                          for i, p in enumerate(probabilities)],
            "inclusion_weighted_sum": str(weighted),
            "inclusion_sum": fraction_record(sum(probabilities)),
            "duplicate_splits": len(rows) - len(seen),
        }

    # G1 must equal G0 with the anchored group excluded, and I1 must be C(75,32).
    g0_sizes = tuple(len(u) for u in data["arms"]["G0"]["units"])
    anchor_index = data["arms"]["G0"]["units"].index(data["anchor"]["members"])
    g1_via_exclusion = lab.count(g0_sizes, TARGET, (anchor_index,))
    if g1_via_exclusion != anchors["G1"]:
        raise SystemExit("G1 != G0 restricted to excluding the anchored group")

    audit.stop()
    elapsed = round(time.time() - started, 3)

    scores_paths = [p for p in audit.paths if "scores" in p.lower()]
    isolation = {
        "window": "plan",
        "opened_paths": list(audit.paths),
        "score_paths_opened": scores_paths,
        "scores_read": bool(scores_paths),
        "ok": not scores_paths,
    }
    if scores_paths:
        raise SystemExit(f"plan phase opened score files: {scores_paths}")

    anchor_probability = Fraction(int(arms_out["G0"]["inclusion"][anchor_index]["numerator"]),
                                  int(arms_out["G0"]["inclusion"][anchor_index]["denominator"]))
    payload = {
        "status": "STAGE8_ARMS_PLAN",
        "protocol": {"path": PROTOCOL.relative_to(ROOT).as_posix(),
                     "sha256": sha256_file(PROTOCOL),
                     "version": 2,
                     "supersedes": {"path": PROTOCOL_V1.relative_to(ROOT).as_posix(),
                                    "sha256": sha256_file(PROTOCOL_V1)}},
        "inputs": {
            "roles": {"path": ROLES.relative_to(ROOT).as_posix(),
                      "sha256": sha256_file(ROLES), "bytes": ROLES.stat().st_size},
            "groups": {"path": GROUPS.relative_to(ROOT).as_posix(),
                       "sha256": sha256_file(GROUPS), "bytes": GROUPS.stat().st_size},
            "decision": {"path": DECISION.relative_to(ROOT).as_posix(),
                         "sha256": sha256_file(DECISION), "bytes": DECISION.stat().st_size},
        },
        "code": {"arms": {"path": pathlib.Path(__file__).resolve().relative_to(ROOT).as_posix(),
                          "sha256": sha256_file(pathlib.Path(__file__).resolve())},
                 "sampler": {"path": (LAB / "src/sampler.py").relative_to(ROOT).as_posix(),
                             "sha256": sha256_file(LAB / "src/sampler.py")}},
        "design": {
            "target": TARGET,
            "draws": DRAWS,
            "budget": BUDGET,
            "seed_template": SEED_TEMPLATE,
            "main_arm": MAIN_ARM,
            "arm_unit_counts": {arm: len(arms_out[arm]["units"]) for arm in ARMS},
            "anchor_group_id": data["anchor"]["group_id"],
            "anchor_size": data["anchor"]["size"],
            "universe_size": len(data["universe"]),
            "eligible_size": len(data["eligible"]),
        },
        "anchors": {
            "counts_match": True,
            "g1_equals_g0_minus_anchor": str(g1_via_exclusion),
            "anchor_selected_allocations": str(anchors["G0"] - anchors["G1"]),
        },
        "inclusion_notes": {
            "G0_anchor_group": {**fraction_record(anchor_probability),
                                "expected_eval_rows_in_10000": repr(float(anchor_probability * DRAWS))},
        },
        "arms": arms_out,
        "isolation": isolation,
        "elapsed_seconds": elapsed,
    }

    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        header = ["arm", "repeat_id", "rank", "eval_idx", "eval_n", "eval_sha256", "cal_n"]
        for arm in ARMS:
            path = OUT / f"manifest-{arm}.csv"
            with path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh, lineterminator="\n")
                writer.writerow(header)
                writer.writerows(manifests[arm])
            payload["arms"][arm]["manifest"] = {
                "path": path.relative_to(ROOT).as_posix(),
                "rows": len(manifests[arm]),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        write_json(ACC / "arms-plan.json", payload)

        digest = {
            "status": "STAGE8_ARMS_PLAN_FROZEN",
            "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "draws": DRAWS,
            "seeds": {arm: str(seed_of(arm)) for arm in ARMS},
            "counts": {arm: arms_out[arm]["count"] for arm in ARMS},
            "manifest_row_counts": {arm: len(manifests[arm]) for arm in ARMS},
            "files": {},
        }
        targets = [PROTOCOL, PROTOCOL_V1, pathlib.Path(__file__).resolve(),
                   LAB / "src/sampler.py",
                   ROLES, GROUPS, DECISION, ACC / "arms-plan.json"]
        targets += [OUT / f"manifest-{arm}.csv" for arm in ARMS]
        for path in targets:
            digest["files"][path.relative_to(ROOT).as_posix()] = {
                "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        write_json(ACC / "plan-digest.json", digest)

    return payload


# ---------------------------------------------------------------- eval

def verify_plan_digest() -> dict:
    digest = read_json(ACC / "plan-digest.json")
    bad = []
    for rel, meta in digest["files"].items():
        path = ROOT / rel
        if not path.is_file():
            bad.append([rel, "missing"])
            continue
        if path.stat().st_size != meta["bytes"] or sha256_file(path) != meta["sha256"]:
            bad.append([rel, "mismatch"])
    if bad:
        raise SystemExit(f"plan digest mismatch: {bad}")
    return digest


def load_plan() -> dict:
    return read_json(ACC / "arms-plan.json")


def read_manifest(arm: str, spec: dict, data: dict, total: int) -> list[dict]:
    sizes = tuple(len(u) for u in spec["units"])
    positions = {key: i for i, key in enumerate(spec["image_keys"])}
    path = OUT / f"manifest-{arm}.csv"
    rows = []
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if row["arm"] != arm:
                raise SystemExit(f"{path.name}: foreign arm {row['arm']}")
            rank = int(row["rank"])
            if not 0 <= rank < total:
                raise SystemExit(f"{path.name}/{row['repeat_id']}: rank out of range")
            subset = lab.decode(sizes, TARGET, rank, spec["excluded"])
            eval_keys = expand(spec["units"], subset)
            idx = [int(x) for x in row["eval_idx"].split()]
            if idx != sorted(idx) or len(set(idx)) != len(idx):
                raise SystemExit(f"{path.name}/{row['repeat_id']}: eval_idx not sorted/unique")
            if [spec["image_keys"][i] for i in idx] != eval_keys:
                raise SystemExit(f"{path.name}/{row['repeat_id']}: rank does not decode to eval_idx")
            if sha256_text("\n".join(eval_keys)) != row["eval_sha256"]:
                raise SystemExit(f"{path.name}/{row['repeat_id']}: row digest mismatch")
            if int(row["eval_n"]) != TARGET or int(row["cal_n"]) != 61:
                raise SystemExit(f"{path.name}/{row['repeat_id']}: bad counts")
            if arm in ("I1", "G1") and data["anchor_keys"] & set(eval_keys):
                raise SystemExit(f"{path.name}/{row['repeat_id']}: anchored image in eval")
            cal_keys = tuple(k for k in data["universe"] if k not in set(eval_keys))
            if len(cal_keys) != 61:
                raise SystemExit(f"{path.name}/{row['repeat_id']}: bad calibration size")
            rows.append({"repeat_id": int(row["repeat_id"]), "rank": rank,
                         "eval_keys": eval_keys, "cal_keys": cal_keys})
    if len(rows) != DRAWS:
        raise SystemExit(f"{path.name}: {len(rows)} rows != {DRAWS}")
    if [r["repeat_id"] for r in rows] != list(range(DRAWS)):
        raise SystemExit(f"{path.name}: repeat_id is not 0..{DRAWS - 1}")
    return rows


def load_scores(data: dict) -> tuple[dict, dict]:
    roles = read_json(ROLES)
    cal_expected = set(roles["pools"]["calibration"])
    ev_expected = set(roles["pools"]["eval_normal"])
    defect_expected = set(roles["pools"]["eval_defect"])

    calibration = {}
    with CAL_CSV.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            calibration[row["relative_path"]] = float(row["score"])
    if set(calibration) != cal_expected:
        raise SystemExit("calibration score keys do not match the role table")

    normals = dict(calibration)
    defects = {}
    with EVAL_CSV.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            key, role, value = row["relative_path"], row["role"], float(row["score"])
            if role == "eval_normal":
                if key not in ev_expected:
                    raise SystemExit(f"unexpected eval normal {key}")
                normals[key] = value
            elif role == "eval_defect":
                if key not in defect_expected:
                    raise SystemExit(f"unexpected defect {key}")
                defects[key] = value
            else:
                raise SystemExit(f"unexpected role {role}")
    if len(normals) != 93 or len(defects) != 212:
        raise SystemExit(f"score pools are {len(normals)}/{len(defects)}, expected 93/212")
    if any(not math.isfinite(v) for v in list(normals.values()) + list(defects.values())):
        raise SystemExit("non-finite score loaded")
    return normals, defects


def thresholds_from(cal_values: list[float]) -> tuple[dict, bool]:
    if len(cal_values) != 61:
        raise SystemExit("thresholds require exactly 61 calibration scores")
    ordered = sorted(cal_values)
    x61, x60 = ordered[-1], ordered[-2]
    mid = (x60 + x61) / 2.0
    values = {
        "MAX": x61,
        "Q99": ordered[rank_of(99, 100, 61) - 1],
        "Q95": ordered[rank_of(95, 100, 61) - 1],
        "Q90": ordered[rank_of(90, 100, 61) - 1],
        "MID12": mid,
    }
    if values["Q99"].hex() != values["MAX"].hex():
        raise SystemExit("Q99 is not bit-identical to MAX")
    if not x60 <= mid <= x61:
        raise SystemExit("MID12 outside the top-two bracket")
    return values, mid in (x60, x61)


def count_above(ordered: list[float], threshold: float) -> int:
    return len(ordered) - bisect.bisect_right(ordered, threshold)


def evaluate_row(cal_values: list[float], normals: list[float], defects: list[float]) -> dict:
    thresholds, degenerate = thresholds_from(cal_values)
    result = {}
    for name in ("MAX", "MID12", "Q95", "Q90"):
        t = thresholds[name]
        result[name] = {"fp": count_above(normals, t), "tp": count_above(defects, t),
                        "hex": t.hex()}
    top, mid = result["MAX"], result["MID12"]
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

    second_high = normals[-2]
    feasible = [t for t in thresholds.values() if t >= second_high]
    c_star_tp = count_above(defects, min(feasible)) if feasible else None
    u_tp = count_above(defects, second_high)
    min_threshold = min(thresholds.values())
    max_normal = normals[-1]
    return {
        "state": state,
        "delta_fp": delta_fp,
        "delta_tp": delta_tp,
        "rules": result,
        "c_star_tp": c_star_tp,
        "u_tp": u_tp,
        "gap": (u_tp - c_star_tp) if c_star_tp is not None else None,
        "min_threshold": min_threshold,
        "max_normal": max_normal,
        "slack": min_threshold - max_normal,
        "all_fp_zero": all(r["fp"] == 0 for r in result.values()),
        "mid_degenerate": degenerate,
        "q99_identity": thresholds["Q99"].hex() == thresholds["MAX"].hex(),
    }


def quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
    return ordered[index]


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    states = {name: sum(1 for r in rows if r["state"] == name) for name in STATE_ORDER}
    state_block = {}
    for name in STATE_ORDER:
        p = states[name] / n
        state_block[name] = {"count": states[name], "p": p,
                             "halfwidth": 1.96 * math.sqrt(p * (1 - p) / n)}

    rules = {}
    for name in ("MAX", "MID12", "Q95", "Q90"):
        fps = [r["rules"][name]["fp"] for r in rows]
        tps = [r["rules"][name]["tp"] for r in rows]
        rules[name] = {
            "fp_mean": sum(fps) / n, "fp_median": quantile(fps, 0.5), "fp_max": max(fps),
            "fp_le1_frac": sum(1 for v in fps if v <= BUDGET) / n,
            "fp_zero_frac": sum(1 for v in fps if v == 0) / n,
            "tp_mean": sum(tps) / n, "tp_median": quantile(tps, 0.5),
            "tp_p05": quantile(tps, 0.05), "tp_p95": quantile(tps, 0.95),
            "tp_min": min(tps), "tp_max": max(tps),
        }

    deltas_tp = [r["delta_tp"] for r in rows]
    deltas_fp = [r["delta_fp"] for r in rows]
    slacks = [r["slack"] for r in rows]
    c_stars = [r["c_star_tp"] for r in rows]
    u_tps = [r["u_tp"] for r in rows]
    gaps = [r["gap"] for r in rows]

    delta_block = {
        "tp_mean": sum(deltas_tp) / n,
        "tp_median": quantile(deltas_tp, 0.5),
        "tp_max": max(deltas_tp),
        "tp_positive_frac": sum(1 for v in deltas_tp if v > 0) / n,
        "fp_mean": sum(deltas_fp) / n,
        "fp_median": quantile(deltas_fp, 0.5),
        "fp_max": max(deltas_fp),
        "fp_positive_frac": sum(1 for v in deltas_fp if v > 0) / n,
        "fp_per_extra_tp": (sum(deltas_fp) / sum(deltas_tp)) if sum(deltas_tp) else None,
    }

    slack_block = {
        "min": min(slacks), "median": quantile(slacks, 0.5), "max": max(slacks),
        "positive_frac": sum(1 for v in slacks if v > 0) / n,
        "negative_frac": sum(1 for v in slacks if v < 0) / n,
        "zero_count": sum(1 for v in slacks if v == 0),
    }

    c_valid = [v for v in c_stars if v is not None]
    gap_valid = [v for v in gaps if v is not None]
    bounds = {
        "c_star_tp_mean": (sum(c_valid) / len(c_valid)) if c_valid else None,
        "c_star_tp_median": quantile(c_valid, 0.5) if c_valid else None,
        "c_star_empty": len(c_stars) - len(c_valid),
        "u_tp_mean": sum(u_tps) / n,
        "u_tp_median": quantile(u_tps, 0.5),
        "gap_mean": (sum(gap_valid) / len(gap_valid)) if gap_valid else None,
        "gap_median": quantile(gap_valid, 0.5) if gap_valid else None,
        "gap_min": min(gap_valid) if gap_valid else None,
        "gap_max": max(gap_valid) if gap_valid else None,
    }

    return {
        "rows": n,
        "states": state_block,
        "rules": rules,
        "delta": delta_block,
        "slack": slack_block,
        "bounds": bounds,
        "all_rules_fp_zero_frac": sum(1 for r in rows if r["all_fp_zero"]) / n,
        "mid_degenerate_rows": sum(1 for r in rows if r["mid_degenerate"]),
        "q99_identity_rows": sum(1 for r in rows if r["q99_identity"]),
        "distinct_splits": len({tuple(r["eval_keys"]) for r in rows}),
        "duplicate_splits": n - len({tuple(r["eval_keys"]) for r in rows}),
        "anchor_in_eval_rows": sum(1 for r in rows if any(
            k in ANCHOR_KEYS for k in r["eval_keys"])) if ANCHOR_KEYS else 0,
    }


ANCHOR_KEYS: set[str] = set()


def adjudicate_i0(normals: dict, defect_sorted: list[float], exact: dict) -> dict:
    """Independent 10x replication, used only when the I0 gate deviates.

    Draws 32-image subsets with ``random.sample`` instead of decoding a group
    rank, so the replication shares no sampling code with the manifest under
    test. The seed and the draw count are fixed; the arm manifest is never
    re-drawn.
    """
    seed = int.from_bytes(sha256_bytes(ADJUDICATION_SEED_TEXT.encode("utf-8")), "big")
    rng = random.Random(seed)
    keys = sorted(normals, key=lambda k: -normals[k])
    values = [normals[k] for k in keys]
    counts = {name: 0 for name in STATE_ORDER}
    for _ in range(ADJUDICATION_DRAWS):
        chosen = set(rng.sample(range(len(values)), TARGET))
        top: list[float] = []
        for index, value in enumerate(values):
            if index in chosen:
                continue
            top.append(value)
            if len(top) == 2:
                break
        x61, x60 = top[0], top[1]
        mid = (x60 + x61) / 2.0
        selected = [values[i] for i in chosen]
        fp_max = sum(1 for v in selected if v > x61)
        fp_mid = sum(1 for v in selected if v > mid)
        tp_max = count_above(defect_sorted, x61)
        tp_mid = count_above(defect_sorted, mid)
        if fp_max >= 2:
            counts["both_over_budget"] += 1
        elif fp_mid >= 2:
            counts["mid_over_budget"] += 1
        elif tp_mid > tp_max:
            counts["budget_gain"] += 1
        else:
            counts["budget_no_gain"] += 1

    block = {"draws": ADJUDICATION_DRAWS, "seed": str(seed),
             "seed_text": ADJUDICATION_SEED_TEXT,
             "sampling": "random.sample over 93 image indices, independent of decode",
             "states": {}}
    ok = True
    for name in STATE_ORDER:
        reference = float(exact["states"][name]["p"])
        observed = counts[name] / ADJUDICATION_DRAWS
        sigma = math.sqrt(reference * (1 - reference) / ADJUDICATION_DRAWS)
        within = abs(observed - reference) <= 3 * sigma + 1e-12
        ok = ok and within
        block["states"][name] = {"count": counts[name], "p": observed,
                                 "exact": reference,
                                 "z": (observed - reference) / sigma if sigma else 0.0,
                                 "within_3sigma": within}
    block["all_within_3sigma"] = ok
    return block


def evaluate(write: bool) -> dict:
    started = time.time()
    digest = verify_plan_digest()
    data = build_arms()
    global ANCHOR_KEYS
    ANCHOR_KEYS = data["anchor_keys"]
    plan_payload = load_plan()
    if plan_payload["protocol"]["sha256"] != sha256_file(PROTOCOL):
        raise SystemExit("protocol changed after the plan was frozen")
    if plan_payload["code"]["arms"]["sha256"] != sha256_file(pathlib.Path(__file__).resolve()):
        raise SystemExit("driver changed after the plan was frozen")

    manifests = {}
    for arm in ARMS:
        spec = data["arms"][arm]
        total = lab.count(tuple(len(u) for u in spec["units"]), TARGET, spec["excluded"])
        if str(total) != plan_payload["arms"][arm]["count"]:
            raise SystemExit(f"{arm}: count changed since the plan was frozen")
        manifests[arm] = read_manifest(arm, spec, data, total)

    normals, defects = load_scores(data)
    normal_sorted = sorted(normals.values())
    defect_sorted = sorted(defects.values())

    per_arm = {}
    row_records = []
    for arm in ARMS:
        results = []
        for row in manifests[arm]:
            cal_values = [normals[k] for k in row["cal_keys"]]
            eval_values = sorted(normals[k] for k in row["eval_keys"])
            rec = evaluate_row(cal_values, eval_values, defect_sorted)
            rec["repeat_id"] = row["repeat_id"]
            rec["eval_keys"] = row["eval_keys"]
            results.append(rec)
            row_records.append([
                arm, row["repeat_id"], rec["state"],
                rec["rules"]["MAX"]["fp"], rec["rules"]["MAX"]["tp"],
                rec["rules"]["MID12"]["fp"], rec["rules"]["MID12"]["tp"],
                rec["rules"]["Q95"]["fp"], rec["rules"]["Q95"]["tp"],
                rec["rules"]["Q90"]["fp"], rec["rules"]["Q90"]["tp"],
                rec["c_star_tp"] if rec["c_star_tp"] is not None else "",
                rec["u_tp"], repr(rec["slack"]),
            ])
        per_arm[arm] = summarise(results)

    # I0 must reproduce the stage 7 exact enumeration within 3 sigma. A failure
    # is recorded and adjudicated by an independent 10x replication (protocol v2
    # section 7.4); it no longer aborts the run.
    exact = read_json(EXACT)
    i0_check = {}
    for name in STATE_ORDER:
        reference = float(exact["states"][name]["p"])
        observed = per_arm["I0"]["states"][name]["p"]
        sigma = math.sqrt(reference * (1 - reference) / DRAWS)
        i0_check[name] = {
            "exact": reference, "observed": observed, "sigma": sigma,
            "z": ((observed - reference) / sigma) if sigma else 0.0,
            "within_3sigma": abs(observed - reference) <= 3 * sigma + 1e-12,
        }
    outside = [name for name in STATE_ORDER if not i0_check[name]["within_3sigma"]]
    adjudication = None
    if outside:
        adjudication = adjudicate_i0(normals, defect_sorted, exact)
        if not adjudication["all_within_3sigma"]:
            raise SystemExit("I0 gate failed and the independent replication also deviates")
    gate = {
        "rule": "per-state |z| <= 3 against the stage 7 exact enumeration",
        "status": "passed" if not outside else "deviation_adjudicated",
        "states_outside_3sigma": outside,
        "adjudication": adjudication,
    }

    payload = {
        "status": "STAGE8_ARMS_EVALUATION",
        "plan_digest": {"path": (ACC / "plan-digest.json").relative_to(ROOT).as_posix(),
                        "sha256": sha256_file(ACC / "plan-digest.json")},
        "scores": {
            "calibration": {"path": CAL_CSV.relative_to(ROOT).as_posix(),
                            "sha256": sha256_file(CAL_CSV)},
            "evaluation": {"path": EVAL_CSV.relative_to(ROOT).as_posix(),
                           "sha256": sha256_file(EVAL_CSV)},
            "normals": len(normals), "defects": len(defects),
        },
        "protocol": {"path": PROTOCOL.relative_to(ROOT).as_posix(),
                     "sha256": sha256_file(PROTOCOL)},
        "decision": "score > threshold; MAX=x61, Q99=rank61, Q95=x58, Q90=x55, "
                    "MID12=(x60+x61)/2.0",        "arms": per_arm,
        "i0_exact_check": i0_check,
        "i0_gate": gate,
        "isolation": {
            "order": "plan manifest frozen and digested before any score file was opened",
            "plan_digest_verified": True,
            "manifest_rows_verified": {arm: len(manifests[arm]) for arm in ARMS},
            "score_paths_opened_in_plan": plan_payload["isolation"]["score_paths_opened"],
        },
        "elapsed_seconds": round(time.time() - started, 3),
    }

    if write:
        ACC.mkdir(parents=True, exist_ok=True)
        with (ACC / "eval-rows.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh, lineterminator="\n")
            writer.writerow(["arm", "repeat_id", "state", "max_fp", "max_tp",
                             "mid_fp", "mid_tp", "q95_fp", "q95_tp", "q90_fp", "q90_tp",
                             "c_star_tp", "u_tp", "slack"])
            writer.writerows(row_records)
        payload["artifacts"] = {
            "eval_rows": {"path": (ACC / "eval-rows.csv").relative_to(ROOT).as_posix(),
                          "rows": len(row_records),
                          "bytes": (ACC / "eval-rows.csv").stat().st_size,
                          "sha256": sha256_file(ACC / "eval-rows.csv")}}
        write_json(ACC / "eval.json", payload)
    return payload


# ---------------------------------------------------------------- selftest

def selftest() -> int:
    checks = []

    def check(name, condition, detail=None):
        checks.append({"check": name, "pass": bool(condition), "detail": detail})

    data = build_arms()
    anchors = expected_counts(data)
    check("universe_93", len(data["universe"]) == 93)
    check("eligible_75", len(data["eligible"]) == 75)
    check("anchor_18", len(data["anchor_keys"]) == 18)

    counts = {}
    for arm in ARMS:
        spec = data["arms"][arm]
        sizes = tuple(len(u) for u in spec["units"])
        counts[arm] = lab.count(sizes, TARGET, spec["excluded"])
        check(f"{arm}_count_anchor", counts[arm] == anchors[arm],
              {"got": str(counts[arm]), "want": str(anchors[arm])})
        probs = lab.inclusion_probabilities(sizes, TARGET, spec["excluded"])
        check(f"{arm}_weighted_inclusion",
              sum(s * p for s, p in zip(sizes, probs)) == TARGET)

    g0_sizes = tuple(len(u) for u in data["arms"]["G0"]["units"])
    anchor_index = data["arms"]["G0"]["units"].index(data["anchor"]["members"])
    check("G1_equals_G0_without_anchor",
          lab.count(g0_sizes, TARGET, (anchor_index,)) == counts["G1"])
    check("I0_is_C_93_32", counts["I0"] == math.comb(93, TARGET))
    check("I1_is_C_75_32", counts["I1"] == math.comb(75, TARGET))
    check("G0_minus_G1_equals_anchor_allocations",
          counts["G0"] - counts["G1"] == int(read_json(DECISION)["grouped_allocations"])
          - int(read_json(DECISION)["anchored_allocations"]))

    probs_i0 = lab.inclusion_probabilities(tuple([1] * 93), TARGET)
    check("I0_each_prob_32_over_93", all(p == Fraction(TARGET, 93) for p in probs_i0))
    probs_i1 = lab.inclusion_probabilities(tuple([1] * 75), TARGET)
    check("I1_each_prob_32_over_75", all(p == Fraction(TARGET, 75) for p in probs_i1))

    seeds = {arm: seed_of(arm) for arm in ARMS}
    check("seeds_distinct", len(set(seeds.values())) == 4, seeds)
    check("seed_formula", seeds["I0"] == int.from_bytes(
        hashlib.sha256(b"stage8-grouped-v1|20261106|I0").digest(), "big"))

    check("rank_zero_is_lexicographic_first",
          lab.decode((1, 1, 1), 1, 0) == (2,), lab.decode((1, 1, 1), 1, 0))
    check("rank_last_is_lexicographic_last",
          lab.decode((1, 1, 1), 1, 2) == (0,))

    check("q99_rank_is_61", rank_of(99, 100, 61) == 61)
    check("q95_rank_is_58", rank_of(95, 100, 61) == 58)
    check("q90_rank_is_55", rank_of(90, 100, 61) == 55)

    thresholds, degenerate = thresholds_from([0.1 * i for i in range(61)])
    check("q99_identical_to_max", thresholds["Q99"].hex() == thresholds["MAX"].hex())
    check("mid12_between", thresholds["MID12"] <= thresholds["MAX"])

    check("digest_round_trip", sha256_text("a\nb") == hashlib.sha256(b"a\nb").hexdigest())
    check("row_digest_order_sensitive", sha256_text("a\nb") != sha256_text("b\na"))

    failed = [c for c in checks if not c["pass"]]
    payload = {"status": "STAGE8_ARMS_SELFTEST", "checks": checks,
               "n_checks": len(checks), "n_failed": len(failed), "passed": not failed}
    write_json(ACC / "selftest.json", payload)
    for item in checks:
        print(("OK   " if item["pass"] else "FAIL ") + item["check"])
    print(f"selftest: {len(checks)} checks, {len(failed)} failed")
    return 0 if not failed else 1


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Stage 8 four-arm driver")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("selftest")
    plan_parser = sub.add_parser("plan")
    plan_parser.add_argument("--write", action="store_true")
    sub.add_parser("eval").add_argument("--write", action="store_true")
    args = parser.parse_args(argv)

    if args.cmd == "selftest":
        return selftest()
    if args.cmd == "plan":
        payload = plan(args.write)
        print(json.dumps({
            "counts": {arm: payload["arms"][arm]["count"] for arm in ARMS},
            "rows": {arm: len(payload["arms"][arm]["units"]) for arm in ARMS},
            "duplicates": {arm: payload["arms"][arm]["duplicate_splits"] for arm in ARMS},
            "anchor_p": payload["inclusion_notes"]["G0_anchor_group"]["value"],
            "scores_read": payload["isolation"]["scores_read"],
            "written": args.write,
            "elapsed": payload["elapsed_seconds"],
        }, ensure_ascii=False, indent=1))
        return 0
    payload = evaluate(args.write)
    for arm in ARMS:
        block = payload["arms"][arm]["states"]
        print(arm, {k: round(v["p"] * 100, 4) for k, v in block.items()})
    print(json.dumps({"gate": {k: v for k, v in payload["i0_gate"].items()
                               if k != "adjudication"}}, ensure_ascii=False))
    if payload["i0_gate"]["adjudication"]:
        print(json.dumps({"adjudication": {
            "draws": payload["i0_gate"]["adjudication"]["draws"],
            "z": {k: round(v["z"], 3) for k, v in
                  payload["i0_gate"]["adjudication"]["states"].items()}}}, ensure_ascii=False))
    print("written:", args.write, "elapsed:", payload["elapsed_seconds"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
