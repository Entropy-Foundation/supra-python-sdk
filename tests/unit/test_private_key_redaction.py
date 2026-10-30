# Copyright © Supra
# Parts of the project are originally copyright © Aptos Foundation
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
import unittest
from unittest import mock

from supra_sdk.account import Account
from supra_sdk.ed25519 import PrivateKey


class TestPrivateKeyRedaction(unittest.TestCase):
    def setUp(self):
        self.key = PrivateKey.random()
        self.raw_hex = self.key.key.encode().hex()
        self.raw_bytes = self.key.key.encode()

    def assert_redacted(self, text: str):
        self.assertNotIn(self.raw_hex, text.lower())
        self.assertNotIn(repr(self.raw_bytes), text)
        self.assertNotIn(self.raw_bytes.decode("latin-1"), text)

    def test_str_repr_format(self):
        self.assert_redacted(str(self.key))
        self.assert_redacted(repr(self.key))
        self.assert_redacted(f"{self.key}")
        self.assert_redacted("%s" % self.key)  # noqa: UP031
        self.assert_redacted("%r" % self.key)  # noqa: UP031
        self.assertIn(str(self.key.public_key()), str(self.key))

    def test_logging(self):
        class Capture(logging.Handler):
            def __init__(self):
                super().__init__()
                self.lines: list[str] = []

            def emit(self, record: logging.LogRecord):
                self.lines.append(self.format(record))

        handler = Capture()
        logger = logging.getLogger("test_private_key_redaction")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        try:
            logger.info("key: %s", self.key)
            logger.info("account: %s", Account(Account.generate().address(), self.key))
        finally:
            logger.removeHandler(handler)
        self.assertEqual(len(handler.lines), 2)
        for line in handler.lines:
            self.assert_redacted(line)

    def test_hex_exports_key(self):
        self.assertEqual(self.key.hex(), f"0x{self.raw_hex}")
        self.assertEqual(PrivateKey.from_str(self.key.hex()), self.key)


@unittest.skipUnless(hasattr(os, "fchmod"), "POSIX file modes only")
class TestAccountStorePermissions(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "account.json")

    def mode(self) -> int:
        return stat.S_IMODE(os.stat(self.path).st_mode)

    def test_new_file_is_owner_only_with_open_umask(self):
        old = os.umask(0)
        try:
            account = Account.generate()
            account.store(self.path)
        finally:
            os.umask(old)
        self.assertEqual(self.mode(), 0o600)
        self.assertEqual(Account.load(self.path), account)

    def test_existing_wide_file_is_tightened(self):
        with open(self.path, "w") as file:
            file.write("old contents that are longer than the new ones" * 100)
        os.chmod(self.path, 0o644)
        account = Account.generate()
        account.store(self.path)
        self.assertEqual(self.mode(), 0o600)
        self.assertEqual(Account.load(self.path), account)
        with open(self.path) as file:
            data = json.load(file)
        self.assertEqual(data["private_key"], account.private_key.hex())

    def test_failed_write_keeps_old_file_and_leaves_no_temp_file(self):
        old = Account.generate()
        old.store(self.path)
        with open(self.path) as file:
            before = file.read()
        with (
            mock.patch("supra_sdk.account.json.dump", side_effect=OSError("disk full")),
            self.assertRaises(OSError),
        ):
            Account.generate().store(self.path)
        with open(self.path) as file:
            self.assertEqual(file.read(), before)
        self.assertEqual(os.listdir(self.dir.name), ["account.json"])
        self.assertEqual(Account.load(self.path), old)


if __name__ == "__main__":
    unittest.main()
