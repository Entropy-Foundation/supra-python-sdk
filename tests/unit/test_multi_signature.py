# Copyright © Supra
# Parts of the project are originally copyright © Aptos Foundation
# SPDX-License-Identifier: Apache-2.0

"""Offline tests for multi-signature ordering, decoding and validation.

Run them also with `python -O` to show that no check depends on `assert`."""

from __future__ import annotations

import itertools
import unittest

from supra_sdk import asymmetric_crypto_wrapper as wrapper, ed25519
from supra_sdk.account_address import AccountAddress
from supra_sdk.authenticator import (
    AccountAuthenticator,
    Authenticator,
    MultiEd25519Authenticator,
    MultiKeyAuthenticator,
    SingleSenderAuthenticator,
)
from supra_sdk.bcs import Deserializer, Serializer
from supra_sdk.transactions import (
    EntryFunction,
    RawTransaction,
    SignedTransaction,
    TransactionArgument,
    TransactionPayload,
)
from supra_sdk.type_tag import StructTag, TypeTag

MESSAGE = b"multi-signature test message"

PRIVATE_KEYS = [
    ed25519.PrivateKey.from_str(
        "4e5e3be60f4bbd5e98d086d932f3ce779ff4b58da99bf9e5241ae1212a29e5fe"
    ),
    ed25519.PrivateKey.from_str(
        "1e70e49b78f976644e2c51754a2f049d3ff041869c669523ba95b172c7329901"
    ),
    ed25519.PrivateKey.from_str(
        "9bf49a6a0755f953811fce125f2683d50429c3bb49e074147e0089a52eae155f"
    ),
]


def serialized(value) -> bytes:
    serializer = Serializer()
    serializer.struct(value)
    return serializer.output()


def raw_transaction(sender: AccountAddress) -> RawTransaction:
    payload = EntryFunction.natural(
        "0x1::coin",
        "transfer",
        [TypeTag(StructTag.from_str("0x1::supra_coin::SupraCoin"))],
        [
            TransactionArgument(sender, Serializer.struct),
            TransactionArgument(5000, Serializer.u64),
        ],
    )
    return RawTransaction(
        sender,
        0,
        TransactionPayload(payload),
        2000,
        0,
        18446744073709551615,
        4,
    )


class MultiEd25519Test(unittest.TestCase):
    def setUp(self):
        self.keys = [key.public_key() for key in PRIVATE_KEYS]
        self.public_key = ed25519.MultiPublicKey(self.keys, 2)

    def sign(self, indexes, message=MESSAGE):
        return [(i, PRIVATE_KEYS[i].sign(message)) for i in indexes]

    def test_signature_order_does_not_matter(self):
        sorted_bytes = serialized(ed25519.MultiSignature(self.sign([0, 2])))
        for order in itertools.permutations([0, 2]):
            signature = ed25519.MultiSignature(self.sign(order))
            self.assertEqual(serialized(signature), sorted_bytes)
            self.assertTrue(self.public_key.verify(MESSAGE, signature))

        for order in itertools.permutations([0, 1, 2]):
            signature = ed25519.MultiSignature(self.sign(order))
            self.assertEqual(
                serialized(signature),
                serialized(ed25519.MultiSignature(self.sign([0, 1, 2]))),
            )
            self.assertTrue(self.public_key.verify(MESSAGE, signature))

    def test_from_key_map_order_does_not_matter(self):
        signatures = {i: PRIVATE_KEYS[i].sign(MESSAGE) for i in range(3)}
        in_order = ed25519.MultiSignature.from_key_map(
            self.public_key,
            [(self.keys[0], signatures[0]), (self.keys[2], signatures[2])],
        )
        reversed_ = ed25519.MultiSignature.from_key_map(
            self.public_key,
            [(self.keys[2], signatures[2]), (self.keys[0], signatures[0])],
        )
        self.assertEqual(serialized(in_order), serialized(reversed_))
        self.assertEqual(in_order, reversed_)
        self.assertTrue(self.public_key.verify(MESSAGE, reversed_))

    def test_wire_layout(self):
        signatures = self.sign([2, 0])
        expected = (
            signatures[1][1].data()
            + signatures[0][1].data()
            # Indexes 0 and 2, counted from the most significant bit.
            + bytes([0b1010_0000, 0, 0, 0])
        )
        encoded = serialized(ed25519.MultiSignature(signatures))
        # BCS byte-vector prefix: 2 * 64 + 4 = 132 = 0x84 0x01.
        self.assertEqual(encoded, bytes([0x84, 0x01]) + expected)
        decoded = Deserializer(encoded).struct(ed25519.MultiSignature)
        self.assertEqual([i for i, _ in decoded.signatures], [0, 2])
        self.assertTrue(self.public_key.verify(MESSAGE, decoded))

    def test_below_threshold_fails_verification(self):
        signature = ed25519.MultiSignature(self.sign([1]))
        self.assertFalse(self.public_key.verify(MESSAGE, signature))
        self.assertFalse(self.public_key.verify(MESSAGE, ed25519.MultiSignature([])))

    def test_wrong_signature_fails_verification(self):
        signature = ed25519.MultiSignature(self.sign([0, 1], b"another message"))
        self.assertFalse(self.public_key.verify(MESSAGE, signature))
        # A valid signature presented under another key's index.
        swapped = ed25519.MultiSignature(
            [(0, PRIVATE_KEYS[1].sign(MESSAGE)), (1, PRIVATE_KEYS[0].sign(MESSAGE))]
        )
        self.assertFalse(self.public_key.verify(MESSAGE, swapped))

    def test_index_beyond_keys_fails_verification(self):
        signature = ed25519.MultiSignature(
            [*self.sign([0, 1]), (3, PRIVATE_KEYS[0].sign(MESSAGE))]
        )
        self.assertFalse(self.public_key.verify(MESSAGE, signature))

    def test_wrong_signature_type_fails_verification(self):
        self.assertFalse(self.public_key.verify(MESSAGE, PRIVATE_KEYS[0].sign(MESSAGE)))

    def test_construction_checks_raise(self):
        with self.assertRaises(ValueError):
            ed25519.MultiPublicKey(self.keys, 0)
        with self.assertRaises(ValueError):
            ed25519.MultiPublicKey(self.keys, 4)
        with self.assertRaises(ValueError):
            ed25519.MultiPublicKey(self.keys[:1], 1)
        with self.assertRaises(ValueError):
            ed25519.MultiSignature([(32, PRIVATE_KEYS[0].sign(MESSAGE))])
        with self.assertRaises(ValueError):
            ed25519.MultiSignature([(-1, PRIVATE_KEYS[0].sign(MESSAGE))])
        with self.assertRaises(ValueError):
            ed25519.MultiSignature(
                [(1, PRIVATE_KEYS[0].sign(MESSAGE)), (1, PRIVATE_KEYS[1].sign(MESSAGE))]
            )

    def test_decoding_checks_raise(self):
        signature = PRIVATE_KEYS[0].sign(MESSAGE).data()
        for payload in (
            # No signatures.
            bytes(4),
            # Bitmap sets two bits for one signature.
            signature + bytes([0b1100_0000, 0, 0, 0]),
            # Bitmap sets no bits for one signature.
            signature + bytes(4),
            # Truncated bitmap.
            signature + bytes(3),
        ):
            serializer = Serializer()
            serializer.to_bytes(payload)
            with self.assertRaises(ValueError):
                Deserializer(serializer.output()).struct(ed25519.MultiSignature)

    def test_signed_transaction_round_trip(self):
        sender = AccountAddress.from_key(self.public_key)
        transaction = raw_transaction(sender)
        signature = ed25519.MultiSignature(
            [
                (2, PRIVATE_KEYS[2].sign(transaction.keyed())),
                (0, PRIVATE_KEYS[0].sign(transaction.keyed())),
            ]
        )
        account_authenticator = AccountAuthenticator(
            MultiEd25519Authenticator(self.public_key, signature)
        )
        signed = SignedTransaction(transaction, account_authenticator)
        self.assertTrue(signed.verify())

        encoded = signed.bytes()
        decoded = SignedTransaction.deserialize(Deserializer(encoded))
        self.assertEqual(decoded, signed)
        self.assertEqual(decoded.bytes(), encoded)
        self.assertTrue(decoded.verify())

    def test_account_authenticator_is_encoded_as_multi_ed25519(self):
        sender = AccountAddress.from_key(self.public_key)
        transaction = raw_transaction(sender)
        signature = ed25519.MultiSignature(
            [(i, PRIVATE_KEYS[i].sign(transaction.keyed())) for i in (0, 1)]
        )
        inner = MultiEd25519Authenticator(self.public_key, signature)
        via_account = SignedTransaction(transaction, AccountAuthenticator(inner))
        direct = SignedTransaction(transaction, Authenticator(inner))
        self.assertEqual(via_account.authenticator.variant, Authenticator.MULTI_ED25519)
        self.assertEqual(via_account.bytes(), direct.bytes())
        self.assertEqual(
            via_account.bytes(),
            serialized(transaction)
            + bytes([Authenticator.MULTI_ED25519])
            + serialized(inner),
        )


class MultiKeyTest(unittest.TestCase):
    def setUp(self):
        self.keys = [key.public_key() for key in PRIVATE_KEYS]
        self.public_key = wrapper.MultiPublicKey(self.keys, 2)

    def sign(self, indexes, message=MESSAGE):
        return [(i, PRIVATE_KEYS[i].sign(message)) for i in indexes]

    def test_signature_order_does_not_matter(self):
        sorted_bytes = serialized(wrapper.MultiSignature(self.sign([0, 2])))
        for order in itertools.permutations([0, 2]):
            signature = wrapper.MultiSignature(self.sign(order))
            self.assertEqual(serialized(signature), sorted_bytes)
            self.assertTrue(self.public_key.verify(MESSAGE, signature))

        for order in itertools.permutations([0, 1, 2]):
            signature = wrapper.MultiSignature(self.sign(order))
            self.assertEqual(
                serialized(signature),
                serialized(wrapper.MultiSignature(self.sign([0, 1, 2]))),
            )
            self.assertTrue(self.public_key.verify(MESSAGE, signature))

    def test_wire_layout_and_decoding(self):
        signatures = self.sign([2, 0])
        encoded = serialized(wrapper.MultiSignature(signatures))
        deserializer = Deserializer(encoded)
        decoded_signatures = deserializer.sequence(wrapper.Signature.deserialize)
        self.assertEqual(
            decoded_signatures,
            [wrapper.Signature(signatures[1][1]), wrapper.Signature(signatures[0][1])],
        )
        # Bitmap is a byte vector; indexes 0 and 2 from the most significant bit.
        self.assertEqual(deserializer.to_bytes(), bytes([0b1010_0000, 0, 0, 0]))
        self.assertEqual(deserializer.remaining(), 0)

        decoded = Deserializer(encoded).struct(wrapper.MultiSignature)
        self.assertEqual([i for i, _ in decoded.signatures], [0, 2])
        self.assertEqual(decoded, wrapper.MultiSignature(signatures))
        self.assertTrue(self.public_key.verify(MESSAGE, decoded))
        self.assertEqual(serialized(decoded), encoded)

    def test_decoding_a_shorter_bitmap_keeps_the_bytes(self):
        signatures = self.sign([0, 2])
        serializer = Serializer()
        serializer.sequence(
            [wrapper.Signature(s) for _, s in signatures], Serializer.struct
        )
        serializer.to_bytes(bytes([0b1010_0000]))
        encoded = serializer.output()

        decoded = Deserializer(encoded).struct(wrapper.MultiSignature)
        self.assertEqual([i for i, _ in decoded.signatures], [0, 2])
        self.assertEqual(serialized(decoded), encoded)

    def test_below_threshold_fails_verification(self):
        signature = wrapper.MultiSignature(self.sign([1]))
        self.assertFalse(self.public_key.verify(MESSAGE, signature))
        self.assertFalse(self.public_key.verify(MESSAGE, wrapper.MultiSignature([])))

    def test_wrong_signature_fails_verification(self):
        signature = wrapper.MultiSignature(self.sign([0, 1], b"another message"))
        self.assertFalse(self.public_key.verify(MESSAGE, signature))

    def test_index_beyond_keys_fails_verification(self):
        signature = wrapper.MultiSignature(
            [*self.sign([0, 1]), (5, PRIVATE_KEYS[0].sign(MESSAGE))]
        )
        self.assertFalse(self.public_key.verify(MESSAGE, signature))

    def test_construction_checks_raise(self):
        with self.assertRaises(ValueError):
            wrapper.MultiPublicKey(self.keys, 0)
        with self.assertRaises(ValueError):
            wrapper.MultiPublicKey(self.keys, 4)
        with self.assertRaises(ValueError):
            wrapper.MultiPublicKey(self.keys[:1], 1)
        with self.assertRaises(ValueError):
            wrapper.MultiSignature([(32, PRIVATE_KEYS[0].sign(MESSAGE))])
        with self.assertRaises(ValueError):
            wrapper.MultiSignature(
                [(1, PRIVATE_KEYS[0].sign(MESSAGE)), (1, PRIVATE_KEYS[1].sign(MESSAGE))]
            )

    def test_decoding_checks_raise(self):
        signature = wrapper.Signature(PRIVATE_KEYS[0].sign(MESSAGE))
        for bitmap in (bytes([0b1100_0000]), bytes(1), b""):
            serializer = Serializer()
            serializer.sequence([signature], Serializer.struct)
            serializer.to_bytes(bitmap)
            with self.assertRaises(ValueError):
                Deserializer(serializer.output()).struct(wrapper.MultiSignature)

    def test_signed_transaction_round_trip(self):
        sender = AccountAddress.from_key(self.public_key)
        transaction = raw_transaction(sender)
        signature = wrapper.MultiSignature(
            [
                (2, PRIVATE_KEYS[2].sign(transaction.keyed())),
                (1, PRIVATE_KEYS[1].sign(transaction.keyed())),
            ]
        )
        account_authenticator = AccountAuthenticator(
            MultiKeyAuthenticator(self.public_key, signature)
        )
        signed = SignedTransaction(transaction, account_authenticator)
        self.assertIsInstance(
            signed.authenticator.authenticator, SingleSenderAuthenticator
        )
        self.assertTrue(signed.verify())

        encoded = signed.bytes()
        decoded = SignedTransaction.deserialize(Deserializer(encoded))
        self.assertEqual(decoded, signed)
        self.assertEqual(decoded.bytes(), encoded)
        self.assertTrue(decoded.verify())


if __name__ == "__main__":
    unittest.main()
