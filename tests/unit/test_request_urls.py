# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

import unittest
from urllib.parse import unquote

import httpx

from supra_sdk.account_address import AccountAddress
from supra_sdk.clients.rest.rest_types import (
    AutomatedTransactionsPagination,
    EventsPagination,
    PaginationWithOrder,
    TransactionType,
)
from supra_sdk.clients.rest.supra_client import SupraClient

ADDRESS = AccountAddress.from_str("0x1")
HASH = "0x" + "ab" * 32
COIN_STORE = "0x1::coin::CoinStore<0x1::supra_coin::SupraCoin>"


class RecordingClient:
    """A `SupraClient` whose HTTP transport records every request and answers with an empty JSON body."""

    def __init__(self, base_url: str):
        self.requests: list[httpx.Request] = []
        self.client = SupraClient(base_url)
        self.client.api_client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(self._handle)
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"data": [], "result": []})

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    @property
    def last_target(self) -> str:
        return self.last.url.raw_path.decode()

    async def close(self):
        await self.client.api_client._client.aclose()


class BaseUrlTests(unittest.IsolatedAsyncioTestCase):
    async def _request_url(self, base_url: str) -> str:
        rec = RecordingClient(base_url)
        await rec.client.account(ADDRESS)
        await rec.close()
        return str(rec.last.url)

    async def test_base_url_with_path_and_no_trailing_slash(self):
        self.assertEqual(
            await self._request_url("https://proxy.example/supra"),
            "https://proxy.example/supra/rpc/v3/accounts/0x1",
        )

    async def test_base_url_with_path_and_trailing_slash(self):
        self.assertEqual(
            await self._request_url("https://proxy.example/supra/"),
            "https://proxy.example/supra/rpc/v3/accounts/0x1",
        )

    async def test_base_url_with_nested_path(self):
        self.assertEqual(
            await self._request_url("https://proxy.example/a/b"),
            "https://proxy.example/a/b/rpc/v3/accounts/0x1",
        )

    async def test_base_url_without_path(self):
        for base_url in ("https://node.example", "https://node.example/"):
            with self.subTest(base_url=base_url):
                self.assertEqual(
                    await self._request_url(base_url),
                    "https://node.example/rpc/v3/accounts/0x1",
                )

    async def test_base_url_with_port(self):
        self.assertEqual(
            await self._request_url("http://localhost:27001"),
            "http://localhost:27001/rpc/v3/accounts/0x1",
        )

    async def test_post_keeps_path_prefix(self):
        rec = RecordingClient("https://proxy.example/supra")
        await rec.client.view("0x1::coin::name", [], [])
        await rec.close()
        self.assertEqual(str(rec.last.url), "https://proxy.example/supra/rpc/v3/view")

    async def test_faucet_keeps_path_prefix(self):
        rec = RecordingClient("https://proxy.example/supra")
        await rec.client.faucet_transaction_by_hash(HASH)
        await rec.close()
        self.assertEqual(
            str(rec.last.url),
            f"https://proxy.example/supra/rpc/v3/wallet/faucet/transactions/{HASH}",
        )


class PathValueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.rec = RecordingClient("https://node.example/prefix")
        self.client = self.rec.client

    async def asyncTearDown(self):
        await self.rec.close()

    async def test_struct_type_with_generics_is_encoded_as_one_segment(self):
        await self.client.account_resource(ADDRESS, COIN_STORE)
        self.assertEqual(
            self.rec.last_target,
            "/prefix/rpc/v3/accounts/0x1/resources/"
            "0x1%3A%3Acoin%3A%3ACoinStore%3C0x1%3A%3Asupra_coin%3A%3ASupraCoin%3E",
        )

    async def test_encoded_struct_type_decodes_to_the_original(self):
        await self.client.account_resource(ADDRESS, COIN_STORE)
        segment = self.rec.last_target.rsplit("/", 1)[1]
        self.assertEqual(unquote(segment), COIN_STORE)

    async def test_type_with_comma_and_space(self):
        type_tag = "0x1::table::Table<u64, 0x1::string::String>"
        await self.client.events_by_type(type_tag)
        self.assertEqual(
            self.rec.last_target,
            "/prefix/rpc/v3/events/"
            "0x1%3A%3Atable%3A%3ATable%3Cu64%2C%200x1%3A%3Astring%3A%3AString%3E",
        )

    async def test_resource_type_special_characters_stay_in_one_segment(self):
        for value in ("a/b", "a?b=c", "a#b", "a/../b", "%2e%2e", "a b"):
            with self.subTest(value=value):
                await self.client.account_resource(ADDRESS, value)
                url = self.rec.last.url
                self.assertEqual(url.query, b"")
                self.assertEqual(url.fragment, "")
                self.assertEqual(
                    url.raw_path.decode().count("/"),
                    len(["", "prefix", "rpc", "v3", "accounts", "0x1", "resources", ""])
                    - 1,
                )
                self.assertEqual(
                    unquote(url.raw_path.decode().rsplit("/", 1)[1]), value
                )

    async def test_module_name_and_event_type_are_encoded(self):
        await self.client.account_module(ADDRESS, "a/b?c#d")
        self.assertEqual(
            self.rec.last_target,
            "/prefix/rpc/v3/accounts/0x1/modules/a%2Fb%3Fc%23d",
        )
        await self.client.events_by_type("x/y?z#w")
        self.assertEqual(self.rec.last_target, "/prefix/rpc/v3/events/x%2Fy%3Fz%23w")

    async def test_empty_string_values_are_rejected(self):
        with self.assertRaises(ValueError):
            await self.client.account_resource(ADDRESS, "")
        with self.assertRaises(ValueError):
            await self.client.account_module(ADDRESS, "")
        with self.assertRaises(ValueError):
            await self.client.events_by_type("")
        self.assertEqual(self.rec.requests, [])

    async def test_hashes_must_be_hex(self):
        bad = ("0x1/../2", "abc?x=1", "abc#frag", "not-hex", "", "0x")
        for value in bad:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    await self.client.transaction_by_hash(value)
                with self.assertRaises(ValueError):
                    await self.client.block_by_hash(value)
                with self.assertRaises(ValueError):
                    await self.client.txs_by_block(value)
                with self.assertRaises(ValueError):
                    await self.client.faucet_transaction_by_hash(value)
        self.assertEqual(self.rec.requests, [])

    async def test_valid_hashes(self):
        await self.client.transaction_by_hash(HASH)
        self.assertEqual(self.rec.last_target, f"/prefix/rpc/v3/transactions/{HASH}")
        await self.client.block_by_hash(HASH)
        self.assertEqual(self.rec.last_target, f"/prefix/rpc/v3/block/{HASH}")
        await self.client.txs_by_block(HASH)
        self.assertEqual(
            self.rec.last_target, f"/prefix/rpc/v3/block/{HASH}/transactions"
        )

    async def test_heights_and_epochs_must_be_non_negative_integers(self):
        for value in (-1, "1/2", "1", 1.5, True, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                await self.client.block_by_height(value)  # type: ignore[arg-type]
        self.assertEqual(self.rec.requests, [])
        await self.client.block_by_height(0)
        self.assertEqual(
            self.rec.last_target.split("?")[0], "/prefix/rpc/v3/block/height/0"
        )

    async def test_addresses_are_validated(self):
        for value in ("0x1/../2", "0x1?x=1", "0x1#a", "zz", "", "0x" + "1" * 65):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    await self.client.account(value)  # type: ignore[arg-type]
                with self.assertRaises(ValueError):
                    await self.client.faucet(value)  # type: ignore[arg-type]
                with self.assertRaises(ValueError):
                    await self.client.get_table_item(value, "u64", "u64", "1")
        self.assertEqual(self.rec.requests, [])

    async def test_address_strings_are_accepted(self):
        await self.client.account("0x1")
        self.assertEqual(self.rec.last_target, "/prefix/rpc/v3/accounts/0x1")

    async def test_table_handle_is_a_validated_address(self):
        handle = "0x" + "ab" * 32
        await self.client.get_table_item(handle, "u64", "u64", "1")
        self.assertEqual(self.rec.last_target, f"/prefix/rpc/v3/tables/{handle}/item")


class QueryParameterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.rec = RecordingClient("https://node.example")
        self.client = self.rec.client

    async def asyncTearDown(self):
        await self.rec.close()

    async def test_pagination_cursor_is_encoded(self):
        cursor = "a&b=c d#e+f"
        await self.client.account_transactions(
            ADDRESS, PaginationWithOrder(count=5, start=cursor, ascending=True)
        )
        url = self.rec.last.url
        self.assertEqual(url.path, "/rpc/v3/accounts/0x1/transactions")
        self.assertEqual(url.fragment, "")
        self.assertEqual(
            dict(url.params), {"count": "5", "start": cursor, "ascending": "true"}
        )
        self.assertNotIn("#", url.raw_path.decode())
        self.assertEqual(url.raw_path.decode().count("?"), 1)

    async def test_events_pagination_keeps_zero_start_height(self):
        await self.client.events_by_type(
            "0x1::coin::CoinDeposit",
            EventsPagination(start_height=0, end_height=10, limit=3, start="x y"),
        )
        self.assertEqual(
            dict(self.rec.last.url.params),
            {"start_height": "0", "end_height": "10", "limit": "3", "start": "x y"},
        )

    async def test_automated_transactions_params(self):
        await self.client.account_automated_transactions(
            ADDRESS,
            AutomatedTransactionsPagination(ascending=False, block_height=7, count=2),
        )
        self.assertEqual(
            dict(self.rec.last.url.params),
            {"ascending": "false", "block_height": "7", "count": "2"},
        )

    async def test_block_query_parameters(self):
        await self.client.block_by_height(
            3, transaction_type=TransactionType.USER, with_finalized_transaction=True
        )
        self.assertEqual(
            dict(self.rec.last.url.params),
            {"with_finalized_transactions": "true", "transaction_type": "user"},
        )

    async def test_none_parameters_are_dropped(self):
        await self.client.account_resources(ADDRESS)
        self.assertEqual(self.rec.last.url.query, b"")


if __name__ == "__main__":
    unittest.main()
