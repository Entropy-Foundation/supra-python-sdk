# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

import unittest
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import httpx

from supra_sdk.account_address import AccountAddress
from supra_sdk.clients import ApiClient
from supra_sdk.clients.api_client import ApiError
from supra_sdk.clients.rest.paging import next_cursor, paginate
from supra_sdk.clients.rest.rest_types import (
    AccountHistoryCategory,
    AutomatedTransactionsPagination,
    EventsPagination,
    Pagination,
    PaginationWithOrder,
)
from supra_sdk.clients.rest.supra_client import SupraClient
from supra_sdk.clients.supra_token_object import SupraTokenObjectClient

ADDRESS = AccountAddress.from_str("0x1")
EVENT_TYPE = "0x1::fungible_asset::Deposit"
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

    def test_absent_or_empty_header_ends_an_empty_page_too(self):
        self.assertIsNone(next_cursor(self.response({}), [], sent="c1"))
        self.assertIsNone(next_cursor(self.response({CURSOR: ""}), []))
        self.assertIsNone(
            next_cursor(self.response({}), [], sent=None, zero_continues=True)
        )

    def test_empty_page_with_a_new_cursor_continues(self):
        response = self.response({CURSOR: "1792406658389090"})
        self.assertEqual(
            next_cursor(response, [], sent="1792406658389084"), "1792406658389090"
        )
        self.assertEqual(next_cursor(response, []), "1792406658389090")

    def test_zero_on_an_empty_page_ends_the_feed(self):
        response = self.response({CURSOR: "0"})
        self.assertIsNone(next_cursor(response, []))
        self.assertIsNone(next_cursor(response, [], sent="1792406658389084"))

    def test_zero_on_a_page_with_items_continues(self):
        self.assertEqual(next_cursor(self.response({CURSOR: "0"}), [1]), "0")

    def test_zero_on_an_empty_page_continues_when_zero_continues(self):
        response = self.response({CURSOR: "0"})
        self.assertEqual(next_cursor(response, [], zero_continues=True), "0")
        self.assertEqual(
            next_cursor(self.response({CURSOR: "5"}), [], zero_continues=True), "5"
        )

    def test_echo_of_the_sent_cursor_on_an_empty_page_ends_the_feed(self):
        self.assertIsNone(next_cursor(self.response({CURSOR: "abcd"}), [], sent="abcd"))
        self.assertIsNone(next_cursor(self.response({CURSOR: "0"}), [], sent=0))

    def test_echo_of_the_sent_cursor_on_a_page_with_items_continues(self):
        self.assertEqual(
            next_cursor(self.response({CURSOR: "abcd"}), [1], sent="abcd"), "abcd"
        )

    def test_empty_sent_cursor_counts_as_none(self):
        self.assertEqual(next_cursor(self.response({CURSOR: "c"}), [], sent=""), "c")

    def test_only_missing_header_ends_keeps_every_present_cursor(self):
        for cursor in ("0", "abcd", "5"):
            self.assertEqual(
                next_cursor(
                    self.response({CURSOR: cursor}),
                    [],
                    sent="abcd",
                    only_missing_header_ends=True,
                ),
                cursor,
            )
        self.assertIsNone(
            next_cursor(self.response({}), [], only_missing_header_ends=True)
        )
        self.assertIsNone(
            next_cursor(self.response({CURSOR: ""}), [], only_missing_header_ends=True)
        )


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

    async def test_zero_cursor_on_an_empty_page_ends_every_feed(self):
        self.response = page([], "0")
        self.assertEqual(await self.client.account_resources(ADDRESS), ([], None))
        self.assertEqual(await self.client.account_modules(ADDRESS), ([], None))
        self.assertEqual(
            await self.client.account_automated_transactions(ADDRESS), ([], None)
        )
        self.response = page([], "0", wrap=True)
        self.assertEqual(await self.client.events_by_type(EVENT_TYPE), ([], None))

    async def test_echo_of_the_sent_cursor_on_an_empty_page_is_the_end(self):
        self.response = page([], "c1")
        self.assertEqual(
            await self.client.account_resources(ADDRESS, Pagination(start="c1")),
            ([], None),
        )
        self.assertEqual(
            await self.client.account_coin_transactions(
                ADDRESS, PaginationWithOrder(start="c1")
            ),
            ([], None),
        )
        self.assertEqual(
            await self.client.account_automated_transactions(
                ADDRESS, AutomatedTransactionsPagination(cursor="c1")
            ),
            ([], None),
        )
        self.response = page([], "c1", wrap=True)
        self.assertEqual(
            await self.client.events_by_type(EVENT_TYPE, EventsPagination(start="c1")),
            ([], None),
        )

    async def test_empty_page_with_a_new_cursor_is_returned(self):
        self.response = page([], "c2")
        self.assertEqual(
            await self.client.account_coin_transactions(
                ADDRESS, PaginationWithOrder(start="c1")
            ),
            ([], "c2"),
        )
        self.response = page([], "c2", wrap=True)
        self.assertEqual(
            await self.client.events_by_type(EVENT_TYPE, EventsPagination(start="c1")),
            ([], "c2"),
        )


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

    async def test_an_empty_page_with_a_new_cursor_does_not_end_the_iteration(self):
        # A filter can exclude every row a page read; the page is empty and the cursor moves on.
        pages = {
            None: page([1], "c1", wrap=True),
            "c1": page([], "c2", wrap=True),
            "c2": page([2], None, wrap=True),
        }
        self.node = await FakeNode.create(
            lambda request: pages[request.url.params.get("start")]
        )
        items = await collect(self.node.client.iter_events_by_type(EVENT_TYPE))
        self.assertEqual(items, [1, 2])
        self.assertEqual(len(self.node.requests), 3)

    async def test_an_empty_coin_transactions_page_with_a_new_cursor_continues(self):
        pages = {
            None: page([1], "100"),
            "100": page([], "90"),
            "90": page([2], "80"),
            "80": page([], "0"),
        }
        self.node = await FakeNode.create(
            lambda request: pages[request.url.params.get("start")]
        )
        items = await collect(self.node.client.iter_account_coin_transactions(ADDRESS))
        self.assertEqual(items, [1, 2])
        self.assertEqual(len(self.node.requests), 4)

    async def test_zero_on_a_page_with_items_continues_the_iteration(self):
        # Block 0 has timestamp 0, so a genesis row's cursor is 0.
        pages = {
            None: page([1], "0"),
            "0": page([2], "5"),
            "5": page([], None),
        }
        self.node = await FakeNode.create(
            lambda request: pages[request.url.params.get("start")]
        )
        items = await collect(
            self.node.client.iter_account_coin_transactions(
                ADDRESS, PaginationWithOrder(ascending=True)
            )
        )
        self.assertEqual(items, [1, 2])
        self.assertEqual(self.node.params(1), {"start": "0", "ascending": "true"})

    async def test_a_missing_header_ends_the_iteration_on_an_empty_page(self):
        self.node = await FakeNode.create(lambda _: page([], None))
        items = await collect(
            self.node.client.iter_account_automated_transactions(ADDRESS)
        )
        self.assertEqual(items, [])
        self.assertEqual(len(self.node.requests), 1)

    async def test_iterator_is_lazy(self):
        self.node = await FakeNode.create(lambda _: page([1], "c"))
        self.node.client.iter_account_resources(ADDRESS)
        self.assertEqual(self.node.requests, [])


class TypedAscendingFeedTests(unittest.IsolatedAsyncioTestCase):
    """`paginate` over a feed read in ascending order with a `type` filter, where `"0"` on the first empty page can
    be a genesis row's position. No feed on this client takes a `type` filter yet; the fetch is built the way such a
    feed would use `next_cursor`."""

    def feed(self, responses: dict[str | None, httpx.Response]):
        self.sent: list[str | None] = []

        async def fetch(p: PaginationWithOrder) -> tuple[list[Any], str | None]:
            self.sent.append(p.start)
            response = responses[p.start]
            items = response.json()
            zero_continues = p.start is None and p.ascending is True
            return items, next_cursor(
                response, items, sent=p.start, zero_continues=zero_continues
            )

        return paginate(
            fetch,
            PaginationWithOrder(ascending=True),
            lambda p, cursor: replace(p, start=cursor),
        )

    async def test_zero_continues_once_and_its_echo_ends_the_feed(self):
        items = await collect(self.feed({None: page([], "0"), "0": page([], "0")}))
        self.assertEqual(items, [])
        self.assertEqual(self.sent, [None, "0"])

    async def test_zero_continues_to_the_rows_after_a_genesis_row(self):
        items = await collect(
            self.feed(
                {None: page([], "0"), "0": page([1, 2], "7"), "7": page([], None)}
            )
        )
        self.assertEqual(items, [1, 2])
        self.assertEqual(self.sent, [None, "0", "7"])

    async def test_zero_on_a_later_empty_page_ends_the_feed(self):
        items = await collect(self.feed({None: page([1], "7"), "7": page([], "0")}))
        self.assertEqual(items, [1])
        self.assertEqual(self.sent, [None, "7"])


class AccountHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await self.node.close()

    async def test_requests_the_history_route_with_the_options(self):
        self.node = await FakeNode.create(lambda _: page([], None))
        await self.node.client.account_history(
            "0x1",
            PaginationWithOrder(count=50, start="12", ascending=True),
            [AccountHistoryCategory.SENT, "fa"],
        )
        self.assertEqual(self.node.requests[0].url.path, "/rpc/v3/accounts/0x1/history")
        self.assertEqual(
            self.node.params(0),
            {
                "count": "50",
                "start": "12",
                "ascending": "true",
                "categories": "sent,fa",
            },
        )

    async def test_sends_no_options_by_default(self):
        self.node = await FakeNode.create(lambda _: page([], None))
        await self.node.client.account_history(ADDRESS)
        self.assertEqual(self.node.params(0), {})

    async def test_a_single_category_is_accepted(self):
        self.node = await FakeNode.create(lambda _: page([], None))
        await self.node.client.account_history(ADDRESS, categories="coin")
        await self.node.client.account_history(
            ADDRESS, categories=AccountHistoryCategory.DA
        )
        self.assertEqual(self.node.params(0), {"categories": "coin"})
        self.assertEqual(self.node.params(1), {"categories": "da"})

    async def test_invalid_categories_are_rejected_before_a_request(self):
        self.node = await FakeNode.create(lambda _: page([], None))
        for categories in ([], ["sent", "automated"], "sent,fa", ["SENT"]):
            with self.assertRaises(ValueError):
                await self.node.client.account_history(ADDRESS, categories=categories)
        self.assertEqual(self.node.requests, [])

    async def test_only_a_missing_header_ends_a_page(self):
        self.node = await FakeNode.create(lambda _: self.response)
        client = self.node.client
        self.response = page([], "0")
        self.assertEqual(await client.account_history(ADDRESS), ([], "0"))
        self.response = page([], "7")
        self.assertEqual(
            await client.account_history(ADDRESS, PaginationWithOrder(start="7")),
            ([], "7"),
        )
        self.response = page([{"n": 1}], "0")
        self.assertEqual(await client.account_history(ADDRESS), ([{"n": 1}], "0"))
        self.response = page([{"n": 1}], None)
        self.assertEqual(await client.account_history(ADDRESS), ([{"n": 1}], None))
        self.response = page([], "")
        self.assertEqual(await client.account_history(ADDRESS), ([], None))

    async def test_a_node_without_the_route_raises_api_error(self):
        self.node = await FakeNode.create(lambda _: httpx.Response(404))
        with self.assertRaises(ApiError) as raised:
            await self.node.client.account_history(ADDRESS)
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.message, "")

    async def test_iterator_pages_past_an_empty_page_and_the_zero_cursor(self):
        # The node filters by category while it scans: a page can be empty and carry a cursor, and "0" is the
        # cursor of a genesis-block row.
        pages = {
            None: page([1], "9"),
            "9": page([], "4"),
            "4": page([], "0"),
            "0": page([2], None),
        }
        self.node = await FakeNode.create(
            lambda request: pages[request.url.params.get("start")]
        )
        items = await collect(
            self.node.client.iter_account_history(
                ADDRESS,
                PaginationWithOrder(count=1),
                (category for category in ["fa", "sent"]),
            )
        )
        self.assertEqual(items, [1, 2])
        self.assertEqual(len(self.node.requests), 4)
        self.assertEqual(self.node.params(0), {"count": "1", "categories": "fa,sent"})
        self.assertEqual(
            self.node.params(3), {"count": "1", "start": "0", "categories": "fa,sent"}
        )

    async def test_iterator_stops_when_a_cursor_repeats(self):
        self.node = await FakeNode.create(lambda _: page([], "0"))
        items = await collect(self.node.client.iter_account_history(ADDRESS))
        self.assertEqual(items, [])
        self.assertEqual(len(self.node.requests), 2)


class ReadObjectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await self.node.close()

    async def test_address_without_resources_takes_one_request(self):
        self.node = await FakeNode.create(lambda _: page([], None))
        result = await SupraTokenObjectClient(self.node.client).read_object(ADDRESS)
        self.assertEqual(result.resources, {})
        self.assertEqual(len(self.node.requests), 1)
        self.assertEqual(self.node.params(0), {"count": "100"})

    async def test_empty_pages_end_when_the_node_echoes_the_cursor(self):
        # An empty page with a cursor continues once; the node's echo of that cursor then ends the feed.
        self.node = await FakeNode.create(lambda _: page([], "c"))
        await SupraTokenObjectClient(self.node.client).read_object(ADDRESS)
        self.assertEqual(len(self.node.requests), 2)
        self.assertEqual(self.node.params(1), {"count": "100", "start": "c"})

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
