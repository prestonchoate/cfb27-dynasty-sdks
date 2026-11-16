import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DynastyClient,
  PartnerClient,
  NotFoundError,
  RateLimitError,
  ConnectionError,
} from "../dist/index.js";

/** A fetch that answers from a queue and records each request. */
function mockFetch(...responses) {
  const calls = [];
  const fn = async (url, init) => {
    calls.push({ url: new URL(url), ...init });
    const r = responses.shift();
    if (!r) throw new Error("unexpected request");
    if (r instanceof Error) throw r;
    return new Response(r.body === undefined ? null : JSON.stringify(r.body), {
      status: r.status ?? 200,
      headers: r.headers,
    });
  };
  fn.calls = calls;
  return fn;
}

test("sends auth, query and Dynasty-Id", async () => {
  const fetch = mockFetch({ body: { league_id: 7, data_version: 1, data: [] } });
  const c = new DynastyClient({ apiKey: "cfbp_x", dynastyId: 7, fetch, baseUrl: "https://api.test/" });
  const res = await c.listSchedule({ season: 2027, played: true, week: undefined });
  assert.equal(res.league_id, 7);
  const call = fetch.calls[0];
  assert.equal(call.url.href, "https://api.test/v1/schedule?season=2027&played=true");
  assert.equal(call.headers.Authorization, "Bearer cfbp_x");
  assert.equal(call.headers["Dynasty-Id"], "7");
  assert.equal(call.method, "GET");
});

test("path parameters and withDynasty", async () => {
  const fetch = mockFetch({ body: {} });
  const c = new DynastyClient({ apiKey: "k", fetch }).withDynasty(99);
  await c.getGame(12, { season: 2026 });
  assert.equal(fetch.calls[0].url.pathname, "/v1/games/12");
  assert.equal(fetch.calls[0].headers["Dynasty-Id"], "99");
});

test("revalidates with If-None-Match and serves 304 from cache", async () => {
  const body = { league_id: 1, data_version: 5, data: { name: "x" } };
  const fetch = mockFetch({ body, headers: { ETag: 'W/"5"' } }, { status: 304 });
  const c = new DynastyClient({ apiKey: "k", fetch });
  const a = await c.getLeague();
  const b = await c.getLeague();
  assert.deepEqual(b, body);
  assert.notEqual(a, b, "each call gets its own copy");
  assert.equal(fetch.calls[1].headers["If-None-Match"], 'W/"5"');
});

test("the cache is keyed by dynasty", async () => {
  const fetch = mockFetch({ body: { a: 1 }, headers: { ETag: '"1"' } }, { body: { a: 2 } });
  const c = new DynastyClient({ apiKey: "k", fetch, dynastyId: 1 });
  await c.getLeague();
  await c.withDynasty(2).getLeague();
  assert.equal(fetch.calls[1].headers["If-None-Match"], undefined);
});

test("retries 429 after Retry-After", async () => {
  const fetch = mockFetch(
    { status: 429, headers: { "Retry-After": "0" }, body: { error: { code: "rate_limited", message: "slow" } } },
    { body: { ok: true } },
  );
  const c = new DynastyClient({ apiKey: "k", fetch });
  assert.deepEqual(await c.listSeasons(), { ok: true });
  assert.equal(fetch.calls.length, 2);
});

test("does not wait out a long Retry-After", async () => {
  const fetch = mockFetch({ status: 429, headers: { "Retry-After": "300" }, body: { error: { code: "rate_limited", message: "refresh at most once per 5 minutes" } } });
  const p = new PartnerClient({ apiKey: "cfbp_x", fetch });
  await assert.rejects(p.refreshDynasties(), (err) => {
    assert.ok(err instanceof RateLimitError);
    assert.equal(err.retryAfter, 300);
    assert.equal(err.code, "rate_limited");
    return true;
  });
});

test("maps error responses to typed errors", async () => {
  const fetch = mockFetch({ status: 404, body: { error: { code: "not_found", message: "no such game" } } });
  const c = new DynastyClient({ apiKey: "k", fetch });
  await assert.rejects(c.getGame(1), (err) => err instanceof NotFoundError && err.code === "not_found" && err.message === "no such game");
});

test("POST sends a JSON body; 204 resolves undefined", async () => {
  const fetch = mockFetch({ status: 201, body: { dynasty_id: 3 } }, { status: 204 });
  const p = new PartnerClient({ apiKey: "cfbp_x", fetch });
  await p.joinInvite(5, { team_id: 10 });
  assert.equal(fetch.calls[0].method, "POST");
  assert.equal(fetch.calls[0].url.pathname, "/partner/v1/invites/5/join");
  assert.deepEqual(JSON.parse(fetch.calls[0].body), { team_id: 10 });
  assert.equal(fetch.calls[0].headers["Content-Type"], "application/json");
  assert.equal(await p.stopSync(3), undefined);
});

test("partner.dynasty reads /v1 with the partner key", async () => {
  const fetch = mockFetch({ body: {} });
  await new PartnerClient({ apiKey: "cfbp_x", fetch }).dynasty(42).getLeague();
  assert.equal(fetch.calls[0].url.pathname, "/v1/league");
  assert.equal(fetch.calls[0].headers["Dynasty-Id"], "42");
});

test("retries GET network errors, then raises ConnectionError", async () => {
  const fetch = mockFetch(new TypeError("boom"), new TypeError("boom"));
  const c = new DynastyClient({ apiKey: "k", fetch, maxRetries: 1 });
  await assert.rejects(c.getLeague(), ConnectionError);
  assert.equal(fetch.calls.length, 2);
});
