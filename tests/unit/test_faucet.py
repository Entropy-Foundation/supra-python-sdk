# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

"""Offline tests for the faucet request."""

import unittest
from unittest import mock

import httpx

from supra_sdk.account_address import AccountAddress
from supra_sdk.clients import (
    ApiClient,
    ApiRateLimitError,
    ApiServiceUnavailableError,
    RetryPolicy,
    UnexpectedResponseError,
)
from supra_sdk.clients.rest import (
    FaucetRequestNotAcceptedError,
    SupraClient,
    SupraClientConfig,
)

ADDRESS = AccountAddress.from_str("0x1")


class FaucetTests(unittest.IsolatedAsyncioTestCase):
    async def make_client(
        self, *responses: httpx.Response, config: SupraClientConfig | None = None
    ) -> SupraClient:
        self.requests: list[httpx.Request] = []
        self.queue = list(responses)

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self.queue.pop(0) if len(self.queue) > 1 else self.queue[0]

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

    async def test_try_later_without_waiting_returns_none(self):
        client = await self.make_client(httpx.Response(200, json="TryLater"))
        self.assertIsNone(await client.faucet(ADDRESS, wait_for_faucet=False))
        self.assertEqual(len(self.requests), 1)

    async def test_try_later_with_waiting_raises_not_accepted(self):
        client = await self.make_client(httpx.Response(200, json="TryLater"))
        with self.assertRaises(FaucetRequestNotAcceptedError):
            await client.faucet(ADDRESS)
        self.assertEqual(len(self.requests), 1)

    async def test_accepted_without_waiting_returns_the_hash(self):
        tx_hash = "0x" + "ab" * 32
        client = await self.make_client(httpx.Response(200, json={"Accepted": tx_hash}))
        self.assertEqual(await client.faucet(ADDRESS, wait_for_faucet=False), tx_hash)

    async def test_unexpected_body_raises(self):
        bodies = [
            httpx.Response(200, json="Something"),
            httpx.Response(200, json=5),
            httpx.Response(200, json=["Accepted"]),
            httpx.Response(200, json={}),
            httpx.Response(200, json={"Accepted": ""}),
            httpx.Response(200, json={"Accepted": 5}),
            httpx.Response(200, json={"Accepted": None}),
            httpx.Response(200, text="<html>gateway</html>"),
            httpx.Response(200, text="[" * 100_000),
        ]
        client = await self.make_client(bodies[0])
        for response in bodies:
            for wait_for_faucet in (False, True):
                with self.subTest(body=response.text[:40], wait=wait_for_faucet):
                    self.queue = [response]
                    with self.assertRaises(UnexpectedResponseError) as ctx:
                        await client.faucet(ADDRESS, wait_for_faucet=wait_for_faucet)
                    self.assertEqual(ctx.exception.field, "Accepted")

    async def test_rate_limit_is_typed(self):
        # The node's body for an address inside the cooldown; the gateway may add `retry_after_seconds`.
        client = await self.make_client(
            httpx.Response(
                429,
                json={
                    "message": "Account 0x1 recently received some tokens. Please try again in 60s.",
                    "retry_after_seconds": 60,
                },
            )
        )
        with self.assertRaises(ApiRateLimitError) as ctx:
            await client.faucet(ADDRESS, wait_for_faucet=False)
        self.assertEqual(ctx.exception.retry_after_seconds, 60)
        self.assertIn("recently received some tokens", ctx.exception.message)

    async def test_faucet_request_is_never_retried(self):
        sleep = mock.AsyncMock()
        with mock.patch("supra_sdk.clients.api_client._sleep", new=sleep):
            client = await self.make_client(
                httpx.Response(503, json={"message": "m"}),
                httpx.Response(200, json={"Accepted": "0x" + "ab" * 32}),
                config=SupraClientConfig(retry=RetryPolicy()),
            )
            with self.assertRaises(ApiServiceUnavailableError):
                await client.faucet(ADDRESS, wait_for_faucet=False)
        self.assertEqual(len(self.requests), 1)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
