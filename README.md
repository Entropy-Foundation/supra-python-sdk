# Supra Python SDK

[![License](https://img.shields.io/badge/license-Apache-green.svg)](LICENSE)
[![Discord chat](https://img.shields.io/discord/850682587273625661?style=flat-square)](https://discord.gg/supralabs)

The `supra-python-sdk` provides a seamless interface for interacting with the Supra-L1 network. It offers comprehensive support for `move-vm` operations and transactions, enabling developers to both query on-chain data and submit `move-vm` based transactions with ease.

- Python 3.12+ support

## Installation

```bash
python -m pip install supra-sdk
```

## Compatibility

The SDK is tested against Supra node `supra_node_v11.7.2` (Mainnet and Testnet) and `supra_node_v12.0.0.rc7` (Devnet).
It calls `/rpc/v3` only.

These need a node from `supra_node_v12.0.0`. On a `supra_node_v11.7.2` node they behave as described:

| Method or parameter | On a `supra_node_v11.7.2` node |
|---|---|
| `account_history`, `iter_account_history` | The node answers HTTP 404 with an empty body, raised as `ApiNotFoundError` with the message `Not Found`. |
| The `settlement` value of `transaction_type` (`account_coin_transactions`, `account_fa_transactions` and their iterators) | The node rejects it as an unknown `type`. |
| `version()`: the `release` field | The key is absent from the response of every v11 release and of `supra_node_v12.0.0.rc1` to `rc6`; it is present from `supra_node_v12.0.0.rc7`. |
| `sequence_number=0` for a sender without an account (`SupraClient.create_fee_payer_transaction`) | The SDK builds and returns the signed transaction, and the node refuses its submission (HTTP 400, "Transaction validation failed: Failed to read the AccountResource"). |

Other behaviour that differs by node release is described in the sections below and in the docstrings:

- Where an account holds SUPRA, and which method lists its movements: [SUPRA as a fungible asset](#supra-as-a-fungible-asset)
  and [Listing an account's SUPRA movements](#listing-an-accounts-supra-movements). A chain created with features 64
  and 65 on (Devnet on `supra_node_v12.0.0`) has no `CoinStore<SupraCoin>`.
- How a feed ends (the `None` cursor, and the cursor `"0"` of a v11.7.x node on an empty page):
  [SUPRA as a fungible asset](#supra-as-a-fungible-asset), `account_coin_transactions` and `account_history`.
- The error for a missing account: `ApiNotFoundError` (404) on a v12 node, `ApiError` (400) on an earlier node;
  see the `ApiNotFoundError` docstring and [Errors, timeouts and retries](#errors-timeouts-and-retries).

## Usage

Check [examples](examples/README.md) section.

### Errors, timeouts and retries

A response with a status other than 200 raises `ApiError` (from `supra_sdk.clients`), whose `message` is the node's
error message, `status_code` the HTTP status, `headers` the response headers and `body` the response body. These
statuses raise a subclass of `ApiError`:

| Status | Class | Extra attribute |
|---|---|---|
| 404 | `ApiNotFoundError` | |
| 408 | `ApiRequestTimeoutError` | |
| 410 | `ApiGoneError` | `oldest_block`, from the `x-supra-oldest-block` header |
| 429 | `ApiRateLimitError` | `retry_after_seconds`, from the body or the `Retry-After` header |
| 503 | `ApiServiceUnavailableError` | |

`view()` raises `UnexpectedResponseError`, which is also a `KeyError`, when a 200 response is not a JSON object with
the `result` field. `faucet()` returns `None` (or raises `FaucetRequestNotAcceptedError` while waiting) when the
200 response is `"TryLater"`, and raises `UnexpectedResponseError` when the 200 body is not JSON or its `Accepted`
field is missing, empty or not a string. A request that exceeds the timeout raises `ClientTimeoutError`,
which is a `httpx.TimeoutException` and carries the request as `request`.

Each phase of a request (connecting, waiting for a pooled connection, writing, reading) is limited to 60 seconds;
`timeout` changes the limit. GET requests are repeated after a 408, 429 or 503 response or a timeout only when
`retry` is set. POST requests and the faucet request are never repeated.

```python
from supra_sdk.clients import RetryPolicy
from supra_sdk.clients.rest import SupraClient, SupraClientConfig

client = SupraClient(
    "https://rpc-testnet.supra.com",
    SupraClientConfig(timeout=30, retry=RetryPolicy(attempts=3, max_delay_seconds=10)),
)
```

### SUPRA as a fungible asset

SUPRA exists in two forms: a `CoinStore` balance and a balance in the account's primary fungible store (metadata
address `0xa`). A Devnet created with SUPRA as a fungible asset from genesis funds accounts in the fungible store only.
Accounts that still hold a `CoinStore` balance keep it there until they migrate it.

- `account_supra_balance` / `account_coin_balance` read `0x1::coin::balance`: the `CoinStore` balance plus the paired
  fungible asset balance, so the sum is the same in either form. The fungible asset part is included only while the
  coin-to-fungible-asset migration feature is enabled and the coin has a paired fungible asset.
- `account_fa_balance` reads the fungible store alone (`0x1::primary_fungible_store::balance`), and is 0 for an account
  that has only a `CoinStore` balance.
- `transfer_fungible_asset` debits the sender's fungible store only. `transfer_supra_coin` moves SUPRA held in either form.
- `migrate_coin_to_fungible_store` moves a `CoinStore` balance into the fungible store. It is meaningful only for
  accounts that still hold a `CoinStore` balance, and cannot be undone. The framework of v11.7.x nodes writes a
  `coin::MigrationFlag` at the store; the v12 framework writes none, and a converted account is one without
  `CoinStore<CoinType>`.
- `account_fa_transactions` lists the transactions of an account's primary fungible store, a page at a time. On
  Devnet an account's SUPRA movements are listed here and not by `account_coin_transactions`. The returned cursor is
  `None` at the end of the feed on v11.7.x and v12 nodes (the method reads a v11.7.x node's `"0"` on an empty page as
  the end). Stop when the cursor is `None`, not on an empty page or on `"0"`: a page filtered by `transaction_type`
  can be empty and still carry a cursor to continue from, and `"0"` can be the position of a genesis row.
  `iter_account_fa_transactions` takes the same arguments and follows the cursor until the feed ends.

```python
balance = await client.account_fa_balance(alice.address())
await client.transfer_fungible_asset(alice, bob.address(), 1_000)
transactions, cursor = await client.account_fa_transactions(bob.address())
```

All of them default to SUPRA and take a `metadata_address` for another fungible asset (`migrate_coin_to_fungible_store`
takes a `coin_type`). See [`examples/fungible_asset.py`](examples/fungible_asset.py).

## Reference Docs

For the function specific documentation, check out the `supra-python-sdk` [reference documentation](https://supra-python-sdk.docs.supra.com/).

## Listing an account's SUPRA movements

Which method lists them depends on where the account holds SUPRA:

- Coin layout (Mainnet and Testnet accounts created before governance enables feature 64 or 65): SUPRA is in the
  account's `CoinStore<SupraCoin>`, and `account_coin_transactions` lists its movements.
- Primary-store layout: SUPRA is in the account's primary fungible store, and `account_coin_transactions` lists
  none of its movements. While feature 64 or 65 is enabled, registering SUPRA creates the primary store instead of a
  `CoinStore<SupraCoin>`, so new accounts hold SUPRA there; so does an account that migrated its SUPRA. On a chain
  created with features 64 and 65 on, such as Devnet on `supra_node_v12.0.0`, no account has a
  `CoinStore<SupraCoin>`. Use `account_history` with the category `fa` (nodes from `supra_node_v12.0.0`) or
  `account_fa_transactions`. SUPRA transfers emit `0x1::fungible_asset::Withdraw` and `Deposit` events, whose `store`
  field names the fungible store, not the account, and no `0x1::coin` events.

```python
history = await client.account_history(address, categories=["fa"])
print(history.entries, history.cursor, history.indexed_from, history.oldest_block)
async for entry in client.iter_account_history(address, categories=["sent", "fa"]):
    print(entry["categories"], entry["transaction"]["hash"])
async for transaction in client.iter_account_fa_transactions(address):
    print(transaction["hash"])
```

## Contributing

If you found a bug or would like to request a feature, please file an [issue](https://github.com/Entropy-Foundation/supra-python-sdk/issues/new).
If, based on the discussion on an issue, you would like to offer a code change, please make a [pull request](https://github.com/Entropy-Foundation/supra-python-sdk/pulls).
