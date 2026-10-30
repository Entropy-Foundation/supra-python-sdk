# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

import unittest
from collections.abc import Callable
from typing import Any

import httpx

from supra_sdk.account_address import AccountAddress
from supra_sdk.clients import ApiClient
from supra_sdk.clients.rest.paging import next_cursor
from supra_sdk.clients.rest.rest_types import (
    AutomatedTransactionsPagination,
    EventsPagination,
    Pagination,
    PaginationWithOrder,
)
from supra_sdk.clients.rest.supra_client import SupraClient
from supra_sdk.clients.supra_token_object import SupraTokenObjectClient

ADDRESS = AccountAddress.from_str("0x1")
EVENT_TYPE = "0x1::coin::CoinDeposit"
CURSOR = "x-supra-cursor"

Handler = Callable[[httpx.Request], httpx.Response]


def page(items: list[Any], cursor: str | None, wrap: bool = False) -> httpx.Response:
    """A node response carrying `items`, with `cursor` in the header when it is not None."""
    headers = {} if cursor is None else {CURSOR: cursor}
    body: Any = {"data": items} if wrap else items
    return httpx.Response(200, json=body, headers=headers)


class FakeNode:
    """A `SupraClient` whose transport records every request and answers through `handler`."""

    def __init__(self, handler: Handler):
        self.requests: list[httpx.Request] = []
        self.handler = handler
        self.client: SupraClient

    @classmethod
    async def create(cls, handler: Handler) -> "FakeNode":
        node = cls(handler)
        client = SupraClient("https://node.example")
        config = client.api_client.api_client_config
        await client.api_client.close()
        client.api_client = ApiClient(
            "https://node.example",
            config,
            transport=httpx.MockTransport(node._handle),
        )
        node.client = client
        return node

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    def params(self, index: int) -> dict[str, str]:
        return dict(self.requests[index].url.params)

    async def close(self):
        await self.client.api_client.close()


async def collect(iterator) -> list[Any]:
    return [item async for item in iterator]


class NextCursorTests(unittest.TestCase):
    def response(self, headers: dict[str, str]) -> httpx.Response:
        return httpx.Response(200, json=[], headers=headers)

    def test_absent_header_is_none(self):
        self.assertIsNone(next_cursor(self.response({}), [{"a": 1}]))

    def test_empty_header_is_none(self):
        self.assertIsNone(next_cursor(self.response({CURSOR: ""}), [{"a": 1}]))

    def test_present_header_is_returned(self):
        self.assertEqual(next_cursor(self.response({CURSOR: "abc"}), [1]), "abc")

    def test_zero_is_a_cursor_unless_asked_otherwise(self):
        self.assertEqual(next_cursor(self.response({CURSOR: "0"}), []), "0")
        self.assertEqual(next_cursor(self.response({CURSOR: "0"}), [1]), "0")

    def test_zero_on_empty_page_ends_the_feed_when_asked(self):
        response = self.response({CURSOR: "0"})
        self.assertIsNone(next_cursor(response, [], zero_ends_empty_page=True))
        self.assertEqual(next_cursor(response, [1], zero_ends_empty_page=True), "0")


class CursorReturnTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.response: httpx.Response = page([], None)
        self.node = await FakeNode.create(lambda _: self.response)
        self.client = self.node.client

    async def asyncTearDown(self):
        await self.node.close()

    async def test_paged_methods_return_none_without_a_cursor(self):
        self.response = page([{"n": 1}], None)
        self.assertEqual(
            await self.client.account_resources(ADDRESS), ([{"n": 1}], None)
        )
        self.assertEqual(await self.client.account_modules(ADDRESS), ([{"n": 1}], None))
        self.assertEqual(
            await self.client.account_coin_transactions(ADDRESS), ([{"n": 1}], None)
        )
        self.assertEqual(
            await self.client.account_automated_transactions(ADDRESS),
            ([{"n": 1}], None),
        )
        self.response = page([{"n": 1}], None, wrap=True)
        self.assertEqual(
            await self.client.events_by_type(EVENT_TYPE), ([{"n": 1}], None)
        )

    async def test_paged_methods_return_none_for_an_empty_cursor(self):
        self.response = page([{"n": 1}], "")
        self.assertEqual(
            await self.client.account_resources(ADDRESS), ([{"n": 1}], None)
        )
        self.assertEqual(await self.client.account_modules(ADDRESS), ([{"n": 1}], None))
        self.assertEqual(
            await self.client.account_coin_transactions(ADDRESS), ([{"n": 1}], None)
        )
        self.assertEqual(
            await self.client.account_automated_transactions(ADDRESS),
            ([{"n": 1}], None),
        )
        self.response = page([{"n": 1}], "", wrap=True)
        self.assertEqual(
            await self.client.events_by_type(EVENT_TYPE), ([{"n": 1}], None)
        )

    async def test_paged_methods_return_a_present_cursor(self):
        self.response = page([{"n": 1}], "c1")
        self.assertEqual(
            await self.client.account_resources(ADDRESS), ([{"n": 1}], "c1")
        )
        self.assertEqual(
            await self.client.account_automated_transactions(ADDRESS),
            ([{"n": 1}], "c1"),
        )

    async def test_v11_zero_cursor_on_an_empty_coin_transactions_page_is_the_end(self):
        self.response = page([], "0")
        self.assertEqual(
            await self.client.account_coin_transactions(ADDRESS), ([], None)
        )

    async def test_zero_cursor_on_a_page_with_items_is_kept(self):
        self.response = page([{"n": 1}], "0")
        self.assertEqual(
            await self.client.account_coin_transactions(ADDRESS), ([{"n": 1}], "0")
        )

    async def test_zero_cursor_is_not_special_on_other_feeds(self):
        self.response = page([], "0")
        self.assertEqual(await self.client.account_resources(ADDRESS), ([], "0"))


class IteratorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await self.node.close()

    async def test_resources_follow_the_cursor_until_it_is_missing(self):
        pages = {
            None: page([1, 2], "c1"),
            "c1": page([3, 4], "c2"),
            "c2": page([5], None),
        }
        self.node = await FakeNode.create(
            lambda request: pages[request.url.params.get("start")]
        )
        items = await collect(
            self.node.client.iter_account_resources(ADDRESS, Pagination(count=2))
        )
        self.assertEqual(items, [1, 2, 3, 4, 5])
        self.assertEqual(len(self.node.requests), 3)
        self.assertEqual(self.node.params(0), {"count": "2"})
        self.assertEqual(self.node.params(1), {"count": "2", "start": "c1"})
        self.assertEqual(self.node.params(2), {"count": "2", "start": "c2"})

    async def test_resources_stop_on_an_empty_page_that_carries_a_cursor(self):
        # A node up to v11.7.x answers the request that reads nothing with the cursor it was given.
        pages = {
            None: page([1], "c1"),
            "c1": page([], "c1"),
        }
        self.node = await FakeNode.create(
            lambda request: pages[request.url.params.get("start")]
        )
        items = await collect(self.node.client.iter_account_resources(ADDRESS))
        self.assertEqual(items, [1])
        self.assertEqual(len(self.node.requests), 2)

    async def test_iteration_stops_when_a_cursor_repeats(self):
        self.node = await FakeNode.create(lambda _: page([1], "same"))
        items = await collect(self.node.client.iter_account_resources(ADDRESS))
        self.assertEqual(items, [1, 1])
        self.assertEqual(len(self.node.requests), 2)

    async def test_modules_iterator(self):
        pages = {None: page([1], "c1"), "c1": page([2], "")}
        self.node = await FakeNode.create(
            lambda request: pages[request.url.params.get("start")]
        )
        items = await collect(self.node.client.iter_account_modules(ADDRESS))
        self.assertEqual(items, [1, 2])
        self.assertEqual(self.node.requests[0].url.path, "/rpc/v3/accounts/0x1/modules")

    async def test_events_iterator_keeps_the_other_options(self):
        pages = {
            None: page([1, 2], "c1", wrap=True),
            "c1": page([3], "", wrap=True),
        }
        self.node = await FakeNode.create(
            lambda request: pages[request.url.params.get("start")]
        )
        items = await collect(
            self.node.client.iter_events_by_type(
                EVENT_TYPE, EventsPagination(start_height=0, end_height=9, limit=2)
            )
        )
        self.assertEqual(items, [1, 2, 3])
        self.assertEqual(
            self.node.params(1),
            {"start_height": "0", "end_height": "9", "limit": "2", "start": "c1"},
        )

    async def test_coin_transactions_iterator_ends_on_the_v11_zero_cursor(self):
        # Testnet: pages of 2 and 1, then an empty page with cursor "0". Continuing from "0" would restart the feed.
        pages = {
            None: page([1, 2], "100"),
            "100": page([3], "50"),
            "50": page([], "0"),
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return pages[request.url.params.get("start")]

        self.node = await FakeNode.create(handler)
        items = await collect(
            self.node.client.iter_account_coin_transactions(
                ADDRESS, PaginationWithOrder(count=2)
            )
        )
        self.assertEqual(items, [1, 2, 3])
        self.assertEqual(len(self.node.requests), 3)

    async def test_coin_transactions_iterator_ends_on_the_v12_missing_header(self):
        pages = {None: page([1, 2], "100"), "100": page([3], None)}
        self.node = await FakeNode.create(
            lambda request: pages[request.url.params.get("start")]
        )
        items = await collect(self.node.client.iter_account_coin_transactions(ADDRESS))
        self.assertEqual(items, [1, 2, 3])
        self.assertEqual(len(self.node.requests), 2)

    async def test_coin_transactions_iterator_keeps_the_order_and_starts_from_start(
        self,
    ):
        pages = {"7": page([1], "8"), "8": page([], None)}
        self.node = await FakeNode.create(
            lambda request: pages[request.url.params.get("start")]
        )
        await collect(
            self.node.client.iter_account_coin_transactions(
                ADDRESS, PaginationWithOrder(start="7", ascending=True)
            )
        )
        self.assertEqual(self.node.params(0), {"start": "7", "ascending": "true"})
        self.assertEqual(self.node.params(1), {"start": "8", "ascending": "true"})

    async def test_automated_transactions_pass_the_cursor_back(self):
        pages = {
            None: page([1, 2], "k1"),
            "k1": page([3], "k2"),
            "k2": page([], None),
        }
        self.node = await FakeNode.create(
            lambda request: pages[request.url.params.get("cursor")]
        )
        items = await collect(
            self.node.client.iter_account_automated_transactions(
                ADDRESS, AutomatedTransactionsPagination(count=2, ascending=True)
            )
        )
        self.assertEqual(items, [1, 2, 3])
        self.assertEqual(self.node.params(0), {"count": "2", "ascending": "true"})
        self.assertEqual(
            self.node.params(1), {"count": "2", "ascending": "true", "cursor": "k1"}
        )
        self.assertEqual(
            self.node.params(2), {"count": "2", "ascending": "true", "cursor": "k2"}
        )

    async def test_no_request_carries_an_empty_cursor(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return page([1], "") if "start" not in request.url.params else page([], "")

        self.node = await FakeNode.create(handler)
        await collect(self.node.client.iter_account_resources(ADDRESS))
        await collect(
            self.node.client.iter_account_modules(ADDRESS, Pagination(start=""))
        )
        await collect(self.node.client.iter_account_coin_transactions(ADDRESS))
        for request in self.node.requests:
            self.assertNotIn(b"start=&", request.url.query + b"&")
            self.assertNotIn(b"cursor=&", request.url.query + b"&")
            for name in ("start", "cursor"):
                self.assertNotEqual(request.url.params.get(name), "")
        self.assertEqual(len(self.node.requests), 3)

    async def test_iterator_is_lazy(self):
        self.node = await FakeNode.create(lambda _: page([1], "c"))
        self.node.client.iter_account_resources(ADDRESS)
        self.assertEqual(self.node.requests, [])


class ReadObjectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await self.node.close()

    async def test_address_without_resources_takes_one_request(self):
        self.node = await FakeNode.create(lambda _: page([], None))
        result = await SupraTokenObjectClient(self.node.client).read_object(ADDRESS)
        self.assertEqual(result.resources, {})
        self.assertEqual(len(self.node.requests), 1)
        self.assertEqual(self.node.params(0), {"count": "100"})

    async def test_address_without_resources_on_a_node_that_echoes_a_cursor(self):
        self.node = await FakeNode.create(lambda _: page([], "c"))
        await SupraTokenObjectClient(self.node.client).read_object(ADDRESS)
        self.assertEqual(len(self.node.requests), 1)

    async def test_follows_the_cursor_and_stops_on_a_missing_one(self):
        resource = {
            "type": "0x1::object::ObjectCore",
            "data": {"allow_ungated_transfer": True, "owner": "0x2"},
        }
        other = {"type": "0x1::other::Thing", "data": {}}
        pages = {
            None: page([other], "c1"),
            "c1": page([resource], None),
        }
        self.node = await FakeNode.create(
            lambda request: pages[request.url.params.get("start")]
        )
        result = await SupraTokenObjectClient(self.node.client).read_object(ADDRESS)
        self.assertEqual(len(self.node.requests), 2)
        self.assertEqual(self.node.params(1), {"count": "100", "start": "c1"})
        self.assertEqual(len(result.resources), 1)

    async def test_full_last_page_does_not_trigger_another_request(self):
        resources = [{"type": f"0x1::other::T{i}", "data": {}} for i in range(100)]
        self.node = await FakeNode.create(lambda _: page(resources, None))
        await SupraTokenObjectClient(self.node.client).read_object(ADDRESS)
        self.assertEqual(len(self.node.requests), 1)


if __name__ == "__main__":
    unittest.main()
