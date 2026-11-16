#!/usr/bin/env python3
"""Summarizes how spec/*.json differ from a git revision, as Markdown.
Usage: scripts/spec-diff.py [rev]   (default HEAD)"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
rev = sys.argv[1] if len(sys.argv) > 1 else "HEAD"


def ops(d):
    return {f"{m.upper()} {p}" for p, item in d["paths"].items() for m in item}


def schemas(d):
    return d.get("components", {}).get("schemas", {})


for name in ("v1", "partner"):
    old = json.loads(subprocess.run(["git", "show", f"{rev}:spec/{name}.json"], cwd=ROOT,
                                    capture_output=True, check=True, text=True).stdout)
    new = json.loads((ROOT / "spec" / f"{name}.json").read_text())
    lines = []
    for label, a, b in (("operation", ops(old), ops(new)), ("schema", set(schemas(old)), set(schemas(new)))):
        lines += [f"- added {label} `{x}`" for x in sorted(b - a)]
        lines += [f"- removed {label} `{x}`" for x in sorted(a - b)]
    both = set(schemas(old)) & set(schemas(new))
    lines += [f"- changed schema `{x}`" for x in sorted(both) if schemas(old)[x] != schemas(new)[x]]
    changed_ops = sorted(f"{m.upper()} {p}" for p in set(old["paths"]) & set(new["paths"])
                         for m in set(old["paths"][p]) & set(new["paths"][p])
                         if old["paths"][p][m] != new["paths"][p][m])
    lines += [f"- changed operation `{x}`" for x in changed_ops]
    if old["info"] != new["info"]:
        lines.append("- changed `info` (title, version or description)")
    if old == new:
        continue
    print(f"**{name}** (spec version {new['info']['version']})")
    print("\n".join(lines) or "- other changes")
    print()
