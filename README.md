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

A 200 response without a field the SDK reads raises `UnexpectedResponseError`, which is also a `KeyError`. A request
that exceeds the timeout raises `ClientTimeoutError`, which is a `httpx.TimeoutException`.

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

## Reference Docs

For the function specific documentation, check out the `supra-python-sdk` [reference documentation](https://supra-python-sdk.docs.supra.com/).

## Contributing

If you found a bug or would like to request a feature, please file an [issue](https://github.com/Entropy-Foundation/supra-python-sdk/issues/new).
If, based on the discussion on an issue, you would like to offer a code change, please make a [pull request](https://github.com/Entropy-Foundation/supra-python-sdk/pulls).
