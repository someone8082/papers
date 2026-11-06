"""Generate the frozen case-24 fixture, once, from a fixed seed.

The fixture is data, not code: it holds only the inputs. Expected counts are
never stored here; verify_metric.py recomputes them by exhaustive subset
enumeration so the reference never depends on a recorded number.

Run once from the repository root:
    E:/yingyong/an/envs/iad-week1/python.exe -B tools/gen_fixtures.py
"""

import json
import pathlib
import random

SEED = 20261106
N_INSTANCES = 40
MAX_GROUPS = 12
MIN_SIZE = 1
MAX_SIZE = 5

REPO = pathlib.Path(__file__).resolve().parents[1]
OUT = REPO / "fixtures" / "case24-cases.json"


def main() -> int:
    rng = random.Random(SEED)
    cases = []
    for index in range(N_INSTANCES):
        n = rng.randint(1, MAX_GROUPS)
        sizes = [rng.randint(MIN_SIZE, MAX_SIZE) for _ in range(n)]
        # Targets are drawn uniformly over the reachable range on purpose: the
        # fixture must not be curated toward non-zero or zero answers.
        target = rng.randint(0, sum(sizes))
        cases.append({"index": index, "sizes": sizes, "target": target})

    payload = {
        "kind": "stage8-grouped-split-fixture",
        "case": 24,
        "seed": SEED,
        "n_instances": N_INSTANCES,
        "bounds": {"max_groups": MAX_GROUPS, "group_size_min": MIN_SIZE,
                   "group_size_max": MAX_SIZE},
        "generator": "tools/gen_fixtures.py",
        "note": "inputs only; expected counts are recomputed by verify_metric.py",
        "cases": cases,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write("\n")

    zero = 0
    for case in cases:
        sizes, target = case["sizes"], case["target"]
        hits = sum(1 for mask in range(1 << len(sizes))
                   if sum(s for i, s in enumerate(sizes) if mask >> i & 1) == target)
        zero += hits == 0
    print(f"wrote {OUT} instances={len(cases)} zero_count_instances={zero}")
    print(f"groups min/max={min(len(c['sizes']) for c in cases)}/"
          f"{max(len(c['sizes']) for c in cases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
