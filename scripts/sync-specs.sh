#!/usr/bin/env bash
# Copies the OpenAPI specs into spec/ and regenerates every SDK.
#
#   scripts/sync-specs.sh                          # from production (what's deployed)
#   scripts/sync-specs.sh https://other.host       # from another deployment
#   scripts/sync-specs.sh ../cfb27-dynasty-api     # from a local checkout of the API repo
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
src="${1:-https://dynasty.prestonchoate.dev}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
if [[ "$src" == http://* || "$src" == https://* ]]; then
  src="${src%/}"
  curl -fsS --retry 3 -A "cfb27-dynasty-sdks-sync" "$src/v1/openapi.json" -o "$tmp/v1.json"
  curl -fsS --retry 3 -A "cfb27-dynasty-sdks-sync" "$src/partner/v1/openapi.json" -o "$tmp/partner.json"
else
  cp "$src/internal/api/openapi.json" "$tmp/v1.json"
  cp "$src/internal/web/partner_openapi.json" "$tmp/partner.json"
fi
# refuse anything that isn't an OpenAPI document (an error page, say)
for f in v1 partner; do
  python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["openapi"].startswith("3.1"), d.get("openapi")' "$tmp/$f.json"
done
cp "$tmp/v1.json" "$here/spec/v1.json"
cp "$tmp/partner.json" "$here/spec/partner.json"
python3 "$here/codegen/gen.py"
