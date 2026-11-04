# Changelog

All notable changes to `supra-sdk` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-11-04

This release is tested against Supra node `supra_node_v11.7.2`, which runs on Mainnet and Testnet, and
`supra_node_v12.0.0.rc7`, which runs on Devnet. The SDK calls `/rpc/v3` only. The README section "Compatibility" lists
the methods and parameters that need a node from `supra_node_v12.0.0` and what a `supra_node_v11.7.2` node does
instead. Entries marked **Breaking:** change behaviour or signatures that code written for 0.1.1 can depend on; each
says what to change.

### Added

- **`SupraClient.submit_transaction_and_wait(signed_transaction)`** — submits a signed transaction, waits until it is
  final and returns its data. It raises `TransactionFailedError` unless the status is `Success`, and waits whatever
  `TransactionConfig.wait_for_transaction` says.
- **`TransactionFailedError`** — raised when a transaction the SDK waited for ends with a status other than `Success`.
  It carries `tx_hash`, `status`, `vm_status` (the Move VM message, for example the abort location and code; `None`
  when the node reports no Move output, as for `Invalid`) and `transaction_data`.
  **`TransactionWaitTimeoutReachedError.last_status`** is the last status the node reported, `None` if the node never
  knew the transaction. `TransactionFailedError`, `TransactionWaitTimeoutReachedError`,
  `FaucetRequestNotAcceptedError` and `MaxGasEstimationError` are exported from `supra_sdk.clients.rest`.
- **Typed HTTP errors**, exported from `supra_sdk.clients`. `ApiError` is still raised for every non-200 response; it
  gains `message` (the `message` field of the node's JSON error body, otherwise the body, or the HTTP reason phrase for
  an empty body), `headers` and `body`, and its constructor `(message, status_code)` is unchanged. These statuses raise
  a subclass of it: `ApiNotFoundError` (404), `ApiRequestTimeoutError` (408), `ApiGoneError` (410; `oldest_block` from
  the `x-supra-oldest-block` header), `ApiRateLimitError` (429; `retry_after_seconds` from the body's
  `retry_after_seconds` or the `Retry-After` header) and `ApiServiceUnavailableError` (503).
  `UnexpectedResponseError` (an `ApiError` and a `KeyError`; `field` names the field) is raised by `view()` and
  `faucet()` for a 200 response that does not have the shape they read. `ClientTimeoutError` (a
  `httpx.TimeoutException`; `url`, `timeout_seconds`, `phase` and `request`) is raised for a request that exceeds the
  timeout.
- **`ApiClientConfig.timeout`** and **`ApiClientConfig.retry`**, keyword-only, also on `SupraClientConfig`. `timeout`
  (default 60) limits each phase of a request, in seconds: connecting, waiting for a pooled connection, writing and
  reading. A value that is not a finite number above 0 raises `ValueError`. `retry` takes a
  `RetryPolicy(attempts=3, max_delay_seconds=10.0, base_delay_seconds=0.25)`: a GET request is then repeated after a
  408, 429 or 503 response or a timeout, up to `attempts` requests in total, after the wait the response asks for or an
  exponential backoff. A response that asks for a wait longer than `max_delay_seconds` is raised at once. The default,
  `None`, repeats no request. POST requests (submit, simulate, view) and the faucet request are never repeated.
- **`version()`** — reads `GET /rpc/v3/version` and returns the node's response as a dict with `version`, `release`,
  `branch`, `commit_hash`, `build_time` and `build_env`. `release` is the node's release tag, for example
  `supra_node_v12.0.0.rc7`. It is absent from the response of every v11 release and of `supra_node_v12.0.0.rc1` to
  `rc6`; read it with `.get("release")`.
- **Fungible asset helpers** on `SupraClient`, which default to SUPRA (metadata address `0xa`):
  - `account_fa_balance(account_address, metadata_address)` reads `0x1::primary_fungible_store::balance`, the
    account's primary fungible store alone. `account_supra_balance` reads `0x1::coin::balance`, which adds the
    fungible store balance to the `CoinStore` balance while the coin-to-fungible-asset migration feature is enabled.
  - `transfer_fungible_asset(sender, recipient, amount, metadata_address, ...)` calls
    `0x1::primary_fungible_store::transfer`. It debits the sender's fungible store only; `transfer_supra_coin` moves
    SUPRA held in either form.
  - `migrate_coin_to_fungible_store(sender, coin_type, ...)` calls `0x1::coin::migrate_to_fungible_store`, which moves
    a `CoinStore` balance into the primary fungible store. It cannot be undone.
  - `account_fa_transactions(account_address, pagination, metadata_address, transaction_type, *, store_address)` and
    `iter_account_fa_transactions` list the transactions of the account's primary store
    (`GET /rpc/v3/accounts/{store}/fa_transactions`), or of the store at `store_address`.
  - The module `supra_sdk.fungible_asset` has `SUPRA_FA_METADATA_ADDRESS` and
    `primary_store_address(owner, metadata_address)`, built on the new `AccountAddress.for_user_derived_object`.

  `account_coin_transactions` lists `CoinStore` movements only. Movements of SUPRA held in a primary fungible store, as
  on Devnet, are listed by `account_fa_transactions` and, on nodes from `supra_node_v12.0.0`, by `account_history`.
  The README sections "SUPRA as a fungible asset" and "Listing an account's SUPRA movements" describe which method to
  use.
- **`account_history(account_address, pagination=None, categories=None)`** and **`iter_account_history`** read
  `GET /rpc/v3/accounts/{address}/history`: every finalized transaction that concerns the account, once each, with the
  categories it matched (`AccountHistoryCategory`: `sent`, `coin`, `fa`, `da`). `account_history` returns an
  `AccountHistoryPage` with `entries`, `cursor`, `indexed_from` (the lowest block height the history covers, from the
  `x-supra-history-indexed-from` header) and `oldest_block` (from the `x-supra-oldest-block` header). An empty or
  unknown category, or names joined with commas, raises `ValueError` before the request. They need a node from
  `supra_node_v12.0.0`; a `supra_node_v11.7.2` node answers 404, raised as `ApiNotFoundError` with the message
  `Not Found`.
- **`transaction_type`** argument on `account_coin_transactions` and `iter_account_coin_transactions`, sent as the
  node's `type` query parameter. `TransactionType` gains `RECORD` and `SETTLEMENT`; a `supra_node_v11.7.2` node rejects
  `settlement` with HTTP 400.
- **Iterators** `iter_account_resources`, `iter_account_modules`, `iter_account_coin_transactions`,
  `iter_account_automated_transactions` and `iter_events_by_type` request further pages until the node sends no next
  cursor or repeats one. An empty page with a new cursor does not end them. `supra_sdk.clients.rest.paging` has the
  cursor rule, `next_cursor`, and `paginate`.
- **`AutomatedTransactionsPagination.cursor`** — the cursor returned with the previous page of
  `account_automated_transactions`, to read the next one. 0.1.1 could not read past the first page.
- **Automation registration parameters version 2.** `AutomationTaskType` (`USER`, `SYSTEM`),
  `AutomationRegistrationParamsV2` (the version 1 fields, a task type and an optional priority) and
  `AutomationRegistrationParams.build(...)`, which returns version 1 without a task type and version 2 with one.
  `SupraClient.register_automation_task` takes `automation_task_type` and `automation_priority`; without a task type it
  registers version 1 parameters, as 0.1.1 did. A priority is allowed only with `AutomationTaskType.SYSTEM`: with any
  other task type or none, `build`, the `AutomationRegistrationParamsV2` constructor and `register_automation_task`
  raise `ValueError` before anything is signed. A user task has no priority; the registry uses its index. Only
  accounts that the automation registry has authorised can register `SYSTEM` tasks.
  `AutomationRegistrationParamsV2.deserialize` also decodes a user task with a priority.
- **`max_gas_amount`** argument on `create_raw_transaction`, `create_signed_transaction`,
  `create_fee_payer_transaction`, `create_multi_agent_transaction`, `transfer_supra_coin`, `transfer_coins` and the
  fungible asset helpers. An integer is used as given; `None` uses `TransactionConfig.max_gas_amount` or the estimate
  described under Changed.
- **`create_raw_transaction(..., fee_payer=...)`** takes the account or address that pays for gas. Its SUPRA balance,
  not the sender's, caps the max gas estimate, and when both the sender and the fee payer are accounts the estimate
  simulates the fee-payer form.
- **`sequence_number`**, keyword-only, on `create_fee_payer_transaction` and `create_multi_agent_transaction`. An
  integer, including 0, is used without reading the sender's account. With 0, a fee payer can sponsor the first
  transaction of a sender that has no account on a node from `supra_node_v12.0.0`; a `supra_node_v11.7.2` node refuses
  the submission (HTTP 400, "Transaction validation failed: Failed to read the AccountResource").
- **`SupraClient.max_transaction_time_to_live()`** returns the node's maximum transaction time-to-live
  (`max_transaction_time_to_live_seconds` of `GET /rpc/v3/transactions/parameters`), read once per client. It returns
  600, without caching it, when the node answers 404 or omits the value.
- **`TypeTag.from_str`** parses a type: primitives, `signer`, `vector<…>` and structs with nested type arguments, for
  example `vector<vector<u64>>` or `0x1::option::Option<vector<u8>>`. `str()` of a `TypeTag` gives a form that parses
  back. New `SignerTag` and `VectorTag`, which `TypeTag.deserialize` decodes. `TypeTag` and `StructTag` are hashable.
- **Multi-signature decoding.** `MultiEd25519Authenticator`, the MultiKey variant of `AccountAuthenticator` and the
  MultiKey `asymmetric_crypto_wrapper.MultiSignature` decode, so a `SignedTransaction` from a MultiEd25519 or MultiKey
  account round-trips through BCS. A MultiKey supports Ed25519 keys only; another key type raises `ValueError` when
  decoded. `MultiEd25519Authenticator.verify` verifies the signature; it raised `NotImplementedError`. The multi-key,
  multi-signature and authenticator classes have `__eq__` and `__hash__`.
- **`py.typed`** — the package ships the PEP 561 marker, so type checkers read its annotations.
- **`ApiClient(..., transport=...)`** takes an optional `httpx` transport, for example `httpx.MockTransport`.
- Address parameters of the REST methods accept a hex string as well as an `AccountAddress`. Block heights and epochs
  accept a string of decimal digits as well as an integer.

### Changed

- **Breaking:** with `TransactionConfig.wait_for_transaction` enabled (the default), `submit_transaction` and every
  helper built on it (the transfer, publish, object, automation, token and fungible asset helpers) raise
  `TransactionFailedError` unless the transaction's final status is `Success`. 0.1.1 waited and returned the hash
  whatever the outcome. `faucet(..., wait_for_faucet=True)` raises it too when the faucet transaction ends `Fail` or
  `Invalid`. To handle a failed transaction, catch `TransactionFailedError`; its `transaction_data` holds the
  transaction. To submit without the check, set `wait_for_transaction=False`: the helpers then return the hash right
  after submission without waiting, as 0.1.1 did with that setting.
- **Breaking:** `wait_for_transaction` and `wait_for_faucet` return only on a final status, `Success`, `Fail` or
  `Invalid`, and still return the data of a `Fail` or `Invalid` transaction. They keep polling through `Pending`,
  `PendingAfterExecution`, a missing status and an unknown one; 0.1.1 returned on any status other than `Pending`. A
  404 whose body is the node's "transaction not found" message means "not seen yet", so for a hash the node has never
  seen (a typo, or a hash from another network) they poll until `transaction_wait_time_in_seconds` and then raise
  `TransactionWaitTimeoutReachedError` with `last_status=None`. 0.1.1 raised `ApiError` with status 404 at once. Code
  that caught that `ApiError` catches `TransactionWaitTimeoutReachedError` and checks `last_status is None`. Other 404
  responses, such as one for a wrong base URL, still raise at once, as `ApiNotFoundError`. The first poll is sent
  without a sleep before it, no poll starts after the deadline, each poll and sleep is bounded by the time remaining,
  and `transaction_wait_time_in_seconds` and `polling_wait_time_in_seconds` accept fractional seconds. The message of
  `TransactionWaitTimeoutReachedError` changed.
- **Breaking:** `TransactionConfig.max_gas_amount` and `TransactionConfig.expiration_ttl` default to `None`; they were
  500,000 and 600. To keep 0.1.1's values, set `SupraClientConfig(max_gas_amount=500_000, expiration_ttl=600)`.
  - Max gas: without a `max_gas_amount` on the call or in the config, the SDK reads the gas payer's SUPRA balance,
    simulates the transaction with the most gas that balance pays for at the gas unit price (at most 2,000,000,000
    units), and uses the gas used times 1.5, rounded up, at least 1,500 units and at most what the balance pays for.
    When the simulation reports the sequence number as ahead of the account's (a transaction sent behind uncommitted
    ones), the account's sequence number is read and the simulation is repeated with it; the transaction keeps its own
    number. A sender given only as an address gets 20,000 units, capped by the balance. When the estimate cannot be
    made (the balance cannot be read or pays for no gas, or the simulation does not succeed), `MaxGasEstimationError`
    is raised, with `status`, `vm_status` and `simulation`, and nothing is submitted. Each transaction without an
    explicit max gas makes a balance read and a simulation request.
  - Expiry: without an `expiration_ttl`, a transaction expires 5 seconds before the node's maximum time-to-live after
    the client's clock: 595 seconds where the maximum is 600, its value on every network. The first such transaction
    of a client reads the maximum from `GET /rpc/v3/transactions/parameters`.
- **Breaking:** `account_resources`, `account_modules`, `account_coin_transactions`, `account_automated_transactions`
  and `events_by_type` return `None` as the cursor when the feed has ended; 0.1.1 returned `""`. They also return
  `None` for the values with which a v11.7.x node ends a feed: `"0"` on an empty page, and the request's own cursor on
  an empty page. The exception is the first request of an ascending `account_coin_transactions` read with a
  `transaction_type`, where `"0"` can be the position of a genesis row and is returned. An empty page with any other
  cursor does not end a feed. Code that compares `cursor == ""` compares `cursor is None`; `while cursor:` loops keep
  working.
- **Breaking:** primitive type tags (`BoolTag`, `U8Tag` to `U256Tag`, `AccountAddressTag`) carry no value and encode
  as the variant byte alone, the encoding the node accepts; 0.1.1 wrote the value after the variant byte. The `.value`
  attribute is removed, equality ignores any value passed, and `str()` gives the type name, for example `u64`. The
  constructors still accept one argument, ignore it and emit a `DeprecationWarning`; write `U64Tag()` instead of
  `U64Tag(0)`. `TypeTag.deserialize` raises `ValueError` for an unknown variant (was `NotImplementedError`), and
  `StructTag.from_str` raises `ValueError` for malformed input or a type that is not a struct (0.1.1 raised whatever
  error the input led to, such as `IndexError`).
- **Breaking:** `str()` of an `ApiError` keeps the form `{message: …, status_code: …}` and holds `ApiError.message`,
  the node's message when the JSON error body has one, where 0.1.1 held the whole response body; the body is
  `ApiError.body`. A request that times out raises `ClientTimeoutError` instead of the `httpx` timeout class;
  `except httpx.TimeoutException` still catches it. The wait for a pooled connection is limited by the timeout (60
  seconds by default); in 0.1.1 it was unlimited.
- **Breaking:** `view()` raises `UnexpectedResponseError` when a 200 response is not JSON or has no `result` field,
  where 0.1.1 raised `json.JSONDecodeError` (a `ValueError`) or `KeyError`. `UnexpectedResponseError` is a `KeyError`
  and not a `ValueError`; code that caught `ValueError` catches `UnexpectedResponseError`.
- **Breaking:** `faucet()` raises `UnexpectedResponseError` when a 200 body is neither `"TryLater"` nor a JSON object
  whose `Accepted` is a non-empty string, including a body that is not JSON. For such bodies 0.1.1 returned `None`,
  `""` or the value as it was with `wait_for_faucet=False`, raised `FaucetRequestNotAcceptedError` for a missing or
  empty `Accepted` with `wait_for_faucet=True`, and raised `json.JSONDecodeError` for a body that is not JSON. Code
  that caught those for these bodies catches `UnexpectedResponseError`.
- **Breaking:** path values are validated before a request is sent, and invalid ones raise `ValueError` where 0.1.1
  sent the request. Addresses and table handles must be account addresses (an `AccountAddress` or a hex string) and are
  sent in canonical form; transaction and block hashes must be 64 hex digits with an optional `0x`; heights and epochs
  must be non-negative integers or strings of decimal digits; other values, such as resource types, module names and
  event types, must be non-empty strings. Each value is sent as one percent-encoded path segment, so a value containing
  `/`, `?`, `#` or `%` stays in its segment. A base URL with a query string or a fragment raises `ValueError`; pass an
  access token through `ApiClientConfig.access_token`. `ApiClient.base_url` always ends in `/`.
- **Breaking:** both `MultiSignature` classes (`ed25519` and `asymmetric_crypto_wrapper`) sort their signatures by key
  index, the order in which the node pairs them with bitmap bits, so the order the caller supplies them in does not
  matter and `.signatures` is sorted. The bytes of a MultiKey signature built from signatures out of index order change.
  A `SignedTransaction` built from a MultiEd25519 `AccountAuthenticator` encodes its authenticator as the transaction
  authenticator `MultiEd25519` instead of `SingleSender`, so its bytes and hash change; one built from
  `Authenticator(MultiEd25519Authenticator(...))` is unchanged. The multi-key and multi-signature constructors raise
  `ValueError` where they used `assert` (so the checks also hold under `python -O`), and reject an empty signature list
  and a repeated key index. The decoders raise `ValueError` for malformed input, such as truncated bytes or a bitmap
  that does not match the number of signatures. `verify` returns `False` for fewer signatures than the threshold, an
  index without a key, a signature of another type or a signature that does not verify. Code that caught
  `AssertionError` catches `ValueError`.
- **Breaking:** `behave` and `types-six` are no longer runtime dependencies. The wheel requires `httpx[http2]`,
  `PyNaCl` and `typing-extensions`; a project that used `behave` or `types-six` through `supra-sdk` declares them
  itself. The `PyNaCl` lower bound is 1.6.2 (was 1.5.0).
- `block_by_height` takes `with_finalized_transactions`, the node's parameter name, as its third parameter. The keyword
  `with_finalized_transaction` is still accepted, keyword-only, and emits a `DeprecationWarning`.
- `ed25519.MultiPublicKey` and the MultiKey `asymmetric_crypto_wrapper.MultiPublicKey` accept a single key; the minimum
  was 2.
- `TypeTag.from_str`, `StructTag.from_str` and `TypeTag.deserialize` raise `ValueError` for a type that nests `vector`
  and struct type arguments 9 or more levels deep (`MAX_TYPE_TAG_NESTING`), the Move type-tag nesting limit.
- The BCS `Deserializer`, `Authenticator` and `AccountAuthenticator` decoding, and `ed25519.PublicKey` and
  `ed25519.Signature` decoding raise `ValueError` for malformed input, where they raised `Exception`.
- The package metadata declares the licence as the SPDX expression `Apache-2.0` (`License-Expression: Apache-2.0`,
  `License-File: LICENSE`, metadata version 2.4) instead of the licence text in the `License` field.
- The package is tested on Python 3.12, 3.13 and 3.14. It requires Python 3.12 or later, as 0.1.1 did.
- The examples in `examples/` default to Devnet (`https://rpc-devnet.supra.com`) and read `SUPRA_RPC_NODE_URL`,
  `SUPRA_FAUCET_URL` and an optional funded key, `SUPRA_EXAMPLES_PRIVATE_KEY`, from the environment. They publish Move
  packages from the precompiled `examples/move/packages.json` instead of running the `supra` CLI, and no longer use
  `aiofiles`. `examples/README.md` describes them.

### Fixed

- **Base URL path prefix.** A base URL with a path, such as `https://host/prefix`, sends requests to
  `https://host/prefix/rpc/v3/…` with or without a trailing slash; 0.1.1 dropped the last path segment when the base
  URL had no trailing slash.
- `create_raw_transaction`, `create_signed_transaction` and the helpers that take a `sequence_number` use 0 as given;
  0.1.1 read the account's sequence number instead.
- `simulate_transaction` simulates an unsigned copy and never modifies the caller's `SignedTransaction`; 0.1.1 left it
  with a zero signature when the simulation request failed.
- `block_by_height` and `txs_by_block` send the transaction type filter as `type`, the node's query parameter; 0.1.1
  sent `transaction_type`, which the node ignores.
- `consensus_block_by_height` requests `/rpc/v3/consensus/block/height/{height}`; 0.1.1 requested
  `/rpc/v3/consensus/height/{height}`.
- `EventsPagination(start_height=0)` sends `start_height=0`; 0.1.1 left it out.
- An empty `start` or `cursor` in the pagination options is not sent.
- `SupraTokenObjectClient.read_object` follows the node's cursor through `iter_account_resources`. An address with no
  resources takes one request.
- `faucet()` handles the node's `"TryLater"` answer, which means no faucet account was free: with
  `wait_for_faucet=False` it returns `None`, and with `wait_for_faucet=True` it raises `FaucetRequestNotAcceptedError`.
  0.1.1 raised `AttributeError`. The faucet request is sent once.
- `ScriptArgument` accepts every variant from `U8` to `U256` (0 to 8); 0.1.1 refused `U16`, `U32` and `U256`.
- `SingleKeyAuthenticator.verify`, and `SignedTransaction.verify()` for a single-key sender, return `True` for a valid
  signature; 0.1.1 returned `False`.

### Removed

- **Breaking:** `asymmetric_crypto_wrapper.index_to_bitmap_value`. `MultiSignature.serialize` builds the bitmap.

### Security

- **Breaking:** `str()` and `repr()` of an `ed25519.PrivateKey` return a redacted form, `PrivateKey(public_key=0x…)`,
  so f-strings, `print` and log output of a private key do not contain the key. `hex()` exports the key and is
  unchanged. Code that used `str(private_key)` or an f-string to export the key calls `private_key.hex()`.
- `Account.store` writes the file with mode 0600, readable and writable by its owner only; in 0.1.1 the mode followed
  the umask. It writes a temporary file in the same directory and renames it over the path, so an existing file is
  replaced and a failed write leaves it intact. On Windows the mode is not applied. The key is stored unencrypted, the
  JSON format is unchanged, and `Account.load` reads files written by 0.1.1.

## [0.1.1] - 2026-02-10

### Changed

- **`TransactionConfig.gas_unit_price`** defaults to `None`, which uses the node's `min_configured_gas_price` from
  `GET /rpc/v3/transactions/estimate_gas_price` instead of 100.

## [0.1.0] - 2025-09-19

First release.

[Unreleased]: https://github.com/Entropy-Foundation/supra-python-sdk/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Entropy-Foundation/supra-python-sdk/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/Entropy-Foundation/supra-python-sdk/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Entropy-Foundation/supra-python-sdk/releases/tag/v0.1.0
