# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

import pathlib
import unittest
from urllib.parse import unquote

import httpx

from supra_sdk.account_address import AccountAddress
from supra_sdk.clients import ApiClient
from supra_sdk.clients.rest import rest_types
from supra_sdk.clients.rest.rest_types import (
    AutomatedTransactionsPagination,
    EventsPagination,
    Pagination,
    PaginationWithOrder,
    TransactionType,
    format_endpoint,
)
from supra_sdk.clients.rest.supra_client import SupraClient
from supra_sdk.metadata import Metadata

ADDRESS = AccountAddress.from_str("0x1")
HASH = "0x" + "ab" * 32
COIN_STORE = "0x1::coin::CoinStore<0x1::supra_coin::SupraCoin>"


class RecordingClient:
    """A `SupraClient` whose HTTP transport records every request and answers with an empty JSON body."""

    def __init__(self, client: SupraClient):
        self.requests: list[httpx.Request] = []
        self.client = client

    @classmethod
    async def create(cls, base_url: str) -> "RecordingClient":
        """Builds a `SupraClient` and swaps its `ApiClient` for one with the same configuration over a mock transport."""
        client = SupraClient(base_url)
        config = client.api_client.api_client_config
        await client.api_client.close()
        rec = cls(client)
        client.api_client = ApiClient(
            base_url, config, transport=httpx.MockTransport(rec._handle)
        )
        return rec

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
        await self.client.api_client.close()


class BaseUrlTests(unittest.IsolatedAsyncioTestCase):
    async def _request_url(self, base_url: str) -> str:
        rec = await RecordingClient.create(base_url)
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

    async def test_base_url_with_query_or_fragment_is_rejected(self):
        for base_url in (
            "https://host/?apikey=k",
            "https://host?apikey=k",
            "https://host/p?x=1",
            "https://host/p#x",
            "https://host/p#",
            "https://host/?",
        ):
            with self.subTest(base_url=base_url):
                with self.assertRaises(ValueError):
                    ApiClient(base_url)
                with self.assertRaises(ValueError):
                    SupraClient(base_url)

    async def test_requests_use_the_real_client_configuration(self):
        rec = await RecordingClient.create("https://node.example")
        await rec.client.account(ADDRESS)
        client = rec.client.api_client._client
        await rec.close()
        self.assertIn(Metadata.SUPRA_HEADER, rec.last.headers)
        self.assertEqual(client.timeout.read, 60.0)
        self.assertIsNone(client.timeout.pool)

    async def test_post_keeps_path_prefix(self):
        rec = await RecordingClient.create("https://proxy.example/supra")
        await rec.client.view("0x1::coin::name", [], [])
        await rec.close()
        self.assertEqual(str(rec.last.url), "https://proxy.example/supra/rpc/v3/view")

    async def test_faucet_keeps_path_prefix(self):
        rec = await RecordingClient.create("https://proxy.example/supra")
        await rec.client.faucet_transaction_by_hash(HASH)
        await rec.close()
        self.assertEqual(
            str(rec.last.url),
            f"https://proxy.example/supra/rpc/v3/wallet/faucet/transactions/{HASH}",
        )


class PathValueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.rec = await RecordingClient.create("https://node.example/prefix")
        self.client = self.rec.client
        self.client.api_client.api_client_config.access_token = "token"

    async def asyncTearDown(self):
        await self.rec.close()

    async def test_struct_type_with_generics_is_encoded_as_one_segment(self):
        await self.client.account_resource(ADDRESS, COIN_STORE)
        self.assertEqual(
            self.rec.last_target,
            "/prefix/rpc/v3/accounts/0x1/resources/"
            "0x1::coin::CoinStore%3C0x1::supra_coin::SupraCoin%3E",
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
            "/prefix/rpc/v3/events/0x1::table::Table%3Cu64,%200x1::string::String%3E",
        )

    async def test_resource_type_special_characters_stay_in_one_segment(self):
        for value in ("a/b", "a?b=c", "a#b", "a/../b", "%2e%2e", "a b", "a%b"):
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

    async def test_hashes_must_be_64_hex_digits(self):
        bad = (
            "0x1/../2",
            "abc?x=1",
            "abc#frag",
            "not-hex",
            "",
            "0x",
            "0x12",
            "0x" + "ab" * 31,
            "0x" + "ab" * 33,
            "0x" + "zz" * 32,
            "0x" + "ab" * 31 + "a/",
        )
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
        bare = "AB" * 32
        await self.client.transaction_by_hash(bare)
        self.assertEqual(self.rec.last_target, f"/prefix/rpc/v3/transactions/{bare}")
        await self.client.transaction_by_hash(HASH)
        self.assertEqual(self.rec.last_target, f"/prefix/rpc/v3/transactions/{HASH}")
        await self.client.block_by_hash(HASH)
        self.assertEqual(self.rec.last_target, f"/prefix/rpc/v3/block/{HASH}")
        await self.client.txs_by_block(HASH)
        self.assertEqual(
            self.rec.last_target, f"/prefix/rpc/v3/block/{HASH}/transactions"
        )

    async def test_heights_and_epochs_reject_invalid_values(self):
        bad = (-1, "-1", "1/2", "", " 1", "1 ", "1.5", "0x10", "١٢", 1.5, True, None)
        for value in bad:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    await self.client.block_by_height(value)  # type: ignore[arg-type]
                with self.assertRaises(ValueError):
                    await self.client.committee_authorization(value)  # type: ignore[arg-type]
        self.assertEqual(self.rec.requests, [])

    async def test_heights_accept_integers_and_decimal_strings(self):
        for value, expected in ((0, "0"), (7, "7"), ("7", "7"), ("007", "7")):
            with self.subTest(value=value):
                await self.client.block_by_height(value)
                self.assertEqual(
                    self.rec.last.url.path, f"/prefix/rpc/v3/block/height/{expected}"
                )

    async def test_epoch_accepts_decimal_string(self):
        await self.client.committee_authorization("12")
        self.assertEqual(
            self.rec.last_target,
            "/prefix/rpc/v3/consensus/committee_authorization/12",
        )

    async def test_addresses_are_validated(self):
        for value in ("0x1/../2", "0x1?x=1", "0x1#a", "zz", "", "0x" + "1" * 65):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    await self.client.account(value)
                with self.assertRaises(ValueError):
                    await self.client.faucet(value)
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


class FormatEndpointTests(unittest.TestCase):
    def test_unknown_placeholder_is_encoded_as_one_segment(self):
        self.assertEqual(
            format_endpoint("rpc/v3/things/{thing_name}", thing_name="a/b?c#d<e>"),
            "rpc/v3/things/a%2Fb%3Fc%23d%3Ce%3E",
        )

    def test_unknown_placeholder_rejects_empty_and_non_strings(self):
        for value in ("", None, 5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                format_endpoint("rpc/v3/things/{thing_name}", thing_name=value)

    def test_placeholders_are_validated_by_name(self):
        template = "x/{address}/{table_handle}/{account_address}"
        for name in ("address", "table_handle", "account_address"):
            with self.subTest(name=name):
                values = {
                    "address": "0x1",
                    "table_handle": "0x2",
                    "account_address": "0x3",
                }
                values[name] = "0x1/../2"
                with self.assertRaises(ValueError):
                    format_endpoint(template, **values)
        for name in ("hash", "block_hash", "tx_hash"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    format_endpoint("x/{" + name + "}", **{name: "0x12"})
                self.assertEqual(
                    format_endpoint("x/{" + name + "}", **{name: HASH}), f"x/{HASH}"
                )
        for name in ("height", "epoch"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    format_endpoint("x/{" + name + "}", **{name: "a"})
                self.assertEqual(
                    format_endpoint("x/{" + name + "}", **{name: "5"}), "x/5"
                )

    def test_addresses_are_canonicalised(self):
        self.assertEqual(format_endpoint("x/{address}", address="0x01"), "x/0x1")
        self.assertEqual(format_endpoint("x/{address}", address=ADDRESS), "x/0x1")

    def test_values_must_match_placeholders(self):
        with self.assertRaises(ValueError):
            format_endpoint("x/{address}")
        with self.assertRaises(ValueError):
            format_endpoint("x/{address}", address="0x1", extra="y")

    def test_every_endpoint_with_placeholders_is_built_by_format_endpoint(self):
        rest_dir = pathlib.Path(rest_types.__file__).parent
        for path in rest_dir.glob("*.py"):
            with self.subTest(module=path.name):
                self.assertNotRegex(path.read_text(), r"_ENDPOINT\.format\(")


class QueryParameterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.rec = await RecordingClient.create("https://node.example")
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

    async def test_automated_transactions_cursor_is_sent(self):
        await self.client.account_automated_transactions(
            ADDRESS, AutomatedTransactionsPagination(count=2, cursor="c 1&2")
        )
        self.assertEqual(
            dict(self.rec.last.url.params), {"count": "2", "cursor": "c 1&2"}
        )

    async def test_block_query_parameters(self):
        await self.client.block_by_height(
            3, transaction_type=TransactionType.USER, with_finalized_transactions=True
        )
        self.assertEqual(
            dict(self.rec.last.url.params),
            {"with_finalized_transactions": "true", "type": "user"},
        )

    async def test_block_by_height_positional_flag_is_the_plural_parameter(self):
        await self.client.block_by_height(3, TransactionType.META, True)
        self.assertEqual(
            dict(self.rec.last.url.params),
            {"with_finalized_transactions": "true", "type": "meta"},
        )

    async def test_block_by_height_deprecated_keyword_still_works(self):
        with self.assertWarns(DeprecationWarning):
            await self.client.block_by_height(3, with_finalized_transaction=True)
        self.assertEqual(
            dict(self.rec.last.url.params), {"with_finalized_transactions": "true"}
        )

    async def test_block_by_height_without_transactions_by_default(self):
        await self.client.block_by_height(3)
        self.assertEqual(
            dict(self.rec.last.url.params), {"with_finalized_transactions": "false"}
        )

    async def test_txs_by_block_sends_type(self):
        await self.client.txs_by_block(HASH, TransactionType.AUTO)
        self.assertEqual(dict(self.rec.last.url.params), {"type": "auto"})
        await self.client.txs_by_block(HASH)
        self.assertEqual(self.rec.last.url.query, b"")

    async def test_consensus_block_by_height_path(self):
        self.client.api_client.api_client_config.access_token = "token"
        await self.client.consensus_block_by_height(12, with_batches=True)
        self.assertEqual(self.rec.last.url.path, "/rpc/v3/consensus/block/height/12")
        self.assertEqual(dict(self.rec.last.url.params), {"with_batches": "true"})

    async def test_empty_cursors_are_never_sent(self):
        await self.client.account_resources(ADDRESS, Pagination(count=3, start=""))
        self.assertEqual(dict(self.rec.last.url.params), {"count": "3"})
        await self.client.account_coin_transactions(
            ADDRESS, PaginationWithOrder(start="")
        )
        self.assertEqual(self.rec.last.url.query, b"")
        await self.client.events_by_type(
            "0x1::coin::CoinDeposit", EventsPagination(start="")
        )
        self.assertEqual(self.rec.last.url.query, b"")
        await self.client.account_automated_transactions(
            ADDRESS, AutomatedTransactionsPagination(cursor="")
        )
        self.assertEqual(self.rec.last.url.query, b"")

    async def test_zero_start_is_kept(self):
        await self.client.account_transactions(ADDRESS, PaginationWithOrder(start=0))
        self.assertEqual(dict(self.rec.last.url.params), {"start": "0"})
        self.assertEqual(
            EventsPagination(start_height=0).to_params(), {"start_height": 0}
        )

    async def test_none_parameters_are_dropped(self):
        await self.client.account_resources(ADDRESS)
        self.assertEqual(self.rec.last.url.query, b"")


if __name__ == "__main__":
    unittest.main()
