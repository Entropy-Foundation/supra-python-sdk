# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

"""Reads a SUPRA fungible asset balance, transfers SUPRA as a fungible asset and lists the store's transactions.

On a Devnet that holds SUPRA as a fungible asset from genesis, the faucet funds land in the primary fungible store and
there is nothing to migrate. On a network where the account still holds a `CoinStore` balance, run the migration first
(`migrate_coin_to_fungible_store`); a fungible asset transfer moves only the fungible store's balance.
"""

import asyncio

from examples.common import RPC_NODE_URL
from supra_sdk.account import Account
from supra_sdk.clients.rest import SupraClient
from supra_sdk.clients.rest.rest_types import PaginationWithOrder


async def main():
    supra_client = SupraClient(RPC_NODE_URL)

    alice = Account.generate()
    bob = Account.generate()

    await supra_client.faucet(alice.address())

    # `account_supra_balance` sums the CoinStore and the fungible store; `account_fa_balance` reads the latter.
    print(
        f"Alice total SUPRA: {await supra_client.account_supra_balance(alice.address())}"
    )
    fa_balance = await supra_client.account_fa_balance(alice.address())
    print(f"Alice SUPRA as fungible asset: {fa_balance}")

    if fa_balance == 0:
        # Alice holds a CoinStore balance (Testnet, Mainnet): move it into the fungible store.
        await supra_client.migrate_coin_to_fungible_store(alice)
        fa_balance = await supra_client.account_fa_balance(alice.address())
        print(f"Alice SUPRA as fungible asset after migration: {fa_balance}")

    # The metadata address defaults to SUPRA (0xa); pass `metadata_address` for another fungible asset.
    await supra_client.transfer_fungible_asset(alice, bob.address(), 1_000)
    print(
        f"Bob SUPRA as fungible asset: {await supra_client.account_fa_balance(bob.address())}"
    )

    # The node lists transactions per fungible store; the helper derives Bob's primary store address.
    cursor = None
    while True:
        pagination = PaginationWithOrder(count=20, start=cursor) if cursor else None
        transactions, cursor = await supra_client.account_fa_transactions(
            bob.address(), pagination
        )
        print(f"Page of {len(transactions)} transactions, next cursor: {cursor}")
        # A v12 node omits the cursor at the end of the feed; a v11.7.0 node ends it with an empty page.
        if cursor is None or not transactions:
            break

    await supra_client.close()


if __name__ == "__main__":
    asyncio.run(main())
