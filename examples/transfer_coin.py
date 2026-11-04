# Copyright © Supra
# Parts of the project are originally copyright © Aptos Foundation
# SPDX-License-Identifier: Apache-2.0

import asyncio

from examples.common import RPC_NODE_URL, fund_accounts
from supra_sdk.account import Account
from supra_sdk.clients.rest import SupraClient


async def main() -> None:
    supra_client = SupraClient(RPC_NODE_URL)

    alice = Account.generate()
    bob = Account.generate()

    print(f"Alice account address: {alice.address()}")
    print(f"Bob account address: {bob.address()}")

    await fund_accounts(supra_client, [alice.address(), bob.address()])

    print("\n=== Initial Balances ===")
    alice_balance = await supra_client.account_supra_balance(alice.address())
    bob_balance = await supra_client.account_supra_balance(bob.address())
    print(f"Alice: {alice_balance}")
    print(f"Bob: {bob_balance}")

    # Have Alice give Bob 1_000 coins
    await supra_client.transfer_supra_coin(alice, bob.address(), 1_000)

    print("\n=== Intermediate Balances ===")
    alice_balance = await supra_client.account_supra_balance(alice.address())
    bob_balance = await supra_client.account_supra_balance(bob.address())
    print(f"Alice: {alice_balance}")
    print(f"Bob: {bob_balance}")

    # Have Alice give Bob another 1_000 coins
    await supra_client.transfer_supra_coin(alice, bob.address(), 1_000)

    print("\n=== Final Balances ===")
    alice_balance = await supra_client.account_supra_balance(alice.address())
    bob_balance = await supra_client.account_supra_balance(bob.address())
    print(f"Alice: {alice_balance}")
    print(f"Bob: {bob_balance}")

    await supra_client.close()


if __name__ == "__main__":
    asyncio.run(main())
