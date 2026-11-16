"""HTTP transport shared by every client: auth, Dynasty-Id, ETag caching,
retries, timeouts and typed errors."""

from __future__ import annotations

import asyncio
import email.utils
import json
import random
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, TypeVar
from urllib.parse import quote

import httpx
from pydantic import BaseModel

from ._version import __version__
from .errors import ConnectionError, error_for

DEFAULT_BASE_URL = "https://dynasty.prestonchoate.dev"
M = TypeVar("M", bound=BaseModel)


def _seg(v: object) -> str:
    return quote(str(v), safe="")


def _query_value(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _jsonable(v: Any) -> Any:
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.isoformat()
    if isinstance(v, BaseModel):
        return v.model_dump(mode="json", by_alias=True, exclude_none=True)
    return v


def _retry_after(h: str | None) -> float | None:
    if not h:
        return None
    try:
        return max(0.0, float(h))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(h)
    except (TypeError, ValueError):
        return None
    return max(0.0, when.timestamp() - time.time())


def _backoff(attempt: int) -> float:
    return 0.5 * 2**attempt * (0.5 + random.random() / 2)


class _EtagCache:
    def __init__(self, size: int):
        self._size = size
        self._entries: OrderedDict[str, tuple[str, bytes]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> tuple[str, bytes] | None:
        with self._lock:
            e = self._entries.get(key)
            if e is not None:
                self._entries.move_to_end(key)
            return e

    def set(self, key: str, etag: str, body: bytes) -> None:
        with self._lock:
            self._entries[key] = (etag, body)
            self._entries.move_to_end(key)
            while len(self._entries) > self._size:
                self._entries.popitem(last=False)


class _Config:
    """Settings and state shared by a client and its with_dynasty copies."""

    def __init__(
        self,
        api_key: str,
        base_url: str | None,
        base_path: str,
        timeout: float,
        max_retries: int,
        max_retry_wait: float,
        etag_cache: bool | int,
        headers: dict[str, str] | None,
    ):
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/") + base_path
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_retry_wait = max_retry_wait
        size = 0 if etag_cache is False else 256 if etag_cache is True else int(etag_cache)
        self.cache = _EtagCache(size) if size > 0 else None
        self.headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": f"cfb27-dynasty-python/{__version__}",
            **(headers or {}),
        }


class _Prepared:
    def __init__(self, cfg: _Config, dynasty_id: int | None, method: str, path: str, query, body):
        self.method = method
        self.url = cfg.base_url + path
        self.params = {k: _query_value(v) for k, v in (query or {}).items() if v is not None}
        self.headers = dict(cfg.headers)
        if dynasty_id is not None:
            self.headers["Dynasty-Id"] = str(dynasty_id)
        self.content: bytes | None = None
        if body is not None:
            clean = {k: _jsonable(v) for k, v in body.items() if v is not None}
            self.content = json.dumps(clean).encode()
            self.headers["Content-Type"] = "application/json"
        self.cache_key = None
        self.cached = None
        if method == "GET" and cfg.cache is not None:
            qs = "&".join(f"{k}={v}" for k, v in sorted(self.params.items()))
            self.cache_key = f"{dynasty_id or ''} {self.url}?{qs}"
            self.cached = cfg.cache.get(self.cache_key)
            if self.cached:
                self.headers["If-None-Match"] = self.cached[0]

    def outcome(self, cfg: _Config, res: httpx.Response, attempt: int, response: type[M] | None):
        """Returns ("done", value), ("retry", seconds) or raises an APIError."""
        if res.status_code == 304 and self.cached:
            return "done", self._parse(self.cached[1], response)
        if res.status_code == 204:
            return "done", None
        if res.is_success:
            etag = res.headers.get("ETag")
            if self.cache_key and etag and cfg.cache is not None:
                cfg.cache.set(self.cache_key, etag, res.content)
            return "done", self._parse(res.content, response)
        retry_after = _retry_after(res.headers.get("Retry-After"))
        retryable = (
            res.status_code == 429 and retry_after is not None and retry_after <= cfg.max_retry_wait
        ) or (self.method == "GET" and res.status_code in (502, 503, 504))
        if retryable and attempt < cfg.max_retries:
            return "retry", retry_after if retry_after is not None else _backoff(attempt)
        try:
            body: Any = res.json()
        except ValueError:
            body = res.text
        code, message = f"http_{res.status_code}", res.reason_phrase or f"HTTP {res.status_code}"
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            code = body["error"].get("code") or code
            message = body["error"].get("message") or message
        raise error_for(res.status_code, code, message, retry_after, body)

    @staticmethod
    def _parse(content: bytes, response: type[M] | None):
        if response is None or not content:
            return None
        return response.model_validate_json(content)


class SyncTransport:
    _cfg: _Config
    _dynasty_id: int | None
    _http: httpx.Client

    def _init_transport(self, cfg: _Config, http_client: httpx.Client | None, dynasty_id: int | None) -> None:
        self._cfg = cfg
        self._dynasty_id = dynasty_id
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client()

    def _request(self, method: str, path: str, *, query=None, body=None, response=None, timeout=None):
        cfg = self._cfg
        req = _Prepared(cfg, self._dynasty_id, method, path, query, body)
        attempt = 0
        while True:
            try:
                res = self._http.request(
                    method, req.url, params=req.params, headers=req.headers, content=req.content,
                    timeout=timeout or cfg.timeout,
                )
            except httpx.TransportError as e:
                if method == "GET" and attempt < cfg.max_retries:
                    time.sleep(_backoff(attempt))
                    attempt += 1
                    continue
                raise ConnectionError(f"{method} {req.url} failed: {e}") from e
            kind, value = req.outcome(cfg, res, attempt, response)
            if kind == "done":
                return value
            time.sleep(value)
            attempt += 1

    def close(self) -> None:
        """Closes the HTTP client if this client created it."""
        if self._owns_http:
            self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class AsyncTransport:
    _cfg: _Config
    _dynasty_id: int | None
    _http: httpx.AsyncClient

    def _init_transport(self, cfg: _Config, http_client: httpx.AsyncClient | None, dynasty_id: int | None) -> None:
        self._cfg = cfg
        self._dynasty_id = dynasty_id
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient()

    async def _request(self, method: str, path: str, *, query=None, body=None, response=None, timeout=None):
        cfg = self._cfg
        req = _Prepared(cfg, self._dynasty_id, method, path, query, body)
        attempt = 0
        while True:
            try:
                res = await self._http.request(
                    method, req.url, params=req.params, headers=req.headers, content=req.content,
                    timeout=timeout or cfg.timeout,
                )
            except httpx.TransportError as e:
                if method == "GET" and attempt < cfg.max_retries:
                    await asyncio.sleep(_backoff(attempt))
                    attempt += 1
                    continue
                raise ConnectionError(f"{method} {req.url} failed: {e}") from e
            kind, value = req.outcome(cfg, res, attempt, response)
            if kind == "done":
                return value
            await asyncio.sleep(value)
            attempt += 1

    async def aclose(self) -> None:
        """Closes the HTTP client if this client created it."""
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()
