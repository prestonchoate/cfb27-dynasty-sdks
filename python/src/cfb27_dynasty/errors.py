"""Errors raised by the clients."""

from __future__ import annotations

import builtins
from typing import Any


class DynastyAPIError(Exception):
    """An error response from the API. ``code`` is stable and machine-readable
    (for example ``not_found`` or ``rate_limited``)."""

    def __init__(self, status: int, code: str, message: str, retry_after: float | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retry_after = retry_after
        """Seconds from the Retry-After header, when present."""
        self.body = body

    def __str__(self) -> str:
        return f"{self.status} {self.code}: {self.message}"


class BadRequestError(DynastyAPIError):
    pass


class AuthenticationError(DynastyAPIError):
    pass


class PermissionDeniedError(DynastyAPIError):
    pass


class NotFoundError(DynastyAPIError):
    pass


class ConflictError(DynastyAPIError):
    pass


class RateLimitError(DynastyAPIError):
    pass


class ServerError(DynastyAPIError):
    pass


class ConnectionError(builtins.ConnectionError):  # noqa: A001
    """The request never got a response: network failure or timeout."""


_BY_STATUS = {
    400: BadRequestError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    429: RateLimitError,
}


def error_for(status: int, code: str, message: str, retry_after: float | None, body: Any) -> DynastyAPIError:
    cls = _BY_STATUS.get(status) or (ServerError if status >= 500 else DynastyAPIError)
    return cls(status, code, message, retry_after, body)
