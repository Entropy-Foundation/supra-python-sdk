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

## Reference Docs

For the function specific documentation, check out the `supra-python-sdk` [reference documentation](https://supra-python-sdk.docs.supra.com/).

## Listing an account's SUPRA movements

Which method lists them depends on where the chain holds SUPRA:

- Coin layout (Mainnet and Testnet, until governance enables features 64 and 65): SUPRA is in the account's
  `CoinStore<SupraCoin>`, and `account_coin_transactions` lists its movements. An account that migrated its SUPRA to
  its primary fungible store has the primary-store layout from then on.
- Primary-store layout (a chain created with features 64 and 65 on, such as Devnet on `supra_node_v12.0.0`): no
  account has a `CoinStore<SupraCoin>`, SUPRA moves between primary fungible stores, and `account_coin_transactions`
  lists none of it. Use `account_history` with the category `fa` (nodes from `supra_node_v12.0.0`) or
  `account_fa_transactions`. SUPRA transfers emit `0x1::fungible_asset::Withdraw` and `Deposit` events, whose `store`
  field names the fungible store, not the account, and no `0x1::coin` events.

```python
entries, cursor = await client.account_history(address, categories=["fa"])
async for entry in client.iter_account_history(address, categories=["sent", "fa"]):
    print(entry["categories"], entry["transaction"]["hash"])
```

## Contributing

If you found a bug or would like to request a feature, please file an [issue](https://github.com/Entropy-Foundation/supra-python-sdk/issues/new).
If, based on the discussion on an issue, you would like to offer a code change, please make a [pull request](https://github.com/Entropy-Foundation/supra-python-sdk/pulls).
