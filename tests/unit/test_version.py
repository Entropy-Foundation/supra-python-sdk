# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

import unittest
from typing import Any

import httpx

from supra_sdk.clients import ApiClient
from supra_sdk.clients.rest.supra_client import SupraClient

V11_RESPONSE = {
    "version": "0.5.0",
    "branch": "",
    "commit_hash": "f52cb25b7dcdd4ad8b7d7530dbc185ecbeefda02",
    "build_time": "2026-11-03 15:04:58 +10:00",
    "build_env": "rustc 1.97.1 (8bab26f4f 2026-07-14)",
}

V12_RESPONSE = {
    "version": "0.5.0",
    "release": "supra_node_v12.0.0.rc7",
    "branch": "",
    "commit_hash": "a89b26e61e6f8ff594f3d0435d9050f0b3488a1d",
    "build_time": "2026-11-03 15:04:16 +10:00",
    "build_env": "rustc 1.99.1 (58cf8f9c3 2026-10-13)",
}


async def _client_answering(
    body: dict[str, Any], requests: list[httpx.Request]
) -> SupraClient:
    """Builds a `SupraClient` whose HTTP transport records requests and answers every one with `body`."""

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=body)

    base_url = "http://node.example"
    client = SupraClient(base_url)
    config = client.api_client.api_client_config
    await client.api_client.close()
    client.api_client = ApiClient(
        base_url, config, transport=httpx.MockTransport(handle)
    )
    return client


class VersionTests(unittest.IsolatedAsyncioTestCase):
    async def test_v12_response_carries_release(self):
        requests: list[httpx.Request] = []
        client = await _client_answering(V12_RESPONSE, requests)
        try:
            result = await client.version()
        finally:
            await client.api_client.close()
        self.assertEqual(result, V12_RESPONSE)
        self.assertEqual(result["release"], "supra_node_v12.0.0.rc7")
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].method, "GET")
        self.assertEqual(requests[0].url.path, "/rpc/v3/version")

    async def test_v11_response_has_no_release(self):
        requests: list[httpx.Request] = []
        client = await _client_answering(V11_RESPONSE, requests)
        try:
            result = await client.version()
        finally:
            await client.api_client.close()
        self.assertEqual(result, V11_RESPONSE)
        self.assertNotIn("release", result)
        self.assertEqual(requests[0].url.path, "/rpc/v3/version")


if __name__ == "__main__":
    unittest.main()
