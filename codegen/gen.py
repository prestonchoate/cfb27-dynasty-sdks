#!/usr/bin/env python3
"""Generates the SDK code from spec/*.json. Run from anywhere:

    python3 codegen/gen.py          # write generated files
    python3 codegen/gen.py --check  # exit 1 if generated files are stale (CI)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gen_go  # noqa: E402
import gen_py  # noqa: E402
import gen_ts  # noqa: E402
from common import shared_schemas  # noqa: E402
from ir import ROOT, load  # noqa: E402


def gofmt(src: str) -> str:
    return subprocess.run(["gofmt"], input=src, capture_output=True, text=True, check=True).stdout


def outputs() -> dict[Path, str]:
    v1 = load("v1", "v1.json")
    partner = load("partner", "partner.json")
    shared = shared_schemas(v1, partner)
    files = {}
    for api, spec in ((v1, "v1.json"), (partner, "partner.json")):
        files[ROOT / f"typescript/src/generated/{api.name}.ts"] = gen_ts.emit(api, shared, spec)
        files[ROOT / f"python/src/cfb27_dynasty/_generated/models_{api.name}.py"] = gen_py.emit_models(api, shared, spec)
        files[ROOT / f"python/src/cfb27_dynasty/_generated/api_{api.name}.py"] = gen_py.emit_api(api, shared, spec)
        files[ROOT / f"go/dynasty/zz_generated_{api.name}.go"] = gofmt(gen_go.emit(api, shared, spec))
    files[ROOT / "python/src/cfb27_dynasty/_generated/__init__.py"] = ""
    return files


def main() -> int:
    check = "--check" in sys.argv
    stale = []
    for path, text in outputs().items():
        if check:
            if not path.exists() or path.read_text() != text:
                stale.append(path.relative_to(ROOT))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_text() != text:
            path.write_text(text)
            print("wrote", path.relative_to(ROOT))
    if stale:
        print("stale generated files (run python3 codegen/gen.py):", *stale, sep="\n  ")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
