# Copyright © Supra
# Parts of the project are originally copyright © Aptos Foundation
# SPDX-License-Identifier: Apache-2.0

import asyncio
import json

from examples.common import RPC_NODE_URL, fund_accounts
from supra_sdk.account import Account
from supra_sdk.bcs import Serializer
from supra_sdk.clients.api_client import ApiError
from supra_sdk.clients.rest import SupraClient
from supra_sdk.transactions import (
    EntryFunction,
    TransactionArgument,
    TransactionPayload,
)
from supra_sdk.type_tag import StructTag, TypeTag

# Max gas of the transfer, which uses fewer than 100 units.
MAX_GAS_AMOUNT = 2_000


async def main() -> None:
    supra_client = SupraClient(RPC_NODE_URL)
    alice = Account.generate()
    bob = Account.generate()

    print(f"Alice account address: {alice.address()}")
    print(f"Bob account address: {bob.address()}")

    await fund_accounts(supra_client, [alice.address()])

    payload = EntryFunction.natural(
        "0x1::coin",
        "transfer",
        [TypeTag(StructTag.from_str("0x1::supra_coin::SupraCoin"))],
        [
            TransactionArgument(bob.address(), Serializer.struct),
            TransactionArgument(100_000, Serializer.u64),
        ],
    )
    # The max gas amount is given: without it the SDK estimates it by simulating the
    # transfer, and that simulation fails while Bob has no coin store.
    signed_transaction = await supra_client.create_signed_transaction(
        alice, TransactionPayload(payload), max_gas_amount=MAX_GAS_AMOUNT
    )

    print("\n=== Simulate before creating Bob's Account ===")
    try:
        simulation_result = await supra_client.simulate_transaction(signed_transaction)
    except ApiError as e:
        print(f"Simulation refused: {e}")
    else:
        status = simulation_result["status"]
        vm_status = simulation_result["output"]["Move"]["vm_status"]
        print(f"Simulation status: {status}, vm_status: {vm_status}")
        assert status != "Success", "Expected the transfer to fail without a coin store"

    print("\n=== Simulate after creating Bob's Account ===")
    await fund_accounts(supra_client, [bob.address()])

    # The same signed transaction, simulated again now that Bob's account exists.
    simulation_result = await supra_client.simulate_transaction(signed_transaction)
    vm_status = simulation_result["output"]["Move"]["vm_status"]
    assert vm_status == "Executed successfully", f"Expected success, got: {vm_status}"
    print(json.dumps(simulation_result, indent=4, sort_keys=True))

    await supra_client.close()


if __name__ == "__main__":
    asyncio.run(main())
