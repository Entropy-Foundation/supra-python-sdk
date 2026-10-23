# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

"""Offline tests of the defaults of a transaction: sequence number, max gas and expiration time."""

import asyncio
import time
import unittest
from collections.abc import Callable
from typing import Any
from unittest import mock

import httpx

from supra_sdk.account import Account
from supra_sdk.account_address import AccountAddress
from supra_sdk.bcs import Serializer
from supra_sdk.clients.api_client import ApiError
from supra_sdk.clients.rest import SupraClient, SupraClientConfig
from supra_sdk.clients.rest.transaction_defaults import EXPIRATION_MARGIN_SECONDS
from supra_sdk.transactions import (
    EntryFunction,
    TransactionArgument,
    TransactionPayload,
)
from supra_sdk.type_tag import StructTag, TypeTag

PREFIX = "/rpc/v3"
GAS_PRICE = 100_000


class FakeNode:
    """A node that answers the requests of transaction building and records them."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []
        self.sequence_number = 7
        self.balance = 10 * 100_000_000
        self.max_ttl = 600
        self.simulation: Callable[[], httpx.Response] = lambda: httpx.Response(
            200, json=simulation_result(988)
        )

    def count(self, method: str, path: str) -> int:
        return self.requests.count((method, path))

    def handler(self, request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        self.requests.append(key)
        if key == ("GET", f"{PREFIX}/transactions/chain_id"):
            return httpx.Response(200, text="6")
        if key == ("GET", f"{PREFIX}/transactions/estimate_gas_price"):
            return httpx.Response(
                200, json={"min_configured_gas_price": GAS_PRICE, "mean_price": 1}
            )
        if key == ("GET", f"{PREFIX}/transactions/parameters"):
            return httpx.Response(
                200, json={"max_transaction_time_to_live_seconds": self.max_ttl}
            )
        if key[0] == "GET" and key[1].startswith(f"{PREFIX}/accounts/"):
            return httpx.Response(200, json={"sequence_number": self.sequence_number})
        if key == ("POST", f"{PREFIX}/view"):
            return httpx.Response(200, json={"result": [str(self.balance)]})
        if key == ("POST", f"{PREFIX}/transactions/simulate"):
            return self.simulation()
        return httpx.Response(404, text=f"unexpected {key}")


def simulation_result(gas_used: int, status: str = "Success") -> dict[str, Any]:
    return {
        "status": status,
        "output": {
            "Move": {"vm_status": "Executed successfully", "gas_used": gas_used}
        },
    }


def make_client(node: FakeNode, config: SupraClientConfig | None = None) -> SupraClient:
    client = SupraClient("http://node.test/", config)
    client.api_client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(node.handler)
    )
    return client


def transfer_payload() -> TransactionPayload:
    return TransactionPayload(
        EntryFunction.natural(
            "0x1::supra_account",
            "transfer_coins",
            [TypeTag(StructTag.from_str("0x1::supra_coin::SupraCoin"))],
            [
                TransactionArgument(
                    AccountAddress.from_str("0x" + "b0" * 32), Serializer.struct
                ),
                TransactionArgument(1, Serializer.u64),
            ],
        )
    )


class TestSequenceNumber(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_zero_makes_no_account_request(self):
        node = FakeNode()
        client = make_client(node)
        sender = Account.generate()
        raw = await client.create_raw_transaction(
            sender, transfer_payload(), sequence_number=0
        )
        self.assertEqual(raw.sequence_number, 0)
        self.assertEqual(
            [r for r in node.requests if "/accounts/" in r[1]],
            [],
        )
        await client.close()

    async def test_none_fetches_the_sequence_number(self):
        node = FakeNode()
        client = make_client(node)
        raw = await client.create_raw_transaction(
            Account.generate(), transfer_payload()
        )
        self.assertEqual(raw.sequence_number, 7)
        await client.close()


NOW = 1_700_000_000
PARAMETERS = ("GET", f"{PREFIX}/transactions/parameters")


async def build_at_fixed_time(client: SupraClient) -> int:
    with mock.patch.object(time, "time", return_value=NOW + 0.9):
        raw = await client.create_raw_transaction(
            Account.generate(), transfer_payload(), sequence_number=0
        )
    return raw.expiration_timestamps_secs


class TestExpiration(unittest.IsolatedAsyncioTestCase):
    async def test_default_expires_below_the_node_maximum_minus_the_margin(self):
        node = FakeNode()
        client = make_client(node)
        expiration = await build_at_fixed_time(client)
        self.assertLessEqual(expiration, NOW + 600 - EXPIRATION_MARGIN_SECONDS)
        self.assertEqual(expiration, NOW + 595)
        await client.close()

    async def test_default_follows_the_nodes_maximum(self):
        node = FakeNode()
        node.max_ttl = 120
        client = make_client(node)
        self.assertEqual(await build_at_fixed_time(client), NOW + 115)
        await client.close()

    async def test_explicit_ttl_is_kept_and_reads_no_parameters(self):
        node = FakeNode()
        client = make_client(node, SupraClientConfig(expiration_ttl=900))
        self.assertEqual(await build_at_fixed_time(client), NOW + 900)
        self.assertEqual(node.count(*PARAMETERS), 0)
        await client.close()

    async def test_parameters_are_read_once_per_client(self):
        node = FakeNode()
        client = make_client(node)
        await build_at_fixed_time(client)
        await build_at_fixed_time(client)
        await asyncio.gather(
            client.max_transaction_time_to_live(),
            client.max_transaction_time_to_live(),
        )
        self.assertEqual(node.count(*PARAMETERS), 1)
        await client.close()
        other_node = FakeNode()
        other = make_client(other_node)
        await build_at_fixed_time(other)
        self.assertEqual(other_node.count(*PARAMETERS), 1)
        await other.close()

    async def test_failed_parameters_read_raises_and_is_not_cached(self):
        node = FakeNode()
        client = make_client(node)
        original = node.handler

        def failing(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/transactions/parameters"):
                return httpx.Response(500, text="down")
            return original(request)

        client.api_client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(failing)
        )
        with self.assertRaises(ApiError):
            await client.max_transaction_time_to_live()
        client.api_client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(original)
        )
        self.assertEqual(await client.max_transaction_time_to_live(), 600)
        await client.close()


if __name__ == "__main__":
    unittest.main()
