# Copyright © Supra
# Parts of the project are originally copyright © Aptos Foundation
# SPDX-License-Identifier: Apache-2.0

"""Sets and reads a message with the `message` module of the `hello_blockchain` package.

`python -m examples.hello_blockchain` publishes the compiled package of
`examples/move/packages.json` under Alice's address and uses it.
`python -m examples.hello_blockchain <address>` uses the package already published at
`<address>` instead, for example one published with:

    supra move tool publish --named-addresses hello_blockchain=<address>
"""

import asyncio
import sys
from typing import Any

from examples.common import RPC_NODE_URL, compiled_package, fund_accounts
from supra_sdk.account import Account
from supra_sdk.account_address import AccountAddress
from supra_sdk.bcs import Serializer
from supra_sdk.clients.api_client import ApiError
from supra_sdk.clients.rest import SupraClient
from supra_sdk.transactions import (
    EntryFunction,
    TransactionArgument,
    TransactionPayload,
)


class HelloBlockchainClient(SupraClient):
    async def get_message(
        self, contract_address: AccountAddress, account_address: AccountAddress
    ) -> dict[str, Any] | None:
        """Retrieve the resource message::MessageHolder::message"""
        resource_type = f"{contract_address}::message::MessageHolder"
        try:
            return await self.account_resource(account_address, resource_type)
        except ApiError as err:
            if "Information not available" not in str(err):
                raise err
            return None

    async def set_message(
        self, contract_address: AccountAddress, sender: Account, message: str
    ) -> str:
        """Potentially initialize and set the resource message::MessageHolder::message"""
        transaction_payload = TransactionPayload(
            EntryFunction.natural(
                f"{contract_address}::message",
                "set_message",
                [],
                [TransactionArgument(message, Serializer.str)],
            )
        )
        signed_transaction = await self.create_signed_transaction(
            sender, transaction_payload
        )
        return await self.submit_transaction(signed_transaction)


async def main(contract_address: AccountAddress | None) -> None:
    alice = Account.generate()
    bob = Account.generate()

    print(f"Alice account address: {alice.address()}")
    print(f"Bob account address: {bob.address()}")

    supra_client = HelloBlockchainClient(RPC_NODE_URL)
    await fund_accounts(supra_client, [alice.address(), bob.address()])

    if contract_address is None:
        print("\n=== Publishing the hello_blockchain package ===")
        package = compiled_package("hello_blockchain", alice.address())
        await supra_client.publish_package(alice, package.metadata, package.modules)
        contract_address = alice.address()
        print(f"Published under {contract_address}")

    print("\n=== Testing Alice ===")
    message = await supra_client.get_message(contract_address, alice.address())
    print(f"Initial value: {message}")
    print('Setting the message to "Hello, Blockchain"')
    await supra_client.set_message(contract_address, alice, "Hello, Blockchain")
    message = await supra_client.get_message(contract_address, alice.address())
    print(f"New value: {message}")

    print("\n=== Testing Bob ===")
    message = await supra_client.get_message(contract_address, bob.address())
    print(f"Initial value: {message}")
    print('Setting the message to "Hello, Blockchain"')
    await supra_client.set_message(contract_address, bob, "Hello, Blockchain")
    message = await supra_client.get_message(contract_address, bob.address())
    print(f"New value: {message}")

    await supra_client.close()


if __name__ == "__main__":
    assert len(sys.argv) <= 2, "Expecting at most the contract address"
    asyncio.run(
        main(AccountAddress.from_str(sys.argv[1]) if len(sys.argv) == 2 else None)
    )
