"""Guard: the fixed acceptance contract and the stage 5-7 archive are intact.

Run from the repository root:

    E:/yingyong/an/envs/iad-week1/python.exe -B guard.py

Exit 0 when every check passes, non-zero otherwise. Nothing is written.

What is checked
---------------
1. PINNED.json itself, against the digest embedded below.
2. The contract, the acceptance runner, the case-24 fixture and the fixture
   generator, by SHA-256 and size.
3. The case count: 24 top-level cases, 40 fixture instances.
4. The four stage 5-7 freeze manifests, outside this repository.
5. Every file those manifests register, and agreement between each manifest and
   the stored snapshot.
6. Git: all of the above are exactly as committed, with no untracked protected
   file. This is what covers guard.py itself.

Limitation, stated plainly: a self-referential digest is not implementable, so
this guard cannot hash its own file against a value it also contains. A
coordinated rewrite of guard.py plus PINNED.json plus the embedded digest below
is out of reach; that case is covered by the recorded commit hash and by the
controller's Git provenance check, not by this file.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import subprocess
import sys

PINNED_SHA256 = "3eff5acbf54a822cc9a9f2437b1d646fe262ffe43983f4808448a4fd116ffcc2"
CASE_COUNT = 24
FIXTURE_INSTANCES = 40

REPO = pathlib.Path(__file__).resolve().parent
PAPERS = REPO.parents[1]
PINNED = REPO / "PINNED.json"

GIT_PROTECTED = ["CONTRACT.md", "verify_metric.py", "guard.py", "PINNED.json",
                 "fixtures", "tools", "README.md"]


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    except Exception:
        pass

    results = []

    def record(ok, label, detail=""):
        results.append((bool(ok), label, detail))

    # 1. PINNED.json itself
    pinned = None
    try:
        actual = sha256_file(PINNED)
        record(actual == PINNED_SHA256, "pinned_digest",
               "" if actual == PINNED_SHA256 else f"actual={actual} expected={PINNED_SHA256}")
        pinned = json.loads(PINNED.read_text(encoding="utf-8"))
    except Exception as exc:
        record(False, "pinned_digest", f"{type(exc).__name__}: {exc}")

    # 2. protected files inside the repository
    if pinned:
        for rel, meta in pinned.get("protected", {}).items():
            path = REPO / rel
            try:
                ok = (path.is_file() and sha256_file(path) == meta["sha256"]
                      and path.stat().st_size == meta["bytes"])
                record(ok, f"protected:{rel}",
                       "" if ok else "digest or size mismatch")
            except Exception as exc:
                record(False, f"protected:{rel}", f"{type(exc).__name__}: {exc}")

        # 3. case count
        try:
            text = (REPO / "verify_metric.py").read_text(encoding="utf-8")
            declared = re.search(r"^TOTAL_CASES = (\d+)$", text, re.MULTILINE)
            declared = int(declared.group(1)) if declared else None
            record(declared == CASE_COUNT == pinned.get("case_count"),
                   "case_count",
                   f"runner={declared} pinned={pinned.get('case_count')} expected={CASE_COUNT}")
        except Exception as exc:
            record(False, "case_count", f"{type(exc).__name__}: {exc}")

        try:
            fixture = json.loads((REPO / "fixtures/case24-cases.json").read_text(encoding="utf-8"))
            record(len(fixture["cases"]) == FIXTURE_INSTANCES
                   == fixture["n_instances"] == pinned.get("fixture_instances"),
                   "fixture_instances",
                   f"cases={len(fixture['cases'])} n={fixture['n_instances']}")
        except Exception as exc:
            record(False, "fixture_instances", f"{type(exc).__name__}: {exc}")

        # 4./5. external archive
        archive = pinned.get("external_archive", {})
        root = REPO / archive.get("root_relative_to_repo", "../..")
        manifests = archive.get("manifests", {})
        snapshot = archive.get("files", {})

        for rel, meta in manifests.items():
            path = root / rel
            try:
                ok = (path.is_file() and sha256_file(path) == meta["sha256"]
                      and path.stat().st_size == meta["bytes"])
                record(ok, f"manifest:{rel}", "" if ok else "digest or size mismatch")
            except Exception as exc:
                record(False, f"manifest:{rel}", f"{type(exc).__name__}: {exc}")

        try:
            registered = {}
            for rel in manifests:
                data = json.loads((root / rel).read_text(encoding="utf-8"))
                for key, meta in data.get("files", {}).items():
                    if key in registered and registered[key] != meta["sha256"]:
                        raise ValueError(f"manifests disagree on {key}")
                    registered[key] = meta["sha256"]
            missing = sorted(set(registered) - set(snapshot))
            extra = sorted(set(snapshot) - set(registered))
            record(not missing and not extra, "archive_coverage",
                   f"missing={missing[:3]} extra={extra[:3]}")
            mismatched = [k for k in registered
                          if k in snapshot and snapshot[k]["sha256"] != registered[k]]
            record(not mismatched, "archive_agreement", f"mismatched={mismatched[:3]}")
        except Exception as exc:
            record(False, "archive_coverage", f"{type(exc).__name__}: {exc}")

        bad = []
        for rel, meta in snapshot.items():
            path = root / rel
            try:
                if not path.is_file() or path.stat().st_size != meta["bytes"] \
                        or sha256_file(path) != meta["sha256"]:
                    bad.append(rel)
            except Exception:
                bad.append(rel)
        record(not bad, "archive_files",
               f"checked={len(snapshot)} changed={bad[:3]}")

    # 6. Git: protected paths identical to HEAD, nothing untracked
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "status", "--porcelain", "--", *GIT_PROTECTED],
            capture_output=True, text=True, check=False,
        )
        dirty = [ln for ln in out.stdout.splitlines() if ln.strip()]
        record(out.returncode == 0 and not dirty, "git_protected_clean",
               f"rc={out.returncode} entries={dirty[:3]}")
    except Exception as exc:
        record(False, "git_protected_clean", f"{type(exc).__name__}: {exc}")

    failed = [r for r in results if not r[0]]
    for ok, label, detail in results:
        suffix = f"  <{detail}>" if detail and not ok else ""
        print(f"{'OK  ' if ok else 'FAIL'} {label}{suffix}")
    print(f"guard: {len(results)} checks, {len(failed)} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
