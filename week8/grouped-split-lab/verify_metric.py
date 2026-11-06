"""Fixed acceptance harness for the grouped split feasibility lab.

24 fixed top-level cases. A passing case contributes 0, a failing case 1; the
sum is ``failed_cases``. A case with several internal assertions still counts
once.

Run from the repository root:

    E:/yingyong/an/envs/iad-week1/python.exe -B verify_metric.py

Behaviour
---------
* Every case runs; a failing assertion, a missing interface, or any exception
  raised by the implementation marks that case failed.
* The final non-empty stdout line is JSON, e.g.
  ``{"failed_cases": 3, "total_cases": 24}``.
* Exit code 0 whenever the measurement completes, even when cases fail.
* Exit code 2 when the fixed input cannot be loaded or the harness itself
  breaks: that is an infrastructure error, never a fabricated metric.
* Nothing is written to disk, so Git-visible files are unchanged.
"""

from __future__ import annotations

import json
import math
import pathlib
import random
import sys
import traceback

REPO = pathlib.Path(__file__).resolve().parent
FIXTURE = REPO / "fixtures" / "case24-cases.json"
TOTAL_CASES = 24
SHUFFLE_SEED = 20261106

sys.path.insert(0, str(REPO))

IMPORT_ERROR = ""
try:
    from src.grouping import group_components
    from src.counting import count_allocations
except Exception:  # pragma: no cover - reported as case failure, not a crash
    IMPORT_ERROR = traceback.format_exc()
    group_components = None
    count_allocations = None


# ---------------------------------------------------------------- helpers


def need(fn, label):
    if fn is None:
        raise AssertionError(f"interface {label} could not be imported")
    return fn


def rejects(fn, args, label=""):
    """The call must raise ValueError (or a subclass) explicitly."""
    fn = need(fn, label or "callable")
    try:
        out = fn(*args)
    except ValueError:
        return
    except NotImplementedError:
        raise AssertionError("not implemented")
    raise AssertionError(f"expected explicit rejection, got {out!r}")


def expect_equal(got, want, label):
    if got != want:
        raise AssertionError(f"{label}: got {got!r}, want {want!r}")


def grouped(keys, edges):
    fn = need(group_components, "group_components")
    out = fn(list(keys), [tuple(e) for e in edges])
    return out


# ------------------------------------------------------------------ cases


def case01_single_node():
    expect_equal(grouped(["only"], []), [["only"]], "single node")


def case02_duplicate_key():
    rejects(group_components, (["a", "b", "a"], []), "duplicate key")
    rejects(group_components, (["a", "a"], [("a", "a")]), "duplicate key with edge")


def case03_unknown_endpoint():
    rejects(group_components, (["a", "b"], [("a", "z")]), "unknown endpoint")
    rejects(group_components, (["a"], [("q", "a")]), "unknown endpoint first")


def case04_self_loop():
    expect_equal(grouped(["a", "b"], [("a", "a")]), [["a"], ["b"]], "self loop")
    expect_equal(grouped(["a", "b"], [("a", "a"), ("b", "b")]),
                 [["a"], ["b"]], "two self loops")


def case05_reverse_and_duplicate_edges():
    base = grouped(["a", "b", "c"], [("a", "b")])
    expect_equal(grouped(["a", "b", "c"], [("b", "a")]), base, "reversed edge")
    expect_equal(grouped(["a", "b", "c"], [("a", "b"), ("a", "b")]), base,
                 "duplicated edge")
    expect_equal(grouped(["a", "b", "c"], [("b", "a"), ("a", "b")]), base,
                 "both directions")


def case06_isolated_nodes():
    expect_equal(grouped(["d", "b", "a"], []), [["a"], ["b"], ["d"]], "isolated")


def case07_chain_transitive():
    expect_equal(grouped(["a", "b", "c", "d", "e"], [("a", "b"), ("b", "c"), ("c", "d")]),
                 [["a", "b", "c", "d"], ["e"]], "chain")


def case08_input_order_invariance():
    keys = ["k1", "k2", "k3", "k4", "k5", "k6"]
    edges = [("k1", "k2"), ("k2", "k3"), ("k5", "k4")]
    base = grouped(keys, edges)
    rng = random.Random(SHUFFLE_SEED)
    for _ in range(8):
        shuffled_keys = keys[:]
        shuffled_edges = edges[:]
        rng.shuffle(shuffled_keys)
        rng.shuffle(shuffled_edges)
        flipped = [(b, a) if rng.random() < 0.5 else (a, b) for a, b in shuffled_edges]
        expect_equal(grouped(shuffled_keys, flipped), base, "order invariance")


def case09_structure_invariants():
    keys = ["z", "A", "b", "a0", "0", "m"]
    edges = [("z", "A"), ("a0", "b"), ("m", "z")]
    out = grouped(keys, edges)
    flat = [k for group in out for k in group]
    expect_equal(sorted(flat), sorted(keys), "each key exactly once")
    expect_equal(len(flat), len(set(flat)), "no duplicate key")
    for group in out:
        expect_equal(group, sorted(group), "members ascending")
        if not group:
            raise AssertionError("empty group returned")
    expected_groups = sorted((sorted(g) for g in out), key=lambda g: g[0])
    expect_equal(out, expected_groups, "groups sorted by smallest member")


def case10_non_positive_size():
    rejects(count_allocations, ([3, 0], 3), "zero size")
    rejects(count_allocations, ([-1, 2], 2), "negative size")
    rejects(count_allocations, ([-3], 0), "negative size only")


def case11_non_integer_size():
    rejects(count_allocations, ([2.0, 1], 3), "float size")
    rejects(count_allocations, ([True, 1], 2), "bool size")
    rejects(count_allocations, (["2"], 2), "string size")


def case12_negative_target():
    rejects(count_allocations, ([2, 2], -1), "negative target")
    rejects(count_allocations, ([], -1), "negative target empty")


def case13_target_above_total():
    rejects(count_allocations, ([2, 2], 5), "target above total")
    rejects(count_allocations, ([1], 2), "target above total small")


def case14_non_integer_target():
    rejects(count_allocations, ([2, 2], True), "bool target")
    rejects(count_allocations, ([2, 2], 2.0), "float target")


def case15_empty_and_zero():
    expect_equal(count_allocations([], 0), 1, "empty groups target 0")


def case16_non_empty_target_zero():
    expect_equal(count_allocations([3, 4], 0), 1, "target 0 with groups")
    expect_equal(count_allocations([1, 2, 5], 0), 1, "target 0 with groups 2")


def case17_target_equals_total():
    expect_equal(count_allocations([3, 4], 7), 1, "target equals total")
    expect_equal(count_allocations([1], 1), 1, "single group full")


def case18_six_singletons():
    expect_equal(count_allocations([1] * 6, 2), 15, "C(6,2)")


def case19_real_scale_feasible():
    expect_equal(count_allocations([32, 61], 32), 1, "32/61 target 32")


def case20_real_scale_infeasible():
    expect_equal(count_allocations([33, 60], 32), 0, "33/60 target 32")


def case21_equal_sizes_distinct():
    expect_equal(count_allocations([32, 32, 29], 32), 2, "two 32-groups")
    expect_equal(count_allocations([5, 5, 5], 10), 3, "three equal groups")


def case22_three_pairs():
    expect_equal(count_allocations([2, 2, 2], 2), 3, "three pairs")


def case23_binomial_exact():
    expect_equal(count_allocations([1] * 93, 32), math.comb(93, 32), "C(93,32)")


def make_case24(fixture):
    def case24_fixture_enumeration():
        if fixture is None:
            raise AssertionError("fixture not loaded")
        for case in fixture["cases"]:
            sizes = case["sizes"]
            target = case["target"]
            reference = sum(
                1
                for mask in range(1 << len(sizes))
                if sum(s for i, s in enumerate(sizes) if mask >> i & 1) == target
            )
            got = count_allocations(list(sizes), target)
            if got != reference:
                raise AssertionError(
                    f"instance {case['index']} sizes={sizes} target={target}: "
                    f"got {got!r}, want {reference}"
                )
    return case24_fixture_enumeration


# -------------------------------------------------------------- harness


def load_fixture():
    """Load and validate the frozen case-24 inputs. Raises on any problem."""
    with FIXTURE.open(encoding="utf-8") as fh:
        data = json.load(fh)
    cases = data["cases"]
    if len(cases) != 40:
        raise ValueError(f"expected 40 instances, got {len(cases)}")
    if data.get("n_instances") != 40:
        raise ValueError("fixture n_instances mismatch")
    for case in cases:
        sizes = case["sizes"]
        target = case["target"]
        if not 1 <= len(sizes) <= 12:
            raise ValueError(f"instance {case['index']}: bad group count {len(sizes)}")
        for size in sizes:
            if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= 5:
                raise ValueError(f"instance {case['index']}: bad size {size!r}")
        if isinstance(target, bool) or not isinstance(target, int) or not 0 <= target <= sum(sizes):
            raise ValueError(f"instance {case['index']}: bad target {target!r}")
    return data


def build_cases(fixture):
    pairs = [
        (1, "single_node", case01_single_node),
        (2, "duplicate_key", case02_duplicate_key),
        (3, "unknown_endpoint", case03_unknown_endpoint),
        (4, "self_loop", case04_self_loop),
        (5, "reverse_and_duplicate_edges", case05_reverse_and_duplicate_edges),
        (6, "isolated_nodes", case06_isolated_nodes),
        (7, "chain_transitive", case07_chain_transitive),
        (8, "input_order_invariance", case08_input_order_invariance),
        (9, "structure_invariants", case09_structure_invariants),
        (10, "non_positive_size", case10_non_positive_size),
        (11, "non_integer_size", case11_non_integer_size),
        (12, "negative_target", case12_negative_target),
        (13, "target_above_total", case13_target_above_total),
        (14, "non_integer_target", case14_non_integer_target),
        (15, "empty_and_zero", case15_empty_and_zero),
        (16, "non_empty_target_zero", case16_non_empty_target_zero),
        (17, "target_equals_total", case17_target_equals_total),
        (18, "six_singletons", case18_six_singletons),
        (19, "real_scale_feasible", case19_real_scale_feasible),
        (20, "real_scale_infeasible", case20_real_scale_infeasible),
        (21, "equal_sizes_distinct", case21_equal_sizes_distinct),
        (22, "three_pairs", case22_three_pairs),
        (23, "binomial_exact", case23_binomial_exact),
        (24, "fixture_enumeration", make_case24(fixture)),
    ]
    if len(pairs) != TOTAL_CASES:
        raise AssertionError(f"case table has {len(pairs)} entries, expected {TOTAL_CASES}")
    if [p[0] for p in pairs] != list(range(1, TOTAL_CASES + 1)):
        raise AssertionError("case ids are not 1..24 in order")
    return pairs


def main() -> int:
    try:
        if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
            sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    except Exception:
        pass

    try:
        fixture = load_fixture()
        cases = build_cases(fixture)
    except Exception as exc:
        print(f"harness error: cannot build fixed input: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        if IMPORT_ERROR:
            print(IMPORT_ERROR, file=sys.stderr)
        return 2

    failed = 0
    for cid, name, fn in cases:
        try:
            fn()
            print(f"case {cid:02d} PASS {name}")
        except AssertionError as exc:
            failed += 1
            print(f"case {cid:02d} FAIL {name}: {exc}")
        except Exception as exc:
            failed += 1
            print(f"case {cid:02d} FAIL {name}: {type(exc).__name__}: {exc}")

    print(json.dumps({"failed_cases": failed, "total_cases": TOTAL_CASES}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
