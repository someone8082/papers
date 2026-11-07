"""Fixed acceptance harness for the whole-group sampler.

24 fixed top-level cases. A passing case contributes 0, a failing case 1; the
sum is ``failed_cases``. A case with several internal assertions still counts
once.

Run from the repository root:

    E:/yingyong/an/envs/iad-week1/python.exe -B verify_sampler.py

Behaviour matches verify_metric.py: the final non-empty stdout line is JSON,
exit 0 whenever the measurement completes, exit 2 on an infrastructure error,
and nothing is written to disk.

Reference values come from two places only. Small-instance counts and marginals
are recomputed here by exhaustive subset enumeration, so they never depend on a
number the implementation produced. The three large anchors for the full 66-group
space are stored in the fixture and trace to the stage 8 decision record.
"""

from __future__ import annotations

import json
import pathlib
import random
import subprocess
import sys
import traceback
from fractions import Fraction

REPO = pathlib.Path(__file__).resolve().parent
FIXTURE = REPO / "sampler_fixtures" / "sampler-cases.json"
TOTAL_CASES = 24
TARGET = 32

sys.path.insert(0, str(REPO))

IMPORT_ERROR = ""
try:
    from src.sampler import count, decode, inclusion_probabilities, sample
except Exception:  # pragma: no cover - reported as case failures, not a crash
    IMPORT_ERROR = traceback.format_exc()
    count = decode = inclusion_probabilities = sample = None


# ---------------------------------------------------------------- helpers


def need(fn, label):
    if fn is None:
        raise AssertionError(f"interface {label} could not be imported")
    return fn


def rejects(fn, args, kwargs=None, label=""):
    """The call must raise ValueError (or a subclass) explicitly."""
    fn = need(fn, label or "callable")
    kwargs = kwargs or {}
    try:
        out = fn(*args, **kwargs)
    except ValueError:
        return
    except NotImplementedError:
        raise AssertionError("not implemented")
    raise AssertionError(f"expected explicit rejection, got {out!r}")


def expect_equal(got, want, label):
    if got != want:
        raise AssertionError(f"{label}: got {got!r}, want {want!r}")


def brute_masks(sizes, target, excluded=()):
    """Every legal subset, as bit masks with bit i meaning group i is chosen."""
    skip = set(excluded)
    n = len(sizes)
    out = []
    for mask in range(1 << n):
        if any(mask >> i & 1 for i in skip):
            continue
        if sum(sizes[i] for i in range(n) if mask >> i & 1) == target:
            out.append(mask)
    return out


def indicator_key(mask, n):
    """Lexicographic key on (b_0, .., b_{n-1}) with 0 < 1."""
    return tuple((mask >> i) & 1 for i in range(n))


def subset(mask, n):
    return tuple(i for i in range(n) if mask >> i & 1)


def pick_instances(fixture, low, high, wanted):
    """Fixture instances whose brute-force count sits in [low, high]."""
    chosen = []
    for case in fixture["instances"]:
        hits = len(brute_masks(case["sizes"], case["target"], case["excluded"]))
        if low <= hits <= high:
            chosen.append((case, hits))
        if len(chosen) == wanted:
            break
    if len(chosen) < wanted:
        raise AssertionError(f"fixture has fewer than {wanted} instances in "
                             f"[{low}, {high}]")
    return chosen


def real_space(fixture):
    real = fixture["real"]
    return real["group_sizes"], real["target"], tuple(real["excluded"])


class Recorder:
    """Stand-in for random.Random that records randrange arguments."""

    def __init__(self, value):
        self.value = value
        self.calls = []

    def randrange(self, n):
        self.calls.append(n)
        return self.value


# ------------------------------------------------------------------ cases


def case01_non_positive_size():
    rejects(count, ([0], 0), label="count")
    rejects(count, ([-2, 3], 3), label="count")
    rejects(decode, ([0], 0, 0), label="decode")


def case02_non_integer_size():
    rejects(count, ([2.0, 1], 3), label="count")
    rejects(count, ([True, 1], 2), label="count")
    rejects(count, (["2"], 2), label="count")


def case03_negative_target():
    rejects(count, ([2, 2], -1), label="count")
    rejects(count, ([], -1), label="count")
    rejects(decode, ([2, 2], -1, 0), label="decode")


def case04_target_above_total():
    rejects(count, ([2, 2], 5), label="count")
    rejects(count, ([1], 2), label="count")


def case05_non_integer_target():
    rejects(count, ([2, 2], True), label="count")
    rejects(count, ([2, 2], 2.0), label="count")
    rejects(decode, ([2, 2], 2.0, 0), label="decode")


def case06_excluded_validation():
    rejects(count, ([2, 2], 2), {"excluded": [2]}, label="out of range")
    rejects(count, ([2, 2], 2), {"excluded": [-1]}, label="negative")
    rejects(count, ([2, 2], 2), {"excluded": [0, 0]}, label="duplicate")
    rejects(count, ([2, 2], 2), {"excluded": [1.0]}, label="float index")
    rejects(count, ([2, 2], 2), {"excluded": [True]}, label="bool index")


def case07_edges_of_target():
    expect_equal(need(count, "count")([], 0), 1, "empty target 0")
    expect_equal(count([3, 4], 0), 1, "target 0 with groups")
    expect_equal(count([3, 4], 7), 1, "target equals total")
    expect_equal(count([1], 1), 1, "single group full")


def case08_equal_sizes_distinct():
    expect_equal(count([2, 2, 2], 2), 3, "three pairs")
    expect_equal(count([32, 32, 29], 32), 2, "two 32-groups")
    expect_equal(count([5, 5, 5], 5), 3, "three equal groups target 5")


def case09_infeasible_and_feasible():
    expect_equal(count([33, 60], 32), 0, "33/60 infeasible")
    expect_equal(count([32, 61], 32), 1, "32/61 feasible")


def make_case10(fixture):
    def case10_fixture_enumeration():
        for case in fixture["instances"]:
            sizes = case["sizes"]
            target = case["target"]
            excluded = case["excluded"]
            want = len(brute_masks(sizes, target, excluded))
            got = count(sizes, target, excluded=excluded)
            if got != want:
                raise AssertionError(f"instance {case['index']} with excluded: "
                                     f"got {got!r}, want {want}")
            want_plain = len(brute_masks(sizes, target))
            got_plain = count(sizes, target)
            if got_plain != want_plain:
                raise AssertionError(f"instance {case['index']} plain: "
                                     f"got {got_plain!r}, want {want_plain}")
    return case10_fixture_enumeration


def make_case11(fixture):
    def case11_real_grouped():
        sizes, _, _ = real_space(fixture)
        want = fixture["real"]["anchors"]["grouped_count"]
        expect_equal(count(sizes, TARGET), want, "G0 grouped count")
        expect_equal(count(list(sizes) + [1], TARGET + 1) >= want, True,
                     "monotone sanity")
    return case11_real_grouped


def make_case12(fixture):
    def case12_real_anchored():
        sizes, target, excluded = real_space(fixture)
        anchors = fixture["real"]["anchors"]
        expect_equal(count(sizes, target, excluded=excluded),
                     anchors["anchored_count"], "G1 anchored count")
        expect_equal(count([1] * 93, TARGET), anchors["per_image_count"],
                     "I0 per-image count")
        if not count(sizes, target, excluded=excluded) < count(sizes, target):
            raise AssertionError("anchoring must exclude at least one allocation")
    return case12_real_anchored


def make_case13(fixture):
    def case13_bijection_small():
        for case, hits in pick_instances(fixture, 8, 512, 2):
            sizes, target, excluded = case["sizes"], case["target"], case["excluded"]
            seen = set()
            for rank in range(hits):
                got = decode(sizes, target, rank, excluded=excluded)
                if len(set(got)) != len(got):
                    raise AssertionError(f"rank {rank}: duplicate index in {got!r}")
                if sum(sizes[i] for i in got) != target:
                    raise AssertionError(f"rank {rank}: sum mismatch for {got!r}")
                if set(got) & set(excluded):
                    raise AssertionError(f"rank {rank}: excluded index in {got!r}")
                seen.add(tuple(got))
            if len(seen) != hits:
                raise AssertionError(f"instance {case['index']}: {len(seen)} distinct "
                                     f"outputs over {hits} ranks")
            rejects(decode, (sizes, target, hits), {"excluded": excluded},
                    label="decode one past the end")
    return case13_bijection_small


def make_case14(fixture):
    def case14_rank_order():
        case, hits = pick_instances(fixture, 8, 512, 1)[0]
        sizes, target, excluded = case["sizes"], case["target"], case["excluded"]
        n = len(sizes)
        masks = brute_masks(sizes, target, excluded)
        ordered = [subset(m, n) for m in sorted(masks, key=lambda m: indicator_key(m, n))]
        got = [decode(sizes, target, rank, excluded=excluded) for rank in range(hits)]
        expect_equal(got, ordered, f"instance {case['index']} rank order")
    return case14_rank_order


def make_case15(fixture):
    def case15_illegal_rank():
        case, hits = pick_instances(fixture, 8, 512, 1)[0]
        sizes, target, excluded = case["sizes"], case["target"], case["excluded"]
        rejects(decode, (sizes, target, hits), {"excluded": excluded}, label="rank==count")
        rejects(decode, (sizes, target, -1), {"excluded": excluded}, label="negative")
        rejects(decode, (sizes, target, 1.5), {"excluded": excluded}, label="float")
        rejects(decode, (sizes, target, True), {"excluded": excluded}, label="bool")
    return case15_illegal_rank


def make_case16(fixture):
    def case16_return_type():
        case, hits = pick_instances(fixture, 1, 64, 1)[0]
        sizes, target, excluded = case["sizes"], case["target"], case["excluded"]
        n = len(sizes)
        for rank in {0, hits // 2, hits - 1}:
            got = decode(sizes, target, rank, excluded=excluded)
            if not isinstance(got, tuple):
                raise AssertionError(f"rank {rank}: {type(got).__name__}, want tuple")
            if list(got) != sorted(got) or len(set(got)) != len(got):
                raise AssertionError(f"rank {rank}: not ascending/unique: {got!r}")
            if any(not isinstance(i, int) or isinstance(i, bool) for i in got):
                raise AssertionError(f"rank {rank}: non-integer index in {got!r}")
            if any(not 0 <= i < n for i in got):
                raise AssertionError(f"rank {rank}: index out of range: {got!r}")
    return case16_return_type


def make_case17(fixture):
    def case17_excluded_never_selected():
        anchored = [c for c in pick_instances(fixture, 1, 1024, 6) if c[0]["excluded"]]
        if not anchored:
            raise AssertionError("no fixture instance with excluded groups")
        for case, hits in anchored[:3]:
            sizes, target, excluded = case["sizes"], case["target"], case["excluded"]
            for rank in range(hits):
                got = decode(sizes, target, rank, excluded=excluded)
                if set(got) & set(excluded):
                    raise AssertionError(f"instance {case['index']} rank {rank}: "
                                         f"excluded group selected: {got!r}")
    return case17_excluded_never_selected


def make_case18(fixture):
    def case18_anchored_set_equality():
        anchored = [c for c in pick_instances(fixture, 4, 512, 8) if c[0]["excluded"]]
        if not anchored:
            raise AssertionError("no fixture instance with excluded groups")
        for case, hits in anchored[:2]:
            sizes, target, excluded = case["sizes"], case["target"], case["excluded"]
            want = {subset(m, len(sizes)) for m in brute_masks(sizes, target, excluded)}
            got = {tuple(decode(sizes, target, rank, excluded=excluded))
                   for rank in range(hits)}
            expect_equal(got, want, f"instance {case['index']} anchored set")
    return case18_anchored_set_equality


def make_case19(fixture):
    def case19_real_endpoints():
        sizes, target, excluded = real_space(fixture)
        total = count(sizes, target, excluded=excluded)
        first = decode(sizes, target, 0, excluded=excluded)
        last = decode(sizes, target, total - 1, excluded=excluded)
        for label, got in (("rank 0", first), ("rank count-1", last)):
            if sum(sizes[i] for i in got) != target:
                raise AssertionError(f"{label}: sum mismatch")
            if set(got) & set(excluded):
                raise AssertionError(f"{label}: excluded group selected")
            if list(got) != sorted(got):
                raise AssertionError(f"{label}: not ascending")
        if tuple(first) == tuple(last):
            raise AssertionError("real space produced a single allocation")
        rejects(decode, (sizes, target, total), {"excluded": excluded},
                label="rank==count at real scale")
    return case19_real_endpoints


def make_case20(fixture):
    def case20_sample_legality():
        case, hits = pick_instances(fixture, 3, 512, 1)[0]
        sizes, target, excluded = case["sizes"], case["target"], case["excluded"]
        rng = random.Random(424242)
        seen = set()
        for _ in range(200):
            got = sample(sizes, target, rng, excluded=excluded)
            if sum(sizes[i] for i in got) != target:
                raise AssertionError(f"illegal draw: {got!r}")
            if set(got) & set(excluded):
                raise AssertionError(f"excluded group drawn: {got!r}")
            if list(got) != sorted(got) or len(set(got)) != len(got):
                raise AssertionError(f"not ascending/unique: {got!r}")
            seen.add(tuple(got))
        if len(seen) < 2:
            raise AssertionError("200 draws produced a single distinct subset")
    return case20_sample_legality


def make_case21(fixture):
    def case21_rank_mechanism():
        case, hits = pick_instances(fixture, 8, 512, 1)[0]
        sizes, target, excluded = case["sizes"], case["target"], case["excluded"]
        total = count(sizes, target, excluded=excluded)
        for value in (0, total - 1, total // 2):
            rec = Recorder(value)
            got = sample(sizes, target, rec, excluded=excluded)
            expect_equal(rec.calls, [total], "randrange called once with the total")
            expect_equal(got, decode(sizes, target, value, excluded=excluded),
                         f"sample equals decode({value})")
    return case21_rank_mechanism


def make_case22(fixture):
    def case22_seed_semantics():
        sizes, target, excluded = real_space(fixture)
        one = [sample(sizes, target, random.Random(11), excluded=excluded)
               for _ in range(100)]
        again = [sample(sizes, target, random.Random(11), excluded=excluded)
                 for _ in range(100)]
        expect_equal(again, one, "same seed replay")
        other = [sample(sizes, target, random.Random(12), excluded=excluded)
                 for _ in range(100)]
        if other == one:
            raise AssertionError("different seeds produced identical 100-draw runs")
        seeds = fixture["arm_seeds"]
        for arm in ("I0", "I1", "G0", "G1"):
            digest = __import__("hashlib").sha256(
                ("stage8-grouped-v1|20261106|" + arm).encode("utf-8")).digest()
            want = str(int.from_bytes(digest, "big"))
            expect_equal(seeds.get(arm), want, f"arm seed {arm}")
    return case22_seed_semantics


AUDIT_SCRIPT = r'''
import json, sys
opened = []
def hook(event, args):
    if event == "open":
        try:
            opened.append(str(args[0]))
        except Exception:
            opened.append("<unprintable>")
sys.addaudithook(hook)
repo, sizes_json, excluded_json = sys.argv[1], sys.argv[2], sys.argv[3]
sizes = json.loads(sizes_json)
excluded = json.loads(excluded_json)
sys.path.insert(0, repo)
import random
from src.sampler import sample
rng = random.Random(20261106)
rows = [sample(sizes, 32, rng, excluded=excluded) for _ in range(50)]
print(json.dumps({"opened": len(opened), "paths": opened,
                  "rows": [[int(i) for i in r] for r in rows]}))
'''


def make_case23(fixture):
    def case23_real_accounting():
        sizes, target, excluded = real_space(fixture)
        total_images = fixture["real"]["total_images"]
        eligible = fixture["real"]["eligible_images"]
        forced_images = total_images - eligible
        rng = random.Random(20261106)
        for _ in range(500):
            got = sample(sizes, target, rng, excluded=excluded)
            eval_images = sum(sizes[i] for i in got)
            if eval_images != target:
                raise AssertionError(f"eval side {eval_images}, want {target}")
            if len(set(got)) != len(got):
                raise AssertionError("duplicate group in draw")
            if set(got) & set(excluded):
                raise AssertionError("forced calibration group selected")
            cal_images = total_images - eval_images
            if cal_images != total_images - target:
                raise AssertionError(f"calibration side {cal_images}")
            if eval_images + cal_images != total_images:
                raise AssertionError("sides do not cover the pool")
            if forced_images != 18:
                raise AssertionError(f"forced images {forced_images}, want 18")

        proc = subprocess.run(
            [sys.executable, "-B", "-c", AUDIT_SCRIPT, str(REPO),
             json.dumps(list(sizes)), json.dumps(list(excluded))],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            check=False,
        )
        if proc.returncode != 0:
            raise AssertionError(f"audited subprocess failed: {proc.stderr.strip()[:400]}")
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        if not lines:
            raise AssertionError("audited subprocess produced no output")
        report = json.loads(lines[-1])
        if report["opened"] < 1:
            raise AssertionError("audit hook recorded no open call: hook is not working")
        bad = [p for p in report["paths"]
               if "week6" in p.replace("\\", "/") or "week7" in p.replace("\\", "/")
               or p.endswith("scores.csv")]
        if bad:
            raise AssertionError(f"sampling opened score files: {bad[:3]}")
        if len(report["rows"]) != 50:
            raise AssertionError("audited subprocess returned a wrong row count")
    return case23_real_accounting


def make_case24(fixture):
    def case24_inclusion_probabilities():
        case, hits = pick_instances(fixture, 8, 512, 1)[0]
        sizes, target, excluded = case["sizes"], case["target"], case["excluded"]
        probs = inclusion_probabilities(sizes, target, excluded=excluded)
        if not isinstance(probs, tuple) or len(probs) != len(sizes):
            raise AssertionError(f"probabilities type/length: {type(probs).__name__}")
        masks = brute_masks(sizes, target, excluded)
        for i, p in enumerate(probs):
            if not isinstance(p, Fraction):
                raise AssertionError(f"p[{i}] is {type(p).__name__}, want Fraction")
            want = Fraction(sum(1 for m in masks if m >> i & 1), hits)
            if p != want:
                raise AssertionError(f"p[{i}]={p}, want {want}")
            if i in excluded and p != 0:
                raise AssertionError(f"p[{i}] must be 0 for an excluded group")
        weighted = sum(Fraction(sizes[i]) * probs[i] for i in range(len(sizes)))
        expect_equal(weighted, Fraction(target), "weighted sum equals target")

        rsizes, rtarget, rexcluded = real_space(fixture)
        rprobs = inclusion_probabilities(rsizes, rtarget, excluded=rexcluded)
        if len(rprobs) != len(rsizes):
            raise AssertionError("real probabilities length mismatch")
        rweighted = sum(Fraction(rsizes[i]) * rprobs[i] for i in range(len(rsizes)))
        expect_equal(rweighted, Fraction(rtarget), "real weighted sum")
        for i in rexcluded:
            if rprobs[i] != 0:
                raise AssertionError(f"real p[{i}] must be 0 for the anchored group")
        if not all(isinstance(p, Fraction) and 0 <= p <= 1 for p in rprobs):
            raise AssertionError("real probabilities escape [0, 1]")

        empty = inclusion_probabilities([33, 60], TARGET)
        if tuple(empty) != (Fraction(0), Fraction(0)):
            raise AssertionError(f"zero-allocation probabilities: got {empty!r}")
    return case24_inclusion_probabilities


# -------------------------------------------------------------- harness


def load_fixture():
    with FIXTURE.open(encoding="utf-8") as fh:
        data = json.load(fh)
    instances = data["instances"]
    if len(instances) != 40 or data.get("n_instances") != 40:
        raise ValueError("fixture instance count mismatch")
    for case in instances:
        sizes = case["sizes"]
        if not 1 <= len(sizes) <= 12:
            raise ValueError(f"instance {case['index']}: bad group count")
        for size in sizes:
            if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= 6:
                raise ValueError(f"instance {case['index']}: bad size {size!r}")
        target = case["target"]
        if isinstance(target, bool) or not isinstance(target, int) \
                or not 0 <= target <= sum(sizes):
            raise ValueError(f"instance {case['index']}: bad target {target!r}")
        excluded = case["excluded"]
        if len(set(excluded)) != len(excluded) or any(
                not 0 <= i < len(sizes) for i in excluded):
            raise ValueError(f"instance {case['index']}: bad excluded {excluded!r}")
    real = data["real"]
    if sum(real["group_sizes"]) != real["total_images"]:
        raise ValueError("real group sizes do not sum to the pool")
    if len(real["group_sizes"]) != 66:
        raise ValueError("real group count mismatch")
    return data


def build_cases(fixture):
    pairs = [
        (1, "non_positive_size", case01_non_positive_size),
        (2, "non_integer_size", case02_non_integer_size),
        (3, "negative_target", case03_negative_target),
        (4, "target_above_total", case04_target_above_total),
        (5, "non_integer_target", case05_non_integer_target),
        (6, "excluded_validation", case06_excluded_validation),
        (7, "edges_of_target", case07_edges_of_target),
        (8, "equal_sizes_distinct", case08_equal_sizes_distinct),
        (9, "infeasible_and_feasible", case09_infeasible_and_feasible),
        (10, "fixture_enumeration", make_case10(fixture)),
        (11, "real_grouped_count", make_case11(fixture)),
        (12, "real_anchored_count", make_case12(fixture)),
        (13, "bijection_small", make_case13(fixture)),
        (14, "rank_order", make_case14(fixture)),
        (15, "illegal_rank", make_case15(fixture)),
        (16, "return_type", make_case16(fixture)),
        (17, "excluded_never_selected", make_case17(fixture)),
        (18, "anchored_set_equality", make_case18(fixture)),
        (19, "real_endpoints", make_case19(fixture)),
        (20, "sample_legality", make_case20(fixture)),
        (21, "rank_mechanism", make_case21(fixture)),
        (22, "seed_semantics", make_case22(fixture)),
        (23, "real_accounting", make_case23(fixture)),
        (24, "inclusion_probabilities", make_case24(fixture)),
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
