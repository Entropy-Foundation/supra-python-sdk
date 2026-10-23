# Copyright © Supra
# Parts of the project are originally copyright © Aptos Foundation
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import cast

from supra_sdk import asymmetric_crypto, ed25519
from supra_sdk.bcs import Deserializer, Serializer


class PublicKey(asymmetric_crypto.PublicKey):
    ED25519: int = 0

    variant: int
    public_key: asymmetric_crypto.PublicKey

    def __init__(self, public_key: asymmetric_crypto.PublicKey):
        if isinstance(public_key, ed25519.PublicKey):
            self.variant = PublicKey.ED25519
        else:
            raise NotImplementedError()
        self.public_key = public_key

    def __eq__(self, other: object):
        if not isinstance(other, PublicKey):
            return NotImplemented
        return self.variant == other.variant and self.public_key == other.public_key

    def __hash__(self) -> int:
        return hash(self.to_bytes())

    def to_crypto_bytes(self) -> bytes:
        serializer = Serializer()
        self.serialize(serializer)
        return serializer.output()

    def verify(self, data: bytes, signature: asymmetric_crypto.Signature) -> bool:
        # Convert signature to the original signature
        sig = cast(Signature, signature)

        return self.public_key.verify(data, sig.signature)

    @staticmethod
    def deserialize(deserializer: Deserializer) -> PublicKey:
        variant = deserializer.uleb128()

        if variant == PublicKey.ED25519:
            public_key: asymmetric_crypto.PublicKey = ed25519.PublicKey.deserialize(
                deserializer
            )
        else:
            raise ValueError(
                f"Unsupported public key type: variant {variant}; "
                "only Ed25519 is supported"
            )

        return PublicKey(public_key)

    def serialize(self, serializer: Serializer):
        serializer.uleb128(self.variant)
        serializer.struct(self.public_key)


class Signature(asymmetric_crypto.Signature):
    ED25519: int = 0

    variant: int
    signature: asymmetric_crypto.Signature

    def __init__(self, signature: asymmetric_crypto.Signature):
        if isinstance(signature, ed25519.Signature):
            self.variant = Signature.ED25519
        else:
            raise NotImplementedError()
        self.signature = signature

    def __eq__(self, other: object):
        if not isinstance(other, Signature):
            return NotImplemented
        return self.variant == other.variant and self.signature == other.signature

    def __hash__(self) -> int:
        return hash(self.to_bytes())

    def get_null_signature(self) -> Signature:
        if self.variant == Signature.ED25519:
            return Signature(ed25519.Signature.get_null_signature())
        else:
            raise NotImplementedError()

    @staticmethod
    def deserialize(deserializer: Deserializer) -> Signature:
        variant = deserializer.uleb128()

        if variant == Signature.ED25519:
            signature: asymmetric_crypto.Signature = ed25519.Signature.deserialize(
                deserializer
            )
        else:
            raise ValueError(
                f"Unsupported signature type: variant {variant}; "
                "only Ed25519 is supported"
            )

        return Signature(signature)

    def serialize(self, serializer: Serializer):
        serializer.uleb128(self.variant)
        serializer.struct(self.signature)


class MultiPublicKey(asymmetric_crypto.PublicKey):
    keys: list[PublicKey]
    threshold: int

    MIN_KEYS = 1
    MAX_KEYS = 32
    MIN_THRESHOLD = 1

    def __init__(self, keys: list[asymmetric_crypto.PublicKey], threshold: int):
        """Raises ValueError if the key count or the threshold is out of range."""
        if not self.MIN_KEYS <= len(keys) <= self.MAX_KEYS:
            raise ValueError(
                f"Must have between {self.MIN_KEYS} and {self.MAX_KEYS} keys."
            )
        if not self.MIN_THRESHOLD <= threshold <= len(keys):
            raise ValueError(
                f"Threshold must be between {self.MIN_THRESHOLD} and {len(keys)}."
            )

        # Ensure keys are wrapped
        self.keys = []
        for key in keys:
            if isinstance(key, PublicKey):
                self.keys.append(key)
            else:
                self.keys.append(PublicKey(key))

        self.threshold = threshold

    def __eq__(self, other: object):
        if not isinstance(other, MultiPublicKey):
            return NotImplemented
        return self.keys == other.keys and self.threshold == other.threshold

    def __hash__(self) -> int:
        return hash(self.to_bytes())

    def __str__(self) -> str:
        return f"{self.threshold}-of-{len(self.keys)} Multi key"

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
        deserializer = Deserializer(indata)
        return deserializer.struct(MultiPublicKey)

    def to_crypto_bytes(self) -> bytes:
        serializer = Serializer()
        serializer.struct(self)
        return serializer.output()

    @staticmethod
    def deserialize(deserializer: Deserializer) -> MultiPublicKey:
        keys = deserializer.sequence(PublicKey.deserialize)
        threshold = deserializer.u8()
        return MultiPublicKey(keys, threshold)

    def serialize(self, serializer: Serializer):
        serializer.sequence(self.keys, Serializer.struct)
        serializer.u8(self.threshold)


class MultiSignature(asymmetric_crypto.Signature):
    signatures: list[tuple[int, Signature]]
    BITMAP_NUM_OF_BYTES: int = 4

    bitmap_num_of_bytes: int

    # Largest bitmap the node accepts when decoding.
    MAX_BITMAP_NUM_OF_BYTES: int = 8192

    def __init__(
        self,
        signatures: list[tuple[int, asymmetric_crypto.Signature]],
        bitmap_num_of_bytes: int = BITMAP_NUM_OF_BYTES,
    ):
        """Signatures are (key index, signature) pairs in any order; they are kept
        sorted by key index, the order the node pairs them with bitmap bits.

        Raises ValueError for an empty list, an index outside the bitmap or a
        repeated index."""
        if not signatures:
            raise ValueError("at least one signature is required")
        if not 1 <= bitmap_num_of_bytes <= self.MAX_BITMAP_NUM_OF_BYTES:
            raise ValueError("bitmap length is invalid")
        self.bitmap_num_of_bytes = bitmap_num_of_bytes
        indexes = [index for index, _ in signatures]
        for index in indexes:
            if not 0 <= index < bitmap_num_of_bytes * 8:
                raise ValueError("bitmap value exceeds maximum value")
        if len(set(indexes)) != len(indexes):
            raise ValueError("duplicate signature index")
        self.signatures = []
        for index, signature in sorted(signatures, key=lambda entry: entry[0]):
            if isinstance(signature, Signature):
                self.signatures.append((index, signature))
            else:
                self.signatures.append((index, Signature(signature)))

    def __eq__(self, other: object):
        if not isinstance(other, MultiSignature):
            return NotImplemented
        return (
            self.signatures == other.signatures
            and self.bitmap_num_of_bytes == other.bitmap_num_of_bytes
        )

    def __hash__(self) -> int:
        return hash(self.to_bytes())

    def __str__(self) -> str:
        return f"{self.signatures}"

    @staticmethod
    def deserialize(deserializer: Deserializer) -> MultiSignature:
        """Reads the signatures and the bitmap, which is a byte vector whose bits
        are numbered from the most significant bit of its first byte.

        The bitmap length is kept so that re-serialising reproduces the bytes.
        Raises ValueError if the bitmap does not match the number of signatures."""
        signatures = deserializer.sequence(Signature.deserialize)
        bitmap = deserializer.to_bytes()
        if not 1 <= len(bitmap) <= MultiSignature.MAX_BITMAP_NUM_OF_BYTES:
            raise ValueError("bitmap length is invalid")
        positions = [
            position
            for position in range(len(bitmap) * 8)
            if bitmap[position // 8] & (128 >> (position % 8))
        ]
        if len(positions) != len(signatures):
            raise ValueError("bitmap does not match the number of signatures")
        return MultiSignature(
            list(zip(positions, signatures, strict=True)), len(bitmap)
        )

    def serialize(self, serializer: Serializer):
        actual_sigs = []
        bitmap = bytearray(self.bitmap_num_of_bytes)

        for i, signature in sorted(self.signatures, key=lambda entry: entry[0]):
            bitmap[i // 8] |= 128 >> (i % 8)
            actual_sigs.append(signature)

        serializer.sequence(actual_sigs, Serializer.struct)
        serializer.to_bytes(bytes(bitmap))

    def unset_signatures(self):
        for i, (pubkey_index, signature) in enumerate(self.signatures):
            self.signatures[i] = (pubkey_index, signature.get_null_signature())
