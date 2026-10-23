# Copyright © Supra
# Parts of the project are originally copyright © Aptos Foundation
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import re
import typing
import warnings

from supra_sdk.account_address import AccountAddress
from supra_sdk.bcs import Deserializable, Deserializer, Serializable, Serializer

# The Move type-tag nesting limit: ``MAX_TYPE_TAG_NESTING`` (9) in
# ``third_party/move/move-core/types/src/safe_serialize.rs`` of the aptos-core fork
# (tag ``aptosvm-v1.16_supra-v1.8.17``), enforced by its ``parse_type_tag`` as
# ``depth >= MAX_TYPE_TAG_NESTING``. A type tag may nest ``vector`` and struct type
# arguments at most 8 levels deep; the same bound applies to parsing and to
# deserialisation here.
MAX_TYPE_TAG_NESTING = 9


def _check_depth(depth: int) -> None:
    if depth >= MAX_TYPE_TAG_NESTING:
        raise ValueError(
            f"Type tag nesting exceeds the Move type-tag nesting limit "
            f"({MAX_TYPE_TAG_NESTING})"
        )


class TypeTag(Deserializable, Serializable):
    """A Move type, as used for the type arguments of a transaction payload.

    The BCS encoding is the variant index followed by the variant's payload. Primitive
    types and ``signer`` have no payload, so ``u64`` encodes as the single byte ``02``.
    ``vector`` carries its element type and a struct carries a ``StructTag``.

    ``TypeTag.from_str`` parses the textual form, for example ``u64``,
    ``vector<vector<u8>>`` or ``0x1::option::Option<vector<u8>>``.
    """

    BOOL: int = 0
    U8: int = 1
    U64: int = 2
    U128: int = 3
    ACCOUNT_ADDRESS: int = 4
    SIGNER: int = 5
    VECTOR: int = 6
    STRUCT: int = 7
    U16: int = 8
    U32: int = 9
    U256: int = 10

    value: typing.Any

    def __init__(self, value: typing.Any):
        self.value = value

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TypeTag):
            return NotImplemented
        return (
            self.value.variant() == other.value.variant() and self.value == other.value
        )

    def __hash__(self) -> int:
        return hash((self.value.variant(), self.value))

    def __str__(self):
        return self.value.__str__()

    def __repr__(self):
        return self.__str__()

    @staticmethod
    def from_str(type_tag: str) -> TypeTag:
        """Parse a type such as ``u64``, ``vector<u8>`` or
        ``0x1::option::Option<vector<u8>>``.

        Raises ``ValueError`` if the string is not a well-formed type or nests deeper
        than the Move type-tag nesting limit (``MAX_TYPE_TAG_NESTING``).
        """
        return _TypeTagParser(type_tag).parse()

    @staticmethod
    def deserialize(deserializer: Deserializer) -> TypeTag:
        """Raises ``ValueError`` for an unknown variant or for nesting deeper than the
        Move type-tag nesting limit (``MAX_TYPE_TAG_NESTING``)."""
        return TypeTag._deserialize(deserializer, 0)

    @staticmethod
    def _deserialize(deserializer: Deserializer, depth: int) -> TypeTag:
        _check_depth(depth)
        variant = deserializer.uleb128()
        primitive = _PRIMITIVE_TAGS_BY_VARIANT.get(variant)
        if primitive is not None:
            return TypeTag(primitive.deserialize(deserializer))
        if variant == TypeTag.VECTOR:
            return TypeTag(VectorTag._deserialize(deserializer, depth))
        if variant == TypeTag.STRUCT:
            return TypeTag(StructTag._deserialize(deserializer, depth))
        raise ValueError(f"Unknown type tag variant {variant}")

    def serialize(self, serializer: Serializer):
        serializer.uleb128(self.value.variant())
        serializer.struct(self.value)


class _PrimitiveTag(Deserializable, Serializable):
    """Base of the type tags that have no payload.

    The constructor accepts, and ignores, one optional argument. Earlier versions
    stored a value in these classes and serialised it after the variant byte, which
    produced bytes the node rejects. Code that still writes ``U64Tag(0)`` keeps
    working and now gets the correct encoding; new code should write ``U64Tag()``.
    """

    VARIANT: typing.ClassVar[int]
    NAME: typing.ClassVar[str]

    def __init__(self, value: typing.Any = None):
        if value is not None:
            warnings.warn(
                f"{type(self).__name__}() takes no value; the value argument is "
                "ignored and will be removed",
                DeprecationWarning,
                stacklevel=2,
            )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _PrimitiveTag):
            return NotImplemented
        return type(self) is type(other)

    def __hash__(self) -> int:
        return hash(self.VARIANT)

    def __str__(self):
        return self.NAME

    def __repr__(self):
        return f"{type(self).__name__}()"

    def variant(self):
        return self.VARIANT

    @classmethod
    def deserialize(cls, _deserializer: Deserializer):
        return cls()

    def serialize(self, serializer: Serializer):
        pass


class BoolTag(_PrimitiveTag):
    VARIANT = TypeTag.BOOL
    NAME = "bool"


class U8Tag(_PrimitiveTag):
    VARIANT = TypeTag.U8
    NAME = "u8"


class U16Tag(_PrimitiveTag):
    VARIANT = TypeTag.U16
    NAME = "u16"


class U32Tag(_PrimitiveTag):
    VARIANT = TypeTag.U32
    NAME = "u32"


class U64Tag(_PrimitiveTag):
    VARIANT = TypeTag.U64
    NAME = "u64"


class U128Tag(_PrimitiveTag):
    VARIANT = TypeTag.U128
    NAME = "u128"


class U256Tag(_PrimitiveTag):
    VARIANT = TypeTag.U256
    NAME = "u256"


class AccountAddressTag(_PrimitiveTag):
    VARIANT = TypeTag.ACCOUNT_ADDRESS
    NAME = "address"


class SignerTag(_PrimitiveTag):
    VARIANT = TypeTag.SIGNER
    NAME = "signer"


_PRIMITIVE_TAGS: tuple[type[_PrimitiveTag], ...] = (
    BoolTag,
    U8Tag,
    U16Tag,
    U32Tag,
    U64Tag,
    U128Tag,
    U256Tag,
    AccountAddressTag,
    SignerTag,
)
_PRIMITIVE_TAGS_BY_VARIANT: dict[int, type[_PrimitiveTag]] = {
    tag.VARIANT: tag for tag in _PRIMITIVE_TAGS
}
_PRIMITIVE_TAGS_BY_NAME: dict[str, type[_PrimitiveTag]] = {
    tag.NAME: tag for tag in _PRIMITIVE_TAGS
}


class VectorTag(Deserializable, Serializable):
    """``vector<T>``. ``value`` is the element ``TypeTag``.

    The argument is a ``TypeTag`` or a bare tag (``U8Tag()``, ``StructTag(...)``,
    another ``VectorTag``), which is wrapped in a ``TypeTag``. Anything else, including
    a string, raises ``TypeError``; parse text explicitly with ``TypeTag.from_str``.
    """

    value: TypeTag

    def __init__(self, value: typing.Any):
        if isinstance(value, (_PrimitiveTag, VectorTag, StructTag)):
            value = TypeTag(value)
        elif not isinstance(value, TypeTag):
            raise TypeError(
                "VectorTag takes a TypeTag or a tag class instance, "
                f"not {type(value).__name__}"
            )
        self.value = value

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, VectorTag):
            return NotImplemented
        return self.value == other.value

    def __hash__(self) -> int:
        return hash((TypeTag.VECTOR, self.value))

    def __str__(self):
        return f"vector<{self.value}>"

    def __repr__(self):
        return self.__str__()

    def variant(self):
        return TypeTag.VECTOR

    @staticmethod
    def deserialize(deserializer: Deserializer) -> VectorTag:
        return VectorTag._deserialize(deserializer, 0)

    @staticmethod
    def _deserialize(deserializer: Deserializer, depth: int) -> VectorTag:
        return VectorTag(TypeTag._deserialize(deserializer, depth + 1))

    def serialize(self, serializer: Serializer):
        self.value.serialize(serializer)


class StructTag(Deserializable, Serializable):
    address: AccountAddress
    module: str
    name: str
    type_args: list[TypeTag]

    def __init__(self, address, module, name, type_args):
        self.address = address
        self.module = module
        self.name = name
        self.type_args = type_args

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, StructTag):
            return NotImplemented
        return (
            self.address == other.address
            and self.module == other.module
            and self.name == other.name
            and self.type_args == other.type_args
        )

    def __hash__(self) -> int:
        return hash(
            (self.address.address, self.module, self.name, tuple(self.type_args))
        )

    def __str__(self) -> str:
        value = f"{self.address}::{self.module}::{self.name}"
        if len(self.type_args) > 0:
            value += f"<{self.type_args[0]}"
            for type_arg in self.type_args[1:]:
                value += f", {type_arg}"
            value += ">"
        return value

    def __repr__(self) -> str:
        return self.__str__()

    @staticmethod
    def from_str(type_tag: str) -> StructTag:
        """Parse a struct such as ``0x1::option::Option<vector<u8>>``.

        Type arguments may be any type, nested up to the Move type-tag nesting limit.
        Raises ``ValueError`` if the string is malformed, nests deeper than that limit,
        or is not a struct.
        """
        parsed = TypeTag.from_str(type_tag).value
        if not isinstance(parsed, StructTag):
            raise ValueError(f"Not a struct type: {type_tag!r}")
        return parsed

    def variant(self):
        return TypeTag.STRUCT

    @staticmethod
    def deserialize(deserializer: Deserializer) -> StructTag:
        return StructTag._deserialize(deserializer, 0)

    @staticmethod
    def _deserialize(deserializer: Deserializer, depth: int) -> StructTag:
        address = deserializer.struct(AccountAddress)
        module = deserializer.str()
        name = deserializer.str()
        type_args = deserializer.sequence(lambda d: TypeTag._deserialize(d, depth + 1))
        return StructTag(address, module, name, type_args)

    def serialize(self, serializer: Serializer):
        self.address.serialize(serializer)
        serializer.str(self.module)
        serializer.str(self.name)
        serializer.sequence(self.type_args, Serializer.struct)


_TOKEN = re.compile(r"\s*(::|<|>|,|[A-Za-z0-9_]+)")
_TRAILING_WHITESPACE = re.compile(r"\s*\Z")
# The identifier rule of ``identifier.rs`` in move-core: a letter followed by letters,
# digits or underscores, or an underscore followed by at least one of those.
_IDENTIFIER = re.compile(r"(?:[A-Za-z][A-Za-z0-9_]*|_[A-Za-z0-9_]+)\Z")
_PUNCTUATION = ("::", "<", ">", ",")


class _TypeTagParser:
    """Recursive-descent parser for the textual form of a ``TypeTag``."""

    def __init__(self, text: str):
        self.text = text
        self.tokens: list[str] = []
        position = 0
        while not _TRAILING_WHITESPACE.match(text, position):
            match = _TOKEN.match(text, position)
            if match is None:
                raise self._error(f"unexpected character at offset {position}")
            self.tokens.append(match.group(1))
            position = match.end()
        self.index = 0

    def _error(self, message: str) -> ValueError:
        return ValueError(f"Invalid type tag {self.text!r}: {message}")

    def _peek(self) -> str | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def _next(self) -> str:
        token = self._peek()
        if token is None:
            raise self._error("unexpected end of input")
        self.index += 1
        return token

    def _expect(self, expected: str) -> None:
        token = self._next()
        if token != expected:
            raise self._error(f"expected {expected!r}, found {token!r}")

    def _identifier(self) -> str:
        token = self._next()
        if not _IDENTIFIER.match(token):
            raise self._error(f"expected an identifier, found {token!r}")
        return token

    def parse(self) -> TypeTag:
        tag = self._type(0)
        if self._peek() is not None:
            raise self._error(f"unexpected {self._peek()!r} after the type")
        return tag

    def _type(self, depth: int) -> TypeTag:
        if depth >= MAX_TYPE_TAG_NESTING:
            raise self._error(
                f"nesting exceeds the Move type-tag nesting limit ({MAX_TYPE_TAG_NESTING})"
            )
        token = self._next()
        if token in _PUNCTUATION:
            raise self._error(f"expected a type, found {token!r}")
        primitive = _PRIMITIVE_TAGS_BY_NAME.get(token)
        if primitive is not None:
            return TypeTag(primitive())
        if token == "vector":
            self._expect("<")
            inner = self._type(depth + 1)
            self._expect(">")
            return TypeTag(VectorTag(inner))
        return self._struct(token, depth)

    def _struct(self, address_token: str, depth: int) -> TypeTag:
        try:
            address = AccountAddress.from_str_relaxed(address_token)
        except (RuntimeError, ValueError):
            raise self._error(
                f"unknown type or invalid address {address_token!r}"
            ) from None
        self._expect("::")
        module = self._identifier()
        self._expect("::")
        name = self._identifier()
        type_args: list[TypeTag] = []
        if self._peek() == "<":
            self._next()
            type_args.append(self._type(depth + 1))
            while self._peek() == ",":
                self._next()
                if self._peek() == ">":
                    raise self._error("trailing comma in the type arguments")
                type_args.append(self._type(depth + 1))
            self._expect(">")
        return TypeTag(StructTag(address, module, name, type_args))
