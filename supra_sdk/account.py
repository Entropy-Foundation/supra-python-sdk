# Copyright © Supra
# Parts of the project are originally copyright © Aptos Foundation
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import contextlib
import json
import os
import tempfile

from supra_sdk import asymmetric_crypto, ed25519
from supra_sdk.account_address import AccountAddress
from supra_sdk.authenticator import AccountAuthenticator
from supra_sdk.bcs import Serializer
from supra_sdk.transactions import RawTransactionInternal


class Account:
    """Represents an account as well as the private, public key-pair for the Supra blockchain."""

    account_address: AccountAddress
    private_key: asymmetric_crypto.PrivateKey

    def __init__(
        self, account_address: AccountAddress, private_key: asymmetric_crypto.PrivateKey
    ):
        self.account_address = account_address
        self.private_key = private_key

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Account):
            return NotImplemented
        return (
            self.account_address == other.account_address
            and self.private_key == other.private_key
        )

    @staticmethod
    def generate() -> Account:
        private_key = ed25519.PrivateKey.random()
        account_address = AccountAddress.from_key(private_key.public_key())
        return Account(account_address, private_key)

    @staticmethod
    def load_key(key: str) -> Account:
        private_key = ed25519.PrivateKey.from_str(key)
        account_address = AccountAddress.from_key(private_key.public_key())
        return Account(account_address, private_key)

    @staticmethod
    def load(path: str) -> Account:
        with open(path) as file:
            data = json.load(file)
        return Account(
            AccountAddress.from_str_relaxed(data["account_address"]),
            ed25519.PrivateKey.from_str(data["private_key"]),
        )

    def store(self, path: str):
        """Writes the address and the private key to `path` as JSON.

        The private key is stored unencrypted. The file is created readable and
        writable only by its owner (mode 0600). An existing file at `path` is
        replaced, not modified in place, so the result is 0600 whatever the old
        file's mode or owner was. The replacement is atomic: the data is written
        to a temporary file in the same directory and renamed over `path`, so a
        crash or a full disk does not leave a partial or empty file, and a
        failed write leaves any existing file intact. On Windows the mode is not
        applied and the file inherits the directory's access control. Read the
        file back with `Account.load`.
        """
        data = {
            "account_address": str(self.account_address),
            "private_key": self.private_key.hex(),
        }
        directory = os.path.dirname(os.path.abspath(path))
        fd, temp_path = tempfile.mkstemp(
            dir=directory, prefix=".account-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w") as file:
                json.dump(data, file)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_path, path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temp_path)
            raise

    def address(self) -> AccountAddress:
        """Returns the address associated with the given account"""
        return self.account_address

    def auth_key(self) -> str:
        """Returns the auth_key for the associated account"""
        return str(AccountAddress.from_key(self.private_key.public_key()))

    def sign(self, data: bytes) -> asymmetric_crypto.Signature:
        return self.private_key.sign(data)

    def sign_simulated_transaction(
        self, transaction: RawTransactionInternal
    ) -> AccountAuthenticator:
        return transaction.sign_simulated(self.private_key.public_key())

    def sign_transaction(
        self, transaction: RawTransactionInternal
    ) -> AccountAuthenticator:
        return transaction.sign(self.private_key)

    def public_key(self) -> asymmetric_crypto.PublicKey:
        """Returns the public key for the associated account"""
        return self.private_key.public_key()


class RotationProofChallenge:
    type_info_account_address: AccountAddress = AccountAddress.from_str("0x1")
    type_info_module_name: str = "account"
    type_info_struct_name: str = "RotationProofChallenge"
    sequence_number: int
    originator: AccountAddress
    current_auth_key: AccountAddress
    new_public_key: asymmetric_crypto.PublicKey

    def __init__(
        self,
        sequence_number: int,
        originator: AccountAddress,
        current_auth_key: AccountAddress,
        new_public_key: asymmetric_crypto.PublicKey,
    ):
        self.sequence_number = sequence_number
        self.originator = originator
        self.current_auth_key = current_auth_key
        self.new_public_key = new_public_key

    def serialize(self, serializer: Serializer):
        self.type_info_account_address.serialize(serializer)
        serializer.str(self.type_info_module_name)
        serializer.str(self.type_info_struct_name)
        serializer.u64(self.sequence_number)
        self.originator.serialize(serializer)
        self.current_auth_key.serialize(serializer)
        serializer.struct(self.new_public_key)
