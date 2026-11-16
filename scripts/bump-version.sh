#!/usr/bin/env bash
# Sets the SDK version everywhere it appears. Usage: scripts/bump-version.sh 0.2.0
set -euo pipefail
v="$1"
cd "$(dirname "$0")/.."
sed -i -E "s/\"version\": \"[^\"]+\"/\"version\": \"$v\"/" typescript/package.json
sed -i -E "s/VERSION = \"[^\"]+\"/VERSION = \"$v\"/" typescript/src/runtime.ts
sed -i -E "s/^version = \"[^\"]+\"/version = \"$v\"/" python/pyproject.toml
sed -i -E "s/__version__ = \"[^\"]+\"/__version__ = \"$v\"/" python/src/cfb27_dynasty/_version.py
sed -i -E "s/const Version = \"[^\"]+\"/const Version = \"$v\"/" go/dynasty/client.go
grep -rn "$v" typescript/package.json typescript/src/runtime.ts python/pyproject.toml python/src/cfb27_dynasty/_version.py go/dynasty/client.go
