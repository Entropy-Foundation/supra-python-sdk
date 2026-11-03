# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

import asyncio
import json
import time
from collections.abc import Awaitable, Callable

from examples.common import RPC_NODE_URL, fund_accounts
from supra_sdk.account import Account
from supra_sdk.account_address import AccountAddress
from supra_sdk.bcs import Serializer
from supra_sdk.clients.rest import SupraClient
from supra_sdk.clients.rest.supra_client import TransactionFailedError
from supra_sdk.clients.rest.transaction_defaults import MaxGasEstimationError
from supra_sdk.transactions import EntryFunction, TransactionArgument

TASK_DURATION_SECONDS = 3600

# The registry refuses registrations and stops while it moves from one automation cycle
# to the next. The example sends the transaction again after a pause, this many times.
CYCLE_TRANSITION_ATTEMPTS = 10
CYCLE_TRANSITION_PAUSE_SECONDS = 3.0


async def outside_cycle_transition(action: Callable[[], Awaitable[str]]) -> str:
    """Runs `action` again while the registry reports a cycle transition in progress."""
    for attempt in range(1, CYCLE_TRANSITION_ATTEMPTS + 1):
        try:
            return await action()
        except (TransactionFailedError, MaxGasEstimationError) as error:
            in_transition = "ECYCLE_TRANSITION_IN_PROGRESS" in str(error.vm_status)
            if not in_transition or attempt == CYCLE_TRANSITION_ATTEMPTS:
                raise
            print("Automation cycle transition in progress, trying again")
            await asyncio.sleep(CYCLE_TRANSITION_PAUSE_SECONDS)
    raise AssertionError("unreachable")


async def main() -> None:
    supra_client = SupraClient(RPC_NODE_URL)
    sender = Account.generate()
    print(f"Automation task creator account address: {sender.address()}")

    await fund_accounts(supra_client, [sender.address()])

    print("Registering automation task")
    automated_function = EntryFunction.natural(
        "0x1::supra_account",
        "transfer",
        [],
        [
            TransactionArgument(AccountAddress.from_str("0x1"), Serializer.struct),
            TransactionArgument(1, Serializer.u64),
        ],
    )
    # Without a task type the task is registered with version 1 of the registration
    # parameters. `automation_task_type` selects version 2. `automation_priority` is
    # accepted only with `AutomationTaskType.SYSTEM`, from an account the registry has
    # authorised for system tasks; a user task's priority is its task index.
    #
    # The node refuses a gas price cap below its minimum gas price. A task runs only in
    # blocks whose gas price is at or below its cap and is skipped in blocks priced above
    # it, so the cap here is the recent median price, within the node's bounds.
    gas_prices = await supra_client.estimate_gas_price()
    gas_price_cap = min(
        max(gas_prices["min_configured_gas_price"], gas_prices["median_gas_price"]),
        gas_prices["max_gas_price"],
    )
    # The registry refuses a task whose duration from the block time of its
    # registration exceeds `task_duration_cap_in_secs` of
    # `0x1::automation_registry::ActiveAutomationRegistryConfigV2` (7200 seconds on a
    # localnet), and a task that expires before the end of the next automation cycle.
    expiry_time = int(time.time()) + TASK_DURATION_SECONDS
    task_registration_tx_hash = await outside_cycle_transition(
        lambda: supra_client.register_automation_task(
            sender,
            automated_function,
            9,
            gas_price_cap,
            1 * (10**8),
            expiry_time,
            [],
        )
    )

    # The registration already succeeded (the helper raised otherwise); fetch its events to read the task index.
    task_registration_tx_data = await supra_client.transaction_by_hash(
        task_registration_tx_hash
    )
    task_index = None
    print(json.dumps(task_registration_tx_data, indent=4))
    for event in task_registration_tx_data["output"]["Move"]["events"]:
        if event["type"] == "0x1::automation_registry::AutomationTaskMetaData":
            task_index = event["data"]["task_index"]

    if task_index is None:
        raise Exception("`task_index` not found in automation registration transaction")
    print(f"Task registered successfully, task_id: {task_index}")

    print(f"Stopping task, task_index: {task_index}")
    await outside_cycle_transition(
        lambda: supra_client.stop_automation_tasks(sender, [int(task_index)])
    )
    print(f"Task stopped successfully, task_index: {task_index}")

    await supra_client.close()


if __name__ == "__main__":
    asyncio.run(main())
