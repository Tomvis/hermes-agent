#!/usr/bin/env python3
"""h5 fork: keep plugins/memory/hindsight equal to the catalog pin (HERMES-33).

Upstream unbundled Hindsight into plugin-catalog/hindsight.yaml; h5 vendors that plugin at the
pinned sha so the sealed image needs no lazy install. `check` fails when an upstream catalog bump
left the vendored copy behind (forksync stops there); `update` re-vendors it at the pin.
Stdlib only: forksync runs it with the host python.
"""
from __future__ import annotations

import hashlib
import io
import re
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "plugin-catalog" / "hindsight.yaml"
VENDORED = ROOT / "plugins" / "memory" / "hindsight"
SKIP = {"tests", "uv.lock", "docs"}  # top-level entries left out of the vendored copy


def _pin() -> tuple[str, str, str]:
    text = CATALOG.read_text(encoding="utf-8")
    field = lambda key: re.search(rf"^{key}:\s*\"?([^\"\n]+)\"?\s*$", text, re.M).group(1).strip()
    repo = field("repo").removeprefix("https://github.com/").removesuffix(".git")
    return repo, field("sha"), field("subdir")


def _upstream() -> dict[str, bytes]:
    repo, sha, subdir = _pin()
    with urllib.request.urlopen(f"https://codeload.github.com/{repo}/tar.gz/{sha}", timeout=120) as r:
        data = r.read()
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            parts = Path(member.name).parts[1:]  # drop the <repo>-<sha>/ prefix
            sub = Path(subdir).parts
            if not member.isfile() or tuple(parts[:len(sub)]) != sub:
                continue
            rel = Path(*parts[len(sub):])
            if rel.parts[0] not in SKIP:
                files[rel.as_posix()] = tar.extractfile(member).read()
    if not files:
        sys.exit(f"h5_vendored_hindsight: {subdir} not found at {repo}@{sha}")
    return files


def _vendored() -> dict[str, bytes]:
    return {p.relative_to(VENDORED).as_posix(): p.read_bytes()
            for p in VENDORED.rglob("*") if p.is_file() and "__pycache__" not in p.parts}


def main(argv: list[str]) -> int:
    action = argv[1] if len(argv) > 1 else "check"
    upstream = _upstream()
    if action == "update":
        shutil.rmtree(VENDORED, ignore_errors=True)
        for rel, data in upstream.items():
            (VENDORED / rel).parent.mkdir(parents=True, exist_ok=True)
            (VENDORED / rel).write_bytes(data)
        print(f"vendored {len(upstream)} files at {_pin()[1][:12]}")
        return 0
    if action != "check":
        sys.exit("usage: h5_vendored_hindsight.py [check|update]")
    local = _vendored()
    digest = lambda files: {k: hashlib.sha256(v).hexdigest() for k, v in files.items()}
    diff = sorted(k for k in upstream.keys() | local.keys() if digest(upstream).get(k) != digest(local).get(k))
    if diff:
        print(f"h5_vendored_hindsight: plugins/memory/hindsight differs from the catalog pin "
              f"{_pin()[1][:12]} ({', '.join(diff)}); run scripts/h5_vendored_hindsight.py update "
              f"and review hindsight-client in the [hindsight] extra", file=sys.stderr)
        return 1
    print(f"plugins/memory/hindsight matches catalog pin {_pin()[1][:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
