"""Guard: the sampler acceptance contract and the first round are intact.

Run from the repository root:

    E:/yingyong/an/envs/iad-week1/python.exe -B guard_sampler.py

Exit 0 when every check passes, non-zero otherwise. Nothing is written.

What is checked
---------------
1. PINNED-SAMPLER.json itself, against the digest embedded below.
2. The sampler contract, runner, fixture and fixture generator.
3. The first round's harness: contract, runner, guard, PINNED.json, case-24
   fixture, fixture generator and README, so that the completed first run
   cannot be disturbed by this one.
4. Case count: 24 sampler cases, 40 fixture instances.
5. The stage 5-7 archive, through PINNED.json's registry: four freeze
   manifests and the 41 files they register.
6. Git: every protected path matches HEAD, and src/ shows at most src/sampler.py
   as modified, which is the only path this run may touch.

Limitation, stated plainly: a self-referential digest is not implementable, so
this file cannot hash itself. Uncommitted edits to guard_sampler.py fail check 6;
a coordinated rewrite of this file plus PINNED-SAMPLER.json is covered by the
recorded commit hash and the controller's Git provenance, not by this file.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import subprocess
import sys

PINNED_SHA256 = "e509250ffb96742c31c6a9c92d57045801cc220c121039568c42b7d6911e229d"
CASE_COUNT = 24
FIXTURE_INSTANCES = 40

REPO = pathlib.Path(__file__).resolve().parent
PINNED = REPO / "PINNED-SAMPLER.json"

GIT_PROTECTED = ["SAMPLER-CONTRACT.md", "verify_sampler.py", "guard_sampler.py",
                 "PINNED-SAMPLER.json", "sampler_fixtures", "sampler_tools"]


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

    pinned = None
    try:
        actual = sha256_file(PINNED)
        record(actual == PINNED_SHA256, "pinned_digest",
               "" if actual == PINNED_SHA256 else f"actual={actual} expected={PINNED_SHA256}")
        pinned = json.loads(PINNED.read_text(encoding="utf-8"))
    except Exception as exc:
        record(False, "pinned_digest", f"{type(exc).__name__}: {exc}")

    if pinned:
        for group in ("protected", "first_round"):
            for rel, meta in pinned.get(group, {}).items():
                path = REPO / rel
                try:
                    ok = (path.is_file() and sha256_file(path) == meta["sha256"]
                          and path.stat().st_size == meta["bytes"])
                    record(ok, f"{group}:{rel}",
                           "" if ok else "digest or size mismatch")
                except Exception as exc:
                    record(False, f"{group}:{rel}", f"{type(exc).__name__}: {exc}")

        try:
            text = (REPO / "verify_sampler.py").read_text(encoding="utf-8")
            declared = re.search(r"^TOTAL_CASES = (\d+)$", text, re.MULTILINE)
            declared = int(declared.group(1)) if declared else None
            record(declared == CASE_COUNT == pinned.get("case_count"),
                   "case_count",
                   f"runner={declared} pinned={pinned.get('case_count')} expected={CASE_COUNT}")
        except Exception as exc:
            record(False, "case_count", f"{type(exc).__name__}: {exc}")

        try:
            fixture = json.loads(
                (REPO / "sampler_fixtures/sampler-cases.json").read_text(encoding="utf-8"))
            record(len(fixture["instances"]) == FIXTURE_INSTANCES
                   == fixture["n_instances"] == pinned.get("fixture_instances"),
                   "fixture_instances",
                   f"instances={len(fixture['instances'])} n={fixture['n_instances']}")
        except Exception as exc:
            record(False, "fixture_instances", f"{type(exc).__name__}: {exc}")

        # stage 5-7 archive, reached through PINNED.json's own registry
        try:
            first = json.loads((REPO / "PINNED.json").read_text(encoding="utf-8"))
            archive = first["external_archive"]
            root = REPO / archive.get("root_relative_to_repo", "../..")
            manifests = archive.get("manifests", {})
            snapshot = archive.get("files", {})
            bad_manifests = []
            for rel, meta in manifests.items():
                path = root / rel
                if not path.is_file() or sha256_file(path) != meta["sha256"]:
                    bad_manifests.append(rel)
            record(not bad_manifests, "archive_manifests",
                   f"manifests={len(manifests)} bad={bad_manifests[:3]}")
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
        except Exception as exc:
            record(False, "archive_files", f"{type(exc).__name__}: {exc}")

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

    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "status", "--porcelain", "--", "src"],
            capture_output=True, text=True, check=False,
        )
        entries = [ln for ln in out.stdout.splitlines() if ln.strip()]
        allowed = {"src/sampler.py"}
        offending = []
        for line in entries:
            path = line[3:].strip().strip('"')
            if not path.startswith("src/"):
                path = f"src/{path}"
            if path not in allowed:
                offending.append(line)
        record(out.returncode == 0 and not offending, "scope_only_sampler",
               f"entries={entries[:3]}")
    except Exception as exc:
        record(False, "scope_only_sampler", f"{type(exc).__name__}: {exc}")

    failed = [r for r in results if not r[0]]
    for ok, label, detail in results:
        suffix = f"  <{detail}>" if detail and not ok else ""
        print(f"{'OK  ' if ok else 'FAIL'} {label}{suffix}")
    print(f"guard: {len(results)} checks, {len(failed)} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
