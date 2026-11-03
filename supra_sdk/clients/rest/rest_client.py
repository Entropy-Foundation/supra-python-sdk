# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

from typing import Any

import httpx

from supra_sdk.clients import ApiClient
from supra_sdk.clients.api_client import UnexpectedResponseError


class RestClient:
    """A base class for building category-specific REST API clients.

    This class provides a shared interface and a common `api_client` instance for sending REST API requests. Other REST
    client classes can inherit from `RestClient` to reuse this functionality.

    Attributes:
        api_client (supra_sdk.clients.api_client.ApiClient): The API client instance used to perform HTTP requests against the REST API.

    """

    api_client: ApiClient

    def __init__(self, api_client: ApiClient):
        """Initializes a `RestClient` instance.

        Args:
            api_client (supra_sdk.clients.api_client.ApiClient): An instance of `ApiClient` responsible for managing HTTP requests.

        """
        self.api_client = api_client

    @staticmethod
    def _response_field(response: httpx.Response, field: str) -> Any:
        """Returns `field` of the JSON object in the body of `response`.

        Raises:
            UnexpectedResponseError: If the body is not a JSON object with `field`.

        """
        try:
            data = response.json()
        except ValueError:
            raise UnexpectedResponseError(field, response) from None
        if not isinstance(data, dict) or field not in data:
            raise UnexpectedResponseError(field, response)
        return data[field]
