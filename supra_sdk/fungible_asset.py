# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

"""Constants and address derivation for fungible assets (the `0x1::fungible_asset` and
`0x1::primary_fungible_store` modules)."""

import hashlib

from supra_sdk.account_address import AccountAddress

SUPRA_FA_METADATA_ADDRESS = AccountAddress.from_str("0xa")
"""Address of the metadata object of SUPRA as a fungible asset, the default of the fungible asset helpers."""

FUNGIBLE_ASSET_METADATA_TYPE = "0x1::fungible_asset::Metadata"
"""Type argument of the `0x1::primary_fungible_store` functions for a fungible asset metadata object."""

_OBJECT_DERIVED_SCHEME = b"\xfc"


def to_account_address(value: AccountAddress | str, name: str) -> AccountAddress:
    """Returns `value` as an `AccountAddress`.

    Args:
        value (AccountAddress | str): An `AccountAddress`, or a hex string accepted by
            `AccountAddress.from_str_relaxed`.
        name (str): Name of the parameter, used in the error message.

    Raises:
        ValueError: If `value` is not a valid account address.

    """
    if isinstance(value, AccountAddress):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an AccountAddress or a hex string")
    try:
        return AccountAddress.from_str_relaxed(value)
    except (RuntimeError, ValueError) as e:
        raise ValueError(f"{name} is not a valid account address: {value!r}") from e


def primary_store_address(
    owner: AccountAddress | str,
    metadata_address: AccountAddress | str = SUPRA_FA_METADATA_ADDRESS,
) -> AccountAddress:
    """Derives the address of an account's primary fungible store for a fungible asset.

    This is `0x1::primary_fungible_store::primary_store_address`: the object address derived from the owner and the
    metadata object, `sha3_256(owner | metadata | 0xFC)`. The store exists only once the account has received the
    asset (or migrated a coin balance of it); the address is the same whether or not it does.

    Args:
        owner (AccountAddress | str): Address of the account that owns the store.
        metadata_address (AccountAddress | str): Address of the fungible asset's metadata object. Default to
            `SUPRA_FA_METADATA_ADDRESS`.

    Returns:
        AccountAddress: Address of the primary fungible store.

    """
    hasher = hashlib.sha3_256()
    hasher.update(to_account_address(owner, "owner").address)
    hasher.update(to_account_address(metadata_address, "metadata_address").address)
    hasher.update(_OBJECT_DERIVED_SCHEME)
    return AccountAddress(hasher.digest())
