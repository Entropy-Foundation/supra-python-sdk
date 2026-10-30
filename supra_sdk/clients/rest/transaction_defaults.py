# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

"""Defaults and helpers for the max gas amount and the expiration time of a transaction."""

from typing import Any

MAX_GAS_ESTIMATE_MULTIPLIER_NUMERATOR = 3
MAX_GAS_ESTIMATE_MULTIPLIER_DENOMINATOR = 2
"""The estimated max gas is the gas used by the simulation times 3/2 (1.5), rounded up. The margin covers a difference
between the state the simulation ran on and the state the transaction executes on."""

MIN_ESTIMATED_MAX_GAS_AMOUNT = 1_500
"""Lowest estimated max gas, in gas units, when the sender's balance pays for it. A transfer that creates the receiver
uses about 1,000 units (988 measured), which times the 1.5 margin is about 1,500; a small package publish uses about
1,562."""

MAX_GAS_AMOUNT_PER_TRANSACTION = 2_000_000_000
"""The maximum gas units per transaction, `txn.maximum_number_of_gas_units` of the on-chain gas schedule. 2,000,000,000
is the compiled default (`MAX_GAS_AMOUNT` in the node's `config/global-constants`) and the value on Mainnet, Testnet and
Devnet. Governance can change it. The SDK does not read it: an estimate for a balance above this many units is
simulated at this value, and a simulation that the network refuses for a lower maximum raises `MaxGasEstimationError`
that says so."""

FALLBACK_MAX_GAS_AMOUNT = 20_000
"""Max gas, in gas units, of a transaction whose sender is only an address: there is no key to build the simulated
authenticator with, so the max gas is not estimated. It covers a one-module publish (about 2,000 units) and a transfer
that creates the receiver (about 1,000). It is capped at what the sender's balance pays for."""

DEFAULT_MAX_TRANSACTION_TTL_SECONDS = 600
"""The node's maximum transaction time-to-live on every network, used when the node does not report it."""

EXPIRATION_MARGIN_SECONDS = 5
"""Seconds subtracted from the node's maximum transaction time-to-live in the default expiration time. The node refuses
a transaction that expires after its own clock plus the maximum TTL, so a node whose clock is up to this many seconds
behind the client's still accepts the transaction."""


class MaxGasEstimationError(Exception):
    """Exception raised when the max gas of a transaction cannot be estimated.

    The max gas is estimated when neither the call nor the `TransactionConfig` sets `max_gas_amount`. Set it
    explicitly to submit without an estimate.

    Attributes:
        status (str | None): Status of the simulation, e.g. `Fail` or `PendingAfterExecution`. `None` if the
            simulation did not run to a result.
        vm_status (str | None): Message of the Move VM for a simulation that ran, e.g. the abort location and code.
        simulation (dict[str, Any] | None): The simulation result as returned by the node, if there was one.

    """

    def __init__(
        self,
        message: str,
        status: str | None = None,
        vm_status: str | None = None,
        simulation: dict[str, Any] | None = None,
    ):
        """Initializes the exception.

        Args:
            message (str): What failed.
            status (str | None): Status of the simulation. Default to None.
            vm_status (str | None): Message of the Move VM. Default to None.
            simulation (dict[str, Any] | None): The simulation result. Default to None.

        """
        self.status = status
        self.vm_status = vm_status
        self.simulation = simulation
        super().__init__(message)


def affordable_gas_amount(balance: int, gas_unit_price: int) -> int:
    """Returns the most gas units the balance pays for at the price, at most `MAX_GAS_AMOUNT_PER_TRANSACTION`.

    The node accepts a transaction only when the gas payer's balance covers `max_gas_amount * gas_unit_price`.
    """
    if gas_unit_price <= 0:
        return MAX_GAS_AMOUNT_PER_TRANSACTION
    return min(balance // gas_unit_price, MAX_GAS_AMOUNT_PER_TRANSACTION)


def is_sequence_number_too_new(simulation: dict[str, Any]) -> bool:
    """Returns whether the simulation was refused because the sequence number is ahead of the account's on the chain.

    Nodes v11.7.0 and v12 report such a simulation with status `PendingAfterExecution` and the name of the VM status
    code, `SEQUENCE_NUMBER_TOO_NEW`, in `output.Move.vm_status`.
    """
    if simulation.get("status") != "PendingAfterExecution":
        return False
    output = simulation.get("output")
    move_output = output.get("Move") if isinstance(output, dict) else None
    vm_status = move_output.get("vm_status") if isinstance(move_output, dict) else None
    return isinstance(vm_status, str) and "SEQUENCE_NUMBER_TOO_NEW" in vm_status


def max_gas_from_simulation(simulation: dict[str, Any], affordable: int) -> int:
    """Returns the max gas to submit with, from the result of a simulation that ran with `affordable` max gas.

    The result is `ceil(gas used * 1.5)`, at least `MIN_ESTIMATED_MAX_GAS_AMOUNT` and at most `affordable`.

    Raises:
        MaxGasEstimationError: If the simulation status is not `Success` or the result has no gas used.

    """
    status = simulation.get("status")
    output = simulation.get("output")
    move_output = output.get("Move") if isinstance(output, dict) else None
    vm_status = move_output.get("vm_status") if isinstance(move_output, dict) else None
    if (
        status != "Success"
        and isinstance(vm_status, str)
        and "MAX_GAS_UNITS_EXCEEDS_MAX_GAS_UNITS_BOUND" in vm_status
    ):
        raise MaxGasEstimationError(
            f"The network's per-transaction gas maximum is below the {affordable} units that the balance pays for "
            f"(status: {status}, vm_status: {vm_status}); governance has lowered it from "
            f"{MAX_GAS_AMOUNT_PER_TRANSACTION}. Set max_gas_amount, at most that maximum "
            "(`txn.maximum_number_of_gas_units` of the on-chain gas schedule)",
            status,
            vm_status,
            simulation,
        )
    if status != "Success":
        raise MaxGasEstimationError(
            f"Simulation of the transaction did not succeed (status: {status}, vm_status: {vm_status}); "
            "fix the transaction or set max_gas_amount to submit it anyway",
            status,
            vm_status,
            simulation,
        )
    gas_used = move_output.get("gas_used") if isinstance(move_output, dict) else None
    if isinstance(gas_used, str) and gas_used.isdigit():
        gas_used = int(gas_used)
    if not isinstance(gas_used, int) or isinstance(gas_used, bool) or gas_used < 0:
        raise MaxGasEstimationError(
            "Simulation of the transaction returned no gas used; set max_gas_amount",
            status,
            vm_status,
            simulation,
        )
    estimate = -(
        -gas_used
        * MAX_GAS_ESTIMATE_MULTIPLIER_NUMERATOR
        // MAX_GAS_ESTIMATE_MULTIPLIER_DENOMINATOR
    )
    return min(max(estimate, MIN_ESTIMATED_MAX_GAS_AMOUNT), affordable)


def default_expiration_timestamp(now: int, max_ttl: int) -> int:
    """Returns the expiration time of a transaction built without an explicit `expiration_ttl`.

    It is `max_ttl - EXPIRATION_MARGIN_SECONDS` seconds after `now`, never before `now + 1`.
    """
    return now + max(max_ttl - EXPIRATION_MARGIN_SECONDS, 1)
