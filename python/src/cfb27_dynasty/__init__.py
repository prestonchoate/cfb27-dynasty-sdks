"""Typed client for the CFB 27 Dynasty API."""

from . import models
from ._clients import AsyncDynastyClient, AsyncPartnerClient, DynastyClient, PartnerClient
from ._transport import DEFAULT_BASE_URL
from ._version import __version__
from .errors import (
    AuthenticationError,
    BadRequestError,
    ConflictError,
    ConnectionError,
    DynastyAPIError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "AsyncDynastyClient",
    "AsyncPartnerClient",
    "AuthenticationError",
    "BadRequestError",
    "ConflictError",
    "ConnectionError",
    "DynastyAPIError",
    "DynastyClient",
    "NotFoundError",
    "PartnerClient",
    "PermissionDeniedError",
    "RateLimitError",
    "ServerError",
    "__version__",
    "models",
]
