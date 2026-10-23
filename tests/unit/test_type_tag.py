# Copyright © Supra
# Parts of the project are originally copyright © Aptos Foundation
# SPDX-License-Identifier: Apache-2.0

"""Offline tests for type tag serialisation and parsing.

The expected bytes were produced by the TypeScript SDK's core library
(``supra-l1-sdk-core`` 2.0.1): ``TypeTagParser(s).parseTypeTag()`` serialised with
``BCS.bcsToBytes``. ``signer`` is not accepted by that parser, so its bytes come from
``new TxnBuilderTypes.TypeTagSigner()``. The variant numbering matches the ``TypeTag``
enum in ``language_storage.rs`` of the aptos-core fork (tag ``aptosvm-v1.16_supra-v1.8.17``).
"""

from __future__ import annotations

import unittest
import warnings

from supra_sdk.account_address import AccountAddress
from supra_sdk.bcs import Deserializer, Serializer
from supra_sdk.type_tag import (
    MAX_TYPE_TAG_NESTING,
    AccountAddressTag,
    BoolTag,
    SignerTag,
    StructTag,
    TypeTag,
    U8Tag,
    U16Tag,
    U32Tag,
    U64Tag,
    U128Tag,
    U256Tag,
    VectorTag,
)

ONE = "00" * 31 + "01"
TWO = "00" * 31 + "02"

# (canonical string, expected hex of the BCS bytes)
FIXTURES = [
    ("bool", "00"),
    ("u8", "01"),
    ("u16", "08"),
    ("u32", "09"),
    ("u64", "02"),
    ("u128", "03"),
    ("u256", "0a"),
    ("address", "04"),
    ("signer", "05"),
    ("vector<u8>", "0601"),
    ("vector<vector<u64>>", "060602"),
    (
        "0x1::option::Option<vector<u8>>",
        "07" + ONE + "066f7074696f6e" + "064f7074696f6e" + "01" + "0601",
    ),
    (
        "0x1::pair::Pair<u64, 0x1::string::String>",
        "07"
        + ONE
        + "0470616972"
        + "0450616972"
        + "02"
        + "02"
        + "07"
        + ONE
        + "06737472696e67"
        + "06537472696e67"
        + "00",
    ),
    (
        "0x1::supra_coin::SupraCoin",
        "07" + ONE + "0a73757072615f636f696e" + "095375707261436f696e" + "00",
    ),
    (
        "0x2::m::S<0x1::a::B<bool>, vector<address>, u256>",
        "07"
        + TWO
        + "016d"
        + "0153"
        + "03"
        + "07"
        + ONE
        + "0161"
        + "0142"
        + "01"
        + "00"
        + "0604"
        + "0a",
    ),
]


class TypeTagSerialisationTest(unittest.TestCase):
    def test_fixture_bytes(self):
        for text, expected in FIXTURES:
            with self.subTest(text):
                tag = TypeTag.from_str(text)
                self.assertEqual(tag.to_bytes().hex(), expected)

    def test_round_trip_through_bytes(self):
        for text, expected in FIXTURES:
            with self.subTest(text):
                tag = TypeTag.from_bytes(bytes.fromhex(expected))
                self.assertEqual(tag, TypeTag.from_str(text))
                self.assertEqual(tag.to_bytes().hex(), expected)

    def test_round_trip_through_string(self):
        for text, _ in FIXTURES:
            with self.subTest(text):
                self.assertEqual(str(TypeTag.from_str(text)), text)

    def test_constructed_tags_match_parsed(self):
        cases = [
            (BoolTag(), "bool"),
            (U8Tag(), "u8"),
            (U16Tag(), "u16"),
            (U32Tag(), "u32"),
            (U64Tag(), "u64"),
            (U128Tag(), "u128"),
            (U256Tag(), "u256"),
            (AccountAddressTag(), "address"),
            (SignerTag(), "signer"),
            (VectorTag(TypeTag(U8Tag())), "vector<u8>"),
            (VectorTag(U8Tag()), "vector<u8>"),
            (VectorTag(TypeTag(VectorTag(TypeTag(U64Tag())))), "vector<vector<u64>>"),
        ]
        for inner, text in cases:
            with self.subTest(text):
                tag = TypeTag(inner)
                self.assertEqual(tag, TypeTag.from_str(text))
                self.assertEqual(str(tag), text)
                self.assertEqual(tag.to_bytes(), TypeTag.from_str(text).to_bytes())

    def test_primitive_tag_ignores_legacy_value_argument(self):
        with self.assertWarns(DeprecationWarning):
            legacy = U64Tag(0)
        self.assertEqual(TypeTag(legacy).to_bytes().hex(), "02")
        with self.assertWarns(DeprecationWarning):
            self.assertEqual(TypeTag(U64Tag(12345)).to_bytes().hex(), "02")
        with self.assertWarns(DeprecationWarning):
            self.assertEqual(TypeTag(BoolTag(True)).to_bytes().hex(), "00")
        self.assertEqual(legacy, U64Tag())
        self.assertNotEqual(TypeTag(U64Tag()), TypeTag(U8Tag()))

    def test_primitive_tag_warning_says_the_value_is_ignored(self):
        with self.assertWarnsRegex(DeprecationWarning, "ignored"):
            SignerTag(1)

    def test_primitive_tag_without_value_does_not_warn(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            for tag in (BoolTag, U8Tag, U16Tag, U32Tag, U64Tag, U128Tag, U256Tag):
                tag()
            AccountAddressTag()
            SignerTag()
            TypeTag.from_str("vector<0x1::a::B<u8, address>>")

    def test_vector_tag_rejects_non_tags(self):
        for value in ("u8", "vector<u8>", 1, None, b"\x01", [U8Tag()], U8Tag):
            with self.subTest(repr(value)), self.assertRaises(TypeError):
                VectorTag(value)

    def test_vector_tag_accepts_every_tag_kind(self):
        struct = StructTag.from_str("0x1::a::B")
        self.assertEqual(VectorTag(struct), VectorTag(TypeTag(struct)))
        self.assertEqual(
            VectorTag(VectorTag(U8Tag())), VectorTag(TypeTag.from_str("vector<u8>"))
        )
        self.assertEqual(VectorTag(SignerTag()), VectorTag(TypeTag(SignerTag())))

    def test_hash_matches_equality(self):
        for text, _ in FIXTURES:
            with self.subTest(text):
                a = TypeTag.from_str(text)
                b = TypeTag.from_str(text)
                self.assertEqual(hash(a), hash(b))
                self.assertEqual(hash(a.value), hash(b.value))
        self.assertEqual(
            hash(TypeTag.from_str("0x1::a::B")),
            hash(TypeTag.from_str(f"0x{ONE}::a::B")),
        )
        self.assertEqual(hash(U64Tag()), hash(U64Tag()))
        self.assertEqual(
            len({TypeTag.from_str("vector<u8>"), TypeTag.from_str("vector< u8 >")}), 1
        )
        distinct = {
            TypeTag.from_str("vector<u8>"),
            TypeTag.from_str("vector<u16>"),
            TypeTag.from_str("u8"),
        }
        self.assertEqual(len(distinct), 3)
        self.assertIn(
            TypeTag.from_str("0x1::a::B<u8>"), {TypeTag.from_str("0x1::a::B<u8>")}
        )
        self.assertNotIn(
            TypeTag.from_str("0x1::a::B<u8>"), {TypeTag.from_str("0x1::a::B<u16>")}
        )

    def test_nesting_limit_in_the_parser(self):
        limit = MAX_TYPE_TAG_NESTING - 1
        self.assertEqual(limit, 8)
        TypeTag.from_str("vector<" * limit + "u8" + ">" * limit)
        with self.assertRaisesRegex(ValueError, "nesting"):
            TypeTag.from_str("vector<" * (limit + 1) + "u8" + ">" * (limit + 1))
        TypeTag.from_str("0x1::a::B<" * limit + "u8" + ">" * limit)
        with self.assertRaisesRegex(ValueError, "nesting"):
            TypeTag.from_str("0x1::a::B<" * (limit + 1) + "u8" + ">" * (limit + 1))
        mixed = "vector<0x1::a::B<" * 4 + "u8" + ">>" * 4
        TypeTag.from_str(mixed)
        with self.assertRaisesRegex(ValueError, "nesting"):
            TypeTag.from_str("vector<" + mixed + ">")

    def test_deep_input_raises_value_error_not_recursion_error(self):
        depth = 100_000
        with self.assertRaises(ValueError):
            TypeTag.from_str("vector<" * depth + "u8" + ">" * depth)
        with self.assertRaises(ValueError):
            TypeTag.from_str("vector<" * depth)
        with self.assertRaises(ValueError):
            TypeTag.from_bytes(bytes([TypeTag.VECTOR]) * depth + bytes([TypeTag.U8]))

    def test_nesting_limit_in_deserialisation(self):
        limit = MAX_TYPE_TAG_NESTING - 1
        ok = bytes([TypeTag.VECTOR]) * limit + bytes([TypeTag.U8])
        self.assertEqual(TypeTag.from_bytes(ok).to_bytes(), ok)
        with self.assertRaisesRegex(ValueError, "nesting"):
            TypeTag.from_bytes(bytes([TypeTag.VECTOR]) + ok)
        with self.assertRaisesRegex(ValueError, "nesting"):
            VectorTag.from_bytes(bytes([TypeTag.VECTOR]) + ok)
        struct_ok = TypeTag.from_str("0x1::a::B<" * limit + "u8" + ">" * limit)
        self.assertEqual(TypeTag.from_bytes(struct_ok.to_bytes()), struct_ok)
        too_deep = TypeTag(
            StructTag(AccountAddress.from_str("0x1"), "a", "B", [struct_ok])
        )
        with self.assertRaisesRegex(ValueError, "nesting"):
            TypeTag.from_bytes(too_deep.to_bytes())
        with self.assertRaisesRegex(ValueError, "nesting"):
            StructTag.from_bytes(too_deep.value.to_bytes())

    def test_identifiers_follow_the_move_rule(self):
        for text in ["0x1::_a::B", "0x1::a_::B_", "0x1::_1::_2", "0x1::A1_b::Z"]:
            with self.subTest(text):
                self.assertEqual(str(TypeTag.from_str(text)), text)
        for text in [
            "0x1::_::B",
            "0x1::a::_",
            "0x1::_::_",
            "0x1::1::B",
            "0x1::a::2",
            "0x1::1a::B",
        ]:
            with self.subTest(text), self.assertRaises(ValueError):
                TypeTag.from_str(text)

    def test_long_input_with_trailing_whitespace_parses(self):
        text = "vector<u8>" + " " * 50_000
        self.assertEqual(TypeTag.from_str(text), TypeTag.from_str("vector<u8>"))
        with self.assertRaises(ValueError):
            TypeTag.from_str("vector<u8>" + " " * 50_000 + "$")

    def test_trailing_comma_error_names_the_comma(self):
        for text in ["0x1::a::B<u8,>", "0x1::a::B<u8, >", "0x1::a::B<u8,u16,>"]:
            with (
                self.subTest(text),
                self.assertRaisesRegex(ValueError, "trailing comma"),
            ):
                TypeTag.from_str(text)

    def test_misplaced_punctuation_errors_name_the_token(self):
        for text, token in [
            ("0x1::a::B<,u8>", "','"),
            ("vector<>", "'>'"),
            ("<u8>", "'<'"),
            ("::", "'::'"),
        ]:
            with self.subTest(text):
                with self.assertRaises(ValueError) as caught:
                    TypeTag.from_str(text)
                message = str(caught.exception)
                self.assertIn(f"expected a type, found {token}", message)
                self.assertNotIn("invalid address", message)

    def test_primitive_tag_alone_serialises_to_nothing(self):
        self.assertEqual(U64Tag().to_bytes(), b"")
        self.assertEqual(U64Tag.from_bytes(b""), U64Tag())

    def test_struct_tag_accessors(self):
        tag = StructTag.from_str("0x1::option::Option<vector<u8>>")
        self.assertEqual(tag.address, AccountAddress.from_str("0x1"))
        self.assertEqual(tag.module, "option")
        self.assertEqual(tag.name, "Option")
        self.assertEqual(tag.type_args, [TypeTag.from_str("vector<u8>")])

    def test_struct_tag_from_str_rejects_non_structs(self):
        for text in ["u64", "vector<u8>", "signer"]:
            with self.subTest(text), self.assertRaises(ValueError):
                StructTag.from_str(text)

    def test_nested_structs(self):
        composite = "0x0::l0::L0<0x1::l10::L10<0x2::l20::L20>, 0x1::l11::L11>"
        derived = StructTag.from_str(composite)
        self.assertEqual(composite, f"{derived}")
        self.assertEqual(derived, StructTag.from_bytes(derived.to_bytes()))

    def test_whitespace_is_ignored(self):
        self.assertEqual(
            TypeTag.from_str(" vector < u8 > "), TypeTag.from_str("vector<u8>")
        )
        self.assertEqual(
            TypeTag.from_str("0x1::a::B<u8,u16>"),
            TypeTag.from_str("0x1::a::B< u8 , u16 >"),
        )

    def test_short_and_long_addresses_parse_equal(self):
        self.assertEqual(
            TypeTag.from_str("0x1::a::B"), TypeTag.from_str(f"0x{ONE}::a::B")
        )

    def test_within_a_sequence(self):
        serializer = Serializer()
        serializer.sequence(
            [TypeTag.from_str("u64"), TypeTag.from_str("vector<u8>")],
            Serializer.struct,
        )
        self.assertEqual(serializer.output().hex(), "02" + "02" + "0601")
        decoded = Deserializer(serializer.output()).sequence(TypeTag.deserialize)
        self.assertEqual(
            decoded, [TypeTag.from_str("u64"), TypeTag.from_str("vector<u8>")]
        )

    def test_parse_errors(self):
        cases = [
            "",
            "   ",
            "u7",
            "U64",
            "string",
            "vector",
            "vector<>",
            "vector<u8",
            "vector<u8>>",
            "vector<u8, u8>",
            "vector<vector<u8>",
            "u64<u8>",
            "u64 u8",
            "0x1::a::B<u8",
            "0x1::a::B<u8>>",
            "0x1::a::B<>",
            "0x1::a::B<u8,>",
            "0x1::a::B<,u8>",
            "0x1::a",
            "0x1::a::",
            "0x1::::B",
            "0x1::1a::B",
            "0xzz::a::B",
            "0x1::a::B::C",
            "0x1::a::B<u8>x",
            "<u8>",
            "u8,u8",
            "0x1::a::B$",
            "0x" + "1" * 65 + "::a::B",
        ]
        for text in cases:
            with self.subTest(text), self.assertRaises(ValueError):
                TypeTag.from_str(text)

    def test_deserialise_unknown_variant(self):
        with self.assertRaises(ValueError):
            TypeTag.from_bytes(bytes([0x0B]))


if __name__ == "__main__":
    unittest.main()
