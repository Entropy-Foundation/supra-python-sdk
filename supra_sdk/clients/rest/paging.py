# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx

CURSOR_HEADER = "x-supra-cursor"


def next_cursor(
    response: httpx.Response,
    page: list[Any],
    *,
    sent: Any = None,
    zero_continues: bool = False,
) -> str | None:
    """Reads the cursor of the next page from the `x-supra-cursor` response header, or `None` when the response ends
    the feed.

    A node from v12 onwards ends a feed by omitting the header. A v11.7.x node ends it with one of these values, each
    of which is read as the end of the feed:

    - an empty header (events, automated transactions, and the resources or modules of an account without any);
    - `"0"` on a page without items (coin and fungible asset transactions);
    - the request's own cursor on a page without items (resources and modules).

    A page without items that carries any other cursor does not end the feed: the node read entries that the
    request's filters excluded, and the next page continues after them. `"0"` on a page with items is a cursor.

    `"0"` is also a valid cursor: block 0 has timestamp 0, so the first row of a store funded at genesis has the
    cursor 0, and a `type` filter that excludes that row leaves an empty page with `"0"`. For the first
    request of an ascending read with a `type` filter on coin or fungible asset transactions, `zero_continues` keeps
    the `"0"`, and the next request continues with `start=0`. On a feed without rows the node answers that request
    with `"0"` again, which the rule for the request's own cursor ends, so this costs at most one more request.

    Args:
        response (httpx.Response): Response of a paged request.
        page (list[Any]): The items of the page the response carried.
        sent (Any): The cursor the request was sent with, or `None` when it carried none. An empty string counts as
            none. Default to None.
        zero_continues (bool): True when the request had no cursor, was ascending and carried a `type` filter on a
            feed whose cursor `"0"` can be the position of a genesis row (coin and fungible asset transactions).
            Default to False.

    Returns:
        str | None: The cursor to pass back to read the next page, or `None` when the feed has ended.

    """
    cursor = response.headers.get(CURSOR_HEADER, "")
    if not cursor.strip():
        return None
    if page:
        return cursor
    if cursor == "0" and zero_continues:
        return cursor
    sent_cursor = None if sent is None or sent == "" else str(sent)
    if cursor == "0" or cursor == sent_cursor:
        return None
    return cursor


async def paginate[P](
    fetch: Callable[[P], Awaitable[tuple[list[Any], str | None]]],
    pagination: P,
    with_cursor: Callable[[P, str], P],
) -> AsyncIterator[Any]:
    """Yields every item of a paged feed, requesting pages until the feed ends.

    The feed ends when `fetch` returns `None` as the cursor (see `next_cursor`), and when the node returns a cursor
    that an earlier response already returned, so that a node that answers with the same cursor forever cannot make
    the iteration loop. An empty page with a new cursor does not end it: a filter can exclude every row a page read.

    Args:
        fetch (Callable): Requests one page for the given pagination options and returns the items and the cursor of
            the next page as computed by `next_cursor`, e.g. a bound `account_resources`.
        pagination (P): Pagination options of the first request.
        with_cursor (Callable): Returns the pagination options of the request that continues from a cursor.

    Yields:
        Any: The items of each page, in the order the node returned them.

    """
    seen: set[str] = set()
    while True:
        items, cursor = await fetch(pagination)
        for item in items:
            yield item
        if cursor is None or cursor in seen:
            return
        seen.add(cursor)
        pagination = with_cursor(pagination, cursor)
