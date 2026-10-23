# Copyright © Supra
# Parts of the project are originally copyright © Aptos Foundation
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import unittest

from supra_sdk import ed25519
from supra_sdk.account_address import AccountAddress
from supra_sdk.authenticator import AccountAuthenticator, SingleKeyAuthenticator
from supra_sdk.bcs import Deserializer, Serializer
from supra_sdk.transactions import (
    EntryFunction,
    RawTransaction,
    SignedTransaction,
    TransactionArgument,
    TransactionPayload,
)


class SingleKeyAuthenticatorTest(unittest.TestCase):
    def setUp(self):
        self.key = ed25519.PrivateKey.random()

    def test_fresh_signature_verifies(self):
        data = b"single key data"
        authenticator = SingleKeyAuthenticator(
            self.key.public_key(), self.key.sign(data)
        )
        self.assertTrue(authenticator.verify(data))

    def test_signature_over_other_data_does_not_verify(self):
        authenticator = SingleKeyAuthenticator(
            self.key.public_key(), self.key.sign(b"signed data")
        )
        self.assertFalse(authenticator.verify(b"other data"))

    def test_signed_transaction_verifies(self):
        sender = AccountAddress.from_key(self.key.public_key())
        payload = EntryFunction.natural(
            "0x1::coin",
            "transfer",
            [],
            [
                TransactionArgument(sender, Serializer.struct),
                TransactionArgument(1, Serializer.u64),
            ],
        )
        transaction = RawTransaction(
            sender, 0, TransactionPayload(payload), 2000, 0, 18446744073709551615, 4
        )
        authenticator = AccountAuthenticator(
            SingleKeyAuthenticator(
                self.key.public_key(), self.key.sign(transaction.keyed())
            )
        )
        signed = SignedTransaction(transaction, authenticator)
        self.assertTrue(signed.verify())

        decoded = SignedTransaction.deserialize(Deserializer(signed.bytes()))
        self.assertTrue(decoded.verify())

        other = SingleKeyAuthenticator(
            self.key.public_key(), self.key.sign(b"not the transaction")
        )
        self.assertFalse(
            SignedTransaction(transaction, AccountAuthenticator(other)).verify()
        )


if __name__ == "__main__":
    unittest.main()
