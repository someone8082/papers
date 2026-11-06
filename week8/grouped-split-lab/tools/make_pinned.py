"""Generate PINNED.json: the frozen digests the guard checks.

Protected inside the repository: the contract, the acceptance runner, the
case-24 fixture, the fixture generator.

Outside the repository: the stage 5-7 freeze manifests and every file those
manifests register. Week 7 registers the 88 MB backbone a second time; the
union is deduplicated by path so the guard hashes it once.

Run once from the repository root, then embed the resulting digest of
PINNED.json into guard.py (PINNED_SHA256). Re-running this script after that
point invalidates the guard on purpose.

    E:/yingyong/an/envs/iad-week1/python.exe -B tools/make_pinned.py
"""

import hashlib
import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
PAPERS = REPO.parents[1]
OUT = REPO / "PINNED.json"

PROTECTED = [
    "CONTRACT.md",
    "verify_metric.py",
    "fixtures/case24-cases.json",
    "tools/gen_fixtures.py",
]

MANIFESTS = [
    "week5/acceptance/freeze-v1-2026-11-02/freeze-manifest.json",
    "week5/acceptance/freeze-second-pool-2026-11-03/freeze-manifest.json",
    "week6/acceptance/route-b-freeze-2026-11-04/freeze-manifest.json",
    "week7/acceptance/stage7-background-2026-11-05/freeze-manifest.json",
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

    manifests = {}
    files = {}
    conflicts = []
    for rel in MANIFESTS:
        path = PAPERS / rel
        manifests[rel] = entry(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, meta in data.get("files", {}).items():
            prev = files.get(key)
            if prev and prev["sha256"] != meta["sha256"]:
                conflicts.append(key)
            files.setdefault(key, {"sha256": meta["sha256"], "bytes": meta["bytes"]})
    if conflicts:
        raise SystemExit(f"manifests disagree on registered files: {conflicts[:3]}")

    payload = {
        "kind": "stage8-grouped-split-pinned",
        "case_count": 24,
        "fixture_instances": 40,
        "protected": protected,
        "external_archive": {
            "root_relative_to_repo": "../..",
            "manifests": manifests,
            "files": {k: files[k] for k in sorted(files)},
        },
    }
    with OUT.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")

    total = sum(v["bytes"] for v in files.values())
    print(f"protected={len(protected)} manifests={len(manifests)} "
          f"archived_files={len(files)} archived_bytes={total}")
    print(f"PINNED_SHA256={sha256_file(OUT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
