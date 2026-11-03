# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

from typing import Any

from supra_sdk.account_address import AccountAddress
from supra_sdk.clients.api_client import UnexpectedResponseError
from supra_sdk.clients.rest.rest_client import RestClient
from supra_sdk.clients.rest.rest_types import (
    FAUCET_ENDPOINT,
    FAUCET_TRANSACTION_ENDPOINT,
    format_endpoint,
)

# The body of a 200 faucet response when no faucet account is free to fund the request.
_FAUCET_TRY_LATER = "TryLater"


class FaucetRestClient(RestClient):
    """A class that provides methods to invoke `Faucet` REST endpoints from a Supra RPC node.

    Attributes:
        api_client (supra_sdk.clients.api_client.ApiClient): Inherited from `RestClient`. Used to send HTTP requests to the Supra RPC node.

    """

    async def faucet(self, address: AccountAddress | str) -> str | None:
        """Requests faucet funds to be sent to the given account address.

        The node answers `{"Accepted": <hash>}` when it submitted a funding transaction and `"TryLater"` when no
        faucet account was free to fund it; a `"TryLater"` answer does not count against the address. The request is
        sent once, whatever `ApiClientConfig.retry` says, because each accepted request funds the account.

        Args:
            address (AccountAddress | str): The target account address to receive funds, as an `AccountAddress`
                or a hex string.

        Returns:
            str | None: The faucet transaction hash when the node answers `Accepted`, None when it answers
                `"TryLater"`.

        Raises:
            ApiRateLimitError: If the address is inside the cooldown after its last grant or has reached the daily
                number of grants (429).
            ApiError: If the node answers with a status other than 200, for example 400 when the account's
                SUPRA balance is at or above the faucet's cap.
            UnexpectedResponseError: If the node answers 200 with a body that is neither `"TryLater"` nor a JSON
                object whose `Accepted` is a non-empty string, including a body that is not JSON.

        """
        endpoint = format_endpoint(FAUCET_ENDPOINT, address=address)
        response = await self.api_client.get(endpoint=endpoint, retryable=False)
        res_data = self._response_json(response, "Accepted")
        if res_data == _FAUCET_TRY_LATER:
            return None
        accepted = res_data.get("Accepted") if isinstance(res_data, dict) else None
        if not isinstance(accepted, str) or not accepted:
            raise UnexpectedResponseError("Accepted", response)
        return accepted

    async def faucet_transaction_by_hash(self, tx_hash: str) -> dict[str, Any]:
        """Retrieves details of a faucet transaction by its hash.

        Args:
            tx_hash (str): The hash of the faucet transaction.

        Returns:
            dict[str, Any]: Faucet transaction details.

        """
        endpoint = format_endpoint(FAUCET_TRANSACTION_ENDPOINT, hash=tx_hash)
        return (await self.api_client.get(endpoint=endpoint)).json()
