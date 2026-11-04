# Supra Python SDK

[![License](https://img.shields.io/badge/license-Apache-green.svg)](LICENSE)
[![Discord chat](https://img.shields.io/discord/850682587273625661?style=flat-square)](https://discord.gg/supralabs)

The `supra-python-sdk` provides a seamless interface for interacting with the Supra-L1 network. It offers comprehensive support for `move-vm` operations and transactions, enabling developers to both query on-chain data and submit `move-vm` based transactions with ease.

- Python 3.12+ support

## Installation

```bash
python -m pip install supra-sdk
```

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

`view()` and `faucet()` raise `UnexpectedResponseError`, which is also a `KeyError`, when a 200 response does not
have the field they read (`result` and `Accepted`). A request that exceeds the timeout raises `ClientTimeoutError`,
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

```python
balance = await client.account_fa_balance(alice.address())
await client.transfer_fungible_asset(alice, bob.address(), 1_000)
transactions, cursor = await client.account_fa_transactions(bob.address())
```

All of them default to SUPRA and take a `metadata_address` for another fungible asset (`migrate_coin_to_fungible_store`
takes a `coin_type`). See [`examples/fungible_asset.py`](examples/fungible_asset.py).

## Reference Docs

For the function specific documentation, check out the `supra-python-sdk` [reference documentation](https://supra-python-sdk.docs.supra.com/).

## Contributing

If you found a bug or would like to request a feature, please file an [issue](https://github.com/Entropy-Foundation/supra-python-sdk/issues/new).
If, based on the discussion on an issue, you would like to offer a code change, please make a [pull request](https://github.com/Entropy-Foundation/supra-python-sdk/pulls).
