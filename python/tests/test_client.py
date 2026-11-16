import json
from datetime import datetime, timezone

import httpx
import pytest
import respx

from cfb27_dynasty import (
    AsyncDynastyClient,
    ConnectionError,
    DynastyClient,
    NotFoundError,
    PartnerClient,
    RateLimitError,
)

BASE = "https://dynasty.prestonchoate.dev"
LEAGUE = {
    "league_id": 7,
    "data_version": 3,
    "data": {
        "league_id": 7,
        "name": "Test",
        "status": "active",
        "season_text": "2027",
        "calendar_year": 2027,
        "current_period": None,
        "last_sync_at": None,
        "last_sync_status": "ok",
        "seasons": [2027],
    },
}


@respx.mock
def test_auth_query_and_dynasty_id():
    route = respx.get(f"{BASE}/v1/schedule").respond(json={"league_id": 7, "data_version": 1, "season": 2027, "data": []})
    c = DynastyClient("cfbp_x", dynasty_id=7)
    res = c.list_schedule(season=2027, played=True)
    assert res.league_id == 7
    req = route.calls.last.request
    assert req.url.params == httpx.QueryParams({"season": "2027", "played": "true"})
    assert req.headers["Authorization"] == "Bearer cfbp_x"
    assert req.headers["Dynasty-Id"] == "7"
    assert req.headers["User-Agent"].startswith("cfb27-dynasty-python/")


@respx.mock
def test_path_params_and_with_dynasty():
    route = respx.get(f"{BASE}/v1/games/12").respond(json={"league_id": 9, "data_version": 1, "data": None})
    c = DynastyClient("k").with_dynasty(99)
    with pytest.raises(Exception):
        c.get_game(12)  # data: null fails validation; we only care about the request
    assert route.calls.last.request.headers["Dynasty-Id"] == "99"


@respx.mock
def test_etag_revalidation():
    route = respx.get(f"{BASE}/v1/league")
    route.side_effect = [
        httpx.Response(200, json=LEAGUE, headers={"ETag": 'W/"3"'}),
        httpx.Response(304),
    ]
    c = DynastyClient("k")
    a = c.get_league()
    b = c.get_league()
    assert b == a and b is not a
    assert route.calls[1].request.headers["If-None-Match"] == 'W/"3"'


@respx.mock
def test_retries_short_429():
    route = respx.get(f"{BASE}/v1/seasons")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}, json={"error": {"code": "rate_limited", "message": "slow"}}),
        httpx.Response(200, json={"league_id": 1, "data_version": 1, "data": []}),
    ]
    assert DynastyClient("k").list_seasons().data == []
    assert route.call_count == 2


@respx.mock
def test_long_retry_after_raises():
    respx.post(f"{BASE}/partner/v1/dynasties/refresh").respond(
        429, headers={"Retry-After": "300"}, json={"error": {"code": "rate_limited", "message": "once per 5 minutes"}}
    )
    with pytest.raises(RateLimitError) as e:
        PartnerClient("cfbp_x").refresh_dynasties()
    assert e.value.retry_after == 300 and e.value.code == "rate_limited"


@respx.mock
def test_typed_errors():
    respx.get(f"{BASE}/v1/games/1").respond(404, json={"error": {"code": "not_found", "message": "no such game"}})
    with pytest.raises(NotFoundError) as e:
        DynastyClient("k").get_game(1)
    assert e.value.code == "not_found" and e.value.status == 404


@respx.mock
def test_post_body_and_204():
    join = respx.post(f"{BASE}/partner/v1/dynasties/3/payments").respond(
        201,
        json={"payment_id": "pi_1", "dynasty_id": 3, "amount_cents": 299, "period_start": "2026-11-01T00:00:00Z",
              "period_end": "2026-12-01T00:00:00Z", "billing": {"status": "active"}},
    )
    stop = respx.delete(f"{BASE}/partner/v1/dynasties/3/sync").respond(204)
    p = PartnerClient("cfbp_x")
    p.report_payment(3, payment_id="pi_1", period_start=datetime(2026, 11, 1, tzinfo=timezone.utc),
                     period_end=datetime(2026, 12, 1, tzinfo=timezone.utc))
    sent = json.loads(join.calls.last.request.content)
    assert sent == {"payment_id": "pi_1", "period_start": "2026-11-01T00:00:00+00:00",
                    "period_end": "2026-12-01T00:00:00+00:00"}
    assert p.stop_sync(3) is None
    assert stop.called


@respx.mock
def test_partner_dynasty_reads_v1():
    route = respx.get(f"{BASE}/v1/league").respond(json=LEAGUE)
    PartnerClient("cfbp_x").dynasty(42).get_league()
    assert route.calls.last.request.headers["Dynasty-Id"] == "42"


@respx.mock
def test_network_errors_retry_then_raise():
    route = respx.get(f"{BASE}/v1/league").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(ConnectionError):
        DynastyClient("k", max_retries=1).get_league()
    assert route.call_count == 2


@respx.mock
async def test_async_client():
    respx.get(f"{BASE}/v1/league").respond(json=LEAGUE)
    async with AsyncDynastyClient("k") as c:
        league = await c.get_league()
    assert league.data.name == "Test"
