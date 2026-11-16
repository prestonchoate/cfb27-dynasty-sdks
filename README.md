# CFB 27 Dynasty API SDKs

Typed clients for the [Dynasty API](https://dynasty.prestonchoate.dev/v1/docs):
read your CFB 27 online dynasty's schedule, standings, rosters, recruiting, stats
and awards, and, with a partner key, manage the dynasties your EA accounts share.

| Language | Package | Docs |
|---|---|---|
| TypeScript / JavaScript | [`cfb27-dynasty`](https://www.npmjs.com/package/cfb27-dynasty) | [typescript/](typescript/README.md) |
| Python | [`cfb27-dynasty`](https://pypi.org/project/cfb27-dynasty/) | [python/](python/README.md) |
| Go | `github.com/prestonchoate/cfb27-dynasty-sdks/go/dynasty` | [go/](go/README.md) |

Every SDK has the same two clients:

- **DynastyClient**: the read-only `/v1` API, with a dynasty key (`cfbk_…`) or a
  partner key (`cfbp_…`) plus a dynasty id.
- **PartnerClient**: the partner API (`/partner/v1`): invites, claim links,
  billed syncing, payments and the event feed. `partner.dynasty(id)` returns a
  DynastyClient that reads that dynasty with the partner key.

And the same behavior:

- **ETag caching.** GET responses are cached and revalidated with
  `If-None-Match`; when nothing changed since the last sync the server answers
  304 and you get the cached copy. Poll as often as you like within the rate limit.
- **Rate limits.** `/v1` allows 120 requests a minute per key. A 429 with a short
  `Retry-After` (up to 60 s by default) is retried for you; longer waits raise a
  rate-limit error carrying `retryAfter`.
- **Retries.** GET requests retry network errors and 502/503/504 with backoff.
  Other methods are never retried after reaching the server.
- **Typed errors.** Error responses become errors with the HTTP status, a stable
  `code` (such as `not_found` or `needs_reauth`) and the server's message.
- **Timeouts.** 30 s for `/v1`; 180 s for the partner API, whose EA-bound calls
  can take up to 150 s.
- **Forward compatible.** Enum fields accept values newer servers add, and
  unknown response fields are ignored (Python keeps them in `model_extra`).

## Development

The types and endpoint methods are generated from the API's OpenAPI specs in
[`spec/`](spec/) by [`codegen/gen.py`](codegen/gen.py) (Python 3.10+, stdlib
only, plus `gofmt`). The transport in each language (auth, caching, retries,
errors) is handwritten.

```sh
scripts/sync-specs.sh ../cfb27-dynasty-api   # copy the latest specs and regenerate
python3 codegen/gen.py --check                # CI: fail if generated code is stale

(cd typescript && npm ci && npm test)
(cd python && uv run pytest)
(cd go && go test ./...)
```

The generator supports the slice of OpenAPI 3.1 the specs use and raises on
anything else, so a spec change that needs new support fails loudly.

Live checks against a real server (read-only):

```sh
DYNASTY_API_KEY=cfbk_… uv run --project python python scripts/live/check.py
DYNASTY_API_KEY=cfbk_… go -C go test -run TestLive ./...
```

## Releasing

Bump the version in all three packages (`scripts/bump-version.sh 0.2.0`), then push a
tag: `v0.2.0` publishes npm and PyPI, and `go/v0.2.0` versions the Go module.

## License

MIT
