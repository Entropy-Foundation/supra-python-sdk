# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

"""Offline tests for how the client reports failed, invalid and not-final transactions."""

import asyncio
import copy
import time
import unittest
from collections.abc import Awaitable, Callable

import httpx

from supra_sdk import ed25519
from supra_sdk.account_address import AccountAddress
from supra_sdk.bcs import Serializer
from supra_sdk.clients.api_client import ApiError
from supra_sdk.clients.rest import (
    FaucetRequestNotAcceptedError,
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

Handler = Callable[[httpx.Request], httpx.Response | Awaitable[httpx.Response]]


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
    """Fake node: submit returns the hash, the faucet accepts, polls return the queued responses in order."""

    def __init__(self, polls: list[httpx.Response]):
        self.polls = list(polls)
        self.poll_count = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/transactions/submit"):
            return httpx.Response(200, json=TX_HASH)
        if "/wallet/faucet/" in path and "/transactions/" not in path:
            return httpx.Response(200, json={"Accepted": TX_HASH})
        self.poll_count += 1
        # The last response repeats once the queue is exhausted.
        return self.polls.pop(0) if len(self.polls) > 1 else self.polls[0]


def ok(data: dict) -> httpx.Response:
    return httpx.Response(200, json=data)


# What the node answers when it does not know a transaction hash.
NOT_FOUND = httpx.Response(
    404, json={"message": f"Information not available for {TX_HASH}"}
)
NOT_FOUND_WITH_REASON = httpx.Response(
    404, json={"message": f"Not Found: Cannot find transaction {TX_HASH}"}
)


class TestTransactionFailureReporting(unittest.IsolatedAsyncioTestCase):
    async def make_client(
        self,
        handler: Handler,
        wait: float = 0.5,
        poll: float = 0.01,
    ) -> SupraClient:
        client = SupraClient(
            "http://node.invalid/",
            SupraClientConfig(
                transaction_wait_time_in_seconds=wait,
                polling_wait_time_in_seconds=poll,
            ),
        )
        # Close the real httpx client the constructor created before swapping in the fake.
        await client.api_client.close()
        client.api_client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )
        self.addAsyncCleanup(client.close)
        return client

    async def test_failed_transaction_raises_with_abort_text_and_hash(self):
        client = await self.make_client(Node([ok(tx_data("Fail", ABORT))]))
        with self.assertRaises(TransactionFailedError) as ctx:
            await client.submit_transaction(make_signed_transaction())
        error = ctx.exception
        self.assertEqual(error.tx_hash, TX_HASH)
        self.assertEqual(error.status, "Fail")
        self.assertEqual(error.vm_status, ABORT)
        self.assertIn(ABORT, str(error))
        self.assertIn(TX_HASH, str(error))

    async def test_invalid_transaction_raises(self):
        client = await self.make_client(
            Node([ok({"hash": TX_HASH, "status": "Invalid"})])
        )
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
        client = await self.make_client(node)
        data = await client.wait_for_transaction(TX_HASH)
        self.assertEqual(data["status"], "Success")
        self.assertEqual(node.poll_count, 3)

    async def test_submit_returns_hash_and_and_wait_returns_data(self):
        client = await self.make_client(
            Node([ok(tx_data("Success", "Executed successfully"))])
        )
        self.assertEqual(
            await client.submit_transaction(make_signed_transaction()), TX_HASH
        )
        data = await client.submit_transaction_and_wait(make_signed_transaction())
        self.assertEqual(data["status"], "Success")

    async def test_submit_without_waiting_does_not_poll(self):
        node = Node([ok(tx_data("Fail", ABORT))])
        client = await self.make_client(node)
        client.transaction_config.wait_for_transaction = False
        self.assertEqual(
            await client.submit_transaction(make_signed_transaction()), TX_HASH
        )
        self.assertEqual(node.poll_count, 0)

    async def test_not_found_then_transaction(self):
        node = Node([NOT_FOUND, NOT_FOUND_WITH_REASON, ok(tx_data("Success", "ok"))])
        client = await self.make_client(node)
        data = await client.wait_for_transaction(TX_HASH)
        self.assertEqual(data["hash"], TX_HASH)
        self.assertEqual(node.poll_count, 3)

    async def test_other_404_responses_are_raised(self):
        others = [
            httpx.Response(404, text=""),
            httpx.Response(404, text="<html>Not Found</html>"),
            httpx.Response(404, json={"message": "something else"}),
            httpx.Response(404, json=["Information not available for"]),
        ]
        for response in others:
            with self.subTest(body=response.text):
                node = Node([response])
                client = await self.make_client(node)
                with self.assertRaises(ApiError) as ctx:
                    await client.wait_for_transaction(TX_HASH)
                self.assertEqual(ctx.exception.status_code, 404)
                self.assertEqual(node.poll_count, 1)

    async def test_timeout_raises_with_hash_and_last_status(self):
        client = await self.make_client(
            Node([ok(tx_data("PendingAfterExecution", "x"))])
        )
        with self.assertRaises(TransactionWaitTimeoutReachedError) as ctx:
            await client.wait_for_transaction(TX_HASH)
        self.assertEqual(ctx.exception.tx_hash, TX_HASH)
        self.assertEqual(ctx.exception.last_status, "PendingAfterExecution")

    async def test_timeout_when_never_found(self):
        client = await self.make_client(Node([NOT_FOUND]))
        with self.assertRaises(TransactionWaitTimeoutReachedError) as ctx:
            await client.wait_for_transaction(TX_HASH)
        self.assertIsNone(ctx.exception.last_status)

    async def test_unknown_and_missing_status_keep_polling(self):
        node = Node(
            [
                ok({"hash": TX_HASH}),
                ok({"hash": TX_HASH, "status": "SomethingNew"}),
                ok(tx_data("Success", "ok")),
            ]
        )
        client = await self.make_client(node)
        data = await client.wait_for_transaction(TX_HASH)
        self.assertEqual(data["status"], "Success")
        self.assertEqual(node.poll_count, 3)

    async def test_timeout_carries_last_unknown_status(self):
        node = Node([ok({"hash": TX_HASH, "status": "SomethingNew"})])
        client = await self.make_client(node, wait=0.1)
        with self.assertRaises(TransactionWaitTimeoutReachedError) as ctx:
            await client.wait_for_transaction(TX_HASH)
        self.assertEqual(ctx.exception.last_status, "SomethingNew")

    async def test_sleep_is_capped_by_time_remaining(self):
        node = Node([ok(tx_data("Pending"))])
        client = await self.make_client(node, wait=0.2, poll=30)
        start = time.monotonic()
        with self.assertRaises(TransactionWaitTimeoutReachedError):
            await client.wait_for_transaction(TX_HASH)
        self.assertLess(time.monotonic() - start, 2)
        # No poll starts after the deadline.
        self.assertEqual(node.poll_count, 1)

    async def test_slow_poll_is_bounded_by_the_deadline(self):
        async def slow(_: httpx.Request) -> httpx.Response:
            await asyncio.sleep(30)
            return ok(tx_data("Success", "ok"))

        client = await self.make_client(slow, wait=0.1)
        start = time.monotonic()
        with self.assertRaises(TransactionWaitTimeoutReachedError) as ctx:
            await client.wait_for_transaction(TX_HASH)
        self.assertLess(time.monotonic() - start, 2)
        self.assertEqual(ctx.exception.tx_hash, TX_HASH)
        self.assertIsNone(ctx.exception.last_status)

    async def test_wait_for_faucet_keeps_polling_until_final(self):
        node = Node([NOT_FOUND, ok(tx_data("Pending")), ok(tx_data("Success", "ok"))])
        client = await self.make_client(node)
        data = await client.wait_for_faucet(TX_HASH)
        self.assertEqual(data["status"], "Success")
        self.assertEqual(node.poll_count, 3)

    async def test_faucet_raises_when_the_faucet_transaction_fails(self):
        client = await self.make_client(Node([ok(tx_data("Fail", ABORT))]))
        with self.assertRaises(TransactionFailedError) as ctx:
            await client.faucet(AccountAddress.from_str("0x1"))
        self.assertEqual(ctx.exception.tx_hash, TX_HASH)
        self.assertEqual(ctx.exception.vm_status, ABORT)

    async def test_faucet_returns_hash_on_success_and_skips_check_without_waiting(self):
        node = Node([ok(tx_data("Success", "ok"))])
        client = await self.make_client(node)
        self.assertEqual(await client.faucet(AccountAddress.from_str("0x1")), TX_HASH)
        self.assertEqual(node.poll_count, 1)
        self.assertEqual(
            await client.faucet(AccountAddress.from_str("0x1"), wait_for_faucet=False),
            TX_HASH,
        )
        self.assertEqual(node.poll_count, 1)

    async def test_faucet_request_not_accepted(self):
        client = await self.make_client(lambda _: httpx.Response(200, json={}))
        with self.assertRaises(FaucetRequestNotAcceptedError):
            await client.faucet(AccountAddress.from_str("0x1"))

    async def test_non_404_error_propagates(self):
        client = await self.make_client(Node([httpx.Response(500, text="boom")]))
        with self.assertRaises(ApiError) as ctx:
            await client.wait_for_transaction(TX_HASH)
        self.assertEqual(ctx.exception.status_code, 500)

    async def test_failed_simulation_leaves_transaction_unchanged(self):
        client = await self.make_client(lambda _: httpx.Response(500, text="boom"))
        signed = make_signed_transaction()
        authenticator = signed.authenticator
        before = copy.deepcopy(authenticator)
        self.assertTrue(signed.verify())
        with self.assertRaises(ApiError):
            await client.simulate_transaction(signed)
        self.assertIs(signed.authenticator, authenticator)
        self.assertEqual(signed.authenticator, before)
        self.assertTrue(signed.verify())

    async def test_successful_simulation_leaves_transaction_unchanged(self):
        client = await self.make_client(lambda _: httpx.Response(200, json=[{"x": 1}]))
        signed = make_signed_transaction()
        before = copy.deepcopy(signed.authenticator)
        await client.simulate_transaction(signed)
        self.assertEqual(signed.authenticator, before)
        self.assertTrue(signed.verify())


if __name__ == "__main__":
    unittest.main()
