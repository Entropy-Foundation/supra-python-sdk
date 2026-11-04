# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

"""Creates an account funded by one faucet grant, for running all the examples.

Run it as `python -m examples.faucet_funder`. It generates a fresh Ed25519 account,
requests SUPRA for it from the faucet once (with the retry on "TryLater" that the
examples use), waits until the balance shows the funds, and prints the account's
private key as hex on stdout, on one line and nothing else. The address and the
progress go to stderr. The output is meant to be assigned to
`SUPRA_EXAMPLES_PRIVATE_KEY`, so that the examples fund their accounts from this
account instead of each requesting from the faucet. This is for CI and for local runs
of all the examples against a network whose faucet limits the requests per IP address,
such as Devnet. It does not send transactions, and it refuses Mainnet.

The environment is the one of the examples (see `examples/README.md`):
`SUPRA_RPC_NODE_URL` and `SUPRA_FAUCET_URL`.

This is not an example.
"""

import asyncio
import sys
from contextlib import redirect_stdout

from examples.common import MAINNET_CHAIN_ID, RPC_NODE_URL, _fund_from_faucet
from supra_sdk.account import Account
from supra_sdk.clients.rest import SupraClient


async def main() -> None:
    supra_client = SupraClient(RPC_NODE_URL)
    try:
        if await supra_client.chain_id() == MAINNET_CHAIN_ID:
            raise RuntimeError("The examples do not send transactions to Mainnet")
        funder = Account.generate()
        print(f"Funding account: {funder.address()}", file=sys.stderr)
        # The funding helper prints its progress to stdout; stdout carries only the key.
        with redirect_stdout(sys.stderr):
            await _fund_from_faucet(supra_client, funder.address())
    finally:
        await supra_client.close()

    print(f"Funded {funder.address()}", file=sys.stderr)
    print(funder.private_key.hex())


if __name__ == "__main__":
    asyncio.run(main())
