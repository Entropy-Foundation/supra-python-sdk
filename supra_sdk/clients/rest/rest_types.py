# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

import re
import string
from dataclasses import dataclass
from enum import Enum
from typing import Any
from urllib.parse import quote

from supra_sdk.account_address import AccountAddress

RPC_API_PREFIX = "rpc/v3"

_HEX_HASH = re.compile(r"(0x)?[0-9a-fA-F]{64}")


def encode_path_segment(value: str, name: str = "value") -> str:
    """Percent-encodes a caller-supplied value so that it forms exactly one URL path segment.

    `:` and `,` are valid in a path segment and are left as they are. Every other character that cannot
    appear in a segment, including `/`, `?`, `#`, `%`, `<`, `>` and space, is encoded. The node decodes path
    segments before parsing them, so a Move type such as `0x1::coin::CoinStore<0x1::supra_coin::SupraCoin>`
    reaches it unchanged and is sent as `0x1::coin::CoinStore%3C0x1::supra_coin::SupraCoin%3E`.

    Args:
        value (str): The value to place in a path segment.
        name (str): Name of the parameter, used in the error message.

    Raises:
        ValueError: If `value` is not a non-empty string.

    """
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return quote(value, safe=":,")


def address_segment(value: AccountAddress | str, name: str = "address") -> str:
    """Validates an account address and returns it as one path segment.

    Args:
        value (AccountAddress | str): An `AccountAddress`, or a hex string accepted by
            `AccountAddress.from_str_relaxed`.
        name (str): Name of the parameter, used in the error message.

    Raises:
        ValueError: If `value` is not a valid account address.

    """
    if isinstance(value, AccountAddress):
        return str(value)
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an AccountAddress or a hex string")
    try:
        return str(AccountAddress.from_str_relaxed(value))
    except (RuntimeError, ValueError) as e:
        raise ValueError(f"{name} is not a valid account address: {value!r}") from e


def hash_segment(value: str, name: str = "hash") -> str:
    """Validates a hash and returns it as one path segment.

    Transaction and block hashes are 32 bytes: 64 hex digits, optionally prefixed with `0x`.

    Args:
        value (str): The hash.
        name (str): Name of the parameter, used in the error message.

    Raises:
        ValueError: If `value` is not 64 hex digits with an optional `0x` prefix.

    """
    if not isinstance(value, str) or not _HEX_HASH.fullmatch(value):
        raise ValueError(
            f"{name} must be 64 hex digits, optionally prefixed with 0x: {value!r}"
        )
    return value


def uint_segment(value: int | str, name: str = "value") -> str:
    """Validates a non-negative integer and returns it as one path segment.

    Args:
        value (int | str): A non-negative integer, or a string of decimal digits, e.g. a block height or an epoch.
        name (str): Name of the parameter, used in the error message.

    Raises:
        ValueError: If `value` is not a non-negative integer or a string of decimal digits.

    """
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return str(int(value))
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return str(value)
    raise ValueError(
        f"{name} must be a non-negative integer or a string of decimal digits: {value!r}"
    )


_ADDRESS_PLACEHOLDERS = frozenset({"address", "account_address", "table_handle"})
_UINT_PLACEHOLDERS = frozenset({"height", "epoch"})


def format_endpoint(template: str, **values: Any) -> str:
    """Fills the placeholders of an endpoint template with validated, percent-encoded path segments.

    Each value is validated and encoded according to its placeholder name: address placeholders (`address`,
    `account_address`, `table_handle`) as account addresses, names ending in `hash` as hashes, `height` and `epoch`
    as non-negative integers, and every other name as a plain string encoded as a single segment.

    Args:
        template (str): Endpoint template with `{name}` placeholders.
        **values: One value for each placeholder.

    Returns:
        str: The endpoint path, relative to the base URL.

    Raises:
        ValueError: If a value is invalid, or the values do not match the template's placeholders.

    """
    placeholders = {
        field for _, field, _, _ in string.Formatter().parse(template) if field
    }
    if placeholders != set(values):
        raise ValueError(
            f"endpoint {template!r} takes {sorted(placeholders)}, got {sorted(values)}"
        )
    segments = {}
    for name, value in values.items():
        if name in _ADDRESS_PLACEHOLDERS:
            segments[name] = address_segment(value, name)
        elif name.endswith("hash"):
            segments[name] = hash_segment(value, name)
        elif name in _UINT_PLACEHOLDERS:
            segments[name] = uint_segment(value, name)
        else:
            segments[name] = encode_path_segment(value, name)
    return template.format(**segments)


# Account endpoints
ACCOUNT_ENDPOINT = f"{RPC_API_PREFIX}/accounts/{{account_address}}"
ACCOUNT_RESOURCE_ENDPOINT = (
    f"{RPC_API_PREFIX}/accounts/{{account_address}}/resources/{{resource_type}}"
)
ACCOUNT_RESOURCES_ENDPOINT = f"{RPC_API_PREFIX}/accounts/{{account_address}}/resources"
ACCOUNT_MODULE_ENDPOINT = (
    f"{RPC_API_PREFIX}/accounts/{{account_address}}/modules/{{module_name}}"
)
ACCOUNT_MODULES_ENDPOINT = f"{RPC_API_PREFIX}/accounts/{{account_address}}/modules"
ACCOUNT_TRANSACTIONS_ENDPOINT = (
    f"{RPC_API_PREFIX}/accounts/{{account_address}}/transactions"
)
ACCOUNT_COIN_TRANSACTIONS_ENDPOINT = (
    f"{RPC_API_PREFIX}/accounts/{{account_address}}/coin_transactions"
)
ACCOUNT_FA_TRANSACTIONS_ENDPOINT = (
    f"{RPC_API_PREFIX}/accounts/{{account_address}}/fa_transactions"
)
ACCOUNT_AUTOMATED_TRANSACTIONS_ENDPOINT = (
    f"{RPC_API_PREFIX}/accounts/{{account_address}}/automated_transactions"
)

# Transaction endpoints
CHAIN_ID_ENDPOINT = f"{RPC_API_PREFIX}/transactions/chain_id"
TRANSACTION_BY_HASH_ENDPOINT = f"{RPC_API_PREFIX}/transactions/{{hash}}"
TRANSACTION_ESTIMATE_GAS_PRICE_ENDPOINT = (
    f"{RPC_API_PREFIX}/transactions/estimate_gas_price"
)
TRANSACTION_PARAMETERS_ENDPOINT = f"{RPC_API_PREFIX}/transactions/parameters"
TRANSACTION_SUBMIT_TRANSACTION_ENDPOINT = f"{RPC_API_PREFIX}/transactions/submit"
TRANSACTION_SIMULATE_TRANSACTION_ENDPOINT = f"{RPC_API_PREFIX}/transactions/simulate"

# View function endpoint
VIEW_FUNCTION_ENDPOINT = f"{RPC_API_PREFIX}/view"

# Table item endpoint
TABLE_ITEMS_ENDPOINT = f"{RPC_API_PREFIX}/tables/{{table_handle}}/item"

# Events endpoints
EVENTS_BY_TYPE_ENDPOINT = f"{RPC_API_PREFIX}/events/{{event_type}}"

# Block endpoints
LATEST_BLOCK_ENDPOINT = f"{RPC_API_PREFIX}/block"
BLOCK_BY_HASH_ENDPOINT = f"{RPC_API_PREFIX}/block/{{block_hash}}"
BLOCK_BY_HEIGHT_ENDPOINT = f"{RPC_API_PREFIX}/block/height/{{height}}"
BLOCK_TRANSACTIONS_ENDPOINT = f"{RPC_API_PREFIX}/block/{{block_hash}}/transactions"

# Consensus endpoints
LATEST_CONSENSUS_BLOCK_ENDPOINT = f"{RPC_API_PREFIX}/consensus/block"
CONSENSUS_BLOCK_BY_HEIGHT_ENDPOINT = f"{RPC_API_PREFIX}/consensus/height/{{height}}"
COMMITTEE_AUTHORIZATION_ENDPOINT = (
    f"{RPC_API_PREFIX}/consensus/committee_authorization/{{epoch}}"
)

# Faucet endpoints
FAUCET_ENDPOINT = f"{RPC_API_PREFIX}/wallet/faucet/{{address}}"
FAUCET_TRANSACTION_ENDPOINT = f"{RPC_API_PREFIX}/wallet/faucet/transactions/{{hash}}"


@dataclass(frozen=True)
class Pagination:
    """Generic pagination parameters.

    Attributes:
        count: Number of items to return, default value is 20 and maximum value is 100.
            In case of `count`>100 only 100 items will be returned.
        start: Cursor or starting point specifying where to start for pagination.

    """

    count: int | None = None
    start: str | int | None = None

    def to_params(self) -> dict[str, Any]:
        """Converts the pagination configuration to a dictionary of query parameters.

        Returns:
            Dict[str, Any]: Dictionary of parameters for HTTP request.

        """
        params: dict[str, Any] = {}
        if self.count is not None:
            params["count"] = self.count
        if self.start is not None:
            params["start"] = self.start
        return params


@dataclass(frozen=True)
class PaginationWithOrder(Pagination):
    """Generic pagination parameters with ordering.

    Attributes:
        ascending: Flag indicating order of lookup. If True, results are in ascending order.

    """

    ascending: bool | None = None

    def to_params(self) -> dict[str, Any]:
        """Converts the pagination configuration to a dictionary of query parameters.

        Returns:
            Dict[str, Any]: Dictionary of parameters for HTTP request.

        """
        params: dict[str, Any] = {}
        if self.count is not None:
            params["count"] = self.count
        if self.start is not None:
            params["start"] = self.start
        if self.ascending is not None:
            params["ascending"] = str(self.ascending).lower()
        return params


@dataclass(frozen=True)
class AutomatedTransactionsPagination:
    """Pagination parameters for automation transaction endpoint.

    Attributes:
        ascending: Flag indicating order of lookup. If True, results are in ascending order.
        block_height: Start block height to consider for transaction retrieval.
        count: Number of items to return, default value is 20 and maximum value is 100.
            In case of `count`>100 only 100 items will be returned.

    """

    ascending: bool | None = None
    block_height: int | None = None
    count: int | None = None

    def to_params(self) -> dict[str, Any]:
        """Converts the pagination configuration to a dictionary of query parameters.

        Returns:
            Dict[str, Any]: Dictionary of parameters for HTTP request.

        """
        params: dict[str, Any] = {}
        if self.ascending is not None:
            params["ascending"] = str(self.ascending).lower()
        if self.block_height is not None:
            params["block_height"] = self.block_height
        if self.count is not None:
            params["count"] = self.count
        return params


@dataclass(frozen=True)
class EventsPagination:
    """Pagination parameters for events retrieval endpoint.

    Attributes:
        start_height (Optional[int]): Starting block height (inclusive).
        end_height (Optional[int]): Ending block height (exclusive).
        limit (Optional[int]): Maximum number of events to return. Defaults to 20, max 100.
        start (Optional[str]): The cursor to start the query from.

    """

    start_height: int | None = None
    end_height: int | None = None
    limit: int | None = None
    start: str | None = None

    def to_params(self) -> dict[str, Any]:
        """Converts the event query configuration to a dictionary of query parameters.

        Returns:
            Dict[str, Any]: Dictionary of parameters for HTTP request.

        """
        params: dict[str, Any] = {}
        if self.start_height is not None:
            params["start_height"] = self.start_height
        if self.end_height is not None:
            params["end_height"] = self.end_height
        if self.limit is not None:
            params["limit"] = self.limit
        if self.start is not None:
            params["start"] = self.start
        return params


class TransactionType(str, Enum):
    """Enumeration of transaction types.

    This enum represents the type of a transaction and it will be used when querying transactions
    with block info via `BLOCK_BY_HEIGHT_ENDPOINT`.

    Attributes:
        AUTO (str): Represents transactions associated with the Supra Automation.
        USER (str): Represents a user transaction type.
        META (str): Represents a metadata transaction type.

    """

    AUTO = "auto"
    USER = "user"
    META = "meta"
