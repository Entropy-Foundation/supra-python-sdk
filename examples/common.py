# Copyright © Supra
# Parts of the project are originally copyright © Aptos Foundation
# SPDX-License-Identifier: Apache-2.0

"""Settings and helpers shared by the examples.

The examples read the network and the funding account from the environment:

- `SUPRA_RPC_NODE_URL`: the base URL of the RPC node (without `/rpc/v3`). Default
  `https://rpc-devnet.supra.com` (Devnet).
- `SUPRA_FAUCET_URL`: the base URL of the node that serves the faucet. Default
  `SUPRA_RPC_NODE_URL`.
- `SUPRA_EXAMPLES_PRIVATE_KEY`: the Ed25519 private key (32 bytes as hex, with or
  without `0x`) of a funded account. When it is set, the examples fund the accounts
  they generate by transfers from this account and do not call the faucet. When it is
  not set, an example funds one generated account from the faucet and funds the other
  accounts it generates by transfers from that account. It sends one faucet request,
  and sends it again, at most four times, while the faucet answers "TryLater".

An empty or whitespace-only variable counts as unset. The examples do not send
transactions to Mainnet.
"""

import asyncio
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from supra_sdk.account import Account
from supra_sdk.account_address import AccountAddress
from supra_sdk.clients.rest import SupraClient
from supra_sdk.clients.rest.supra_client import FaucetRequestNotAcceptedError

DEVNET_RPC_URL = "https://rpc-devnet.supra.com"

RPC_NODE_URL = (os.getenv("SUPRA_RPC_NODE_URL") or "").strip() or DEVNET_RPC_URL
FAUCET_URL = (os.getenv("SUPRA_FAUCET_URL") or "").strip() or RPC_NODE_URL

PRIVATE_KEY_VARIABLE = "SUPRA_EXAMPLES_PRIVATE_KEY"

MAINNET_CHAIN_ID = 8

QUANTS_PER_SUPRA = 10**8

# SUPRA given to each account that `fund_accounts` funds, unless the example asks for
# another amount. It pays for the gas of a few transactions at the minimum gas price.
DEFAULT_FUNDING_QUANTS = 10 * QUANTS_PER_SUPRA

# Gas units reserved for each funding transfer when checking the funding account's
# balance. The node accepts a transfer only if the balance covers the amount plus the
# max gas at the gas price, and the SDK sets the max gas to 1.5 times the gas the
# simulated transfer uses, with no upper bound. A transfer to a new account uses about
# 1,000 units on Devnet today, so the estimate is about 1,500 to 1,600 units; the
# reserve covers an estimate of up to 2,000. The check is made before sending, and a
# transfer can still fail if the gas it uses rises.
FUNDING_TRANSFER_GAS_UNITS = 2_000

# Pauses before the second to fifth faucet request, sent while the faucet answers
# "TryLater". After the fifth request the example gives up.
FAUCET_RETRY_PAUSES_SECONDS = (5.0, 10.0, 20.0, 40.0)

# How long to wait for the faucet's funds to show in the balance, and how often to look.
FAUCET_BALANCE_TIMEOUT_SECONDS = 180.0
FAUCET_BALANCE_POLL_SECONDS = 2.0

PACKAGES_PATH = Path(__file__).parent / "move" / "packages.json"

# The account that funds the accounts of this example, once it is known.
_funding_account: Account | None = None


async def fund_accounts(
    supra_client: SupraClient,
    addresses: list[AccountAddress],
    quants: int = DEFAULT_FUNDING_QUANTS,
) -> None:
    """Sends `quants` of SUPRA to each of `addresses` from the funding account.

    The funding account is the account of `SUPRA_EXAMPLES_PRIVATE_KEY` when it is set.
    Otherwise it is an account generated on the first call and funded from the faucet
    at `SUPRA_FAUCET_URL`; later calls in the same process reuse it.

    Before sending, it checks that the funding account's balance covers the transfers:
    `quants` for each address plus `FUNDING_TRANSFER_GAS_UNITS` of gas for each at the
    node's minimum gas price.

    Raises:
        RuntimeError: If the node is a Mainnet node, or the funding account's balance
            does not cover the transfers.

    """
    if await supra_client.chain_id() == MAINNET_CHAIN_ID:
        raise RuntimeError("The examples do not send transactions to Mainnet")
    funder = await _funder(supra_client)

    gas_unit_price = (await supra_client.estimate_gas_price())[
        "min_configured_gas_price"
    ]
    needed = len(addresses) * (quants + FUNDING_TRANSFER_GAS_UNITS * gas_unit_price)
    balance = await supra_client.account_supra_balance(funder.address())
    if balance < needed:
        source = f" (the account of {PRIVATE_KEY_VARIABLE})" if _private_key() else ""
        raise RuntimeError(
            f"The funding account {funder.address()}{source} holds "
            f"{_supra(balance)} SUPRA; funding {len(addresses)} account(s) needs "
            f"{_supra(needed)} SUPRA, {_supra(needed - balance)} SUPRA more"
        )

    for address in addresses:
        await supra_client.transfer_supra_coin(funder, address, quants)
        print(f"Funded {address} with {quants} quants from {funder.address()}")


def _supra(quants: int) -> str:
    """Formats an amount of quants as SUPRA, with all eight decimals."""
    return f"{quants // QUANTS_PER_SUPRA}.{quants % QUANTS_PER_SUPRA:08d}"


def _private_key() -> str:
    """The value of SUPRA_EXAMPLES_PRIVATE_KEY; empty or whitespace counts as unset."""
    return (os.getenv(PRIVATE_KEY_VARIABLE) or "").strip()


async def _funder(supra_client: SupraClient) -> Account:
    global _funding_account
    if _funding_account is not None:
        return _funding_account

    private_key = _private_key()
    if private_key:
        funder = Account.load_key(private_key)
    else:
        funder = Account.generate()
        await _fund_from_faucet(supra_client, funder.address())
    print(f"Funding account: {funder.address()}")
    _funding_account = funder
    return funder


async def _fund_from_faucet(supra_client: SupraClient, address: AccountAddress) -> None:
    """Funds `address` from the faucet and waits until its balance shows the funds."""
    faucet_client = (
        supra_client if FAUCET_URL == RPC_NODE_URL else SupraClient(FAUCET_URL)
    )
    try:
        faucet_tx_hash = None
        for pause in (*FAUCET_RETRY_PAUSES_SECONDS, None):
            try:
                faucet_tx_hash = await faucet_client.faucet(
                    address, wait_for_faucet=False
                )
            # SDK versions that do not handle a "TryLater" body raise AttributeError
            # from the request for it. Nothing else in this call is caught.
            except (FaucetRequestNotAcceptedError, AttributeError):
                faucet_tx_hash = None
            if faucet_tx_hash:
                break
            # The faucet answered "TryLater" (the request returned no hash).
            if pause is None:
                break
            print(f"The faucet answered TryLater; requesting again in {pause:g} s")
            await asyncio.sleep(pause)

        if not faucet_tx_hash:
            raise FaucetRequestNotAcceptedError

        # The request was accepted; wait for its transaction once, outside the retry.
        faucet_data = await faucet_client.wait_for_faucet(faucet_tx_hash)
        if faucet_data.get("status") != "Success":
            raise RuntimeError(
                f"The faucet transaction {faucet_tx_hash} ended with status "
                f"{faucet_data.get('status')}"
            )
    finally:
        if faucet_client is not supra_client:
            await faucet_client.close()

    # The faucet may be served by another node than `supra_client`'s.
    deadline = time.monotonic() + FAUCET_BALANCE_TIMEOUT_SECONDS
    while await supra_client.account_supra_balance(address) == 0:
        if time.monotonic() > deadline:
            raise RuntimeError(f"{address} holds no SUPRA after the faucet request")
        await asyncio.sleep(FAUCET_BALANCE_POLL_SECONDS)


@dataclass(frozen=True)
class CompiledPackage:
    """A Move package of `move/packages.json`, compiled for one address."""

    metadata: bytes
    modules: list[bytes]
    scripts: list[bytes]


def compiled_package(name: str, address: AccountAddress) -> CompiledPackage:
    """Returns the package `name` of `move/packages.json` compiled for `address`.

    The packages in the file were compiled for the address it names. Every occurrence of
    that address in the bytecode (the address of the package's modules, and constants
    equal to it) is replaced by `address`. The metadata contains no address.
    """
    data = json.loads(PACKAGES_PATH.read_text())
    placeholder = AccountAddress.from_str(data["address"]).address
    package = data["packages"][name]

    def relocate(code_hex: str) -> bytes:
        code = bytes.fromhex(code_hex)
        if placeholder not in code:
            raise ValueError(f"The bytecode of {name} does not contain its address")
        return code.replace(placeholder, address.address)

    return CompiledPackage(
        metadata=bytes.fromhex(package["metadata"]),
        modules=[relocate(module) for module in package["modules"]],
        scripts=[relocate(script) for script in package["scripts"]],
    )
