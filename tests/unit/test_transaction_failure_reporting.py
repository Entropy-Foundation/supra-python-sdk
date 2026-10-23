# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

"""Offline tests for how the client reports failed, invalid and not-final transactions."""

import copy
import unittest
from collections.abc import Callable

import httpx

from supra_sdk import ed25519
from supra_sdk.account_address import AccountAddress
from supra_sdk.bcs import Serializer
from supra_sdk.clients.rest import (
    SupraClient,
    SupraClientConfig,
    TransactionFailedError,
    TransactionWaitTimeoutReachedError,
)
from supra_sdk.transactions import (
    EntryFunction,
    RawTransaction,
    SignedTransaction,
    TransactionArgument,
    TransactionPayload,
)
from supra_sdk.type_tag import StructTag, TypeTag

TX_HASH = "0x" + "ab" * 32
ABORT = "Move abort in 0x1::coin: EINSUFFICIENT_BALANCE(0x10006)"


def make_client(handler: Callable[[httpx.Request], httpx.Response]) -> SupraClient:
    client = SupraClient(
        "http://node.invalid/",
        SupraClientConfig(
            transaction_wait_time_in_seconds=0.5, polling_wait_time_in_seconds=0.01
        ),
    )
    client.api_client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )
    return client


def tx_data(status: str, vm_status: str | None = None) -> dict:
    output = {"Move": {"gas_used": 1, "events": [], "vm_status": vm_status}}
    return {
        "hash": TX_HASH,
        "status": status,
        "output": None if status == "Pending" else output,
    }


def make_signed_transaction() -> SignedTransaction:
    private_key = ed25519.PrivateKey.random()
    sender = AccountAddress.from_key(private_key.public_key())
    payload = EntryFunction.natural(
        "0x1::coin",
        "transfer",
        [TypeTag(StructTag.from_str("0x1::supra_coin::SupraCoin"))],
        [
            TransactionArgument(sender, Serializer.struct),
            TransactionArgument(1, Serializer.u64),
        ],
    )
    raw = RawTransaction(sender, 0, TransactionPayload(payload), 2000, 100, 2**63, 4)
    return SignedTransaction(raw, raw.sign(private_key))


class Node:
    """Fake node: submit returns the hash, polls return the queued responses in order."""

    def __init__(self, polls: list[httpx.Response]):
        self.polls = list(polls)
        self.poll_count = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/transactions/submit"):
            return httpx.Response(200, json=TX_HASH)
        self.poll_count += 1
        # The last response repeats once the queue is exhausted.
        return self.polls.pop(0) if len(self.polls) > 1 else self.polls[0]


def ok(data: dict) -> httpx.Response:
    return httpx.Response(200, json=data)


NOT_FOUND = httpx.Response(404, json={"error": "not found"})


class TestTransactionFailureReporting(unittest.IsolatedAsyncioTestCase):
    async def test_failed_transaction_raises_with_abort_text_and_hash(self):
        client = make_client(Node([ok(tx_data("Fail", ABORT))]))
        with self.assertRaises(TransactionFailedError) as ctx:
            await client.submit_transaction(make_signed_transaction())
        error = ctx.exception
        self.assertEqual(error.tx_hash, TX_HASH)
        self.assertEqual(error.status, "Fail")
        self.assertEqual(error.vm_status, ABORT)
        self.assertIn(ABORT, str(error))
        self.assertIn(TX_HASH, str(error))

    async def test_invalid_transaction_raises(self):
        client = make_client(Node([ok({"hash": TX_HASH, "status": "Invalid"})]))
        with self.assertRaises(TransactionFailedError) as ctx:
            await client.submit_transaction(make_signed_transaction())
        self.assertEqual(ctx.exception.status, "Invalid")
        self.assertIsNone(ctx.exception.vm_status)

    async def test_pending_after_execution_then_success(self):
        node = Node(
            [
                ok(tx_data("Pending")),
                ok(tx_data("PendingAfterExecution", "SEQUENCE_NUMBER_TOO_NEW")),
                ok(tx_data("Success", "Executed successfully")),
            ]
        )
        client = make_client(node)
        data = await client.wait_for_transaction(TX_HASH)
        self.assertEqual(data["status"], "Success")
        self.assertEqual(node.poll_count, 3)

    async def test_submit_returns_hash_and_and_wait_returns_data(self):
        client = make_client(Node([ok(tx_data("Success", "Executed successfully"))]))
        self.assertEqual(
            await client.submit_transaction(make_signed_transaction()), TX_HASH
        )
        data = await client.submit_transaction_and_wait(make_signed_transaction())
        self.assertEqual(data["status"], "Success")

    async def test_not_found_then_transaction(self):
        node = Node([NOT_FOUND, NOT_FOUND, ok(tx_data("Success", "ok"))])
        client = make_client(node)
        data = await client.wait_for_transaction(TX_HASH)
        self.assertEqual(data["hash"], TX_HASH)
        self.assertEqual(node.poll_count, 3)

    async def test_timeout_raises_with_hash_and_last_status(self):
        client = make_client(Node([ok(tx_data("PendingAfterExecution", "x"))]))
        with self.assertRaises(TransactionWaitTimeoutReachedError) as ctx:
            await client.wait_for_transaction(TX_HASH)
        self.assertEqual(ctx.exception.tx_hash, TX_HASH)
        self.assertEqual(ctx.exception.last_status, "PendingAfterExecution")

    async def test_timeout_when_never_found(self):
        client = make_client(Node([NOT_FOUND]))
        with self.assertRaises(TransactionWaitTimeoutReachedError) as ctx:
            await client.wait_for_transaction(TX_HASH)
        self.assertIsNone(ctx.exception.last_status)

    async def test_wait_for_faucet_keeps_polling_until_final(self):
        node = Node([NOT_FOUND, ok(tx_data("Pending")), ok(tx_data("Success", "ok"))])
        client = make_client(node)
        data = await client.wait_for_faucet(TX_HASH)
        self.assertEqual(data["status"], "Success")
        self.assertEqual(node.poll_count, 3)

    async def test_non_404_error_propagates(self):
        client = make_client(Node([httpx.Response(500, text="boom")]))
        from supra_sdk.clients.api_client import ApiError

        with self.assertRaises(ApiError):
            await client.wait_for_transaction(TX_HASH)

    async def test_failed_simulation_leaves_transaction_unchanged(self):
        client = make_client(lambda _: httpx.Response(500, text="boom"))
        signed = make_signed_transaction()
        authenticator = signed.authenticator
        before = copy.deepcopy(authenticator)
        self.assertTrue(signed.verify())
        with self.assertRaises(Exception):
            await client.simulate_transaction(signed)
        self.assertIs(signed.authenticator, authenticator)
        self.assertEqual(signed.authenticator, before)
        self.assertTrue(signed.verify())

    async def test_successful_simulation_leaves_transaction_unchanged(self):
        client = make_client(lambda _: httpx.Response(200, json=[{"x": 1}]))
        signed = make_signed_transaction()
        before = copy.deepcopy(signed.authenticator)
        await client.simulate_transaction(signed)
        self.assertEqual(signed.authenticator, before)
        self.assertTrue(signed.verify())


if __name__ == "__main__":
    unittest.main()
