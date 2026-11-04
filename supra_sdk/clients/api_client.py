# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

import asyncio
import contextlib
import json
import math
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC
from email.utils import parsedate_to_datetime
from http import HTTPStatus
from typing import Any

import httpx

from supra_sdk.metadata import Metadata

DEFAULT_TIMEOUT_SECONDS = 60.0
"""Default limit, in seconds, of each phase of a request: connecting, reading, writing and waiting for a connection
from the pool."""

OLDEST_BLOCK_HEADER = "x-supra-oldest-block"
"""Response header in which the node reports the height of the oldest block it still stores."""

HISTORY_INDEXED_FROM_HEADER = "x-supra-history-indexed-from"
"""Response header in which the node reports the lowest block height the account history covers."""

# Statuses after which a GET is repeated when `ApiClientConfig.retry` is set.
_RETRYABLE_STATUSES = frozenset(
    {
        HTTPStatus.REQUEST_TIMEOUT,
        HTTPStatus.TOO_MANY_REQUESTS,
        HTTPStatus.SERVICE_UNAVAILABLE,
    }
)

_DECIMAL = re.compile(r"[0-9]+")

# Beyond 64 doublings any base delay above zero exceeds every useful `max_delay_seconds`.
_MAX_BACKOFF_DOUBLINGS = 64

# Indirection so that tests can replace the wait between attempts.
_sleep = asyncio.sleep


@dataclass(frozen=True)
class RetryPolicy:
    """Policy for repeating GET requests that failed in a way that a later attempt can succeed.

    A GET request is repeated after a response with status 408, 429 or 503 and after a request timeout, until
    `attempts` requests in total have been sent. The wait before a repeat is the number of seconds the response asks
    for (the `retry_after_seconds` field of the body, otherwise the `Retry-After` header). When the response asks for
    nothing, the wait is `base_delay_seconds` doubled after each attempt. No wait is longer than `max_delay_seconds`:
    a response that asks for a longer wait is not repeated, and its error is raised at once. POST requests are never
    repeated, and neither is the faucet request.

    Attributes:
        attempts (int): Maximum number of requests sent, the first included. At least 1. Default to 3.
        max_delay_seconds (float): Longest wait, in seconds, before a repeat. Default to 10.
        base_delay_seconds (float): Wait, in seconds, before the first repeat when the response does not ask for one.
            Default to 0.25.

    Raises:
        ValueError: If `attempts` is not an integer of at least 1, or a delay is negative or not finite.

    """

    attempts: int = 3
    max_delay_seconds: float = 10.0
    base_delay_seconds: float = 0.25

    def __post_init__(self):
        if (
            isinstance(self.attempts, bool)
            or not isinstance(self.attempts, int)
            or self.attempts < 1
        ):
            raise ValueError(
                f"attempts must be an integer of at least 1, got {self.attempts!r}"
            )
        for name in ("max_delay_seconds", "base_delay_seconds"):
            value = getattr(self, name)
            if not _is_non_negative_number(value):
                raise ValueError(
                    f"{name} must be a finite number of at least 0, got {value!r}"
                )

    def backoff_seconds(self, attempt: int) -> float:
        """The wait before repeating attempt number `attempt` (counted from 1) when the response asks for none."""
        # The exponent is capped so that a large `attempts` cannot overflow a float.
        doublings = min(attempt - 1, _MAX_BACKOFF_DOUBLINGS)
        return min(self.max_delay_seconds, self.base_delay_seconds * 2.0**doublings)


@dataclass
class ApiClientConfig:
    """Holds configuration options related to the generic API client.

    Attributes:
        http2 (bool): Whether to use HTTP/2 for requests. Default to False.
        access_token (Optional[str]): Optional access token (JWT) for authentication. Default to None.
        timeout (float): Limit, in seconds, of each phase of a request: connecting, reading, writing and waiting for a
            free connection from the pool. A request that exceeds it raises `ClientTimeoutError`. Keyword only.
            Default to 60.
        retry (RetryPolicy | None): Policy for repeating GET requests after a 408, 429 or 503 response or a timeout.
            Keyword only. Default to None: no request is repeated.

    """

    http2: bool = False
    access_token: str | None = None
    timeout: float = field(default=DEFAULT_TIMEOUT_SECONDS, kw_only=True)
    retry: RetryPolicy | None = field(default=None, kw_only=True)

    def raise_if_access_token_not_exists(self):
        """Raise an error if the access token is not set.

        Checks whether `self.access_token` exists. If it does not, an
        `AuthorizationKeyNotSpecifiedError` is raised.

        Raises:
            AuthorizationKeyNotSpecifiedError: If `self.access_token` is missing or None.

        """
        if not self.access_token:
            raise AuthorizationKeyNotSpecifiedError


class ApiClient:
    """A generic API client for making HTTP requests, it acts as a base class for specific API clients.

    Attributes:
        _client (httpx.AsyncClient): HTTP client to send the http request.
        base_url (str): The base URL of the API, always ending in `/`. A path prefix such as
            `https://host/prefix` is kept: requests go to `https://host/prefix/rpc/v3/...`.
        api_client_config (ApiClientConfig): Configuration options for API client.

    """

    _client: httpx.AsyncClient
    base_url: str
    api_client_config: ApiClientConfig

    def __init__(
        self,
        base_url: str,
        api_client_config: ApiClientConfig | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        """Initializes the API client.

        Args:
            base_url (str): The base URL of the API: scheme, host and an optional path prefix. It must not contain a
                query string or a fragment; pass an access token through `ApiClientConfig` instead.
            api_client_config (ApiClientConfig): Configuration options for API client. Default to None.
            transport (httpx.AsyncBaseTransport | None): Optional HTTP transport, e.g. `httpx.MockTransport` in tests.
                Default to None, which uses httpx's default network transport.

        Raises:
            ValueError: If `base_url` contains a query string or a fragment, or `api_client_config.timeout` is not a
                finite number greater than 0.

        """
        if "?" in base_url or "#" in base_url:
            raise ValueError(
                f"base_url must not contain a query string or a fragment: {base_url!r}"
            )
        api_client_config = api_client_config or ApiClientConfig()
        timeout_seconds = api_client_config.timeout
        if not _is_non_negative_number(timeout_seconds) or timeout_seconds == 0:
            raise ValueError(
                f"timeout must be a finite number of seconds greater than 0, got {timeout_seconds!r}"
            )
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"
        limits = httpx.Limits()
        timeout = httpx.Timeout(timeout_seconds)
        headers = {Metadata.SUPRA_HEADER: Metadata.get_supra_header_val()}
        self._client = httpx.AsyncClient(
            http2=api_client_config.http2,
            limits=limits,
            timeout=timeout,
            headers=headers,
            transport=transport,
        )
        self.api_client_config = api_client_config

    def _url(self, endpoint: str) -> str:
        """Appends a relative endpoint to the base URL, keeping any path prefix of the base URL.

        Args:
            endpoint (str): Endpoint relative to the base URL. Its path values must already be percent-encoded.

        Returns:
            str: The full request URL.

        """
        return self.base_url + endpoint.lstrip("/")

    async def close(self):
        """Closes the HTTP client session."""
        await self._client.aclose()

    async def get(
        self,
        endpoint: str,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        strict_mode: bool | None = True,
        retryable: bool = True,
    ) -> httpx.Response:
        """Performs an asynchronous GET request.

        When `ApiClientConfig.retry` is set and `retryable` is true, the request is repeated under that policy after a
        408, 429 or 503 response or a timeout (see `RetryPolicy`). The response of the last attempt is returned or, in
        strict mode, raised as an error.

        Args:
            endpoint (str): Endpoint to call.
            headers (dict[str, str] | None): Optional headers. Default to None.
            params (dict[str, Any] | None): Optional query parameters. Default to None.
            strict_mode (bool | None): If enabled then raises an error when request response status
                code is not 200. Default to True.
            retryable (bool): Whether the request may be repeated under `ApiClientConfig.retry`. Pass False for a
                request that has an effect on the node. Default to True.

        Returns:
            httpx.Response: The response from the server.

        Raises:
            ApiError: In strict mode, if the status code is not 200. The subclass names the status: see `ApiError`.
            ClientTimeoutError: If the last attempt exceeded `ApiClientConfig.timeout`.

        """
        params = params or {}
        params = {key: val for key, val in params.items() if val is not None}
        headers = headers or {}

        if self.api_client_config.access_token:
            headers["Authorization"] = f"Bearer {self.api_client_config.access_token}"

        url = self._url(endpoint)
        policy = self.api_client_config.retry if retryable else None
        attempts = policy.attempts if policy else 1
        attempt = 1
        while True:
            last = attempt >= attempts
            try:
                response = await self._client.get(
                    url=url, params=params, headers=headers
                )
            except httpx.TimeoutException as error:
                if last or policy is None:
                    raise self._timeout_error(url, error) from error
                await _sleep(policy.backoff_seconds(attempt))
                attempt += 1
                continue
            if (
                last
                or policy is None
                or response.status_code not in _RETRYABLE_STATUSES
            ):
                break
            delay = policy.backoff_seconds(attempt)
            requested = retry_after_seconds(
                _json_or_none(response.text), response.headers
            )
            if requested is not None:
                if requested > policy.max_delay_seconds:
                    break
                delay = requested
            await _sleep(delay)
            attempt += 1

        if strict_mode and response.status_code != HTTPStatus.OK:
            raise api_error_from_response(response)
        return response

    async def post(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, Any] | None = None,
        data: dict[str, Any] | bytes | None = None,
        strict_mode: bool | None = True,
    ) -> httpx.Response:
        """Performs an asynchronous POST request.

        A POST request is sent once: it is never repeated under `ApiClientConfig.retry`.

        Args:
            endpoint (str): API endpoint.
            params (dict[str, Any] | None): Query parameters. Default to None.
            headers (dict[str, Any] | None): Request headers. Default to None.
            data (dict[str, Any] | bytes | None): POST body data. Default to None.
            strict_mode (bool | None): If enabled then raises an error when request response status code is not 200.
                Default to True.

        Returns:
            httpx.Response: The response from the server.

        Raises:
            ApiError: In strict mode, if the status code is not 200. The subclass names the status: see `ApiError`.
            ClientTimeoutError: If the request exceeded `ApiClientConfig.timeout`.

        """
        params = params or {}
        params = {key: val for key, val in params.items() if val is not None}
        headers = headers or {}

        content: str | bytes
        if not isinstance(data, bytes):
            headers["Content-Type"] = "application/json"
            content = json.dumps(data)
        else:
            content = data

        url = self._url(endpoint)
        try:
            response = await self._client.post(
                url=url,
                params=params,
                headers=headers,
                content=content,
            )
        except httpx.TimeoutException as error:
            raise self._timeout_error(url, error) from error
        if strict_mode and response.status_code != HTTPStatus.OK:
            raise api_error_from_response(response)
        return response

    def _timeout_error(
        self, url: str, error: httpx.TimeoutException
    ) -> "ClientTimeoutError":
        try:
            request: httpx.Request | None = error.request
        except RuntimeError:
            # httpx attaches the request to errors raised while sending one; this covers any it did not.
            request = None
        return ClientTimeoutError(
            url, self.api_client_config.timeout, type(error).__name__, request=request
        )


class ApiError(Exception):
    """Exception raised when the API returns a non-200 response.

    It is the base class of the errors for specific statuses, so `except ApiError` matches every error response:

    - `ApiNotFoundError`: 404.
    - `ApiRequestTimeoutError`: 408.
    - `ApiGoneError`: 410, with `oldest_block`.
    - `ApiRateLimitError`: 429, with `retry_after_seconds`.
    - `ApiServiceUnavailableError`: 503.
    - `UnexpectedResponseError`: a 200 response to `view` or `faucet` whose body does not have the expected shape.

    A request that exceeds the client's timeout raises `ClientTimeoutError`, which is not an `ApiError`.

    Attributes:
        message (str): The `message` field of the node's JSON error body. When the body has none, the response body
            itself, and when the body is empty, the HTTP reason phrase of the status.
        status_code (int): The HTTP status code returned.
        headers (httpx.Headers): The response headers (case-insensitive). Empty when the error was not built from a
            response.
        body (str): The response body as text.

    """

    message: str
    status_code: int
    headers: httpx.Headers
    body: str

    def __init__(
        self,
        message: str,
        status_code: int,
        headers: Mapping[str, str] | None = None,
        body: str | None = None,
    ):
        """Initialize the exception with message and response status code.

        Args:
            message (str): Error message.
            status_code (int): The HTTP status code returned.
            headers (Mapping[str, str] | None): The response headers. Default to None (no headers).
            body (str | None): The response body. Default to None, which uses `message`.

        """
        self.message = message
        self.status_code = status_code
        self.headers = httpx.Headers(headers)
        self.body = message if body is None else body
        super().__init__(f"{{message: {message}, status_code: {status_code}}}")


class ApiNotFoundError(ApiError):
    """Exception raised when the API returns 404: the requested account, resource, module, transaction or route is
    not available on the node.

    Nodes before `supra_node_v12.0.0` answer a missing account with 400 instead, which raises `ApiError`; they answer
    a missing resource with 404.
    """


class ApiRequestTimeoutError(ApiError):
    """Exception raised when the API returns 408: the server, or a gateway in front of it, stopped waiting for the
    request. A GET can be repeated, which `RetryPolicy` does when set."""


def parse_height_header(headers: Mapping[str, str], name: str) -> int | None:
    """Reads a block height from a response header.

    Args:
        headers (Mapping[str, str]): The response headers.
        name (str): Name of the header.

    Returns:
        int | None: The height, or `None` when the header is absent or its value, once stripped, is not decimal digits.

    """
    value = headers.get(name)
    if value is None or not _DECIMAL.fullmatch(value.strip()):
        return None
    # ValueError: more digits than `int` converts (`sys.get_int_max_str_digits`).
    with contextlib.suppress(ValueError):
        return int(value)
    return None


class ApiGoneError(ApiError):
    """Exception raised when the API returns 410: the requested data existed, but the node has pruned it.

    Attributes:
        oldest_block (int | None): Height of the oldest block the node still stores, from the `x-supra-oldest-block`
            response header; a request starting from that height can be answered. `None` when the header is absent or
            not a decimal integer.

    """

    oldest_block: int | None

    def __init__(
        self,
        message: str,
        status_code: int,
        headers: Mapping[str, str] | None = None,
        body: str | None = None,
    ):
        """Initialize the exception and read `oldest_block` from the headers.

        Args:
            message (str): Error message.
            status_code (int): The HTTP status code returned.
            headers (Mapping[str, str] | None): The response headers. Default to None (no headers).
            body (str | None): The response body. Default to None, which uses `message`.

        """
        super().__init__(message, status_code, headers, body)
        self.oldest_block = parse_height_header(self.headers, OLDEST_BLOCK_HEADER)


class ApiRateLimitError(ApiError):
    """Exception raised when the API returns 429: the caller sent too many requests, for example faucet requests
    for the same account.

    Attributes:
        retry_after_seconds (float | None): Number of seconds the server asks the caller to wait: the
            `retry_after_seconds` field of the JSON body, otherwise the `Retry-After` header (seconds or an HTTP
            date). `None` when the response gives neither.

    """

    retry_after_seconds: float | None

    def __init__(
        self,
        message: str,
        status_code: int,
        headers: Mapping[str, str] | None = None,
        body: str | None = None,
    ):
        """Initialize the exception and read `retry_after_seconds` from the body and the headers.

        Args:
            message (str): Error message.
            status_code (int): The HTTP status code returned.
            headers (Mapping[str, str] | None): The response headers. Default to None (no headers).
            body (str | None): The response body. Default to None, which uses `message`.

        """
        super().__init__(message, status_code, headers, body)
        self.retry_after_seconds = retry_after_seconds(
            _json_or_none(self.body), self.headers
        )


class ApiServiceUnavailableError(ApiError):
    """Exception raised when the API returns 503: the node cannot serve the request at the moment, for example
    because its transaction pool is full. The request can be repeated later."""


class UnexpectedResponseError(ApiError, KeyError):
    """Exception raised when a 200 response does not have the shape the SDK expects, such as a missing field.

    It is also a `KeyError`, which the SDK raised for a missing field before this class existed.

    Attributes:
        field (str): The field the SDK expected in the response body.

    """

    field: str

    def __init__(
        self, field: str, response: httpx.Response, problem: str | None = None
    ):
        """Initialize the exception from the response that lacks a usable `field`.

        Args:
            field (str): The field the SDK expected in the response body.
            response (httpx.Response): The response.
            problem (str | None): What is wrong with the response, completing the sentence "The response of <URL>
                ...". Defaults to "has no '<field>' field".

        """
        self.field = field
        if problem is None:
            problem = f"has no {field!r} field"
        super().__init__(
            f"The response of {_request_url(response)} {problem}",
            response.status_code,
            response.headers,
            response.text,
        )

    def __str__(self) -> str:
        # `KeyError.__str__` would quote the message.
        return Exception.__str__(self)


class ClientTimeoutError(httpx.TimeoutException):
    """Exception raised when a request exceeds `ApiClientConfig.timeout` in any phase: connecting, waiting for a
    connection from the pool, writing or reading.

    It is a `httpx.TimeoutException`, the error raised before this class existed, and not an `ApiError`: the server
    sent no response. Like the `httpx` error it replaces, it carries the request as `request`.

    Attributes:
        url (str): The request URL, without query parameters.
        timeout_seconds (float): The timeout that was exceeded.
        phase (str): Name of the `httpx` timeout that was raised: `ConnectTimeout`, `PoolTimeout`, `WriteTimeout` or
            `ReadTimeout`.

    """

    url: str
    timeout_seconds: float
    phase: str

    def __init__(
        self,
        url: str,
        timeout_seconds: float,
        phase: str,
        *,
        request: httpx.Request | None = None,
    ):
        """Initialize the exception with the request URL, the timeout and the phase that timed out.

        Args:
            url (str): The request URL, without query parameters.
            timeout_seconds (float): The timeout that was exceeded.
            phase (str): Name of the `httpx` timeout that was raised.
            request (httpx.Request | None): The request that timed out. Default to None.

        """
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.phase = phase
        super().__init__(
            f"Request to {url} timed out after {timeout_seconds} seconds ({phase})",
            request=request,
        )

    def __reduce__(self) -> tuple[Any, ...]:
        # The arguments of `__init__` differ from `self.args`, which holds the message only.
        return (
            type(self),
            (self.url, self.timeout_seconds, self.phase),
            self.__dict__,
        )


class AuthorizationKeyNotSpecifiedError(Exception):
    """Exception raised when consensus api endpoints are accessed without defining `access_token` in `ClientConfig`."""

    def __init__(self):
        """Initialize the exception with a default message."""
        super().__init__("Authorization key is not specified")


_ERRORS_BY_STATUS: dict[int, type[ApiError]] = {
    HTTPStatus.NOT_FOUND: ApiNotFoundError,
    HTTPStatus.REQUEST_TIMEOUT: ApiRequestTimeoutError,
    HTTPStatus.GONE: ApiGoneError,
    HTTPStatus.TOO_MANY_REQUESTS: ApiRateLimitError,
    HTTPStatus.SERVICE_UNAVAILABLE: ApiServiceUnavailableError,
}


def api_error_from_response(response: httpx.Response) -> ApiError:
    """Builds the error for a non-200 response: the subclass of `ApiError` for its status, or `ApiError` itself.

    Args:
        response (httpx.Response): The response.

    Returns:
        ApiError: The error, with the node's `message`, the status code, the headers and the body.

    """
    body = response.text
    error_class = _ERRORS_BY_STATUS.get(response.status_code, ApiError)
    return error_class(
        _error_message(body, response.status_code),
        response.status_code,
        response.headers,
        body,
    )


def retry_after_seconds(data: Any, headers: Mapping[str, str]) -> float | None:
    """The number of seconds an error response asks the caller to wait before repeating the request.

    Args:
        data (Any): The parsed JSON body, or None. Its `retry_after_seconds` field is used when present and is a
            finite, non-negative int or float (not a bool), or a string that `float()` accepts for such a value,
            for example `"1.5"`, `"1e3"` or `"1_000"`.
        headers (Mapping[str, str]): The response headers. Their `Retry-After` value, delta-seconds or an HTTP date,
            is used when the body has no `retry_after_seconds`.

    Returns:
        float | None: The number of seconds, or None when the response asks for no wait.

    """
    if isinstance(data, dict):
        value = data.get("retry_after_seconds")
        seconds = _seconds(value.strip() if isinstance(value, str) else value)
        if seconds is not None:
            return seconds

    header = httpx.Headers(headers).get("retry-after")
    if header is None:
        return None
    header = header.strip()
    if _DECIMAL.fullmatch(header):
        return _seconds(header)
    try:
        date = parsedate_to_datetime(header)
        if date.tzinfo is None:
            date = date.replace(tzinfo=UTC)
        return float(max(0, math.ceil(date.timestamp() - time.time())))
    except (TypeError, ValueError, OverflowError):
        return None


def _error_message(body: str, status_code: int) -> str:
    data = _json_or_none(body)
    if isinstance(data, dict):
        message = data.get("message")
        if isinstance(message, str) and message:
            return message
    if body:
        return body
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return f"HTTP {status_code}"


def _json_or_none(text: str) -> Any:
    # A body nested deeper than the interpreter's recursion limit raises RecursionError.
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        return None


def _seconds(value: Any) -> float | None:
    """`value` as a finite, non-negative number of seconds: from an int or a float, or a str in `float` syntax."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        seconds = float(value)
    except (ValueError, OverflowError):
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _is_non_negative_number(value: Any) -> bool:
    return not isinstance(value, str) and _seconds(value) is not None


def _request_url(response: httpx.Response) -> str:
    try:
        return str(response.request.url.copy_with(query=None))
    except RuntimeError:
        return "the request"
