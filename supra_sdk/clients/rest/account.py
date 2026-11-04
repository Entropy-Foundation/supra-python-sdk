# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

from collections.abc import AsyncIterator, Iterable
from dataclasses import replace
from typing import Any

from supra_sdk.account_address import AccountAddress
from supra_sdk.clients.rest.paging import next_cursor, paginate
from supra_sdk.clients.rest.rest_client import RestClient
from supra_sdk.clients.rest.rest_types import (
    ACCOUNT_AUTOMATED_TRANSACTIONS_ENDPOINT,
    ACCOUNT_COIN_TRANSACTIONS_ENDPOINT,
    ACCOUNT_ENDPOINT,
    ACCOUNT_FA_TRANSACTIONS_ENDPOINT,
    ACCOUNT_HISTORY_ENDPOINT,
    ACCOUNT_MODULE_ENDPOINT,
    ACCOUNT_MODULES_ENDPOINT,
    ACCOUNT_RESOURCE_ENDPOINT,
    ACCOUNT_RESOURCES_ENDPOINT,
    ACCOUNT_TRANSACTIONS_ENDPOINT,
    AccountHistoryCategory,
    AutomatedTransactionsPagination,
    Pagination,
    PaginationWithOrder,
    TransactionType,
    format_endpoint,
)
from supra_sdk.fungible_asset import (
    SUPRA_FA_METADATA_ADDRESS,
    primary_store_address,
)


class AccountRestClient(RestClient):
    """A class that provides methods to invoke `Account` REST endpoints from a Supra RPC node.

    Attributes:
        api_client (supra_sdk.clients.api_client.ApiClient): Inherited from `RestClient`. Used to send HTTP requests to the Supra RPC node.

    """

    async def account(
        self,
        account_address: AccountAddress | str,
    ) -> dict[str, str]:
        """Provides the authentication key and the sequence number of the given account.

        Args:
            account_address (AccountAddress | str): Address of the account, as an `AccountAddress` or a hex string.

        Returns:
            dict[str, str]: The authentication key and sequence number of the given account.

        """
        endpoint = format_endpoint(ACCOUNT_ENDPOINT, account_address=account_address)
        return (await self.api_client.get(endpoint=endpoint)).json()

    async def account_resource(
        self,
        account_address: AccountAddress | str,
        resource_type: str,
    ) -> dict[str, Any]:
        """Retrieves an individual resource from a given account.

        Args:
            account_address (AccountAddress | str): Address of the account, as an `AccountAddress` or a hex string.
            resource_type (str): Type of the resource e.g. '0x1::account::Account'.

        Returns:
            dict[str, Any]: An individual resource from a given account.

        """
        endpoint = format_endpoint(
            ACCOUNT_RESOURCE_ENDPOINT,
            account_address=account_address,
            resource_type=resource_type,
        )
        return (await self.api_client.get(endpoint=endpoint)).json()

    async def account_resources(
        self,
        account_address: AccountAddress | str,
        pagination: Pagination | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Retrieves all account resources for a given account.

        Args:
            account_address (AccountAddress | str): Address of the account, as an `AccountAddress` or a hex string.
            pagination (Pagination | None): Pagination options. Default to None.

        Returns:
            tuple[list[dict[str, Any]], str | None]: A tuple containing,
                - list[dict[str, Any]]: All account resources for a given account.
                - str | None: Cursor to retrieve the next page, or `None` when the feed has ended.

        """
        endpoint = format_endpoint(
            ACCOUNT_RESOURCES_ENDPOINT, account_address=account_address
        )
        params = pagination.to_params() if pagination else {}
        response = await self.api_client.get(endpoint=endpoint, params=params)
        page = response.json()
        return page, next_cursor(response, page, sent=params.get("start"))

    def iter_account_resources(
        self,
        account_address: AccountAddress | str,
        pagination: Pagination | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Iterates over all resources of a given account, requesting further pages until the feed ends.

        The iteration ends when the node sends no next cursor or repeats one (see
        `supra_sdk.clients.rest.paging.next_cursor`). An empty page with a new cursor does not end it.

        Args:
            account_address (AccountAddress | str): Address of the account, as an `AccountAddress` or a hex string.
            pagination (Pagination | None): Pagination options of the first request; `count` sets the page size and
                `start` the cursor to begin from. Default to None.

        Returns:
            AsyncIterator[dict[str, Any]]: The resources, in the order the node returns them.

        """
        return paginate(
            lambda p: self.account_resources(account_address, p),
            pagination or Pagination(),
            lambda p, cursor: replace(p, start=cursor),
        )

    async def account_module(
        self,
        account_address: AccountAddress | str,
        module_name: str,
    ) -> dict[str, Any]:
        """Retrieves an individual module from a given account.

        Args:
            account_address (AccountAddress | str): Address of the account, as an `AccountAddress` or a hex string.
            module_name (str): Name of the module to retrieve e.g. 'account'

        Returns:
            dict[str, Any]: An individual module from a given account.

        """
        endpoint = format_endpoint(
            ACCOUNT_MODULE_ENDPOINT,
            account_address=account_address,
            module_name=module_name,
        )
        return (await self.api_client.get(endpoint=endpoint)).json()

    async def account_modules(
        self,
        account_address: AccountAddress | str,
        pagination: Pagination | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Retrieves all account modules from a given account.

        Args:
            account_address (AccountAddress | str): Address of the account, as an `AccountAddress` or a hex string.
            pagination (Pagination | None): Pagination options. Default to None.

        Returns:
            tuple[list[dict[str, Any]], str | None]: A tuple containing,
                - list[dict[str, Any]]: All account modules from a given account.
                - str | None: Cursor to retrieve the next page, or `None` when the feed has ended.

        """
        endpoint = format_endpoint(
            ACCOUNT_MODULES_ENDPOINT, account_address=account_address
        )
        params = pagination.to_params() if pagination else {}
        response = await self.api_client.get(endpoint=endpoint, params=params)
        page = response.json()
        return page, next_cursor(response, page, sent=params.get("start"))

    def iter_account_modules(
        self,
        account_address: AccountAddress | str,
        pagination: Pagination | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Iterates over all modules of a given account, requesting further pages until the feed ends.

        The iteration ends when the node sends no next cursor or repeats one (see
        `supra_sdk.clients.rest.paging.next_cursor`). An empty page with a new cursor does not end it.

        Args:
            account_address (AccountAddress | str): Address of the account, as an `AccountAddress` or a hex string.
            pagination (Pagination | None): Pagination options of the first request; `count` sets the page size and
                `start` the cursor to begin from. Default to None.

        Returns:
            AsyncIterator[dict[str, Any]]: The modules, in the order the node returns them.

        """
        return paginate(
            lambda p: self.account_modules(account_address, p),
            pagination or Pagination(),
            lambda p, cursor: replace(p, start=cursor),
        )

    async def account_transactions(
        self,
        account_address: AccountAddress | str,
        pagination: PaginationWithOrder | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieves details of finalized transactions sent by a given account.

        Args:
            account_address (AccountAddress | str): Address of the account, as an `AccountAddress` or a hex string.
            pagination (PaginationWithOrder | None): Pagination options. Default to None.
                Note: Sequence number would be used as start in pagination option.

        Returns:
            list[dict[str, Any]]: Details of finalized transactions sent by a given account.

        """
        endpoint = format_endpoint(
            ACCOUNT_TRANSACTIONS_ENDPOINT, account_address=account_address
        )
        params = pagination.to_params() if pagination else {}
        return (await self.api_client.get(endpoint=endpoint, params=params)).json()

    async def account_coin_transactions(
        self,
        account_address: AccountAddress | str,
        pagination: PaginationWithOrder | None = None,
        transaction_type: TransactionType | str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Retrieves details of finalized coin deposit/withdraw type transactions associated with a given account.

        It lists movements of the account's `CoinStore` only. It does not list SUPRA held in primary fungible stores,
        which is how accounts hold SUPRA on Devnet, and on Testnet and Mainnet once a feature that holds SUPRA in
        primary stores (64 or 65) is enabled. Use `account_fa_transactions` for those.

        Args:
            account_address (AccountAddress | str): Address of the account, as an `AccountAddress` or a hex string.
            pagination (PaginationWithOrder | None): Pagination options. Default to None.
            transaction_type (TransactionType | str | None): Keeps only transactions of this type (`auto`, `user`,
                `meta`, `record` or, on v12 nodes only, `settlement`), as a `TransactionType` or its string value.
                It is sent as the node's `type` query parameter; a v11.7.x node rejects `settlement` with HTTP 400.
                The node applies it after reading a page, so a filtered page can be empty and still carry a cursor.
                Default to None, which keeps every type; an empty string is not sent and also keeps every type.

        Returns:
            tuple[list[dict[str, Any]], str | None]: A tuple containing,
                - list[dict[str, Any]]: Details of finalized coin deposit/withdraw type transactions associated with a
                    given account. While feature 64 or 65 is enabled, registering SUPRA creates the account's primary
                    fungible store instead of a `CoinStore<SupraCoin>`, so new accounts, and accounts that migrated
                    their SUPRA, hold SUPRA in their primary store and the list holds none of its movements. On a
                    chain created with those features on, such as Devnet, no account has a `CoinStore<SupraCoin>`.
                    `account_history` with the category `fa` lists those movements too, on nodes from
                    `supra_node_v12.0.0`.
                - str | None: Cursor to retrieve the next page, or `None` when the feed has ended. Nodes up to
                    v11.7.x end this feed with the cursor `0` on an empty page; that is reported as `None` too,
                    except for the first request (no `start`) of an ascending read with a `transaction_type`: block 0
                    has timestamp 0, so `0` can be the position of a genesis row that the filter excluded, and `0` is
                    returned. The node answers the request with `start=0` that follows with `0` again (v11.7.x) or
                    without a cursor (v12) when the feed has no further rows; both end the feed. An empty page
                    carrying a cursor other than `0` and the request's own does not end the feed.

        """
        endpoint = format_endpoint(
            ACCOUNT_COIN_TRANSACTIONS_ENDPOINT, account_address=account_address
        )
        params = pagination.to_params() if pagination else {}
        # An empty `transaction_type` is not a type, so, like an empty `start`, it is not sent.
        filtered = transaction_type is not None and transaction_type != ""
        if filtered:
            params["type"] = str(
                transaction_type.value
                if isinstance(transaction_type, TransactionType)
                else transaction_type
            )
        response = await self.api_client.get(endpoint=endpoint, params=params)
        page = response.json()
        # Without a `type` filter `"0"` on an empty page is the end of the feed on both node lines. With one, the
        # first ascending page can be empty with `"0"` because the filter excluded a genesis row, so it continues.
        sent = params.get("start")
        zero_continues = (
            sent is None
            and pagination is not None
            and pagination.ascending is True
            and filtered
        )
        return page, next_cursor(
            response, page, sent=sent, zero_continues=zero_continues
        )

    def iter_account_coin_transactions(
        self,
        account_address: AccountAddress | str,
        pagination: PaginationWithOrder | None = None,
        transaction_type: TransactionType | str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Iterates over all coin deposit/withdraw type transactions of a given account, requesting further pages
        until the feed ends.

        The iteration ends when the node sends no next cursor or repeats one (see
        `supra_sdk.clients.rest.paging.next_cursor`). An empty page with a new cursor does not end it.

        It does not list SUPRA held in primary fungible stores: that of every account on a chain created with
        features 64 and 65 on, such as Devnet, and, while feature 64 or 65 is enabled, that of new accounts and of
        accounts that migrated their SUPRA; see `account_coin_transactions`. Use `account_fa_transactions`, or
        `iter_account_history` with the category `fa` on nodes from `supra_node_v12.0.0`, for those.

        Args:
            account_address (AccountAddress | str): Address of the account, as an `AccountAddress` or a hex string.
            pagination (PaginationWithOrder | None): Pagination options of the first request; `count` sets the page
                size, `start` the cursor to begin from and `ascending` the order. Default to None.
            transaction_type (TransactionType | str | None): Keeps only transactions of this type, as for
                `account_coin_transactions`; `settlement` needs a v12 node. Default to None, which keeps every type.

        Returns:
            AsyncIterator[dict[str, Any]]: The transactions, in the requested order.

        """
        return paginate(
            lambda p: self.account_coin_transactions(
                account_address, p, transaction_type
            ),
            pagination or PaginationWithOrder(),
            lambda p, cursor: replace(p, start=cursor),
        )

    async def account_fa_transactions(
        self,
        account_address: AccountAddress | str,
        pagination: PaginationWithOrder | None = None,
        metadata_address: AccountAddress | str = SUPRA_FA_METADATA_ADDRESS,
        transaction_type: TransactionType | str | None = None,
        *,
        store_address: AccountAddress | str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Retrieves details of finalized transactions that deposited to or withdrew from an account's fungible store.

        The node lists these transactions per fungible store (`GET /rpc/v3/accounts/{store}/fa_transactions`), not
        per account. This method derives the address of the account's primary store of the fungible asset
        (`supra_sdk.fungible_asset.primary_store_address`) and queries it, so it lists the transactions that moved
        the asset of `metadata_address` in or out of that store: SUPRA by default (`0xa`). It does not list
        transactions that touched the account's `CoinStore`; use `account_coin_transactions` for those. SUPRA moved
        before a migration to the fungible store is listed by `account_coin_transactions`, and after it here.

        Paging: pass the returned cursor as `PaginationWithOrder(start=cursor)` to read the next page, and stop a
        walk, filtered or not, when the returned cursor is `None`. A walk that also stops on a cursor it has already
        been given cannot loop. An empty page does not end the walk: the node's cursor is that of the last row it
        read, whether or not the row matched `transaction_type`, so a filtered page can be empty and still carry a
        cursor. The returned cursor is computed from the `x-supra-cursor` header:

        - header absent or empty: `None`. A v12 node omits the header at the end of the feed.
        - page with rows: the header, `"0"` included.
        - page without rows and header `"0"`: `None`, which is how a v11.7.x node ends the feed. The exception is the
          first request (no `start`) of an ascending read with a `transaction_type`: block 0 has timestamp 0, so
          `"0"` can be the position of a genesis row that the filter excluded, and `"0"` is returned. If the feed
          has no further rows the node answers the request with `start="0"` with `"0"` again, which the next rule
          ends.
        - page without rows and header equal to the request's `start`: `None`.
        - any other page without rows: the header.

        An empty `start` is not sent.

        Args:
            account_address (AccountAddress | str): Address of the account that owns the store, as an
                `AccountAddress` or a hex string.
            pagination (PaginationWithOrder | None): Pagination options. Default to None.
            metadata_address (AccountAddress | str): Address of the fungible asset's metadata object. Default to
                `SUPRA_FA_METADATA_ADDRESS` (`0xa`).
            transaction_type (TransactionType | str | None): Keeps only transactions of this type (`auto`, `user`,
                `meta`, `record` or, on v12 nodes only, `settlement`), as a `TransactionType` or its string value.
                The node applies it after reading a page. Default to None, which keeps every type.
            store_address (AccountAddress | str | None): Address of a fungible store to query instead of the primary
                store derived from `account_address` and `metadata_address`, for example a store address read from
                an event. When given, `account_address` and `metadata_address` are not used. Default to None.

        Returns:
            tuple[list[dict[str, Any]], str | None]: A tuple containing,
                - list[dict[str, Any]]: Details of the finalized transactions of the store.
                - str | None: Cursor to retrieve the next page, or `None` when the feed has ended.

        Raises:
            ValueError: If an address is not a valid account address.

        """
        store = (
            primary_store_address(account_address, metadata_address)
            if store_address is None
            else store_address
        )
        endpoint = format_endpoint(
            ACCOUNT_FA_TRANSACTIONS_ENDPOINT, account_address=store
        )
        params = pagination.to_params() if pagination else {}
        # An empty cursor is not a position, so it is never sent.
        start = params.get("start")
        if start is None or start == "":
            params.pop("start", None)
        if transaction_type is not None:
            params["type"] = str(
                transaction_type.value
                if isinstance(transaction_type, TransactionType)
                else transaction_type
            )
        response = await self.api_client.get(endpoint=endpoint, params=params)
        page = response.json()
        sent = params.get("start")
        zero_continues = (
            sent is None
            and pagination is not None
            and pagination.ascending is True
            and transaction_type is not None
        )
        return page, next_cursor(
            response, page, sent=sent, zero_continues=zero_continues
        )

    def iter_account_fa_transactions(
        self,
        account_address: AccountAddress | str,
        pagination: PaginationWithOrder | None = None,
        metadata_address: AccountAddress | str = SUPRA_FA_METADATA_ADDRESS,
        transaction_type: TransactionType | str | None = None,
        *,
        store_address: AccountAddress | str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Iterates over all transactions of an account's fungible store, requesting further pages until the feed
        ends.

        The iteration ends when the node sends no next cursor or repeats one (see
        `supra_sdk.clients.rest.paging.next_cursor`). An empty page with a new cursor does not end it.

        Args:
            account_address (AccountAddress | str): Address of the account that owns the store, as an
                `AccountAddress` or a hex string.
            pagination (PaginationWithOrder | None): Pagination options of the first request; `count` sets the page
                size, `start` the cursor to begin from and `ascending` the order. Default to None.
            metadata_address (AccountAddress | str): Address of the fungible asset's metadata object. Default to
                `SUPRA_FA_METADATA_ADDRESS` (`0xa`).
            transaction_type (TransactionType | str | None): Keeps only transactions of this type, as for
                `account_fa_transactions`; `settlement` needs a v12 node. Default to None, which keeps every type.
            store_address (AccountAddress | str | None): Address of a fungible store to query instead of the primary
                store derived from `account_address` and `metadata_address`. Default to None.

        Returns:
            AsyncIterator[dict[str, Any]]: The transactions, in the requested order.

        Raises:
            ValueError: If an address is not a valid account address; raised when the iteration starts.

        """
        return paginate(
            lambda p: self.account_fa_transactions(
                account_address,
                p,
                metadata_address,
                transaction_type,
                store_address=store_address,
            ),
            pagination or PaginationWithOrder(),
            lambda p, cursor: replace(p, start=cursor),
        )

    async def account_automated_transactions(
        self,
        account_address: AccountAddress | str,
        pagination: AutomatedTransactionsPagination | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Retrieves details of finalized automated transactions based on the automation tasks registered by a given
            account.

        Args:
            account_address (AccountAddress | str): Address of the account, as an `AccountAddress` or a hex string.
            pagination (AutomatedTransactionsPagination | None): Pagination options; set `cursor` to the value
                returned with the previous page to read the next one. Default to None.

        Returns:
            tuple[list[dict[str, Any]], str | None]: A tuple containing,
                - list[dict[str, Any]]: Details of finalized automated transactions details based on the automation
                    tasks registered by a given account.
                - str | None: Cursor to retrieve the next page, or `None` when the feed has ended.

        """
        endpoint = format_endpoint(
            ACCOUNT_AUTOMATED_TRANSACTIONS_ENDPOINT, account_address=account_address
        )
        params = pagination.to_params() if pagination else {}
        response = await self.api_client.get(endpoint=endpoint, params=params)
        page = response.json()
        return page, next_cursor(response, page, sent=params.get("cursor"))

    def iter_account_automated_transactions(
        self,
        account_address: AccountAddress | str,
        pagination: AutomatedTransactionsPagination | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Iterates over all automated transactions of a given account, requesting further pages until the feed ends.

        The iteration ends when the node sends no next cursor or repeats one (see
        `supra_sdk.clients.rest.paging.next_cursor`). An empty page with a new cursor does not end it.

        Args:
            account_address (AccountAddress | str): Address of the account, as an `AccountAddress` or a hex string.
            pagination (AutomatedTransactionsPagination | None): Pagination options of the first request; `count`
                sets the page size, `block_height` the block to begin from and `ascending` the order. Default to None.

        Returns:
            AsyncIterator[dict[str, Any]]: The transactions, in the requested order.

        """
        return paginate(
            lambda p: self.account_automated_transactions(account_address, p),
            pagination or AutomatedTransactionsPagination(),
            lambda p, cursor: replace(p, cursor=cursor),
        )

    async def account_history(
        self,
        account_address: AccountAddress | str,
        pagination: PaginationWithOrder | None = None,
        categories: Iterable[AccountHistoryCategory | str] | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Retrieves the history of an account: every finalized transaction that concerns the account, once each,
        with the categories it matched for the account (`GET /rpc/v3/accounts/{address}/history`).

        It lists the transfers of SUPRA held in primary fungible stores (category `fa`), which
        `account_coin_transactions` does not.

        Needs a node from `supra_node_v12.0.0`. A node before v12 (Testnet and Mainnet until they run v12) answers
        HTTP 404 with an empty body, raised as `supra_sdk.clients.api_client.ApiError` with `status_code` 404 and an
        empty `message`.

        Automated transactions and automation registry records are not listed; use
        `account_automated_transactions` for those. While the node sends the `x-supra-history-indexed-from` response
        header, the history does not cover the blocks below the height it names: the node is indexing, or has not
        indexed, the blocks it held before it kept the history. This method does not return that header, so a caller
        cannot tell from its result whether the history covers the older blocks.

        Paging: the node applies `categories` while it scans the account's history and reads at most 8 rows for
        each entry requested, so a page can hold fewer entries than `count`, or none, before the history is
        exhausted. The history ends only when the response has no `x-supra-cursor` header, which the returned cursor
        reports as `None`. An empty page with a cursor does not end it, and `"0"` is a valid cursor: the position of
        a genesis-block row on a chain whose genesis timestamp is 0. Pass the returned cursor as
        `PaginationWithOrder(start=cursor)` to read the next page.

        Args:
            account_address (AccountAddress | str): Address of the account, as an `AccountAddress` or a hex string.
            pagination (PaginationWithOrder | None): Pagination options: `count` is the number of entries to scan
                for (node default 20, at most 100), `start` the cursor of the previous page (exclusive) and
                `ascending` the order (node default descending). Default to None.
            categories (Iterable[AccountHistoryCategory | str] | None): Return only transactions that matched at
                least one of these categories: `sent` (the account sent it), `coin` (coins moved in or out of the
                account), `fa` (a fungible asset store the account owned moved), `da` (a digital asset or object
                event names the account), as `AccountHistoryCategory` members or their string values. A single
                category is accepted too. Default to None, which the node reads as all four.

        Returns:
            tuple[list[dict[str, Any]], str | None]: A tuple containing,
                - list[dict[str, Any]]: The entries, each `{"categories": [...], "transaction": {...}}`, where
                    `categories` lists the categories the transaction matched for the account, in the order `sent`,
                    `coin`, `fa`, `da`, and `transaction` is a `TransactionV3`, tagged by `txn_type`, as
                    `account_coin_transactions` returns it.
                - str | None: Cursor to retrieve the next page, or `None` when the history has ended.

        Raises:
            ValueError: If `categories` is empty or names something other than `sent`, `coin`, `fa` or `da`.

        """
        endpoint = format_endpoint(
            ACCOUNT_HISTORY_ENDPOINT, account_address=account_address
        )
        params = pagination.to_params() if pagination else {}
        if categories is not None:
            params["categories"] = _history_categories_param(categories)
        response = await self.api_client.get(endpoint=endpoint, params=params)
        page = response.json()
        # The route exists only on v12 nodes, which end a feed by omitting the header; `"0"` is a cursor here.
        return page, next_cursor(response, page, only_missing_header_ends=True)

    def iter_account_history(
        self,
        account_address: AccountAddress | str,
        pagination: PaginationWithOrder | None = None,
        categories: Iterable[AccountHistoryCategory | str] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Iterates over the history of an account, requesting further pages until the history ends.

        The iteration ends when a response has no `x-supra-cursor` header, or when the node repeats a cursor. An
        empty page with a cursor and the cursor `"0"` do not end it. See `account_history` for the node release it
        needs and what the history covers.

        Args:
            account_address (AccountAddress | str): Address of the account, as an `AccountAddress` or a hex string.
            pagination (PaginationWithOrder | None): Pagination options of the first request; `count` sets the page
                size, `start` the cursor to begin from and `ascending` the order. Default to None.
            categories (Iterable[AccountHistoryCategory | str] | None): Categories to return transactions of, as for
                `account_history`. Default to None, which the node reads as all four.

        Returns:
            AsyncIterator[dict[str, Any]]: The entries `{"categories": [...], "transaction": {...}}`, in the
                requested order.

        """
        if categories is not None and not isinstance(categories, str):
            categories = tuple(categories)
        return paginate(
            lambda p: self.account_history(account_address, p, categories),
            pagination or PaginationWithOrder(),
            lambda p, cursor: replace(p, start=cursor),
        )


def _history_categories_param(
    categories: Iterable[AccountHistoryCategory | str],
) -> str:
    """The `categories` query parameter of `account_history`: the category names, comma separated.

    Raises:
        ValueError: If `categories` is empty or names something other than `sent`, `coin`, `fa` or `da`.

    """
    selected = [categories] if isinstance(categories, str) else categories
    names = []
    for category in selected:
        try:
            names.append(AccountHistoryCategory(category).value)
        except ValueError as e:
            valid = ", ".join(c.value for c in AccountHistoryCategory)
            raise ValueError(f"categories must name only {valid}: {category!r}") from e
    if not names:
        raise ValueError("categories must name at least one category")
    return ",".join(names)
