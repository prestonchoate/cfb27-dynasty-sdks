# cfb27-dynasty

Typed Python client for the CFB 27 [Dynasty API](https://dynasty.prestonchoate.dev/v1/docs),
with sync and async clients and pydantic models. Python 3.10+.

```sh
pip install cfb27-dynasty
```

## Read a dynasty

```python
import os
from cfb27_dynasty import DynastyClient, NotFoundError

with DynastyClient(os.environ["DYNASTY_API_KEY"]) as client:
    league = client.get_league().data
    print(league.name, league.season_text)

    for g in client.list_schedule(week=3, user_games=True).data:
        print(g.away.team, "@", g.home.team)

    try:
        client.get_game(123456)
    except NotFoundError:
        print("no such game")
```

Async (for discord.py and friends):

```python
from cfb27_dynasty import AsyncDynastyClient

async with AsyncDynastyClient(api_key) as client:
    standings = await client.list_standings()
```

Models live in `cfb27_dynasty.models`. Fields keep the API's names, except
Python keywords, which get a trailing underscore (`Recruit.class_`).

## Partner API

```python
from cfb27_dynasty import PartnerClient

partner = PartnerClient(os.environ["PARTNER_KEY"])
dynasties = [d for a in partner.list_dynasties().accounts for d in a.dynasties or []]

# read a dynasty you have access to with the same key
standings = partner.dynasty(dynasties[0].dynasty_id).list_standings()

# join an invite (waits on EA; up to ~150 s)
result = partner.join_invite(invite_id, team_id=42)

# poll the event feed
feed = partner.list_events(after=last_seen)
```

## Options

```python
DynastyClient(
    api_key,
    dynasty_id=123,          # required with a partner key
    base_url="https://…",    # site root, without /v1
    timeout=30.0,            # seconds per attempt (partner default 180)
    max_retries=2,
    max_retry_wait=60.0,     # longest Retry-After waited out automatically
    etag_cache=True,         # or a size, or False
    headers={"X-Trace": "…"},
    http_client=httpx.Client(...),
)
```

Every method takes `timeout=` too. `client.with_dynasty(id)` returns a client
for another dynasty sharing the same key, connection pool and cache.

Errors: `DynastyAPIError` (with `status`, `code`, `message`, `retry_after`) and its
subclasses `BadRequestError`, `AuthenticationError`, `PermissionDeniedError`,
`NotFoundError`, `ConflictError`, `RateLimitError` and `ServerError`;
`cfb27_dynasty.ConnectionError` when no response arrived.
