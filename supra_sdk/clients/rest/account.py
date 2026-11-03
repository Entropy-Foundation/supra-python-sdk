# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

from typing import Any

import httpx

from supra_sdk.account_address import AccountAddress
from supra_sdk.clients.rest.rest_client import RestClient
from supra_sdk.clients.rest.rest_types import (
    ACCOUNT_AUTOMATED_TRANSACTIONS_ENDPOINT,
    ACCOUNT_COIN_TRANSACTIONS_ENDPOINT,
    ACCOUNT_ENDPOINT,
    ACCOUNT_FA_TRANSACTIONS_ENDPOINT,
    ACCOUNT_MODULE_ENDPOINT,
    ACCOUNT_MODULES_ENDPOINT,
    ACCOUNT_RESOURCE_ENDPOINT,
    ACCOUNT_RESOURCES_ENDPOINT,
    ACCOUNT_TRANSACTIONS_ENDPOINT,
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


def _next_cursor(
    response: httpx.Response,
    page: list[Any],
    *,
    sent: Any = None,
    zero_continues: bool = False,
) -> str | None:
    """The cursor of the next page of `fa_transactions`, or `None` when the response ends the feed. The rule is
    stated at `AccountRestClient.account_fa_transactions`.

    Args:
        response (httpx.Response): Response of a paged request.
        page (list[Any]): The items of the page the response carried.
        sent (Any): The cursor the request was sent with, or `None` when it carried none. An empty string counts as
            none. Default to None.
        zero_continues (bool): True when the request had no cursor, was ascending and carried a `type` filter.
            Default to False.

    Returns:
        str | None: The cursor to pass back to read the next page, or `None` when the feed has ended.

    """
    cursor = response.headers.get("x-supra-cursor", "")
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
    ) -> tuple[list[dict[str, Any]], str]:
        """Retrieves all account resources for a given account.

        Args:
            account_address (AccountAddress | str): Address of the account, as an `AccountAddress` or a hex string.
            pagination (Pagination | None): Pagination options. Default to None.

        Returns:
            tuple[list[dict[str, Any]], str]: A tuple containing,
                - list[dict[str, Any]]: All account resources for a given account.
                - str: Cursor to retrieve the next page.

        """
        endpoint = format_endpoint(
            ACCOUNT_RESOURCES_ENDPOINT, account_address=account_address
        )
        params = pagination.to_params() if pagination else {}
        response = await self.api_client.get(endpoint=endpoint, params=params)
        return response.json(), response.headers.get("x-supra-cursor", "")

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
    ) -> tuple[list[dict[str, Any]], str]:
        """Retrieves all account modules from a given account.

        Args:
            account_address (AccountAddress | str): Address of the account, as an `AccountAddress` or a hex string.
            pagination (Pagination | None): Pagination options. Default to None.

        Returns:
            tuple[list[dict[str, Any]], str]: A tuple containing,
                - list[dict[str, Any]]: All account modules from a given account.
                - str: Cursor to retrieve the next page.

        """
        endpoint = format_endpoint(
            ACCOUNT_MODULES_ENDPOINT, account_address=account_address
        )
        params = pagination.to_params() if pagination else {}
        response = await self.api_client.get(endpoint=endpoint, params=params)
        return response.json(), response.headers.get("x-supra-cursor", "")

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
    ) -> tuple[list[dict[str, Any]], str]:
        """Retrieves details of finalized coin deposit/withdraw type transactions associated with a given account.

        It lists movements of the account's `CoinStore` only. It does not list SUPRA held in primary fungible stores,
        which is how accounts hold SUPRA on Devnet, and on Testnet and Mainnet once the features that hold SUPRA in
        primary stores (64 and 65) are enabled. Use `account_fa_transactions` for those.

        Args:
            account_address (AccountAddress | str): Address of the account, as an `AccountAddress` or a hex string.
            pagination (PaginationWithOrder | None): Pagination options. Default to None.

        Returns:
            tuple[list[dict[str, Any]], str]: A tuple containing,
                - list[dict[str, Any]]: Details of finalized coin deposit/withdraw type transactions associated with a
                    given account.
                - str: Cursor to retrieve the next page.

        """
        endpoint = format_endpoint(
            ACCOUNT_COIN_TRANSACTIONS_ENDPOINT, account_address=account_address
        )
        params = pagination.to_params() if pagination else {}
        response = await self.api_client.get(endpoint=endpoint, params=params)
        return response.json(), response.headers.get("x-supra-cursor", "")

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
        return page, _next_cursor(
            response, page, sent=sent, zero_continues=zero_continues
        )

    async def account_automated_transactions(
        self,
        account_address: AccountAddress | str,
        pagination: AutomatedTransactionsPagination | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        """Retrieves details of finalized automated transactions based on the automation tasks registered by a given
            account.

        Args:
            account_address (AccountAddress | str): Address of the account, as an `AccountAddress` or a hex string.
            pagination (AutomatedTransactionsPagination | None): Pagination options. Default to None.

        Returns:
            tuple[list[dict[str, Any]], str]: A tuple containing,
                - list[dict[str, Any]]: Details of finalized automated transactions details based on the automation
                    tasks registered by a given account.
                - str: Cursor to retrieve the next page.

        """
        endpoint = format_endpoint(
            ACCOUNT_AUTOMATED_TRANSACTIONS_ENDPOINT, account_address=account_address
        )
        params = pagination.to_params() if pagination else {}
        response = await self.api_client.get(endpoint=endpoint, params=params)
        return response.json(), response.headers.get("x-supra-cursor", "")
