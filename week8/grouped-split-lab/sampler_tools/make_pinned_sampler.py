"""Generate PINNED-SAMPLER.json: the digests guard_sampler.py checks.

Two layers. This repository's sampler contract, runner, fixture and fixture
generator are hashed directly. The first round's harness is hashed as well so
that a change to CONTRACT.md, verify_metric.py, guard.py, PINNED.json or the
case-24 fixture is caught here too. The stage 5-7 archive is not re-listed: the
new guard reads ::PINNED.json's external_archive registry and re-hashes those
41 files, and ::PINNED.json's own digest is registered here, so the protection
is transitive without duplicating the list.

Run once from the repository root, then embed the resulting digest of
PINNED-SAMPLER.json into guard_sampler.py (PINNED_SHA256).

    E:/yingyong/an/envs/iad-week1/python.exe -B sampler_tools/make_pinned_sampler.py
"""

import hashlib
import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
OUT = REPO / "PINNED-SAMPLER.json"

PROTECTED = [
    "SAMPLER-CONTRACT.md",
    "verify_sampler.py",
    "sampler_fixtures/sampler-cases.json",
    "sampler_tools/gen_sampler_fixtures.py",
]

FIRST_ROUND = [
    "CONTRACT.md",
    "verify_metric.py",
    "guard.py",
    "PINNED.json",
    "fixtures/case24-cases.json",
    "tools/gen_fixtures.py",
    "README.md",
]


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def entry(path: pathlib.Path) -> dict:
    return {"sha256": sha256_file(path), "bytes": path.stat().st_size}


def main() -> int:
    protected = {}
    for rel in PROTECTED:
        path = REPO / rel
        if not path.is_file():
            raise SystemExit(f"missing protected file: {rel}")
        protected[rel] = entry(path)

    first_round = {}
    for rel in FIRST_ROUND:
        path = REPO / rel
        if not path.is_file():
            raise SystemExit(f"missing first-round file: {rel}")
        first_round[rel] = entry(path)

    payload = {
        "kind": "stage8-sampler-pinned",
        "case_count": 24,
        "fixture_instances": 40,
        "protected": protected,
        "first_round": first_round,
        "archive_via": "PINNED.json",
        "scope": {"mutable": ["src/sampler.py"]},
    }
    with OUT.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")

    print(f"protected={len(protected)} first_round={len(first_round)}")
    print(f"PINNED_SAMPLER_SHA256={sha256_file(OUT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
