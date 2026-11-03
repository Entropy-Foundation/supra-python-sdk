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
  accounts it generates by transfers from that account, so it calls the faucet once.

An empty variable counts as unset. The examples do not send transactions to Mainnet.
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

RPC_NODE_URL = os.getenv("SUPRA_RPC_NODE_URL") or DEVNET_RPC_URL
FAUCET_URL = os.getenv("SUPRA_FAUCET_URL") or RPC_NODE_URL

PRIVATE_KEY_VARIABLE = "SUPRA_EXAMPLES_PRIVATE_KEY"

MAINNET_CHAIN_ID = 8

QUANTS_PER_SUPRA = 10**8

# SUPRA given to each account that `fund_accounts` funds, unless the example asks for
# another amount. It pays for the gas of a few transactions at the minimum gas price.
DEFAULT_FUNDING_QUANTS = 10 * QUANTS_PER_SUPRA

# How long to retry a faucet request that the faucet does not accept ("try later"),
# and how long to wait for the faucet's funds to show in the balance.
FAUCET_TIMEOUT_SECONDS = 180.0
FAUCET_RETRY_INTERVAL_SECONDS = 2.0

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
    Otherwise it is an account generated on the first call and funded once from the
    faucet at `SUPRA_FAUCET_URL`; later calls in the same process reuse it.

    Raises:
        RuntimeError: If the node is a Mainnet node, or the account of
            `SUPRA_EXAMPLES_PRIVATE_KEY` holds no SUPRA.

    """
    if await supra_client.chain_id() == MAINNET_CHAIN_ID:
        raise RuntimeError("The examples do not send transactions to Mainnet")
    funder = await _funder(supra_client)
    for address in addresses:
        await supra_client.transfer_supra_coin(funder, address, quants)
        print(f"Funded {address} with {quants} quants from {funder.address()}")


async def _funder(supra_client: SupraClient) -> Account:
    global _funding_account
    if _funding_account is not None:
        return _funding_account

    private_key = os.getenv(PRIVATE_KEY_VARIABLE) or ""
    if private_key:
        funder = Account.load_key(private_key.strip())
        if await supra_client.account_supra_balance(funder.address()) == 0:
            raise RuntimeError(
                f"The account of {PRIVATE_KEY_VARIABLE} ({funder.address()}) holds no SUPRA"
            )
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
    deadline = time.monotonic() + FAUCET_TIMEOUT_SECONDS
    try:
        while True:
            try:
                await faucet_client.faucet(address)
                break
            except FaucetRequestNotAcceptedError:
                if time.monotonic() > deadline:
                    raise
                await asyncio.sleep(FAUCET_RETRY_INTERVAL_SECONDS)
    finally:
        if faucet_client is not supra_client:
            await faucet_client.close()

    # The faucet may be served by another node than `supra_client`'s.
    while await supra_client.account_supra_balance(address) == 0:
        if time.monotonic() > deadline:
            raise RuntimeError(f"{address} holds no SUPRA after the faucet request")
        await asyncio.sleep(FAUCET_RETRY_INTERVAL_SECONDS)


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
