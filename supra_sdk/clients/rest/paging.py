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
    zero_ends_empty_page: bool = False,
) -> str | None:
    """Reads the cursor of the next page from the `x-supra-cursor` response header.

    A feed ends when the header is absent or empty, and the result is then `None`. Nodes up to v11.7.x send an empty
    header at the end of most feeds; later nodes omit it.

    Args:
        response (httpx.Response): Response of a paged request.
        page (list[Any]): The items of the page the response carried.
        zero_ends_empty_page (bool): Treat the cursor `"0"` on an empty page as the end of the feed. Nodes up to
            v11.7.x answer the request that reads no coin transaction with `x-supra-cursor: 0`, and a request that
            continues from `0` restarts the feed from the newest transaction. Later nodes omit the header instead, and
            `0` is a valid cursor there when the page lists items. Default to False.

    Returns:
        str | None: The cursor to pass back to read the next page, or `None` when the feed has ended.

    """
    cursor = response.headers.get(CURSOR_HEADER, "")
    if not cursor.strip():
        return None
    if zero_ends_empty_page and cursor == "0" and not page:
        return None
    return cursor


async def paginate[P](
    fetch: Callable[[P], Awaitable[tuple[list[Any], str | None]]],
    pagination: P,
    with_cursor: Callable[[P, str], P],
) -> AsyncIterator[Any]:
    """Yields every item of a paged feed, requesting pages until the feed ends.

    The feed ends at the first empty page, at the first response without a cursor, and when the node returns a cursor
    that an earlier response already returned, so that a node that answers with the same cursor forever cannot make
    the iteration loop.

    Args:
        fetch (Callable): Requests one page for the given pagination options and returns the items and the cursor of
            the next page, e.g. a bound `account_resources`.
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
        if not items or cursor is None or cursor in seen:
            return
        seen.add(cursor)
        pagination = with_cursor(pagination, cursor)
