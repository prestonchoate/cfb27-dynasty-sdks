# cfb27-dynasty

Typed TypeScript/JavaScript client for the CFB 27 [Dynasty API](https://dynasty.prestonchoate.dev/v1/docs).
No dependencies; works in Node 20+, Deno, Bun and browsers (the `/v1` API allows any origin).

```sh
npm install cfb27-dynasty
```

## Read a dynasty

```ts
import { DynastyClient, NotFoundError } from "cfb27-dynasty";

const client = new DynastyClient({ apiKey: process.env.DYNASTY_API_KEY! });

const { data: league } = await client.getLeague();
console.log(league.name, league.season_text);

const { data: games } = await client.listSchedule({ week: 3, user_games: true });
for (const g of games) console.log(g.away.team, "@", g.home.team);

try {
  await client.getGame(123456);
} catch (err) {
  if (err instanceof NotFoundError) console.log("no such game");
  else throw err;
}
```

Responses keep the API's field names (`snake_case`) and include `data_version`,
which changes whenever a sync brings new data.

Don't ship a dynasty key in a public web page: anyone can read it. Call the API
from a server, or accept that the key's data is public.

## Partner API

```ts
import { PartnerClient } from "cfb27-dynasty";

const partner = new PartnerClient({ apiKey: process.env.PARTNER_KEY! });
const { accounts } = await partner.listDynasties();
const dynasties = accounts.flatMap((a) => a.dynasties ?? []);

// read a dynasty you have access to with the same key
const standings = await partner.dynasty(dynasties[0].dynasty_id).listStandings();

// poll the event feed
let after: number | undefined;
const feed = await partner.listEvents({ after });
after = feed.next_after;
```

## Options

```ts
new DynastyClient({
  apiKey: "cfbk_…",
  dynastyId: 123,            // required with a partner key
  baseUrl: "https://…",      // site root, without /v1
  timeoutMs: 30_000,         // per attempt (partner default 180 000)
  maxRetries: 2,
  maxRetryWaitMs: 60_000,    // longest Retry-After waited out automatically
  etagCache: true,           // or a size, or false
  fetch: customFetch,
  headers: { "X-Trace": "…" },
});
```

Every method also takes `{ signal, timeoutMs, headers }` as its last argument.
`client.withDynasty(id)` returns a client for another dynasty sharing the same
key and cache.

Errors: `DynastyApiError` (with `status`, `code`, `message`, `retryAfter`) and its
subclasses `BadRequestError`, `AuthenticationError`, `PermissionDeniedError`,
`NotFoundError`, `ConflictError`, `RateLimitError` and `ServerError`;
`ConnectionError` when no response arrived.
