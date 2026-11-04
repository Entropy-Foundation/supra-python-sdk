# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

"""Constants and address derivation for fungible assets (the `0x1::fungible_asset` and
`0x1::primary_fungible_store` modules)."""

from supra_sdk.account_address import AccountAddress, to_account_address

SUPRA_FA_METADATA_ADDRESS = AccountAddress.from_str("0xa")
"""Address of the metadata object of SUPRA as a fungible asset, the default of the fungible asset helpers."""

FUNGIBLE_ASSET_METADATA_TYPE = "0x1::fungible_asset::Metadata"
"""Type argument of the `0x1::primary_fungible_store` functions for a fungible asset metadata object."""


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
    return AccountAddress.for_user_derived_object(
        to_account_address(owner, "owner"),
        to_account_address(metadata_address, "metadata_address"),
    )
