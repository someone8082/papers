"""Generate the frozen sampler fixture, once, from a fixed seed.

The fixture holds inputs and external anchors only. Counts and marginals that a
harness can recompute on the spot are deliberately NOT stored: verify_sampler.py
recomputes them by exhaustive enumeration so the reference never depends on a
number produced by the implementation under test.

The three large anchors cannot be brute forced. They are copied from the stage 8
decision record (independent sparse-polynomial recomputation, scores_read=false)
and re-derived here with a memoised recursion that is written differently from
the suffix table the implementation is expected to use. A disagreement stops
generation.

Run once from the repository root:
    E:/yingyong/an/envs/iad-week1/python.exe -B sampler_tools/gen_sampler_fixtures.py
"""

import csv
import hashlib
import json
import pathlib
import random
from functools import lru_cache

SEED = 20261106
N_INSTANCES = 40
MAX_GROUPS = 12
MIN_SIZE = 1
MAX_SIZE = 6
MAX_EXCLUDED = 2
TARGET = 32
ARM_SEED_PREFIX = "stage8-grouped-v1|20261106|"

REPO = pathlib.Path(__file__).resolve().parents[1]
PAPERS = REPO.parents[1]
GROUPS_CSV = PAPERS / "week8/acceptance/stage8-grouping-2026-11-06/groups-dh4.csv"
DECISION = PAPERS / "week8/acceptance/stage8-grouping-2026-11-06/decision-check.json"
OUT = REPO / "sampler_fixtures" / "sampler-cases.json"


def recount(sizes, target, excluded=()):
    """Memoised recursion over (position, remaining): a different route."""
    skip = set(excluded)

    @lru_cache(maxsize=None)
    def walk(i, remaining):
        if i == len(sizes):
            return 1 if remaining == 0 else 0
        total = walk(i + 1, remaining)
        if i not in skip and sizes[i] <= remaining:
            total += walk(i + 1, remaining - sizes[i])
        return total

    return walk(0, target)


def main() -> int:
    decision = json.loads(DECISION.read_text(encoding="utf-8"))
    rows = list(csv.DictReader(GROUPS_CSV.open(encoding="utf-8", newline="")))
    sizes = [int(row["size"]) for row in rows]
    forced = [i for i, row in enumerate(rows) if row["eval_eligible"] != "1"]

    if len(sizes) != 66 or sum(sizes) != 93:
        raise SystemExit(f"unexpected group layout: n={len(sizes)} total={sum(sizes)}")
    if forced != [3] or sizes[3] != 18:
        raise SystemExit(f"unexpected forced groups: {forced}")

    grouped = recount(sizes, TARGET)
    anchored = recount(sizes, TARGET, forced)
    per_image = recount([1] * 93, TARGET)

    for label, mine, recorded in (
        ("grouped", grouped, decision["grouped_allocations"]),
        ("anchored", anchored, decision["anchored_allocations"]),
        ("images", per_image, decision["unrestricted_allocations"]),
    ):
        if mine != recorded:
            raise SystemExit(f"{label} mismatch: recount={mine} record={recorded}")

    rng = random.Random(SEED)
    instances = []
    for index in range(N_INSTANCES):
        n = rng.randint(1, MAX_GROUPS)
        shape = [rng.randint(MIN_SIZE, MAX_SIZE) for _ in range(n)]
        target = rng.randint(0, sum(shape))
        k = rng.randint(0, min(MAX_EXCLUDED, n - 1)) if n > 1 else 0
        excluded = sorted(rng.sample(range(n), k))
        instances.append({"index": index, "sizes": shape, "target": target,
                          "excluded": excluded})

    arm_seeds = {}
    for arm in ("I0", "I1", "G0", "G1"):
        digest = hashlib.sha256((ARM_SEED_PREFIX + arm).encode("utf-8")).digest()
        arm_seeds[arm] = str(int.from_bytes(digest, "big"))

    payload = {
        "kind": "stage8-sampler-fixture",
        "case": 24,
        "seed": SEED,
        "n_instances": N_INSTANCES,
        "bounds": {"max_groups": MAX_GROUPS, "group_size_min": MIN_SIZE,
                   "group_size_max": MAX_SIZE, "max_excluded": MAX_EXCLUDED},
        "generator": "sampler_tools/gen_sampler_fixtures.py",
        "note": ("inputs and external anchors only; counts and marginals are "
                 "recomputed by verify_sampler.py"),
        "rank_order": "lexicographic on (b_0..b_{n-1}) with 0<1, b_0 most significant",
        "instances": instances,
        "real": {
            "group_sizes": sizes,
            "excluded": forced,
            "target": TARGET,
            "total_images": sum(sizes),
            "eligible_images": sum(s for i, s in enumerate(sizes) if i not in forced),
            "anchors": {
                "grouped_count": grouped,
                "anchored_count": anchored,
                "per_image_count": per_image,
                "source": "week8/acceptance/stage8-grouping-2026-11-06/decision-check.json",
            },
        },
        "arm_seeds": arm_seeds,
        "arm_seed_rule": "int.from_bytes(SHA256(UTF8('" + ARM_SEED_PREFIX + "' + arm)), 'big')",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write("\n")

    with_excluded = sum(1 for c in instances if c["excluded"])
    print(f"wrote {OUT} instances={len(instances)} with_excluded={with_excluded}")
    print(f"grouped={grouped} anchored={anchored} per_image={per_image}")
    print(f"arm_seeds={json.dumps(arm_seeds)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
