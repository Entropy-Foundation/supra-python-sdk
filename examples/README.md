# Examples

Runnable examples of the **`supra-python-sdk`**. Each example covers one use case: coin transfers, sponsored and
multi-agent transactions, simulation, key rotation, multisig accounts, tokens, publishing Move packages, automation
tasks and the faucet.

## Requirements

- Python 3.12 or later.
- [`uv`](https://docs.astral.sh/uv/) ([installation guide](https://docs.astral.sh/uv/getting-started/installation/)).

The examples need only the SDK's own dependencies. They do not need a Move toolchain: the Move packages they publish
are committed in compiled form (see [Move packages](#move-packages)).

## Networks

The examples run against Devnet by default (`https://rpc-devnet.supra.com`). Set `SUPRA_RPC_NODE_URL` to run them
against another network, for example Testnet (`https://rpc-testnet.supra.com`) or a localnet
(`http://localhost:27001`). The examples refuse to send transactions to Mainnet.

## Environment

| Variable | Meaning |
|---|---|
| `SUPRA_RPC_NODE_URL` | Base URL of the RPC node, without `/rpc/v3`. Default `https://rpc-devnet.supra.com` (Devnet). |
| `SUPRA_FAUCET_URL` | Base URL of the node that serves the faucet. Default `SUPRA_RPC_NODE_URL`. |
| `SUPRA_EXAMPLES_PRIVATE_KEY` | Ed25519 private key (32 bytes as hex, with or without `0x`) of a funded account. Optional. |

An empty or whitespace-only variable counts as unset.

Every example generates fresh accounts. It funds them in one of two ways:

- With `SUPRA_EXAMPLES_PRIVATE_KEY` set, the account of that key sends SUPRA to each generated account. No faucet is
  called (except by `faucet.py`, which demonstrates the faucet). The key is never printed; the examples print the
  account's address.
- Without it, the example funds one generated account from the faucet and that account sends SUPRA to the other
  generated accounts. The faucet can answer `TryLater` when it cannot serve the request yet. Every example except
  `faucet.py` then sends the request again after 5, 10, 20 and 40 seconds, so it sends at most five requests, and fails
  after the fifth `TryLater`. It waits for the faucet transaction once, after the faucet accepts a request.
  `faucet.py` sends one request and does not send it again.

Before funding, an example checks that the funding account holds the SUPRA it is about to send plus 2,000 units of gas
per transfer at the node's minimum gas price, and otherwise stops with the shortfall in SUPRA.

Without a key, each example makes its own faucet request, and the Devnet faucet limits the requests from one IP
address (across all its endpoints), so it can refuse them when several examples run in a row. A localnet faucet has no
such limit. To run all the examples against Devnet, either set `SUPRA_EXAMPLES_PRIVATE_KEY` to a funded account, or
create one from a single faucet grant with `examples/faucet_funder.py`:

```bash
SUPRA_EXAMPLES_PRIVATE_KEY="$(uv run python -m examples.faucet_funder)" make examples EXAMPLES_EXCLUDE=faucet
```

`faucet_funder.py` generates an account, requests SUPRA for it once (with the retry on `TryLater` described above),
waits until the balance shows, and prints only the private key on stdout; the address and the progress go to stderr.
On Devnet the funder holds 5,000 SUPRA from the grant, and a run of all the examples uses about 325 SUPRA of it.
`EXAMPLES_EXCLUDE=faucet` leaves out `faucet.py`, because its own request would be a second faucet request from the
same IP address.

Each generated account receives 10 SUPRA (`multisig.py`: 30 SUPRA for each account that sends transactions, 1 SUPRA for
each signer); a full run of `make examples` takes about 325 SUPRA from the funding account, most of it left in the
generated accounts.

Two runs that use the same `SUPRA_EXAMPLES_PRIVATE_KEY` at the same time send transactions from the same account and
race for its sequence numbers, so their funding transfers can fail. Run one at a time per key.

The scheduled workflow `.github/workflows/examples.yaml` runs the examples against Devnet that way, once a day and on
manual dispatch. It uses no repository secret: each run creates a funder account with one faucet request, masks its
key in the log, and runs `make examples EXAMPLES_EXCLUDE=faucet` from that account.

Keep private keys in environment variables or an untracked file. Do not commit them.

## Running

One example, from the repository root:

```bash
uv run python -m examples.<example_filename_without_py_extension>
```

For example:

```bash
# Devnet, accounts funded from a funded account
SUPRA_EXAMPLES_PRIVATE_KEY=<key> uv run python -m examples.transfer_coin

# A localnet, accounts funded from the localnet faucet
SUPRA_RPC_NODE_URL=http://localhost:27001 uv run python -m examples.transfer_coin
```

Every example, in sequence. `make examples` runs all of them even when one fails, then exits with a non-zero status
and lists the failed examples if any failed. It needs `SUPRA_RPC_NODE_URL` set, so that the network the examples send
transactions to is chosen explicitly:

```bash
SUPRA_RPC_NODE_URL=https://rpc-devnet.supra.com SUPRA_EXAMPLES_PRIVATE_KEY=<key> make examples
SUPRA_RPC_NODE_URL=http://localhost:27001 make examples
```

`EXAMPLES_EXCLUDE` names the examples to leave out, for example `make examples EXAMPLES_EXCLUDE="faucet rotate_key"`.

An example exits with a non-zero status when a step raises, which includes every transaction that does not end with
status `Success`.

## The examples

| Example | Shows |
|---|---|
| [`automation.py`](./automation.py) | Registering an automation task and stopping it |
| [`faucet.py`](./faucet.py) | One faucet request, sent without waiting, then waiting for the faucet transaction |
| [`fee_payer_transfer_coin.py`](./fee_payer_transfer_coin.py) | A coin transfer whose gas a sponsor pays, simulated and then submitted |
| [`fungible_asset.py`](./fungible_asset.py) | Reading a SUPRA balance as a fungible asset, migrating a `CoinStore` balance when the fungible balance is 0, a fungible asset transfer, and walking the receiver's fungible store transactions |
| [`hello_blockchain.py`](./hello_blockchain.py) | Publishing the `hello_blockchain` package and calling its entry function; `python -m examples.hello_blockchain <address>` uses a package already published at `<address>` |
| [`multisig.py`](./multisig.py) | A 2-of-3 MultiEd25519 account: a transfer, rotating an account's key to the multisig key, publishing and upgrading the `upgrade_and_govern` package, and a Move script; `python -m examples.multisig true` pauses between the steps |
| [`rotate_key.py`](./rotate_key.py) | Rotating an account's authentication key to another Ed25519 key, then to a MultiEd25519 key |
| [`simple_nft.py`](./simple_nft.py) | A token collection and token of `0x3::token`: create, offer, claim, and a multi-agent transfer |
| [`simple_supra_token.py`](./simple_supra_token.py) | A collection and token of the object-based token standard, and token transfers |
| [`simulate_transfer_coin.py`](./simulate_transfer_coin.py) | Simulating a transfer before and after the receiver has a coin store |
| [`supra_token.py`](./supra_token.py) | Adding, removing and updating the properties of an object-based token, and transferring it |
| [`transfer_coin.py`](./transfer_coin.py) | SUPRA transfers and balances |
| [`transfer_two_by_two.py`](./transfer_two_by_two.py) | A multi-agent Move script (`two_by_two_transfer.mv`) with two senders and two receivers |
| [`your_coin.py`](./your_coin.py) | Publishing the `moon_coin` package, a managed coin, and registering, minting and transferring the coin |

[`common.py`](./common.py) reads the environment and funds the generated accounts. [`faucet_funder.py`](./faucet_funder.py)
is not an example: it creates the funded account described under [Environment](#environment).

## Move packages

[`move/packages.json`](./move/packages.json) holds the compiled packages that `hello_blockchain.py`, `multisig.py` and
`your_coin.py` publish: for each package, the package metadata, the module bytecode and the script bytecode, as hex.
They were compiled for the address named in the file, and `compiled_package` of `common.py` replaces that address
with the publisher's in the bytecode before publishing. The metadata contains no address.

The sources are in [`Entropy-Foundation/aptos-core`](https://github.com/Entropy-Foundation/aptos-core) at the tag
`aptosvm-v1.16_supra-v1.8.9`, and are licensed under Apache-2.0; the compiled packages derive from them:

| Package in `packages.json` | Source directory | Named address |
|---|---|---|
| `hello_blockchain` | `aptos-move/move-examples/hello_blockchain` | `hello_blockchain` |
| `moon_coin` | `aptos-move/move-examples/moon_coin` | `MoonCoin` |
| `upgrade_and_govern_genesis` | `aptos-move/move-examples/upgrade_and_govern/genesis` | `upgrade_and_govern` |
| `upgrade_and_govern_upgrade` | `aptos-move/move-examples/upgrade_and_govern/upgrade` | `upgrade_and_govern` |

Each was compiled with the `supra` CLI of node release v11.7.2, against the framework packages
(`aptos-move/framework/*`) of the same tag, with:

```bash
supra move tool compile --save-metadata --package-dir <source directory> \
  --named-addresses <named address>=0x9c1f5e3a7b2d4c6e8f0a1b3c5d7e9f2a4b6c8d0e1f3a5b7c9d2e4f6a8b0c1d3e
```

The outputs are `build/<package name>/package-metadata.bcs`, `build/<package name>/bytecode_modules/*.mv` and
`build/<package name>/bytecode_scripts/*.mv`; `packages.json` lists the modules in the order of publication
(`parameters` before `transfer`) and, for `upgrade_and_govern_upgrade`, the script `set_and_transfer`.
