#!/usr/bin/env bash
# Copies the OpenAPI specs from the API repo and regenerates every SDK.
# Usage: scripts/sync-specs.sh [path-to-cfb27-dynasty-api]
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
api="${1:-$here/../golang/cfb27-dynasty-api}"
cp "$api/internal/api/openapi.json" "$here/spec/v1.json"
cp "$api/internal/web/partner_openapi.json" "$here/spec/partner.json"
python3 "$here/codegen/gen.py"
