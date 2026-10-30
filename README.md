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

### SUPRA as a fungible asset

SUPRA exists in two forms: a `CoinStore` balance and a balance in the account's primary fungible store (metadata
address `0xa`). A Devnet created with SUPRA as a fungible asset from genesis funds accounts in the fungible store only;
Testnet and Mainnet accounts hold a `CoinStore` balance until they migrate it.

- `account_supra_balance` / `account_coin_balance` read `0x1::coin::balance`: the `CoinStore` balance plus the paired
  fungible asset balance, so the sum is the same in either form.
- `account_fa_balance` reads the fungible store alone (`0x1::primary_fungible_store::balance`), and is 0 for an account
  that has only a `CoinStore` balance.
- `transfer_fungible_asset` debits the sender's fungible store only. `transfer_supra_coin` moves SUPRA held in either form.
- `migrate_coin_to_fungible_store` moves a `CoinStore` balance into the fungible store. It is meaningful only where a
  `CoinStore` exists, and cannot be undone.
- `account_fa_transactions` lists the transactions of an account's primary fungible store, a page at a time. The
  returned cursor is `None` at the end of the feed (a v11.7.0 node ends it with an empty page instead).

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
