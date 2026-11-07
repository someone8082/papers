"""Independent, read-only-input audit; writes a new sidecar, never old results.

Exact state masses partition allocations by the two highest calibration keys.
Required eval/cal memberships force whole units; free units are counted by
integer polynomial coefficients. No sampler or existing evaluator is imported.
"""
import bisect
import csv
import hashlib
import json
import math
from collections import Counter
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACC = ROOT / 'week8/acceptance/stage8-arms-2026-11-06'
OUT = ACC / 'exact-audit-v1.json'


def coefficient(sizes, target):
    if target < 0:
        return 0
    ways = [0] * (target + 1)
    ways[0] = 1
    for size in sizes:
        for t in range(target, size - 1, -1):
            ways[t] += ways[t - size]
    return ways[target]


def probability(numerator, denominator):
    p = Fraction(numerator, denominator)
    return {'exact': str(p), 'p': float(p)}


def main():
    if OUT.exists():
        raise SystemExit('Refusing existing audit output')
    plan = json.loads((ACC / 'arms-plan.json').read_text(encoding='utf-8'))
    digest = json.loads((ACC / 'plan-digest.json').read_text(encoding='utf-8'))
    for rel, meta in digest['files'].items():
        data = (ROOT / rel).read_bytes()
        assert len(data) == meta['bytes'] and hashlib.sha256(data).hexdigest() == meta['sha256'], rel
    values, normal, defects = {}, [], []
    for filename in ('calibration-scores.csv', 'evaluation-scores.csv'):
        with (ROOT / 'week7/outputs/background-448-r1' / filename).open(encoding='utf-8', newline='') as f:
            for row in csv.DictReader(f):
                key, score = row['relative_path'], float(row['score'])
                assert key not in values and math.isfinite(score)
                values[key] = score
                (normal if '/good/' in key else defects).append(key)
    ordered = sorted(normal, key=lambda k: values[k], reverse=True)
    assert len(ordered) == len({values[k] for k in ordered}) == 93
    dv = sorted(values[k] for k in defects)
    assert len(dv) == 212
    tp = lambda t: len(dv) - bisect.bisect_right(dv, t)
    previous = {}
    with (ACC / 'eval-rows.csv').open(encoding='utf-8', newline='') as f:
        for row in csv.DictReader(f):
            index = (row['arm'], int(row['repeat_id']))
            assert index not in previous
            previous[index] = row
    result = {'status': 'STAGE8_EXACT_AUDIT', 'method': __doc__,
              'frozen_hashes_checked': len(digest['files']), 'arms': {}}
    states = ('budget_gain', 'budget_no_gain', 'mid_over_budget', 'both_over_budget')
    for arm in ('I0', 'I1', 'G0', 'G1'):
        spec = plan['arms'][arm]
        units = [set(u) for u in spec['units']]
        selectable = set().union(*units)

        def completions(eval_required, cal_required):
            if eval_required - selectable or eval_required & cal_required:
                return 0
            forced, free = 0, []
            for unit in units:
                ev, ca = bool(unit & eval_required), bool(unit & cal_required)
                if ev and ca:
                    return 0
                if ev:
                    forced += len(unit)
                elif not ca:
                    free.append(len(unit))
            return coefficient(free, 32 - forced)

        total = coefficient([len(u) for u in units], 32)
        assert total == int(spec['count'])
        masses = Counter({s: 0 for s in states})
        for j in range(1, 34):
            for i in range(j):
                cal_required = {ordered[i], ordered[j]}
                eval_required = set(ordered[:j]) - {ordered[i]}
                weight = completions(eval_required, cal_required)
                if not weight:
                    continue
                high, second = values[ordered[i]], values[ordered[j]]
                mid = (high + second) / 2.0
                assert second < mid < high
                fp_max = i
                fp_mid = sum(values[k] > mid for k in ordered) - 1
                state = ('both_over_budget' if fp_max >= 2 else
                         'mid_over_budget' if fp_mid >= 2 else
                         'budget_gain' if tp(mid) > tp(high) else 'budget_no_gain')
                masses[state] += weight
        assert sum(masses.values()) == total, (arm, sum(masses.values()), total)
        pair = completions(set(ordered[:2]), set())
        p1, p2 = (Fraction(completions({k}, set()), total) for k in ordered[:2])
        assert pair == masses['both_over_budget']
        rec = {'total': str(total), 'exact_states': {s: probability(masses[s], total) for s in states},
               'top_two_joint': probability(pair, total),
               'top_two_marginals': [str(p1), str(p2)],
               'top_two_covariance': str(Fraction(pair, total) - p1*p2)}
        bounds = []
        mismatch, changed, lower, higher = 0, 0, 0, 0
        empirical = Counter()
        with (ROOT / f'week8/outputs/arms-v1/manifest-{arm}.csv').open(encoding='utf-8', newline='') as f:
            for row in csv.DictReader(f):
                ek = {spec['image_keys'][int(x)] for x in row['eval_idx'].split()}
                assert len(ek) == 32
                assert hashlib.sha256('\n'.join(sorted(ek)).encode()).hexdigest() == row['eval_sha256']
                cal = sorted(values[k] for k in normal if k not in ek)
                ev = sorted(values[k] for k in ek)
                assert len(cal) == 61
                thresholds = {'max': cal[-1], 'mid': (cal[-2]+cal[-1])/2.0,
                              'q95': cal[57], 'q90': cal[54]}
                fresh = {}
                for name,t in thresholds.items():
                    fresh[name+'_fp'] = len(ev)-bisect.bisect_right(ev,t)
                    fresh[name+'_tp'] = tp(t)
                state = ('both_over_budget' if fresh['max_fp']>=2 else
                         'mid_over_budget' if fresh['mid_fp']>=2 else
                         'budget_gain' if fresh['mid_tp']>fresh['max_tp'] else 'budget_no_gain')
                empirical[state] += 1
                old = previous[arm, int(row['repeat_id'])]
                mismatch += int(old['state'] != state or any(int(old[k]) != v for k,v in fresh.items()))
                feasible = [t for t in cal if sum(x>t for x in ev)<=1]
                c = max((sum(x>t for x in dv) for t in feasible), default=None)
                u = sum(x>ev[-2] for x in dv)
                assert u == int(old['u_tp'])
                old_c = int(old['c_star_tp']) if old['c_star_tp'] else None
                if c != old_c:
                    changed += 1
                    if c is not None and old_c is not None:
                        lower += c < old_c
                        higher += c > old_c
                bounds.append((c,u))
        assert len(bounds)==10000 and mismatch==0
        valid = [(c,u) for c,u in bounds if c is not None]
        rec.update({'rows':len(bounds),'states':dict(empirical),'four_rule_and_state_row_mismatches':mismatch,
                    'c_star_changed_rows':changed,'correct_c_star_lower_rows':lower,'correct_c_star_higher_rows':higher,
                    'bounds_corrected':{'feasible_rows':len(valid),'infeasible_rows':len(bounds)-len(valid),
                        'c_star_mean_given_feasible':sum(c for c,u in valid)/len(valid),
                        'u_mean_all':sum(u for c,u in bounds)/len(bounds),
                        'u_mean_given_feasible':sum(u for c,u in valid)/len(valid),
                        'gap_mean_given_feasible':sum(u-c for c,u in valid)/len(valid)}})
        result['arms'][arm] = rec
    p = result['arms']['I0']['exact_states']['mid_over_budget']['p']
    result['i0_mid_over_standard_error_pp'] = 100*math.sqrt(p*(1-p)/10000)
    result['i0_mid_over_three_sigma_pp'] = 3*result['i0_mid_over_standard_error_pp']
    result['source_hashes'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in (ACC/'plan-digest.json', ACC/'eval.json', ACC/'eval-rows.csv', Path(__file__))}
    with OUT.open('x',encoding='utf-8') as f:
        json.dump(result,f,ensure_ascii=False,indent=2)
        f.write('\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
