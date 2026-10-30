# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

"""Offline tests for the fungible asset helpers of the client, over a fake node."""

import hashlib
import json
import unittest

import httpx

from supra_sdk.account import Account
from supra_sdk.account_address import AccountAddress
from supra_sdk.bcs import Deserializer
from supra_sdk.clients import ApiClient
from supra_sdk.clients.rest import (
    SupraClient,
    SupraClientConfig,
    TransactionFailedError,
)
from supra_sdk.clients.rest.rest_types import PaginationWithOrder, TransactionType
from supra_sdk.fungible_asset import (
    FUNGIBLE_ASSET_METADATA_TYPE,
    SUPRA_FA_METADATA_ADDRESS,
    primary_store_address,
)
from supra_sdk.transactions import SignedTransaction, SupraTransaction

OWNER = AccountAddress.from_str("0x" + "11" * 32)
RECIPIENT = AccountAddress.from_str("0x" + "22" * 32)
OTHER_METADATA = AccountAddress.from_str("0x" + "33" * 32)
TX_HASH = "0x" + "ab" * 32


def expected_store(owner: AccountAddress, metadata: AccountAddress) -> str:
    """The primary store address, computed here from the Move definition: sha3_256(owner | metadata | 0xFC)."""
    digest = hashlib.sha3_256(owner.address + metadata.address + b"\xfc").digest()
    return "0x" + digest.hex()


class FakeNode:
    """Records every request and answers the few endpoints the helpers use."""

    def __init__(self, fa_transactions: httpx.Response | None = None):
        self.requests: list[httpx.Request] = []
        self.view_balance = "500"
        self.final_status = "Success"
        self.fa_transactions = fa_transactions or httpx.Response(200, json=[])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/transactions/chain_id"):
            return httpx.Response(200, text="4")
        if path.endswith("/transactions/submit"):
            return httpx.Response(200, json=TX_HASH)
        if path.endswith("/view"):
            return httpx.Response(200, json={"result": [self.view_balance]})
        if path.endswith("/fa_transactions"):
            return self.fa_transactions
        if path.endswith(f"/transactions/{TX_HASH}"):
            output = {"Move": {"gas_used": 1, "events": [], "vm_status": "aborted"}}
            return httpx.Response(
                200,
                json={"hash": TX_HASH, "status": self.final_status, "output": output},
            )
        return httpx.Response(404, json={"message": f"unexpected {path}"})

    def of(self, suffix: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path.endswith(suffix)]

    def submitted(self) -> SignedTransaction:
        (request,) = self.of("/transactions/submit")
        transaction = SupraTransaction.deserialize(Deserializer(request.content))
        return transaction.value


class FungibleAssetHelperTests(unittest.IsolatedAsyncioTestCase):
    async def make_client(
        self, node: FakeNode, wait_for_transaction: bool = False
    ) -> SupraClient:
        config = SupraClientConfig(
            gas_unit_price=100,
            max_gas_amount=2000,
            expiration_ttl=60,
            wait_for_transaction=wait_for_transaction,
            transaction_wait_time_in_seconds=0.5,
            polling_wait_time_in_seconds=0.01,
        )
        client = SupraClient("http://node.invalid/", config)
        await client.api_client.close()
        client.api_client = ApiClient(
            "http://node.invalid/",
            client.api_client.api_client_config,
            transport=httpx.MockTransport(node),
        )
        self.addAsyncCleanup(client.close)
        return client


class TestPrimaryStoreAddress(unittest.TestCase):
    def test_matches_the_move_derivation(self):
        self.assertEqual(
            str(primary_store_address(OWNER, OTHER_METADATA)),
            expected_store(OWNER, OTHER_METADATA),
        )

    def test_defaults_to_supra_and_accepts_strings(self):
        self.assertEqual(
            primary_store_address(OWNER),
            primary_store_address(str(OWNER), "0xa"),
        )
        self.assertEqual(
            str(primary_store_address(OWNER)),
            expected_store(OWNER, SUPRA_FA_METADATA_ADDRESS),
        )

    def test_differs_by_owner_and_metadata(self):
        self.assertNotEqual(
            primary_store_address(OWNER), primary_store_address(RECIPIENT)
        )
        self.assertNotEqual(
            primary_store_address(OWNER), primary_store_address(OWNER, OTHER_METADATA)
        )

    def test_rejects_an_invalid_address(self):
        with self.assertRaises(ValueError):
            primary_store_address("not-an-address")


class TestAccountFaBalance(FungibleAssetHelperTests):
    async def test_reads_the_primary_store_of_supra_by_default(self):
        node = FakeNode()
        client = await self.make_client(node)
        balance = await client.account_fa_balance(OWNER)
        self.assertEqual(balance, 500)
        (request,) = node.requests
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.url.path, "/rpc/v3/view")
        self.assertEqual(
            json.loads(request.content),
            {
                "function": "0x1::primary_fungible_store::balance",
                "type_arguments": [FUNGIBLE_ASSET_METADATA_TYPE],
                "arguments": [str(OWNER), "0xa"],
            },
        )

    async def test_reads_another_metadata_address(self):
        node = FakeNode()
        node.view_balance = "18446744073709551615"
        client = await self.make_client(node)
        balance = await client.account_fa_balance(str(OWNER), OTHER_METADATA)
        self.assertEqual(balance, 2**64 - 1)
        body = json.loads(node.requests[0].content)
        self.assertEqual(body["arguments"], [str(OWNER), str(OTHER_METADATA)])

    async def test_zero_balance_without_a_store(self):
        node = FakeNode()
        node.view_balance = "0"
        client = await self.make_client(node)
        self.assertEqual(await client.account_fa_balance(OWNER), 0)

    async def test_invalid_address_sends_nothing(self):
        node = FakeNode()
        client = await self.make_client(node)
        with self.assertRaises(ValueError):
            await client.account_fa_balance(OWNER, "zz")
        self.assertEqual(node.requests, [])

    async def test_coin_balance_still_reads_coin_balance(self):
        node = FakeNode()
        client = await self.make_client(node)
        await client.account_supra_balance(OWNER)
        body = json.loads(node.requests[0].content)
        self.assertEqual(body["function"], "0x1::coin::balance")
        self.assertEqual(body["type_arguments"], ["0x1::supra_coin::SupraCoin"])


class TestTransferFungibleAsset(FungibleAssetHelperTests):
    def sender(self) -> Account:
        return Account.generate()

    async def test_builds_the_primary_store_transfer(self):
        node = FakeNode()
        client = await self.make_client(node)
        sender = self.sender()
        tx_hash = await client.transfer_fungible_asset(
            sender, RECIPIENT, 1_000, sequence_number=7
        )
        self.assertEqual(tx_hash, TX_HASH)
        signed = node.submitted()
        raw = signed.transaction
        self.assertEqual(raw.sender, sender.address())
        self.assertEqual(raw.sequence_number, 7)
        self.assertEqual(raw.max_gas_amount, 2000)
        self.assertEqual(raw.gas_unit_price, 100)
        self.assertEqual(raw.chain_id, 4)
        entry = raw.payload.value
        self.assertEqual(entry.module.address, AccountAddress.from_str("0x1"))
        self.assertEqual(entry.module.name, "primary_fungible_store")
        self.assertEqual(entry.function, "transfer")
        self.assertEqual(
            [str(t) for t in entry.ty_args], [FUNGIBLE_ASSET_METADATA_TYPE]
        )
        self.assertEqual(
            entry.args,
            [
                SUPRA_FA_METADATA_ADDRESS.address,
                RECIPIENT.address,
                (1_000).to_bytes(8, "little"),
            ],
        )
        self.assertTrue(signed.verify())

    async def test_transfers_another_metadata_address(self):
        node = FakeNode()
        client = await self.make_client(node)
        await client.transfer_fungible_asset(
            self.sender(), RECIPIENT, 5, str(OTHER_METADATA), sequence_number=0
        )
        entry = node.submitted().transaction.payload.value
        self.assertEqual(entry.args[0], OTHER_METADATA.address)
        self.assertEqual(entry.args[2], (5).to_bytes(8, "little"))

    async def test_invalid_metadata_address_sends_nothing(self):
        node = FakeNode()
        client = await self.make_client(node)
        with self.assertRaises(ValueError):
            await client.transfer_fungible_asset(
                self.sender(), RECIPIENT, 1, "zz", sequence_number=0
            )
        self.assertEqual(node.requests, [])

    async def test_failed_transfer_raises_with_the_hash(self):
        node = FakeNode()
        node.final_status = "Fail"
        client = await self.make_client(node, wait_for_transaction=True)
        with self.assertRaises(TransactionFailedError) as ctx:
            await client.transfer_fungible_asset(
                self.sender(), RECIPIENT, 1, sequence_number=0
            )
        self.assertEqual(ctx.exception.tx_hash, TX_HASH)
        self.assertEqual(ctx.exception.status, "Fail")


class TestMigrateCoinToFungibleStore(FungibleAssetHelperTests):
    async def test_builds_the_migration_for_supra(self):
        node = FakeNode()
        client = await self.make_client(node)
        sender = Account.generate()
        tx_hash = await client.migrate_coin_to_fungible_store(sender, sequence_number=3)
        self.assertEqual(tx_hash, TX_HASH)
        raw = node.submitted().transaction
        self.assertEqual(raw.sequence_number, 3)
        entry = raw.payload.value
        self.assertEqual(entry.module.name, "coin")
        self.assertEqual(entry.function, "migrate_to_fungible_store")
        self.assertEqual(
            [str(t) for t in entry.ty_args], ["0x1::supra_coin::SupraCoin"]
        )
        self.assertEqual(entry.args, [])

    async def test_migrates_another_coin_type(self):
        node = FakeNode()
        client = await self.make_client(node)
        sender = Account.generate()
        coin_type = "0x" + "44" * 32 + "::my_coin::MyCoin"
        await client.migrate_coin_to_fungible_store(
            sender, coin_type, sequence_number=0
        )
        entry = node.submitted().transaction.payload.value
        self.assertEqual([str(t) for t in entry.ty_args], [coin_type])


class TestAccountFaTransactions(FungibleAssetHelperTests):
    def page(self, cursor: str | None, body: list | None = None) -> httpx.Response:
        headers = {} if cursor is None else {"x-supra-cursor": cursor}
        return httpx.Response(200, json=body or [], headers=headers)

    async def fetch(self, node: FakeNode, *args, **kwargs):
        client = await self.make_client(node)
        result = await client.account_fa_transactions(*args, **kwargs)
        return result, node.of("/fa_transactions")[-1]

    async def test_queries_the_derived_primary_store_of_supra(self):
        node = FakeNode(self.page("42", [{"hash": TX_HASH}]))
        (transactions, cursor), request = await self.fetch(node, OWNER)
        self.assertEqual(transactions, [{"hash": TX_HASH}])
        self.assertEqual(cursor, "42")
        self.assertEqual(request.method, "GET")
        self.assertEqual(
            request.url.path,
            f"/rpc/v3/accounts/{expected_store(OWNER, SUPRA_FA_METADATA_ADDRESS)}/fa_transactions",
        )
        self.assertEqual(dict(request.url.params), {})

    async def test_metadata_address_changes_the_store(self):
        node = FakeNode()
        _, request = await self.fetch(node, str(OWNER), metadata_address=OTHER_METADATA)
        self.assertIn(expected_store(OWNER, OTHER_METADATA), request.url.path)

    async def test_store_address_is_queried_as_given(self):
        node = FakeNode()
        store = AccountAddress.from_str("0x" + "55" * 32)
        _, request = await self.fetch(node, OWNER, store_address=store)
        self.assertEqual(request.url.path, f"/rpc/v3/accounts/{store}/fa_transactions")

    async def test_pagination_and_type_are_sent(self):
        node = FakeNode()
        _, request = await self.fetch(
            node,
            OWNER,
            PaginationWithOrder(count=5, start="17", ascending=True),
            transaction_type=TransactionType.AUTO,
        )
        self.assertEqual(
            dict(request.url.params),
            {"count": "5", "start": "17", "ascending": "true", "type": "auto"},
        )

    async def test_type_accepts_a_string_for_record_and_settlement(self):
        node = FakeNode()
        _, request = await self.fetch(node, OWNER, transaction_type="record")
        self.assertEqual(dict(request.url.params), {"type": "record"})

    async def test_absent_cursor_header_is_none(self):
        node = FakeNode(self.page(None))
        (_, cursor), _ = await self.fetch(node, OWNER)
        self.assertIsNone(cursor)

    async def test_empty_cursor_header_is_none(self):
        node = FakeNode(self.page(""))
        (_, cursor), _ = await self.fetch(node, OWNER)
        self.assertIsNone(cursor)

    async def test_zero_is_a_valid_cursor(self):
        node = FakeNode(self.page("0"))
        (_, cursor), _ = await self.fetch(node, OWNER)
        self.assertEqual(cursor, "0")

    async def test_empty_start_is_not_sent(self):
        node = FakeNode()
        _, request = await self.fetch(
            node, OWNER, PaginationWithOrder(start="", count=3)
        )
        self.assertEqual(dict(request.url.params), {"count": "3"})

    async def test_start_zero_is_sent(self):
        node = FakeNode()
        _, request = await self.fetch(node, OWNER, PaginationWithOrder(start=0))
        self.assertEqual(dict(request.url.params), {"start": "0"})

    async def test_cursor_walks_the_feed_to_its_end(self):
        responses = [self.page("2", [{"n": 1}]), self.page(None, [{"n": 2}])]
        node = FakeNode()
        client = await self.make_client(node)
        collected: list[dict] = []
        cursor: str | None = None
        for response in responses:
            node.fa_transactions = response
            pagination = PaginationWithOrder(start=cursor) if cursor else None
            page, cursor = await client.account_fa_transactions(OWNER, pagination)
            collected.extend(page)
        self.assertIsNone(cursor)
        self.assertEqual(collected, [{"n": 1}, {"n": 2}])
        starts = [r.url.params.get("start") for r in node.of("/fa_transactions")]
        self.assertEqual(starts, [None, "2"])

    async def test_invalid_address_sends_nothing(self):
        node = FakeNode()
        client = await self.make_client(node)
        with self.assertRaises(ValueError):
            await client.account_fa_transactions("zz")
        self.assertEqual(node.requests, [])


if __name__ == "__main__":
    unittest.main()
