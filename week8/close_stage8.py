"""Verify stage 8 closure and register final bytes, without overwriting outputs."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WEEK = ROOT / 'week8'
LAB = WEEK / 'grouped-split-lab'
OUTPUT = WEEK / 'acceptance/stage8-closure-2026-11-07/closure-check.json'
CONTROL = Path('C:/Users/23029/.codex/skills/codex-autoresearch/scripts/autoresearch.py')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return {'bytes': path.stat().st_size, 'sha256': h.hexdigest()}


def run(args, cwd):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    assert p.returncode == 0, (args, p.stdout, p.stderr)
    return {'command': args, 'returncode': p.returncode,
            'stdout': p.stdout, 'stderr': p.stderr}


def main():
    if OUTPUT.exists():
        raise SystemExit('Refusing existing closure-check.json')
    acc = WEEK / 'acceptance'
    registry_specs = [
        (acc/'stage8-arms-2026-11-06/plan-digest.json', ROOT),
        (acc/'stage8-arms-v2-2026-11-07/verification-digest.json', acc/'stage8-arms-v2-2026-11-07'),
        (acc/'stage8-arms-v2-2026-11-07/report-v2-check.json', ROOT),
    ]
    registry_results = []
    for path, base in registry_specs:
        data = json.loads(path.read_text(encoding='utf-8'))
        files = data['files']
        for rel, meta in files.items():
            resolved = (base / rel).resolve()
            assert resolved.is_relative_to(ROOT)
            assert digest(resolved) == meta, rel
        registry_results.append({'path': path.relative_to(ROOT).as_posix(),
                                 'checked': len(files), 'mismatches': 0})

    commands = [('grouping_acceptance', LAB, ['verify_metric.py']),
                ('grouping_guard', LAB, ['guard.py']),
                ('sampler_acceptance', LAB, ['verify_sampler.py']),
                ('sampler_guard', LAB, ['guard_sampler.py']),
                ('candidate_regression', ROOT, ['week8/arms_v2.py', 'selftest'])]
    checks = {}
    for name, cwd, args in commands:
        record = run([sys.executable, '-B', *args], cwd)
        if name.endswith('acceptance'):
            measurement = json.loads(record['stdout'].strip().splitlines()[-1])
            assert measurement == {'failed_cases': 0, 'total_cases': 24}
        elif name.endswith('guard'):
            assert '0 failed' in record['stdout']
        else:
            assert 'selftest: 13 checks, 0 failed' in record['stdout']
        checks[name] = record

    status = json.loads(run([sys.executable, '-B', str(CONTROL), 'status',
                             '--repo', str(LAB)], ROOT)['stdout'])
    assert status['status'] == 'complete' and status['metric']['current'] == 0
    assert status['repository']['consistent'] and not status['repository']['dirty_paths']
    archive = LAB/'autoresearch-results/archive/20261106-132606'
    runs = {}
    for name, folder in [('grouping', archive), ('sampler', LAB/'autoresearch-results')]:
        events = [json.loads(line) for line in (folder/'events.jsonl').read_text(encoding='utf-8').splitlines() if line]
        assert [e['event'] for e in events] == ['baseline', 'iteration', 'complete']
        assert events[0]['metric'] == 24 and events[1]['retained_metric'] == events[2]['metric'] == 0
        assert events[1]['guard'] == 'pass' and events[1]['outcome'] == 'keep'
        runs[name] = {'run_id': events[-1]['run_id'], 'head': events[-1]['head'],
                      'iterations': 1, 'baseline': 24, 'final': 0, 'status': 'complete'}

    exact = json.loads((acc/'stage8-arms-2026-11-06/exact-audit-v1.json').read_text(encoding='utf-8'))
    independent = json.loads((acc/'stage8-arms-v2-2026-11-07/independent-eval-v2.json').read_text(encoding='utf-8'))
    assert sum(v['fields_compared'] for v in independent['row_comparison'].values()) == 400000
    assert all(v['mismatches'] == 0 for v in independent['row_comparison'].values())
    source_aliases = {
        'plan-digest-v1': acc/'stage8-arms-2026-11-06/plan-digest.json',
        'eval-v2.json': acc/'stage8-arms-v2-2026-11-07/eval-v2.json',
        'eval-rows-v2.csv': acc/'stage8-arms-v2-2026-11-07/eval-rows-v2.csv',
        'verifier': WEEK/'verify_arms_v2.py',
    }
    assert set(independent['source_hashes']) == set(source_aliases)
    for rel, sha in independent['source_hashes'].items():
        assert digest(source_aliases[rel])['sha256'] == sha, rel
    for rel, sha in exact['source_hashes'].items():
        assert digest(ROOT/rel)['sha256'] == sha, rel

    # Register deliberate research outputs; omit caches, scratch and Git internals.
    paths = set(p for p in WEEK.iterdir() if p.suffix in ('.py', '.md'))
    paths.update(p for p in acc.rglob('*') if p.is_file() and p.suffix in ('.json', '.csv'))
    paths.update((WEEK/'outputs/arms-v1').glob('manifest-*.csv'))
    tracked = run(['git', 'ls-files', '-z'], LAB)['stdout'].split('\0')
    paths.update(LAB/rel for rel in tracked if rel)
    paths.update(p for p in (LAB/'autoresearch-results').rglob('*')
                 if p.is_file() and p.suffix in ('.json', '.jsonl'))
    paths.discard(OUTPUT)
    links_checked = 0
    for doc in (WEEK/'README.md', WEEK/'stage8-closure-2026-11-07.md', WEEK/'week8-report-grouped-split-v2.md'):
        for link in re.findall(r'\]\(([^)]+)\)', doc.read_text(encoding='utf-8')):
            if '://' in link:
                continue
            resolved = (doc.parent/link).resolve()
            assert resolved.exists() or resolved == OUTPUT, link
            links_checked += 1
    payload = {'status': 'STAGE8_GROUPED_SPLIT_CLOSED_VERIFIED', 'closed': True,
               'closure_date': '2026-11-07', 'timezone': 'Asia/Shanghai',
               'inference_performed': False, 'new_experiments_started': False,
               'registry_checks': registry_results, 'checks': checks,
               'controller_status': status, 'engineering_runs': runs,
               'existing_independent_row_validation': independent['row_comparison'],
               'exact_states': {a: rec['exact_states'] for a,rec in exact['arms'].items()},
               'links_checked': links_checked,
               'files': {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(paths)},
               'self_digest': 'Excluded: this manifest does not register its own digest',
               'scope_note': 'Local closure; GitHub publication remains the earlier selected snapshot.'}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open('x', encoding='utf-8', newline='\n') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(json.dumps({'status': payload['status'], 'registered_files': len(paths),
                      'registry_checks': registry_results, 'links_checked': links_checked}))


if __name__ == '__main__':
    main()
