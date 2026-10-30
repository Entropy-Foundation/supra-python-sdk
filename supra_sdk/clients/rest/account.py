# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

from supra_sdk.account_address import AccountAddress
from supra_sdk.clients.rest.paging import next_cursor, paginate
from supra_sdk.clients.rest.rest_client import RestClient
from supra_sdk.clients.rest.rest_types import (
    ACCOUNT_AUTOMATED_TRANSACTIONS_ENDPOINT,
    ACCOUNT_COIN_TRANSACTIONS_ENDPOINT,
    ACCOUNT_ENDPOINT,
    ACCOUNT_MODULE_ENDPOINT,
    ACCOUNT_MODULES_ENDPOINT,
    ACCOUNT_RESOURCE_ENDPOINT,
    ACCOUNT_RESOURCES_ENDPOINT,
    ACCOUNT_TRANSACTIONS_ENDPOINT,
    AutomatedTransactionsPagination,
    Pagination,
    PaginationWithOrder,
    format_endpoint,
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
        return page, next_cursor(response, page)

    def iter_account_resources(
        self,
        account_address: AccountAddress | str,
        pagination: Pagination | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Iterates over all resources of a given account, requesting further pages until the feed ends.

        The iteration stops at the first empty page or the first response without a cursor.

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
        return page, next_cursor(response, page)

    def iter_account_modules(
        self,
        account_address: AccountAddress | str,
        pagination: Pagination | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Iterates over all modules of a given account, requesting further pages until the feed ends.

        The iteration stops at the first empty page or the first response without a cursor.

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
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Retrieves details of finalized coin deposit/withdraw type transactions associated with a given account.

        Args:
            account_address (AccountAddress | str): Address of the account, as an `AccountAddress` or a hex string.
            pagination (PaginationWithOrder | None): Pagination options. Default to None.

        Returns:
            tuple[list[dict[str, Any]], str | None]: A tuple containing,
                - list[dict[str, Any]]: Details of finalized coin deposit/withdraw type transactions associated with a
                    given account.
                - str | None: Cursor to retrieve the next page, or `None` when the feed has ended. Nodes up to
                    v11.7.x end this feed with the cursor `0` on an empty page; that is reported as `None` too.

        """
        endpoint = format_endpoint(
            ACCOUNT_COIN_TRANSACTIONS_ENDPOINT, account_address=account_address
        )
        params = pagination.to_params() if pagination else {}
        response = await self.api_client.get(endpoint=endpoint, params=params)
        page = response.json()
        return page, next_cursor(response, page, zero_ends_empty_page=True)

    def iter_account_coin_transactions(
        self,
        account_address: AccountAddress | str,
        pagination: PaginationWithOrder | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Iterates over all coin deposit/withdraw type transactions of a given account, requesting further pages
        until the feed ends.

        The iteration stops at the first empty page or the first response without a cursor.

        Args:
            account_address (AccountAddress | str): Address of the account, as an `AccountAddress` or a hex string.
            pagination (PaginationWithOrder | None): Pagination options of the first request; `count` sets the page
                size, `start` the cursor to begin from and `ascending` the order. Default to None.

        Returns:
            AsyncIterator[dict[str, Any]]: The transactions, in the requested order.

        """
        return paginate(
            lambda p: self.account_coin_transactions(account_address, p),
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
        return page, next_cursor(response, page)

    def iter_account_automated_transactions(
        self,
        account_address: AccountAddress | str,
        pagination: AutomatedTransactionsPagination | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Iterates over all automated transactions of a given account, requesting further pages until the feed ends.

        The iteration stops at the first empty page or the first response without a cursor.

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
