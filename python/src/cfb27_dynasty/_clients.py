from __future__ import annotations

import copy

import httpx

from ._generated.api_partner import AsyncPartnerAPI, PartnerAPI
from ._generated.api_v1 import AsyncDynastyAPI, DynastyAPI
from ._transport import AsyncTransport, SyncTransport, _Config

V1_TIMEOUT = 30.0
# Partner requests that reach EA can take up to 150 s.
PARTNER_TIMEOUT = 180.0


def _config(api_key, base_url, base_path, timeout, max_retries, max_retry_wait, etag_cache, headers):
    return _Config(api_key, base_url, base_path, timeout, max_retries, max_retry_wait, etag_cache, headers)


class DynastyClient(DynastyAPI, SyncTransport):
    """Reads one dynasty's cached data from ``/v1``.

    ``dynasty_id`` is required with a partner key (``cfbp_…``); a dynasty key
    (``cfbk_…``) names its own dynasty and ignores it.

    >>> client = DynastyClient(api_key="cfbk_…")
    >>> games = client.list_schedule(week=3).data
    """

    def __init__(
        self,
        api_key: str,
        *,
        dynasty_id: int | None = None,
        base_url: str | None = None,
        timeout: float = V1_TIMEOUT,
        max_retries: int = 2,
        max_retry_wait: float = 60.0,
        etag_cache: bool | int = True,
        headers: dict[str, str] | None = None,
        http_client: httpx.Client | None = None,
    ):
        cfg = _config(api_key, base_url, "/v1", timeout, max_retries, max_retry_wait, etag_cache, headers)
        self._init_transport(cfg, http_client, dynasty_id)

    def with_dynasty(self, dynasty_id: int) -> DynastyClient:
        """A client for another dynasty sharing this one's key, settings, HTTP
        connection pool and ETag cache."""
        c = copy.copy(self)
        c._dynasty_id = dynasty_id
        c._owns_http = False
        return c


class AsyncDynastyClient(AsyncDynastyAPI, AsyncTransport):
    """Async version of :class:`DynastyClient`."""

    def __init__(
        self,
        api_key: str,
        *,
        dynasty_id: int | None = None,
        base_url: str | None = None,
        timeout: float = V1_TIMEOUT,
        max_retries: int = 2,
        max_retry_wait: float = 60.0,
        etag_cache: bool | int = True,
        headers: dict[str, str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        cfg = _config(api_key, base_url, "/v1", timeout, max_retries, max_retry_wait, etag_cache, headers)
        self._init_transport(cfg, http_client, dynasty_id)

    def with_dynasty(self, dynasty_id: int) -> AsyncDynastyClient:
        c = copy.copy(self)
        c._dynasty_id = dynasty_id
        c._owns_http = False
        return c


class PartnerClient(PartnerAPI, SyncTransport):
    """Calls the partner API (``/partner/v1``) with a partner key (``cfbp_…``)."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str | None = None,
        timeout: float = PARTNER_TIMEOUT,
        max_retries: int = 2,
        max_retry_wait: float = 60.0,
        headers: dict[str, str] | None = None,
        http_client: httpx.Client | None = None,
    ):
        cfg = _config(api_key, base_url, "/partner/v1", timeout, max_retries, max_retry_wait, False, headers)
        self._init_transport(cfg, http_client, None)
        self._args = dict(api_key=api_key, base_url=base_url, max_retries=max_retries,
                          max_retry_wait=max_retry_wait, headers=headers)

    def dynasty(self, dynasty_id: int) -> DynastyClient:
        """A ``/v1`` client that reads ``dynasty_id`` with this partner key and
        shares this client's connection pool."""
        c = DynastyClient(dynasty_id=dynasty_id, http_client=self._http, **self._args)
        return c


class AsyncPartnerClient(AsyncPartnerAPI, AsyncTransport):
    """Async version of :class:`PartnerClient`."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str | None = None,
        timeout: float = PARTNER_TIMEOUT,
        max_retries: int = 2,
        max_retry_wait: float = 60.0,
        headers: dict[str, str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        cfg = _config(api_key, base_url, "/partner/v1", timeout, max_retries, max_retry_wait, False, headers)
        self._init_transport(cfg, http_client, None)
        self._args = dict(api_key=api_key, base_url=base_url, max_retries=max_retries,
                          max_retry_wait=max_retry_wait, headers=headers)

    def dynasty(self, dynasty_id: int) -> AsyncDynastyClient:
        return AsyncDynastyClient(dynasty_id=dynasty_id, http_client=self._http, **self._args)
