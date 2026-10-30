# Copyright © Supra
# Parts of the project are originally copyright © Aptos Foundation
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import cast

from nacl.signing import SigningKey, VerifyKey

from supra_sdk import asymmetric_crypto
from supra_sdk.bcs import Deserializer, Serializer


class PrivateKey(asymmetric_crypto.PrivateKey):
    LENGTH: int = 32

    key: SigningKey

    def __init__(self, key: SigningKey):
        self.key = key

    def __eq__(self, other: object):
        if not isinstance(other, PrivateKey):
            return NotImplemented
        return self.key == other.key

    def __str__(self) -> str:
        """Returns a redacted form that identifies the key by its public key.

        The private key is never part of `str()`, `repr()`, f-strings or log
        output. Use `hex()` to export it explicitly.
        """
        return f"PrivateKey(public_key={self.public_key()})"

    def __repr__(self) -> str:
        return self.__str__()

    @staticmethod
    def from_str(value: str) -> PrivateKey:
        if value[0:2] == "0x":
            value = value[2:]
        return PrivateKey(SigningKey(bytes.fromhex(value)))

    def hex(self) -> str:
        """Returns the private key as 0x-prefixed hex. This is the explicit export of the secret."""
        return f"0x{self.key.encode().hex()}"

    def public_key(self) -> PublicKey:
        return PublicKey(self.key.verify_key)

    @staticmethod
    def random() -> PrivateKey:
        return PrivateKey(SigningKey.generate())

    def sign(self, data: bytes) -> Signature:
        return Signature(self.key.sign(data).signature)

    @staticmethod
    def deserialize(deserializer: Deserializer) -> PrivateKey:
        key = deserializer.to_bytes()
        if len(key) != PrivateKey.LENGTH:
            raise Exception("Length mismatch")

        return PrivateKey(SigningKey(key))

    def serialize(self, serializer: Serializer):
        serializer.to_bytes(self.key.encode())


class PublicKey(asymmetric_crypto.PublicKey):
    LENGTH: int = 32

    key: VerifyKey

    def __init__(self, key: VerifyKey):
        self.key = key

    def __eq__(self, other: object):
        if not isinstance(other, PublicKey):
            return NotImplemented
        return self.key == other.key

    def __str__(self) -> str:
        return f"0x{self.key.encode().hex()}"

    def verify(self, data: bytes, signature: asymmetric_crypto.Signature) -> bool:
        try:
            signature = cast(Signature, signature)
            self.key.verify(data, signature.data())
        except Exception:
            return False
        return True

    def to_crypto_bytes(self) -> bytes:
        return self.key.encode()

    @staticmethod
    def deserialize(deserializer: Deserializer) -> PublicKey:
        key = deserializer.to_bytes()
        if len(key) != PublicKey.LENGTH:
            raise ValueError("Length mismatch")

        return PublicKey(VerifyKey(key))

    def serialize(self, serializer: Serializer):
        serializer.to_bytes(self.key.encode())


class MultiPublicKey(asymmetric_crypto.PublicKey):
    keys: list[PublicKey]
    threshold: int

    MIN_KEYS = 1
    MAX_KEYS = 32
    MIN_THRESHOLD = 1

    def __init__(self, keys: list[PublicKey], threshold: int):
        """Raises ValueError if the key count or the threshold is out of range."""
        if not self.MIN_KEYS <= len(keys) <= self.MAX_KEYS:
            raise ValueError(
                f"Must have between {self.MIN_KEYS} and {self.MAX_KEYS} keys."
            )
        if not self.MIN_THRESHOLD <= threshold <= len(keys):
            raise ValueError(
                f"Threshold must be between {self.MIN_THRESHOLD} and {len(keys)}."
            )

        self.keys = keys
        self.threshold = threshold

    def __eq__(self, other: object):
        if not isinstance(other, MultiPublicKey):
            return NotImplemented
        return self.keys == other.keys and self.threshold == other.threshold

    def __hash__(self) -> int:
        return hash(bytes(self.to_crypto_bytes()))

    def __str__(self) -> str:
        return f"{self.threshold}-of-{len(self.keys)} Multi-Ed25519 public key"

    def verify(self, data: bytes, signature: asymmetric_crypto.Signature) -> bool:
        """Returns True only if the signature set meets the threshold and every
        signature verifies against the key at its index."""
        if not isinstance(signature, MultiSignature):
            return False
        if len(signature.signatures) < self.threshold:
            return False
        for idx, sig in signature.signatures:
            if idx >= len(self.keys):
                return False
            if not self.keys[idx].verify(data, sig):
                return False
        return True

    @staticmethod
    def from_crypto_bytes(indata: bytes) -> MultiPublicKey:
        if len(indata) % PublicKey.LENGTH != 1:
            raise ValueError("MultiPublicKey length is invalid")
        total_keys = len(indata) // PublicKey.LENGTH
        keys: list[PublicKey] = []
        for idx in range(total_keys):
            start = idx * PublicKey.LENGTH
            end = (idx + 1) * PublicKey.LENGTH
            keys.append(PublicKey(VerifyKey(indata[start:end])))
        threshold = indata[-1]
        return MultiPublicKey(keys, threshold)

    def to_crypto_bytes(self) -> bytes:
        key_bytes = bytearray()
        for key in self.keys:
            key_bytes.extend(key.to_crypto_bytes())
        key_bytes.append(self.threshold)
        return key_bytes  # type: ignore[return-value]  # returns a bytearray

    @staticmethod
    def deserialize(deserializer: Deserializer) -> MultiPublicKey:
        indata = deserializer.to_bytes()
        return MultiPublicKey.from_crypto_bytes(indata)

    def serialize(self, serializer: Serializer):
        serializer.to_bytes(self.to_crypto_bytes())


class Signature(asymmetric_crypto.Signature):
    LENGTH: int = 64

    signature: bytes

    def __init__(self, signature: bytes):
        self.signature = signature

    def __eq__(self, other: object):
        if not isinstance(other, Signature):
            return NotImplemented
        return self.signature == other.signature

    def __str__(self) -> str:
        return f"0x{self.signature.hex()}"

    @staticmethod
    def get_null_signature() -> Signature:
        return Signature(bytes(Signature.LENGTH))

    def data(self) -> bytes:
        return self.signature

    @staticmethod
    def deserialize(deserializer: Deserializer) -> Signature:
        signature = deserializer.to_bytes()
        if len(signature) != Signature.LENGTH:
            raise ValueError("Length mismatch")

        return Signature(signature)

    def serialize(self, serializer: Serializer):
        serializer.to_bytes(self.signature)


class MultiSignature(asymmetric_crypto.Signature):
    signatures: list[tuple[int, Signature]]
    BITMAP_NUM_OF_BYTES: int = 4

    def __init__(self, signatures: list[tuple[int, Signature]]):
        """Signatures are (key index, signature) pairs in any order; they are kept
        sorted by key index, the order the node pairs them with bitmap bits.

        Raises ValueError for an empty list, an index outside the bitmap or a
        repeated index."""
        if not signatures:
            raise ValueError("at least one signature is required")
        indexes = [index for index, _ in signatures]
        for index in indexes:
            if not 0 <= index < self.BITMAP_NUM_OF_BYTES * 8:
                raise ValueError("bitmap value exceeds maximum value")
        if len(set(indexes)) != len(indexes):
            raise ValueError("duplicate signature index")
        self.signatures = sorted(signatures, key=lambda entry: entry[0])

    def __eq__(self, other: object):
        if not isinstance(other, MultiSignature):
            return NotImplemented
        return self.signatures == other.signatures

    def __hash__(self) -> int:
        return hash(self.to_bytes())

    def __str__(self) -> str:
        return f"{self.signatures}"

    @staticmethod
    def from_key_map(
        public_key: MultiPublicKey,
        signatures_map: list[tuple[PublicKey, Signature]],
    ) -> MultiSignature:
        """Builds a signature from (public key, signature) pairs given in any order.

        Raises ValueError if a public key is not one of the multi-key's keys."""
        signatures = []

        for entry in signatures_map:
            try:
                index = public_key.keys.index(entry[0])
            except ValueError:
                raise ValueError("public key is not part of the multi-key") from None
            signatures.append((index, entry[1]))
        return MultiSignature(signatures)

    @staticmethod
    def deserialize(deserializer: Deserializer) -> MultiSignature:
        """Raises ValueError if the length or the bitmap is inconsistent."""
        signature_bytes = deserializer.to_bytes()
        count, remainder = divmod(len(signature_bytes), Signature.LENGTH)
        if (
            remainder != MultiSignature.BITMAP_NUM_OF_BYTES
            or count == 0
            or count > MultiPublicKey.MAX_KEYS
        ):
            raise ValueError("MultiSignature length is invalid")

        bitmap = int.from_bytes(
            signature_bytes[-MultiSignature.BITMAP_NUM_OF_BYTES :], "big"
        )
        positions = [
            position
            for position in range(MultiSignature.BITMAP_NUM_OF_BYTES * 8)
            if bitmap & (1 << (31 - position))
        ]
        if len(positions) != count:
            raise ValueError(
                "MultiSignature bitmap does not match the number of signatures"
            )

        signatures = []
        for current, position in enumerate(positions):
            left = current * Signature.LENGTH
            signature = Signature(signature_bytes[left : left + Signature.LENGTH])
            signatures.append((position, signature))

        return MultiSignature(signatures)

    def serialize(self, serializer: Serializer):
        signature_bytes = bytearray()
        bitmap = 0

        for index, signature in sorted(self.signatures, key=lambda entry: entry[0]):
            bitmap = bitmap | (1 << (31 - index))
            signature_bytes.extend(signature.data())

        signature_bytes.extend(
            bitmap.to_bytes(MultiSignature.BITMAP_NUM_OF_BYTES, "big")
        )
        serializer.to_bytes(signature_bytes)  # type: ignore[arg-type]  # bytearray

    def unset_signatures(self):
        null_signature = Signature.get_null_signature()
        for i, (pubkey_index, _signature) in enumerate(self.signatures):
            self.signatures[i] = (pubkey_index, null_signature)
