# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

"""Offline tests of the defaults of a transaction: sequence number, max gas and expiration time."""

import asyncio
import json
import time
import unittest
from collections.abc import Callable
from typing import Any
from unittest import mock

import httpx

from supra_sdk.account import Account
from supra_sdk.account_address import AccountAddress
from supra_sdk.authenticator import FeePayerAuthenticator
from supra_sdk.bcs import Deserializer, Serializer
from supra_sdk.clients.api_client import ApiError
from supra_sdk.clients.rest import MaxGasEstimationError, SupraClient, SupraClientConfig
from supra_sdk.clients.rest.transaction_defaults import (
    EXPIRATION_MARGIN_SECONDS,
    FALLBACK_MAX_GAS_AMOUNT,
    MIN_ESTIMATED_MAX_GAS_AMOUNT,
)
from supra_sdk.transactions import (
    EntryFunction,
    SignedTransaction,
    SupraTransaction,
    TransactionArgument,
    TransactionPayload,
)
from supra_sdk.type_tag import StructTag, TypeTag


def decode_simulated(body: bytes) -> SignedTransaction:
    return SupraTransaction.deserialize(Deserializer(body)).value


PREFIX = "/rpc/v3"
GAS_PRICE = 100_000


class FakeNode:
    """A node that answers the requests of transaction building and records them."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []
        self.sequence_number = 7
        self.balance = 10 * 100_000_000
        self.max_ttl = 600
        self.balances: dict[str, int] = {}
        self.view_arguments: list[list[str]] = []
        self.simulated: list[bytes] = []
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
            arguments = json.loads(request.content)["arguments"]
            self.view_arguments.append(arguments)
            balance = self.balances.get(arguments[0], self.balance)
            return httpx.Response(200, json={"result": [str(balance)]})
        if key == ("POST", f"{PREFIX}/transactions/simulate"):
            self.simulated.append(request.content)
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


SIMULATE = ("POST", f"{PREFIX}/transactions/simulate")
VIEW = ("POST", f"{PREFIX}/view")


class TestMaxGas(unittest.IsolatedAsyncioTestCase):
    async def create(
        self,
        node: FakeNode,
        config: SupraClientConfig | None = None,
        **kwargs: Any,
    ):
        client = make_client(node, config)
        self.addAsyncCleanup(client.close)
        return await client.create_raw_transaction(
            Account.generate(), transfer_payload(), sequence_number=0, **kwargs
        )

    async def test_default_is_the_simulated_gas_used_with_the_margin(self):
        node = FakeNode()
        node.simulation = lambda: httpx.Response(200, json=simulation_result(4_000))
        raw = await self.create(node)
        self.assertEqual(raw.max_gas_amount, 6_000)
        self.assertEqual(node.count(*SIMULATE), 1)

    async def test_margin_rounds_up(self):
        node = FakeNode()
        node.simulation = lambda: httpx.Response(200, json=simulation_result(2_001))
        self.assertEqual((await self.create(node)).max_gas_amount, 3_002)

    async def test_small_gas_used_is_raised_to_the_minimum(self):
        node = FakeNode()
        node.simulation = lambda: httpx.Response(200, json=simulation_result(988))
        raw = await self.create(node)
        self.assertEqual(raw.max_gas_amount, MIN_ESTIMATED_MAX_GAS_AMOUNT)

    async def test_ten_supra_account_gets_an_affordable_default(self):
        node = FakeNode()
        node.balance = 10 * 100_000_000
        raw = await self.create(node)
        self.assertLessEqual(raw.max_gas_amount * raw.gas_unit_price, node.balance)

    async def test_default_is_capped_by_the_balance(self):
        node = FakeNode()
        node.balance = 1_000 * GAS_PRICE + 99_999
        node.simulation = lambda: httpx.Response(200, json=simulation_result(4_000))
        raw = await self.create(node)
        self.assertEqual(raw.max_gas_amount, 1_000)

    async def test_simulation_runs_with_the_affordable_max_gas(self):
        node = FakeNode()
        node.balance = 5_000 * GAS_PRICE
        await self.create(node)
        simulated = decode_simulated(node.simulated[0])
        self.assertEqual(simulated.transaction.max_gas_amount, 5_000)

    async def test_explicit_call_value_makes_no_simulation_or_balance_request(self):
        node = FakeNode()
        raw = await self.create(node, max_gas_amount=123_456)
        self.assertEqual(raw.max_gas_amount, 123_456)
        self.assertEqual(node.count(*SIMULATE), 0)
        self.assertEqual(node.count(*VIEW), 0)

    async def test_explicit_config_value_makes_no_simulation_request(self):
        node = FakeNode()
        raw = await self.create(node, SupraClientConfig(max_gas_amount=77_000))
        self.assertEqual(raw.max_gas_amount, 77_000)
        self.assertEqual(node.count(*SIMULATE), 0)

    async def test_call_value_overrides_config_value(self):
        node = FakeNode()
        raw = await self.create(
            node, SupraClientConfig(max_gas_amount=77_000), max_gas_amount=5
        )
        self.assertEqual(raw.max_gas_amount, 5)

    async def test_explicit_value_is_not_capped_by_the_balance(self):
        node = FakeNode()
        node.balance = 0
        raw = await self.create(node, max_gas_amount=500_000)
        self.assertEqual(raw.max_gas_amount, 500_000)

    async def test_failed_simulation_raises_with_its_status(self):
        node = FakeNode()
        result = simulation_result(10, "Fail")
        result["output"]["Move"]["vm_status"] = "Move abort in 0x1::coin: 0x10006"
        node.simulation = lambda: httpx.Response(200, json=result)
        with self.assertRaises(MaxGasEstimationError) as context:
            await self.create(node)
        self.assertEqual(context.exception.status, "Fail")
        self.assertIn("0x10006", context.exception.vm_status)
        self.assertIn("0x10006", str(context.exception))

    async def test_not_final_simulation_raises(self):
        node = FakeNode()
        node.simulation = lambda: httpx.Response(
            200, json=simulation_result(10, "PendingAfterExecution")
        )
        with self.assertRaises(MaxGasEstimationError):
            await self.create(node)

    async def test_rejected_simulation_request_raises(self):
        node = FakeNode()
        node.simulation = lambda: httpx.Response(400, text="bad transaction")
        with self.assertRaises(MaxGasEstimationError) as context:
            await self.create(node)
        self.assertIsInstance(context.exception.__cause__, ApiError)

    async def test_simulation_without_gas_used_raises(self):
        node = FakeNode()
        node.simulation = lambda: httpx.Response(
            200, json={"status": "Success", "output": {"Move": {"vm_status": "ok"}}}
        )
        with self.assertRaises(MaxGasEstimationError):
            await self.create(node)

    async def test_failed_balance_read_raises(self):
        node = FakeNode()
        original = node.handler

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/view"):
                return httpx.Response(500, text="down")
            return original(request)

        client = SupraClient("http://node.test/")
        client.api_client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )
        self.addAsyncCleanup(client.close)
        with self.assertRaises(MaxGasEstimationError):
            await client.create_raw_transaction(
                Account.generate(), transfer_payload(), sequence_number=0
            )

    async def test_balance_too_low_for_one_unit_raises(self):
        node = FakeNode()
        node.balance = GAS_PRICE - 1
        with self.assertRaises(MaxGasEstimationError):
            await self.create(node)
        self.assertEqual(node.count(*SIMULATE), 0)

    async def test_address_sender_gets_the_fallback_without_simulation(self):
        node = FakeNode()
        node.balance = 100 * 100_000_000
        client = make_client(node)
        self.addAsyncCleanup(client.close)
        address = Account.generate().address()
        raw = await client.create_raw_transaction(
            address, transfer_payload(), sequence_number=0
        )
        self.assertEqual(raw.max_gas_amount, FALLBACK_MAX_GAS_AMOUNT)
        self.assertEqual(node.count(*SIMULATE), 0)
        node.balance = 300 * GAS_PRICE
        raw = await client.create_raw_transaction(
            address, transfer_payload(), sequence_number=0
        )
        self.assertEqual(raw.max_gas_amount, 300)

    def pipelined_node(self, depends_on_uncommitted: bool = False) -> FakeNode:
        """A node whose account is at sequence number 3 and that refuses numbers above it."""
        node = FakeNode()
        node.sequence_number = 3

        def simulation() -> httpx.Response:
            number = decode_simulated(node.simulated[-1]).transaction.sequence_number
            if number > 3:
                return httpx.Response(
                    200,
                    json={
                        "status": "PendingAfterExecution",
                        "output": {
                            "Move": {
                                "gas_used": 0,
                                "vm_status": "Transaction Validation failed: "
                                "ValidationFailed(..., SEQUENCE_NUMBER_TOO_NEW)",
                            }
                        },
                    },
                )
            if depends_on_uncommitted:
                return httpx.Response(200, json=simulation_result(0, "Fail"))
            return httpx.Response(200, json=simulation_result(4_000))

        node.simulation = simulation
        return node

    async def test_too_new_number_is_simulated_at_the_chain_number(self):
        node = self.pipelined_node()
        client = make_client(node)
        self.addAsyncCleanup(client.close)
        signed = await client.create_signed_transaction(
            Account.generate(), transfer_payload(), sequence_number=5
        )
        self.assertEqual(signed.transaction.max_gas_amount, 6_000)
        self.assertEqual(signed.transaction.sequence_number, 5)
        self.assertTrue(signed.verify())
        numbers = [
            decode_simulated(body).transaction.sequence_number
            for body in node.simulated
        ]
        self.assertEqual(numbers, [5, 3])
        self.assertEqual(len([r for r in node.requests if "/accounts/" in r[1]]), 1)

    async def test_number_at_the_chain_number_is_simulated_once(self):
        node = self.pipelined_node()
        client = make_client(node)
        self.addAsyncCleanup(client.close)
        raw = await client.create_raw_transaction(
            Account.generate(), transfer_payload(), sequence_number=3
        )
        self.assertEqual(raw.sequence_number, 3)
        self.assertEqual(node.count(*SIMULATE), 1)

    async def test_failure_at_the_chain_number_raises(self):
        node = self.pipelined_node(depends_on_uncommitted=True)
        client = make_client(node)
        self.addAsyncCleanup(client.close)
        with self.assertRaises(MaxGasEstimationError) as context:
            await client.create_raw_transaction(
                Account.generate(), transfer_payload(), sequence_number=5
            )
        self.assertEqual(context.exception.status, "Fail")
        self.assertIn("set max_gas_amount", str(context.exception))
        self.assertEqual(node.count(*SIMULATE), 2)

    async def test_fee_payer_balance_caps_a_raw_transaction_of_an_empty_sender(self):
        node = FakeNode()
        sender, fee_payer = Account.generate(), Account.generate()
        node.balances[str(sender.address())] = 0
        node.balances[str(fee_payer.address())] = 800 * GAS_PRICE
        client = make_client(node)
        self.addAsyncCleanup(client.close)
        raw = await client.create_raw_transaction(
            sender, transfer_payload(), sequence_number=0, fee_payer=fee_payer
        )
        self.assertEqual(node.view_arguments, [[str(fee_payer.address())]])
        self.assertEqual(raw.max_gas_amount, 800)
        simulated = decode_simulated(node.simulated[0])
        self.assertIsInstance(
            simulated.authenticator.authenticator, FeePayerAuthenticator
        )

    async def test_fee_payer_without_a_balance_still_raises(self):
        node = FakeNode()
        sender, fee_payer = Account.generate(), Account.generate()
        node.balances[str(fee_payer.address())] = 0
        client = make_client(node)
        self.addAsyncCleanup(client.close)
        with self.assertRaises(MaxGasEstimationError):
            await client.create_raw_transaction(
                sender, transfer_payload(), sequence_number=0, fee_payer=fee_payer
            )

    async def test_fee_payer_address_gets_the_fallback_capped_by_its_balance(self):
        node = FakeNode()
        sender, fee_payer = Account.generate(), Account.generate()
        node.balances[str(sender.address())] = 0
        node.balances[str(fee_payer.address())] = 300 * GAS_PRICE
        client = make_client(node)
        self.addAsyncCleanup(client.close)
        raw = await client.create_raw_transaction(
            sender,
            transfer_payload(),
            sequence_number=0,
            fee_payer=fee_payer.address(),
        )
        self.assertEqual(raw.max_gas_amount, 300)
        self.assertEqual(node.count(*SIMULATE), 0)

    async def test_fee_payer_with_explicit_max_gas_reads_no_balance(self):
        node = FakeNode()
        client = make_client(node)
        self.addAsyncCleanup(client.close)
        await client.create_raw_transaction(
            Account.generate(),
            transfer_payload(),
            sequence_number=0,
            max_gas_amount=9,
            fee_payer=Account.generate(),
        )
        self.assertEqual(node.count(*VIEW), 0)

    async def test_example_style_transaction_for_an_address_serialises(self):
        """The multisig example builds its transactions this way: an address sender and an explicit max gas."""
        node = FakeNode()
        node.balance = 0
        client = make_client(node)
        self.addAsyncCleanup(client.close)
        raw = await client.create_raw_transaction(
            AccountAddress.from_str("0x" + "ab" * 32),
            transfer_payload(),
            sequence_number=1,
            max_gas_amount=20_000,
        )
        self.assertEqual(raw.max_gas_amount, 20_000)
        self.assertEqual(node.count(*VIEW), 0)
        serializer = Serializer()
        raw.serialize(serializer)
        self.assertGreater(len(serializer.output()), 0)

    async def test_signed_transaction_keeps_a_valid_signature(self):
        node = FakeNode()
        client = make_client(node)
        self.addAsyncCleanup(client.close)
        signed = await client.create_signed_transaction(
            Account.generate(), transfer_payload(), 0
        )
        self.assertTrue(signed.verify())
        self.assertEqual(node.count(*SIMULATE), 1)
        simulated = decode_simulated(node.simulated[0])
        self.assertFalse(simulated.verify())

    async def test_fee_payer_balance_pays_and_is_simulated(self):
        node = FakeNode()
        client = make_client(node)
        self.addAsyncCleanup(client.close)
        sender, fee_payer = Account.generate(), Account.generate()
        signed = await client.create_fee_payer_transaction(
            sender, fee_payer, [], transfer_payload()
        )
        self.assertEqual(node.view_arguments, [[str(fee_payer.address())]])
        self.assertEqual(node.count(*SIMULATE), 1)
        self.assertEqual(
            signed.transaction.max_gas_amount, MIN_ESTIMATED_MAX_GAS_AMOUNT
        )

    async def test_multi_agent_transaction_is_simulated(self):
        node = FakeNode()
        client = make_client(node)
        self.addAsyncCleanup(client.close)
        signed = await client.create_multi_agent_transaction(
            Account.generate(), [Account.generate()], transfer_payload()
        )
        self.assertEqual(node.count(*SIMULATE), 1)
        self.assertEqual(
            signed.transaction.max_gas_amount, MIN_ESTIMATED_MAX_GAS_AMOUNT
        )


if __name__ == "__main__":
    unittest.main()
