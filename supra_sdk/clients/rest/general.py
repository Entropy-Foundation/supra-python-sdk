# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

from supra_sdk.account_address import AccountAddress
from supra_sdk.clients.rest.paging import next_cursor, paginate
from supra_sdk.clients.rest.rest_client import RestClient
from supra_sdk.clients.rest.rest_types import (
    CHAIN_ID_ENDPOINT,
    EVENTS_BY_TYPE_ENDPOINT,
    TABLE_ITEMS_ENDPOINT,
    VIEW_FUNCTION_ENDPOINT,
    EventsPagination,
    format_endpoint,
)


class GeneralRestClient(RestClient):
    """A class that provides convenient methods to interact with general REST endpoints like `View`, `table` and `Event`
    from a Supra RPC node.

    Attributes:
        api_client (supra_sdk.clients.api_client.ApiClient): Inherited from `RestClient`. Used to send HTTP requests to the Supra RPC node.

    """

    async def network_chain_id(self):
        """Provides the network Chain-ID.

        Returns:
            int: Network Chain-ID.

        """
        return int((await self.api_client.get(endpoint=CHAIN_ID_ENDPOINT)).text)

    async def view(
        self,
        function: str,
        type_arguments: list[str],
        arguments: list[str],
    ) -> list[Any]:
        """Execute a view Move function with the given parameters and return its execution result.

        Args:
            function (str): Entry function id is string representation of an entry function defined on-chain.
            type_arguments (list[str]): Type arguments of the function.
            arguments (list[str]): Arguments of the function.

        Returns:
            list[Any]: Execution results of the view function.

        """
        data = {
            "function": function,
            "type_arguments": type_arguments,
            "arguments": arguments,
        }
        res_data = (
            await self.api_client.post(endpoint=VIEW_FUNCTION_ENDPOINT, data=data)
        ).json()
        return res_data["result"]

    async def get_table_item(
        self,
        table_handle: AccountAddress | str,
        key_type: str,
        value_type: str,
        key: Any,
    ) -> dict[str, Any]:
        """Retrieves an item from a table by key.

        Args:
            table_handle (AccountAddress | str): Table handle to lookup, as an `AccountAddress` or a hex string.
                Should be retrieved using account resources API.
            key_type (str): The type of the table key.
            value_type (str): The type of the table value.
            key (str): The key to fetch from the table.

        Returns:
            dict[str, Any]: Item associated with the key in the table.

        """
        endpoint = format_endpoint(TABLE_ITEMS_ENDPOINT, table_handle=table_handle)
        data = {
            "key_type": key_type,
            "value_type": value_type,
            "key": key,
        }
        return (await self.api_client.post(endpoint=endpoint, data=data)).json()

    async def events_by_type(
        self, event_type: str, pagination: EventsPagination | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Retrieves events of a given type.

        Args:
            event_type (str): The fully qualified name of the event struct e.g. '0x1::coin::CoinDeposit'.
            pagination (EventsPagination | None): Pagination options. Default to None.

        Returns:
            tuple[list[dict[str, Any]], str | None]: A tuple containing,
                - list[dict[str, Any]]: List of events.
                - str | None: Cursor to retrieve the next page, or `None` when the feed has ended.

        """
        endpoint = format_endpoint(EVENTS_BY_TYPE_ENDPOINT, event_type=event_type)
        params = pagination.to_params() if pagination else {}
        response = await self.api_client.get(endpoint=endpoint, params=params)
        events = response.json()["data"]
        return events, next_cursor(response, events)

    def iter_events_by_type(
        self, event_type: str, pagination: EventsPagination | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Iterates over all events of a given type, requesting further pages until the feed ends.

        The iteration stops at the first empty page or the first response without a cursor.

        Args:
            event_type (str): The fully qualified name of the event struct e.g. '0x1::coin::CoinDeposit'.
            pagination (EventsPagination | None): Pagination options of the first request; `limit` sets the page
                size, `start` the cursor to begin from, and `start_height` and `end_height` the block range.
                Default to None.

        Returns:
            AsyncIterator[dict[str, Any]]: The events, in the order the node returns them.

        """
        return paginate(
            lambda p: self.events_by_type(event_type, p),
            pagination or EventsPagination(),
            lambda p, cursor: replace(p, start=cursor),
        )
