# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

"""Funds a new account from the faucet at `SUPRA_FAUCET_URL` with one faucet request.

`SupraClient.faucet` waits for the faucet transaction by default. This example sends
the request without waiting and then waits for the transaction with
`SupraClient.wait_for_faucet`.
"""

import asyncio

from examples.common import FAUCET_URL
from supra_sdk.account import Account
from supra_sdk.clients.rest import SupraClient


async def main() -> None:
    supra_client = SupraClient(FAUCET_URL)
    alice = Account.generate()
    print(f"Alice account address: {alice.address()}")

    tx_hash = await supra_client.faucet(alice.address(), wait_for_faucet=False)
    assert tx_hash, "The faucet did not accept the request, try again"
    print(f"Faucet request accepted, tx_hash: {tx_hash}")

    faucet_transaction = await supra_client.wait_for_faucet(tx_hash)
    print(f"Faucet transaction status: {faucet_transaction['status']}")
    assert faucet_transaction["status"] == "Success", "The faucet transaction failed"

    alice_balance = await supra_client.account_supra_balance(alice.address())
    print(f"Alice's balance: {alice_balance}")

    await supra_client.close()


if __name__ == "__main__":
    asyncio.run(main())
