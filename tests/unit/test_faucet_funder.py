# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import contextlib
import io
import unittest
from unittest import mock

from examples import faucet_funder
from supra_sdk.account_address import AccountAddress


class FakeClient:
    chain_id_value = 255

    def __init__(self, *_args: object, **_kwargs: object):
        self.closed = False

    async def chain_id(self) -> int:
        return self.chain_id_value

    async def close(self) -> None:
        self.closed = True


class MainnetClient(FakeClient):
    chain_id_value = 8


async def noisy_fund(_client: object, _address: AccountAddress) -> None:
    # The funding helper reports progress with print().
    print("The faucet answered TryLater; requesting again in 5 s")


class TestFaucetFunder(unittest.IsolatedAsyncioTestCase):
    async def test_stdout_is_one_key_line(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(faucet_funder, "SupraClient", FakeClient),
            mock.patch.object(faucet_funder, "_fund_from_faucet", noisy_fund),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            await faucet_funder.main()

        lines = stdout.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(stdout.getvalue().endswith("\n"))
        self.assertRegex(lines[0], r"^0x[0-9a-f]{64}$")
        self.assertIn("TryLater", stderr.getvalue())
        self.assertIn("Funding account: 0x", stderr.getvalue())
        self.assertNotIn(lines[0], stderr.getvalue())
        self.assertNotIn("TryLater", stdout.getvalue())

    async def test_refuses_mainnet(self):
        stdout = io.StringIO()
        fund = mock.AsyncMock()
        with (
            mock.patch.object(faucet_funder, "SupraClient", MainnetClient),
            mock.patch.object(faucet_funder, "_fund_from_faucet", fund),
            contextlib.redirect_stdout(stdout),
            self.assertRaisesRegex(RuntimeError, "Mainnet"),
        ):
            await faucet_funder.main()
        fund.assert_not_called()
        self.assertEqual(stdout.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
