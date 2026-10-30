# Copyright © Supra
# Parts of the project are originally copyright © Aptos Foundation
# SPDX-License-Identifier: Apache-2.0

"""Offline tests for ``ScriptArgument``.

The expected bytes were produced by the TypeScript SDK's core library
(``supra-l1-sdk-core`` 2.0.1): each ``TxnBuilderTypes.TransactionArgument*`` serialised
with ``BCS.Serializer``. The variant numbering matches the ``TransactionArgument`` enum
in ``move-core/types/src/transaction_argument.rs`` of the aptos-core fork (tag
``aptosvm-v1.16_supra-v1.8.17``).
"""

from __future__ import annotations

import unittest

from supra_sdk.account_address import AccountAddress
from supra_sdk.bcs import Deserializer, Serializer
from supra_sdk.transactions import ScriptArgument

# (variant, value, expected hex)
FIXTURES = [
    (ScriptArgument.U8, 255, "00ff"),
    (ScriptArgument.U64, 258, "010201000000000000"),
    (ScriptArgument.U128, 1 << 100, "0200000000000000000000000010000000"),
    (
        ScriptArgument.ADDRESS,
        AccountAddress.from_str_relaxed("0x1234"),
        "03" + "00" * 30 + "1234",
    ),
    (ScriptArgument.U8_VECTOR, b"\x01\xff", "040201ff"),
    (ScriptArgument.BOOL, True, "0501"),
    (ScriptArgument.U16, 513, "060102"),
    (ScriptArgument.U32, 67305985, "0701020304"),
    (
        ScriptArgument.U256,
        1 << 200,
        "08" + "00" * 25 + "01" + "00" * 6,
    ),
]


class ScriptArgumentTest(unittest.TestCase):
    def test_variant_numbers(self):
        self.assertEqual(
            [
                ScriptArgument.U8,
                ScriptArgument.U64,
                ScriptArgument.U128,
                ScriptArgument.ADDRESS,
                ScriptArgument.U8_VECTOR,
                ScriptArgument.BOOL,
                ScriptArgument.U16,
                ScriptArgument.U32,
                ScriptArgument.U256,
            ],
            list(range(9)),
        )

    def test_every_variant_is_constructible(self):
        for variant, value, _ in FIXTURES:
            with self.subTest(variant):
                self.assertEqual(ScriptArgument(variant, value).variant, variant)

    def test_out_of_range_variants_are_rejected(self):
        for variant in (-1, 9, 100):
            with self.subTest(variant), self.assertRaises(Exception):
                ScriptArgument(variant, 0)

    def test_serialised_bytes(self):
        for variant, value, expected in FIXTURES:
            with self.subTest(variant):
                serializer = Serializer()
                ScriptArgument(variant, value).serialize(serializer)
                self.assertEqual(serializer.output().hex(), expected)

    def test_round_trip(self):
        for variant, value, expected in FIXTURES:
            with self.subTest(variant):
                decoded = ScriptArgument.deserialize(
                    Deserializer(bytes.fromhex(expected))
                )
                self.assertEqual(decoded, ScriptArgument(variant, value))
                serializer = Serializer()
                decoded.serialize(serializer)
                self.assertEqual(serializer.output().hex(), expected)

    def test_deserialise_unknown_variant(self):
        with self.assertRaises(Exception):
            ScriptArgument.deserialize(Deserializer(bytes([9, 0])))


if __name__ == "__main__":
    unittest.main()
