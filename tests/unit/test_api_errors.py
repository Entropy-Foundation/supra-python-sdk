# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

"""Offline tests for the typed HTTP errors, the request timeout and the GET retry policy."""

import pickle
import unittest
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest import mock

import httpx

from supra_sdk.account_address import AccountAddress
from supra_sdk.clients import (
    ApiClient,
    ApiClientConfig,
    ApiError,
    ApiGoneError,
    ApiNotFoundError,
    ApiRateLimitError,
    ApiRequestTimeoutError,
    ApiServiceUnavailableError,
    ClientTimeoutError,
    RetryPolicy,
    UnexpectedResponseError,
)
from supra_sdk.clients.rest import SupraClient, SupraClientConfig

ADDRESS = AccountAddress.from_str("0x1")
ACCOUNT = {"sequence_number": "0", "authentication_key": "0x1"}

Handler = Callable[[httpx.Request], httpx.Response]


class Node:
    """Fake node that answers each request with the next queued response; the last one repeats."""

    def __init__(self, *responses: httpx.Response | Exception):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = (
            self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        )
        if isinstance(response, Exception):
            raise response
        return response


class Sleeps:
    """Records the waits between attempts instead of sleeping."""

    def __init__(self):
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


class ClientTestCase(unittest.IsolatedAsyncioTestCase):
    async def make_client(
        self, handler: Handler, config: SupraClientConfig | None = None
    ) -> SupraClient:
        client = SupraClient("http://node.invalid/", config)
        api_client_config = client.api_client.api_client_config
        await client.api_client.close()
        client.api_client = ApiClient(
            "http://node.invalid/",
            api_client_config,
            transport=httpx.MockTransport(handler),
        )
        self.addAsyncCleanup(client.close)
        return client

    def patch_sleep(self) -> Sleeps:
        sleeps = Sleeps()
        patcher = mock.patch("supra_sdk.clients.api_client._sleep", new=sleeps)
        patcher.start()
        self.addCleanup(patcher.stop)
        return sleeps


class ErrorTypeTests(ClientTestCase):
    async def asyncSetUp(self):
        self.node = Node(httpx.Response(200, json=ACCOUNT))
        self.client = await self.make_client(self.node)

    async def error_for(self, response: httpx.Response) -> ApiError:
        self.node.responses = [response]
        with self.assertRaises(ApiError) as ctx:
            await self.client.account(ADDRESS)
        return ctx.exception

    async def test_status_selects_the_error_class(self):
        cases = {
            400: ApiError,
            404: ApiNotFoundError,
            408: ApiRequestTimeoutError,
            410: ApiGoneError,
            429: ApiRateLimitError,
            500: ApiError,
            503: ApiServiceUnavailableError,
        }
        for status, error_class in cases.items():
            with self.subTest(status=status):
                error = await self.error_for(
                    httpx.Response(status, json={"message": "m"})
                )
                self.assertIs(type(error), error_class)
                self.assertEqual(error.status_code, status)

    async def test_message_is_the_node_message(self):
        # The body the node answers for a missing account.
        body = {"message": "Not Found: Resource not found: 0x1::account::Account"}
        error = await self.error_for(httpx.Response(404, json=body))
        self.assertEqual(error.message, body["message"])
        self.assertEqual(
            error.body,
            '{"message":"Not Found: Resource not found: 0x1::account::Account"}',
        )
        self.assertIn(body["message"], str(error))

    async def test_message_falls_back_to_the_body_then_the_reason_phrase(self):
        cases = [
            (httpx.Response(500, text="boom"), "boom"),
            (
                httpx.Response(404, json=["Information not available"]),
                '["Information not available"]',
            ),
            (httpx.Response(404, json={"message": ""}), '{"message":""}'),
            (httpx.Response(408, text=""), "Request Timeout"),
            (httpx.Response(599, text=""), "HTTP 599"),
        ]
        for response, message in cases:
            with self.subTest(message=message):
                error = await self.error_for(response)
                self.assertEqual(error.message, message)

    async def test_headers_are_kept(self):
        error = await self.error_for(
            httpx.Response(500, json={"message": "m"}, headers={"X-Custom": "v"})
        )
        self.assertEqual(error.headers["x-custom"], "v")

    async def test_rate_limit_retry_after_from_the_body(self):
        error = await self.error_for(
            httpx.Response(
                429,
                json={"message": "slow down", "retry_after_seconds": 76680},
                headers={"Retry-After": "5"},
            )
        )
        self.assertIsInstance(error, ApiRateLimitError)
        assert isinstance(error, ApiRateLimitError)
        self.assertEqual(error.retry_after_seconds, 76680)
        self.assertEqual(error.message, "slow down")

    async def test_rate_limit_retry_after_from_the_header(self):
        future = format_datetime(
            datetime.now(UTC) + timedelta(seconds=120), usegmt=True
        )
        cases = [
            ({"retry_after_seconds": "12"}, {}, 12),
            ({"message": "m"}, {"Retry-After": "30"}, 30),
            ({"retry_after_seconds": -1}, {"Retry-After": "7"}, 7),
            ({"retry_after_seconds": "x"}, {}, None),
            ({"message": "m"}, {"Retry-After": "soon"}, None),
            ({"message": "m"}, {}, None),
        ]
        for body, headers, expected in cases:
            with self.subTest(body=body, headers=headers):
                error = await self.error_for(
                    httpx.Response(429, json=body, headers=headers)
                )
                assert isinstance(error, ApiRateLimitError)
                self.assertEqual(error.retry_after_seconds, expected)
        error = await self.error_for(
            httpx.Response(429, text="", headers={"Retry-After": future})
        )
        assert isinstance(error, ApiRateLimitError)
        assert error.retry_after_seconds is not None
        self.assertTrue(115 <= error.retry_after_seconds <= 121)

    async def test_gone_oldest_block_from_the_header(self):
        cases = [
            ({"x-supra-oldest-block": "149399"}, 149399),
            ({}, None),
            ({"x-supra-oldest-block": "abc"}, None),
            ({"x-supra-oldest-block": "-5"}, None),
        ]
        for headers, expected in cases:
            with self.subTest(headers=headers):
                error = await self.error_for(
                    httpx.Response(410, json={"message": "pruned"}, headers=headers)
                )
                assert isinstance(error, ApiGoneError)
                self.assertEqual(error.oldest_block, expected)

    async def test_deeply_nested_body_is_kept_as_text(self):
        body = "[" * 100_000
        for status in (500, 429):
            with self.subTest(status=status):
                error = await self.error_for(httpx.Response(status, text=body))
                self.assertEqual(error.message, body)
        error = await self.error_for(httpx.Response(429, text=body))
        assert isinstance(error, ApiRateLimitError)
        self.assertIsNone(error.retry_after_seconds)

    async def test_out_of_range_numbers_are_ignored(self):
        huge = "1" + "0" * 400
        cases = [
            ('{"retry_after_seconds": ' + huge + "}", {}, None),
            ('{"retry_after_seconds": ' + "1" * 5000 + "}", {}, None),
            ('{"retry_after_seconds": "1e999"}', {}, None),
            ('{"retry_after_seconds": ' + huge + "}", {"Retry-After": "4"}, 4),
            ("{}", {"Retry-After": "9" * 500}, None),
            ("{}", {"Retry-After": "Fri, 31 Dec 99999 23:59:59 GMT"}, None),
        ]
        for body, headers, expected in cases:
            with self.subTest(body=body[:40], headers=headers):
                error = await self.error_for(
                    httpx.Response(429, text=body, headers=headers)
                )
                assert isinstance(error, ApiRateLimitError)
                self.assertEqual(error.retry_after_seconds, expected)
        error = await self.error_for(
            httpx.Response(410, text="{}", headers={"x-supra-oldest-block": "9" * 5000})
        )
        assert isinstance(error, ApiGoneError)
        self.assertIsNone(error.oldest_block)

    async def test_error_built_without_a_response(self):
        error = ApiError("text", 400)
        self.assertEqual(error.body, "text")
        self.assertEqual(len(error.headers), 0)
        self.assertEqual(str(error), "{message: text, status_code: 400}")


class UnexpectedResponseTests(ClientTestCase):
    async def test_view_without_result_names_the_field(self):
        for response in (
            httpx.Response(200, json={"other": 1}),
            httpx.Response(200, json=[1]),
            httpx.Response(200, text="not json"),
        ):
            with self.subTest(body=response.text):
                client = await self.make_client(Node(response))
                with self.assertRaises(UnexpectedResponseError) as ctx:
                    await client.view("0x1::m::f", [], [])
                error = ctx.exception
                self.assertIsInstance(error, KeyError)
                self.assertIsInstance(error, ApiError)
                self.assertEqual(error.field, "result")
                self.assertEqual(error.status_code, 200)
                self.assertIn("'result'", str(error))
                self.assertIn("rpc/v3/view", str(error))

    async def test_view_result_is_returned(self):
        client = await self.make_client(
            Node(httpx.Response(200, json={"result": ["1"]}))
        )
        self.assertEqual(await client.view("0x1::m::f", [], []), ["1"])


class TimeoutTests(ClientTestCase):
    async def test_timeout_sets_every_phase_including_the_pool(self):
        node = Node(httpx.Response(200, json=ACCOUNT))
        client = await self.make_client(node, SupraClientConfig(timeout=5))
        timeout = client.api_client._client.timeout
        self.assertEqual(
            (timeout.connect, timeout.read, timeout.write, timeout.pool),
            (5, 5, 5, 5),
        )
        await client.account(ADDRESS)
        self.assertEqual(
            node.requests[0].extensions["timeout"],
            {"connect": 5, "read": 5, "write": 5, "pool": 5},
        )

    async def test_default_timeout_is_60_seconds_with_a_pool_limit(self):
        client = ApiClient("http://node.invalid/")
        self.addAsyncCleanup(client.close)
        self.assertEqual(client._client.timeout.read, 60)
        self.assertEqual(client._client.timeout.pool, 60)

    async def test_invalid_timeout_is_rejected(self):
        for value in (0, -1, float("inf"), float("nan"), True, 10**400, "5"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ApiClient("http://node.invalid/", ApiClientConfig(timeout=value))  # type: ignore[arg-type]

    async def test_timeout_raises_client_timeout_error(self):
        node = Node(httpx.ReadTimeout("read timed out"))
        client = await self.make_client(node, SupraClientConfig(timeout=2))
        with self.assertRaises(ClientTimeoutError) as ctx:
            await client.account(ADDRESS)
        self.assertIsInstance(ctx.exception, httpx.TimeoutException)
        self.assertEqual(ctx.exception.timeout_seconds, 2)
        self.assertEqual(ctx.exception.phase, "ReadTimeout")
        self.assertEqual(len(node.requests), 1)

    async def test_timeout_error_keeps_the_request(self):
        node = Node(httpx.ReadTimeout("read timed out"))
        client = await self.make_client(node)
        with self.assertRaises(httpx.TimeoutException) as ctx:
            await client.account(ADDRESS)
        self.assertIs(ctx.exception.request, node.requests[0])
        self.assertEqual(
            str(ctx.exception.request.url), "http://node.invalid/rpc/v3/accounts/0x1"
        )

    async def test_timeout_error_pickles(self):
        node = Node(httpx.ReadTimeout("read timed out"))
        client = await self.make_client(node, SupraClientConfig(timeout=2))
        with self.assertRaises(ClientTimeoutError) as ctx:
            await client.account(ADDRESS)
        restored = pickle.loads(pickle.dumps(ctx.exception))
        self.assertIsInstance(restored, ClientTimeoutError)
        self.assertEqual(str(restored), str(ctx.exception))
        self.assertEqual(restored.url, ctx.exception.url)
        self.assertEqual(restored.timeout_seconds, 2)
        self.assertEqual(restored.phase, "ReadTimeout")
        self.assertEqual(restored.request.url, ctx.exception.request.url)
        without_request = ClientTimeoutError("http://x/", 1, "PoolTimeout")
        restored = pickle.loads(pickle.dumps(without_request))
        self.assertEqual(str(restored), str(without_request))
        with self.assertRaises(RuntimeError):
            _ = restored.request

    async def test_post_timeout_raises_client_timeout_error(self):
        node = Node(httpx.ConnectTimeout("connect timed out"))
        client = await self.make_client(node, SupraClientConfig(retry=RetryPolicy()))
        with self.assertRaises(ClientTimeoutError):
            await client.view("0x1::m::f", [], [])
        self.assertEqual(len(node.requests), 1)


class RetryTests(ClientTestCase):
    async def test_retry_policy_validation(self):
        for kwargs in (
            {"attempts": 0},
            {"attempts": 1.5},
            {"attempts": True},
            {"max_delay_seconds": -1},
            {"base_delay_seconds": float("inf")},
            {"max_delay_seconds": 10**400},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                RetryPolicy(**kwargs)  # type: ignore[arg-type]

    async def test_get_is_not_retried_by_default(self):
        node = Node(httpx.Response(408, text=""), httpx.Response(200, json=ACCOUNT))
        client = await self.make_client(node)
        with self.assertRaises(ApiRequestTimeoutError):
            await client.account(ADDRESS)
        self.assertEqual(len(node.requests), 1)

    async def test_408_then_200_returns_the_200_body(self):
        sleeps = self.patch_sleep()
        node = Node(httpx.Response(408, text=""), httpx.Response(200, json=ACCOUNT))
        client = await self.make_client(node, SupraClientConfig(retry=RetryPolicy()))
        self.assertEqual(await client.account(ADDRESS), ACCOUNT)
        self.assertEqual(len(node.requests), 2)
        self.assertEqual(sleeps.delays, [0.25])

    async def test_timeout_then_200_returns_the_200_body(self):
        self.patch_sleep()
        node = Node(
            httpx.ReadTimeout("read timed out"), httpx.Response(200, json=ACCOUNT)
        )
        client = await self.make_client(node, SupraClientConfig(retry=RetryPolicy()))
        self.assertEqual(await client.account(ADDRESS), ACCOUNT)
        self.assertEqual(len(node.requests), 2)

    async def test_attempts_are_bounded_with_exponential_backoff(self):
        sleeps = self.patch_sleep()
        node = Node(httpx.Response(503, json={"message": "busy"}))
        policy = RetryPolicy(attempts=4, base_delay_seconds=1, max_delay_seconds=3)
        client = await self.make_client(node, SupraClientConfig(retry=policy))
        with self.assertRaises(ApiServiceUnavailableError) as ctx:
            await client.account(ADDRESS)
        self.assertEqual(ctx.exception.message, "busy")
        self.assertEqual(len(node.requests), 4)
        self.assertEqual(sleeps.delays, [1, 2, 3])

    async def test_timeouts_are_bounded_and_no_wait_follows_the_last(self):
        sleeps = self.patch_sleep()
        node = Node(httpx.ReadTimeout("read timed out"))
        client = await self.make_client(
            node, SupraClientConfig(retry=RetryPolicy(attempts=3))
        )
        with self.assertRaises(ClientTimeoutError):
            await client.account(ADDRESS)
        self.assertEqual(len(node.requests), 3)
        self.assertEqual(sleeps.delays, [0.25, 0.5])

    async def test_backoff_of_a_large_attempt_number_is_capped(self):
        policy = RetryPolicy(attempts=10**6, max_delay_seconds=7)
        self.assertEqual(policy.backoff_seconds(10**6), 7)
        self.assertEqual(RetryPolicy(base_delay_seconds=0).backoff_seconds(10**6), 0)

    async def test_retry_after_on_a_503_is_honoured(self):
        sleeps = self.patch_sleep()
        node = Node(
            httpx.Response(503, json={"message": "m"}, headers={"Retry-After": "3"}),
            httpx.Response(200, json=ACCOUNT),
        )
        client = await self.make_client(node, SupraClientConfig(retry=RetryPolicy()))
        self.assertEqual(await client.account(ADDRESS), ACCOUNT)
        self.assertEqual(sleeps.delays, [3])

    async def test_http_date_retry_after_is_honoured(self):
        sleeps = self.patch_sleep()
        date = format_datetime(datetime.now(UTC) + timedelta(seconds=5), usegmt=True)
        node = Node(
            httpx.Response(429, json={"message": "m"}, headers={"Retry-After": date}),
            httpx.Response(200, json=ACCOUNT),
        )
        client = await self.make_client(node, SupraClientConfig(retry=RetryPolicy()))
        self.assertEqual(await client.account(ADDRESS), ACCOUNT)
        self.assertEqual(len(sleeps.delays), 1)
        self.assertTrue(3 <= sleeps.delays[0] <= 6)

    async def test_retry_after_is_honoured(self):
        sleeps = self.patch_sleep()
        node = Node(
            httpx.Response(429, json={"message": "m", "retry_after_seconds": 2}),
            httpx.Response(429, json={"message": "m"}, headers={"Retry-After": "1"}),
            httpx.Response(200, json=ACCOUNT),
        )
        client = await self.make_client(node, SupraClientConfig(retry=RetryPolicy()))
        self.assertEqual(await client.account(ADDRESS), ACCOUNT)
        self.assertEqual(sleeps.delays, [2, 1])

    async def test_retry_after_above_the_cap_is_raised_at_once(self):
        sleeps = self.patch_sleep()
        node = Node(
            httpx.Response(429, json={"message": "m", "retry_after_seconds": 76680}),
            httpx.Response(200, json=ACCOUNT),
        )
        client = await self.make_client(node, SupraClientConfig(retry=RetryPolicy()))
        with self.assertRaises(ApiRateLimitError) as ctx:
            await client.account(ADDRESS)
        self.assertEqual(ctx.exception.retry_after_seconds, 76680)
        self.assertEqual(len(node.requests), 1)
        self.assertEqual(sleeps.delays, [])

    async def test_other_errors_are_not_retried(self):
        self.patch_sleep()
        node = Node(httpx.Response(200, json=ACCOUNT))
        client = await self.make_client(node, SupraClientConfig(retry=RetryPolicy()))
        for status in (400, 404, 410, 500, 502):
            with self.subTest(status=status):
                node.responses = [httpx.Response(status, json={"message": "m"})]
                node.requests = []
                with self.assertRaises(ApiError):
                    await client.account(ADDRESS)
                self.assertEqual(len(node.requests), 1)

    async def test_post_is_never_retried(self):
        sleeps = self.patch_sleep()
        node = Node(httpx.Response(200, json={"result": []}))
        client = await self.make_client(node, SupraClientConfig(retry=RetryPolicy()))
        for status in (408, 429, 503):
            with self.subTest(status=status):
                node.responses = [httpx.Response(status, json={"message": "m"})]
                node.requests = []
                with self.assertRaises(ApiError):
                    await client.view("0x1::m::f", [], [])
                with self.assertRaises(ApiError):
                    await client.submit(b"\x00")
                self.assertEqual(len(node.requests), 2)
                self.assertTrue(all(r.method == "POST" for r in node.requests))
        self.assertEqual(sleeps.delays, [])

    async def test_non_strict_get_returns_the_last_response(self):
        self.patch_sleep()
        node = Node(httpx.Response(503, text="busy"))
        client = await self.make_client(
            node, SupraClientConfig(retry=RetryPolicy(attempts=2))
        )
        response = await client.api_client.get("rpc/v3/x", strict_mode=False)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(len(node.requests), 2)


if __name__ == "__main__":
    unittest.main()
