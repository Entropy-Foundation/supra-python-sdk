# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

import asyncio
import copy
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from supra_sdk.account import Account
from supra_sdk.account_address import AccountAddress
from supra_sdk.authenticator import (
    Authenticator,
    FeePayerAuthenticator,
    MultiAgentAuthenticator,
)
from supra_sdk.bcs import Serializer
from supra_sdk.clients import ApiClient, ApiClientConfig
from supra_sdk.clients.api_client import ApiError
from supra_sdk.clients.rest.account import AccountRestClient
from supra_sdk.clients.rest.block import BlockRestClient
from supra_sdk.clients.rest.consensus import ConsensusRestClient
from supra_sdk.clients.rest.faucet import FaucetRestClient
from supra_sdk.clients.rest.general import GeneralRestClient
from supra_sdk.clients.rest.transaction import TransactionRestClient
from supra_sdk.clients.rest.transaction_defaults import (
    DEFAULT_MAX_TRANSACTION_TTL_SECONDS,
    FALLBACK_MAX_GAS_AMOUNT,
    MaxGasEstimationError,
    affordable_gas_amount,
    default_expiration_timestamp,
    is_sequence_number_too_new,
    max_gas_from_simulation,
)
from supra_sdk.fungible_asset import (
    FUNGIBLE_ASSET_METADATA_TYPE,
    SUPRA_FA_METADATA_ADDRESS,
    to_account_address,
)
from supra_sdk.transactions import (
    AutomationRegistrationParams,
    AutomationTaskType,
    EntryFunction,
    FeePayerRawTransaction,
    MultiAgentRawTransaction,
    RawTransaction,
    SignedTransaction,
    SupraTransaction,
    TransactionArgument,
    TransactionPayload,
)
from supra_sdk.type_tag import StructTag, TypeTag

_MAX_TTL_KEY = "max_transaction_time_to_live_seconds"


@dataclass
class TransactionConfig:
    """Configuration options for transaction payload generation and polling.

    This dataclass defines default parameters that are used in transaction payload generation and polling operation.
    It is intended to be passed into functions of the `SupraClient` that involves transaction payload generation and
    submission.

    Attributes:
        expiration_ttl (int | None): Time-to-live, in seconds, before a transaction expires and is rejected by the
            network, counted from the client's clock. An integer is used as given, even if it exceeds the node's
            maximum (the node then refuses the transaction). `None` (the default) expires the transaction
            `max_transaction_time_to_live_seconds - 5` seconds after the client's clock, where the maximum is read
            once per client from `rpc/v3/transactions/parameters` (600 on every network; 600 is also used, without
            caching, when the node answers 404 or omits the value). The node refuses a
            transaction that expires after its own clock plus the maximum, so the 5-second margin lets the node's
            clock be up to 5 seconds behind the client's.
        gas_unit_price (int): Price per unit of gas used to execute the transaction. Defaults to
            `min_configured_gas_price` obtained from `rpc/v3/transactions/estimate_gas_price` endpoint.
        max_gas_amount (int | None): Maximum number of gas units allowed per transaction. An integer is used as
            given. `None` (the default) estimates it for each transaction by simulation: the gas used times 1.5, at
            least 1,500 units and at most what the sender's SUPRA balance pays for at the gas unit price. The node
            accepts a transaction only if the balance covers `max_gas_amount * gas_unit_price`, and the estimate
            raises `MaxGasEstimationError` when the balance cannot pay for the simulation or the simulation does not
            succeed. Set an integer to skip the simulation.
        transaction_wait_time_in_seconds (float): Seconds to wait for a transaction to be final before timing out.
            Defaults to 20.
        polling_wait_time_in_seconds (float): Delay, in seconds, between successive polling attempts when waiting for
            transaction confirmation. Defaults to 1.
        wait_for_transaction (bool): Whether to wait for the transaction to be final after submission. When enabled,
            `SupraClient.submit_transaction` and the helpers built on it raise `TransactionFailedError` unless the
            transaction succeeded. When disabled they return the hash right after submission and do not check the
            outcome. Defaults to True.

    """

    expiration_ttl: int | None = None
    gas_unit_price: int | None = None
    max_gas_amount: int | None = None
    transaction_wait_time_in_seconds: float = 20
    polling_wait_time_in_seconds: float = 1
    wait_for_transaction: bool = True


@dataclass
class SupraClientConfig(TransactionConfig, ApiClientConfig):
    """Configuration for the Supra client.

    This dataclass inherits from both `TransactionConfig` and `ApiClientConfig`, allowing a single object to hold both
    transaction-related parameters and API client connection settings.
    """


def _single_signer(
    sender: Account,
) -> Callable[[RawTransaction], SignedTransaction]:
    def sign(raw_transaction: RawTransaction) -> SignedTransaction:
        return SignedTransaction(
            raw_transaction, sender.sign_transaction(raw_transaction)
        )

    return sign


def _multi_agent_signer(
    sender: Account, secondary_accounts: list[Account]
) -> Callable[[RawTransaction], SignedTransaction]:
    def sign(raw_transaction: RawTransaction) -> SignedTransaction:
        multi_agent_raw_transaction = MultiAgentRawTransaction(
            raw_transaction, [x.address() for x in secondary_accounts]
        )
        authenticator = Authenticator(
            MultiAgentAuthenticator(
                sender.sign_transaction(multi_agent_raw_transaction),
                [
                    (x.address(), x.sign_transaction(multi_agent_raw_transaction))
                    for x in secondary_accounts
                ],
            )
        )
        return SignedTransaction(multi_agent_raw_transaction.inner(), authenticator)

    return sign


def _fee_payer_signer(
    sender: Account, fee_payer: Account, secondary_accounts: list[Account]
) -> Callable[[RawTransaction], SignedTransaction]:
    def sign(raw_transaction: RawTransaction) -> SignedTransaction:
        fee_payer_raw_transaction = FeePayerRawTransaction(
            raw_transaction,
            [x.address() for x in secondary_accounts],
            fee_payer.address(),
        )
        authenticator = Authenticator(
            FeePayerAuthenticator(
                sender.sign_transaction(fee_payer_raw_transaction),
                [
                    (x.address(), x.sign_transaction(fee_payer_raw_transaction))
                    for x in secondary_accounts
                ],
                (
                    fee_payer.address(),
                    fee_payer.sign_transaction(fee_payer_raw_transaction),
                ),
            )
        )
        return SignedTransaction(fee_payer_raw_transaction.inner(), authenticator)

    return sign


class SupraClient(
    AccountRestClient,
    TransactionRestClient,
    BlockRestClient,
    ConsensusRestClient,
    FaucetRestClient,
    GeneralRestClient,
):
    """Unified client for interacting with all Supra REST API endpoints, as well as generating and submitting
    transaction payloads in a seamless manner.

    This class acts as a single entry point for developers, combining multiple specialized REST clients into one unified
    interface. With `SupraClient`, you can access account information, submit and query transactions, retrieve block
    data, inspect consensus status, request testnet funds from the faucet, and query other general network information —
    all from a single client instance.

    In addition to REST API access, `SupraClient` provides a convenient set of methods for constructing various types of
    transaction payloads and handling transaction submission. This significantly simplifies the end-to-end process of
    building, signing, and submitting transactions to the Supra network.

    Attributes:
        _chain_id (int | None): The chain-id of the network.
        api_client (supra_sdk.clients.api_client.ApiClient): Inherited from `RestClient`. Used to send HTTP requests to
            the Supra RPC node.

    """

    _chain_id: int | None
    _transaction_parameters: dict[str, Any] | None
    transaction_config: TransactionConfig

    def __init__(
        self, base_url: str, supra_client_config: SupraClientConfig | None = None
    ):
        """Initializes the REST client.

        Args:
            base_url (str): The base URL of the API.
            supra_client_config (SupraClientConfig): Configuration options for requests.

        """
        self._chain_id = None
        self._transaction_parameters = None
        self._transaction_parameters_lock = asyncio.Lock()
        supra_client_config = supra_client_config or SupraClientConfig()

        transaction_config = TransactionConfig(
            expiration_ttl=supra_client_config.expiration_ttl,
            gas_unit_price=supra_client_config.gas_unit_price,
            max_gas_amount=supra_client_config.max_gas_amount,
            transaction_wait_time_in_seconds=supra_client_config.transaction_wait_time_in_seconds,
            polling_wait_time_in_seconds=supra_client_config.polling_wait_time_in_seconds,
            wait_for_transaction=supra_client_config.wait_for_transaction,
        )
        self.transaction_config = transaction_config

        api_client_config = ApiClientConfig(
            http2=supra_client_config.http2,
            access_token=supra_client_config.access_token,
        )
        super().__init__(ApiClient(base_url, api_client_config))

    async def close(self):
        """Closes the HTTP client session."""
        await self.api_client.close()

    async def chain_id(self):
        """Provides the network Chain-ID.

        Returns:
            int: Network Chain-ID.

        """
        if not self._chain_id:
            self._chain_id = await self.network_chain_id()
        return self._chain_id

    async def max_transaction_time_to_live(self) -> int:
        """Provides the node's maximum transaction time-to-live in seconds.

        The value (`max_transaction_time_to_live_seconds` of `rpc/v3/transactions/parameters`) is read from the node
        once per client and cached. A node that has no such endpoint (404) or an answer without the key gets
        `DEFAULT_MAX_TRANSACTION_TTL_SECONDS` (600, the maximum on every network); that fallback is not cached, so the
        next call reads the node again. Any other failed read raises and is not cached.

        Returns:
            int: The largest number of seconds after the node's clock at which a transaction may expire.

        """
        async with self._transaction_parameters_lock:
            if self._transaction_parameters is None:
                try:
                    parameters = await self.transaction_parameters()
                except ApiError as error:
                    if error.status_code != HTTPStatus.NOT_FOUND:
                        raise
                    return DEFAULT_MAX_TRANSACTION_TTL_SECONDS
                if (
                    not isinstance(parameters, dict)
                    or parameters.get(_MAX_TTL_KEY) is None
                ):
                    return DEFAULT_MAX_TRANSACTION_TTL_SECONDS
                self._transaction_parameters = parameters
            return int(self._transaction_parameters[_MAX_TTL_KEY])

    async def account_supra_balance(self, account_address: AccountAddress) -> int:
        """Provides the Supra coin balance associated with the given account.

        This reads `0x1::coin::balance<SupraCoin>`, which is the sum of the account's `CoinStore` balance and the
        balance of its primary store of the paired fungible asset (SUPRA as a fungible asset, `0xa`), whichever form
        the SUPRA is held in. The sum includes the fungible asset balance only while the node's framework has the
        coin-to-fungible-asset migration feature enabled and the coin has a paired fungible asset. It does not say
        which form holds the SUPRA: `account_fa_balance` reads the fungible store alone.

        Args:
            account_address (AccountAddress): Address of the account.

        Returns:
            int: The Supra coin balance associated with the given account.

        """
        return await self.account_coin_balance(
            account_address, "0x1::supra_coin::SupraCoin"
        )

    async def account_coin_balance(
        self,
        account_address: AccountAddress,
        coin_type: str,
    ) -> int:
        """Provides the given `coin_type` coin balance associated with the given account.

        This reads `0x1::coin::balance<coin_type>`: the account's `CoinStore` balance plus, for a coin that has a
        paired fungible asset (SUPRA does), the balance of the account's primary store of that fungible asset. See
        `account_supra_balance`.

        Args:
            account_address (AccountAddress): Address of the account.
            coin_type (str): The type of the coin for which balance needs to be provided.

        Returns:
            int: The given `coin_type` coin balance associated with the given account.

        """
        response = await self.view(
            "0x1::coin::balance", [coin_type], [str(account_address)]
        )
        return int(response[0])

    async def account_fa_balance(
        self,
        account_address: AccountAddress | str,
        metadata_address: AccountAddress | str = SUPRA_FA_METADATA_ADDRESS,
    ) -> int:
        """Provides the balance of the account's primary fungible store for a fungible asset.

        This reads `0x1::primary_fungible_store::balance`, the fungible store alone. SUPRA that the account still
        holds in a `CoinStore` is not part of it, and an account with no primary store has a balance of 0. SUPRA is
        held as a fungible asset from genesis on a Devnet that was created that way (faucet funds land in the primary
        store), while a Testnet or Mainnet account holds a `CoinStore` balance until it migrates with
        `migrate_coin_to_fungible_store`. `account_supra_balance` reads the sum of both forms.

        Args:
            account_address (AccountAddress | str): Address of the account, as an `AccountAddress` or a hex string.
            metadata_address (AccountAddress | str): Address of the fungible asset's metadata object. Default to
                `SUPRA_FA_METADATA_ADDRESS` (`0xa`, SUPRA).

        Returns:
            int: The balance of the account's primary store, in the asset's smallest unit (quants for SUPRA).

        Raises:
            ValueError: If an address is not a valid account address.

        """
        response = await self.view(
            "0x1::primary_fungible_store::balance",
            [FUNGIBLE_ASSET_METADATA_TYPE],
            [
                str(to_account_address(account_address, "account_address")),
                str(to_account_address(metadata_address, "metadata_address")),
            ],
        )
        return int(response[0])

    async def account_sequence_number(
        self,
        account_address: AccountAddress | str,
    ) -> int:
        """Provides the current sequence number of the given account.

        Args:
            account_address (AccountAddress | str): Address of the account, as an `AccountAddress` or a hex string.

        Returns:
            int: The current sequence number for the given account.

        """
        response = await self.account(account_address)
        return int(response["sequence_number"])

    async def submit_transaction(
        self,
        signed_transaction: SignedTransaction,
    ) -> str:
        """Submits a given signed transaction to the Supra network.

        This method wraps the given `signed_transaction` under `SupraTransaction`, serializes wrapped object using
        BCS serialization, submits serialized payload on the rpc node endpoint, and returns the transaction hash.

        If `TransactionConfig.wait_for_transaction` is enabled (the default), the method then waits for the
        transaction to be final and raises `TransactionFailedError` unless its status is `Success`. If it is
        disabled, the method returns the hash right after submission and the outcome of the transaction is not
        checked. Use `submit_transaction_and_wait` to get the final transaction data.

        Args:
            signed_transaction (SignedTransaction): Signed transaction object to submit transaction.

        Returns:
            str: Transaction hash of the submitted transaction.

        Raises:
            TransactionFailedError: If waiting is enabled and the final status is not `Success`.
            TransactionWaitTimeoutReachedError: If waiting is enabled and the transaction is not final within
                `TransactionConfig.transaction_wait_time_in_seconds`.

        """
        if self.transaction_config.wait_for_transaction:
            transaction_hash, _ = await self._submit_wait_and_check(signed_transaction)
            return transaction_hash
        return await self.submit(SupraTransaction(signed_transaction).to_bytes())

    async def submit_transaction_and_wait(
        self,
        signed_transaction: SignedTransaction,
    ) -> dict[str, Any]:
        """Submits a signed transaction, waits until it is final and returns its data.

        This method always waits, regardless of `TransactionConfig.wait_for_transaction`.

        Args:
            signed_transaction (SignedTransaction): Signed transaction object to submit transaction.

        Returns:
            dict[str, Any]: The transaction data, whose status is `Success`.

        Raises:
            TransactionFailedError: If the final status is not `Success`.
            TransactionWaitTimeoutReachedError: If the transaction is not final within
                `TransactionConfig.transaction_wait_time_in_seconds`.

        """
        _, transaction_data = await self._submit_wait_and_check(signed_transaction)
        return transaction_data

    async def _submit_wait_and_check(
        self, signed_transaction: SignedTransaction
    ) -> tuple[str, dict[str, Any]]:
        transaction_hash = await self.submit(
            SupraTransaction(signed_transaction).to_bytes()
        )
        transaction_data = await self.wait_for_transaction(transaction_hash)
        _raise_if_not_successful(transaction_hash, transaction_data)
        return transaction_hash, transaction_data

    async def wait_for_transaction(self, tx_hash: str) -> dict[str, Any]:
        """Waits until a transaction is final and returns its data.

        This method polls the transaction until its status is `Success`, `Fail` or `Invalid`. Any other status keeps
        it polling: `Pending`, `PendingAfterExecution` (the node reports it for a transaction that was executed but
        may still succeed later, e.g. because its sequence number is too new), a missing status or an unknown one.
        A 404 whose body is the node's "transaction not found" message (a JSON object with a `message` starting
        "Information not available for" or containing "Cannot find transaction") means "not seen yet" and polling
        continues; any other 404, such as a wrong base URL or a missing route, is raised as `ApiError`. The final
        data is returned whatever the status is, so the caller must check `status`.

        The wait never starts a poll after `TransactionConfig.transaction_wait_time_in_seconds` has passed, bounds each
        poll by the time remaining, and sleeps at most the time remaining between polls. The first poll always
        happens.

        Args:
            tx_hash (str): The hash of the transaction to wait for.

        Returns:
            dict[str, Any]: The final transaction data.

        Raises:
            TransactionWaitTimeoutReachedError: If the transaction is not final within
                `TransactionConfig.transaction_wait_time_in_seconds`. The error carries the hash and the last status
                seen (`None` if the node never knew the transaction).

        """
        return await self._wait_until_final(tx_hash, self.transaction_by_hash)

    async def _wait_until_final(
        self,
        tx_hash: str,
        fetch: Callable[[str], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        timeout = self.transaction_config.transaction_wait_time_in_seconds
        deadline = time.monotonic() + timeout
        last_status: str | None = None
        first_poll = True
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 and not first_poll:
                raise TransactionWaitTimeoutReachedError(tx_hash, timeout, last_status)
            try:
                transaction_data = await asyncio.wait_for(
                    fetch(tx_hash), timeout=remaining if remaining > 0 else None
                )
            except TimeoutError:
                # The poll itself outlasted the deadline.
                raise TransactionWaitTimeoutReachedError(
                    tx_hash, timeout, last_status
                ) from None
            except ApiError as error:
                if not _is_transaction_not_found(error):
                    raise
            else:
                status = transaction_data.get("status")
                if isinstance(status, str):
                    last_status = status
                if status in _FINAL_STATUSES:
                    return transaction_data
            first_poll = False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TransactionWaitTimeoutReachedError(tx_hash, timeout, last_status)
            await asyncio.sleep(
                min(self.transaction_config.polling_wait_time_in_seconds, remaining)
            )

    async def simulate_transaction(
        self, signed_transaction: SignedTransaction
    ) -> dict[str, Any]:
        """Simulates a given signed transaction.

        The simulation is sent with the signatures removed, so there is no need to provide a transaction with invalid
        signatures. The given `signed_transaction` is never modified, whether the simulation succeeds or fails.

        Args:
            signed_transaction (SignedTransaction): Signed transaction object for simulation simulate.

        Returns:
            dict[str, Any]: Transaction simulation result.

        """
        authenticator_clone = copy.deepcopy(signed_transaction.authenticator)
        authenticator_clone.unset_signature()
        unsigned_copy = SignedTransaction(
            signed_transaction.transaction, authenticator_clone
        )
        return await self.simulate(SupraTransaction(unsigned_copy).to_bytes())

    async def create_raw_transaction(
        self,
        sender: Account | AccountAddress,
        transaction_payload: TransactionPayload,
        sequence_number: int | None = None,
        max_gas_amount: int | None = None,
        fee_payer: Account | AccountAddress | None = None,
    ) -> RawTransaction:
        """Creates a raw transaction.

        This method builds a raw transaction with the provided sender, payload, and optionally a custom sequence number
        and max gas amount.

        The transaction expires `TransactionConfig.expiration_ttl` seconds after the client's clock. Without an
        `expiration_ttl` it expires 5 seconds before the node's maximum time-to-live (`rpc/v3/transactions/parameters`,
        read once per client), so that a node whose clock is up to 5 seconds behind the client's accepts it.

        The max gas amount is `max_gas_amount`, else `TransactionConfig.max_gas_amount`, used as given. When neither is
        set it is estimated: the transaction is simulated with the most gas the sender's SUPRA balance pays for at the
        gas unit price (`balance // gas_unit_price`, at most 2,000,000,000 units), and the max gas amount is the gas used
        times 1.5, rounded up, at least 1,500 and at most what the balance pays for. The node accepts a transaction only
        if the sender's balance covers `max_gas_amount * gas_unit_price`, so an estimate needs a balance of at least the
        gas used times the gas unit price. When `sender` is only an address there is no key to simulate with, and the
        max gas amount is 20,000 units, at most what the balance pays for. The estimate is made against the node's
        committed state. When the simulation reports the sequence number as ahead of the account's on the chain (a
        transaction sent behind uncommitted ones), the account's sequence number is read and the transaction is
        simulated again with that number; the returned transaction keeps `sequence_number`. A transaction that depends
        on an uncommitted one does not simulate to `Success` even then: set `max_gas_amount` for it.

        Args:
            sender (Account | AccountAddress): The account object or its address.
            transaction_payload (TransactionPayload): The transaction payload.
            sequence_number (int | None): The sender's sequence number. `None` fetches it from the node; any integer,
                including 0, is used as given without a request. Default to None.
            max_gas_amount (int | None): Max gas units for this transaction. `None` uses the config value or the
                estimate described above. Default to None.
            fee_payer (Account | AccountAddress | None): The account that will pay for gas when the transaction is
                wrapped for a fee payer. Its SUPRA balance, not the sender's, caps the estimated max gas, and the
                simulation is made in fee-payer form (with no secondary signers) when both `sender` and `fee_payer`
                are accounts; with only the fee payer's address there is no key to simulate with and the fallback of
                20,000 units applies. It does not change the raw transaction, which is the same for every payer; no
                balance is read when the max gas is explicit. Default to None.

        Returns:
            RawTransaction: The constructed raw transaction object.

        Raises:
            MaxGasEstimationError: If the max gas amount has to be estimated and the balance cannot be read, is too
                low to pay for any gas, or the simulation fails or does not succeed.

        """
        gas_payer = None
        to_signed = None
        if fee_payer is not None:
            gas_payer = (
                fee_payer.address() if isinstance(fee_payer, Account) else fee_payer
            )
            if isinstance(sender, Account) and isinstance(fee_payer, Account):
                to_signed = _fee_payer_signer(sender, fee_payer, [])
        return await self._build_raw_transaction(
            sender,
            transaction_payload,
            sequence_number,
            max_gas_amount,
            to_signed,
            gas_payer,
        )

    async def _build_raw_transaction(
        self,
        sender: Account | AccountAddress,
        transaction_payload: TransactionPayload,
        sequence_number: int | None,
        max_gas_amount: int | None,
        to_signed: Callable[[RawTransaction], SignedTransaction] | None = None,
        gas_payer: AccountAddress | None = None,
    ) -> RawTransaction:
        """Builds the raw transaction; `to_signed` and `gas_payer` give the form that is simulated to estimate max gas.

        `to_signed` turns the raw transaction into the signed transaction that will be submitted (default: signed by
        `sender` alone, when `sender` is an `Account`). `gas_payer` is the account whose balance pays for gas (default:
        the sender).
        """
        sender_address = sender.address() if isinstance(sender, Account) else sender
        resolved_sequence_number = (
            await self.account_sequence_number(sender_address)
            if sequence_number is None
            else sequence_number
        )
        gas_unit_price = (
            self.transaction_config.gas_unit_price
            or (await self.estimate_gas_price())["min_configured_gas_price"]
        )
        expiration_timestamp = await self._expiration_timestamp()
        chain_id = await self.chain_id()

        def build(max_gas: int, sequence_number: int | None = None) -> RawTransaction:
            return RawTransaction(
                sender_address,
                (
                    resolved_sequence_number
                    if sequence_number is None
                    else sequence_number
                ),
                transaction_payload,
                max_gas,
                gas_unit_price,
                expiration_timestamp,
                chain_id,
            )

        if max_gas_amount is None:
            max_gas_amount = self.transaction_config.max_gas_amount
        if max_gas_amount is None:
            if to_signed is None and gas_payer is None and isinstance(sender, Account):
                to_signed = _single_signer(sender)
            max_gas_amount = await self._estimate_max_gas_amount(
                sender_address,
                gas_payer or sender_address,
                gas_unit_price,
                build,
                to_signed,
            )
        return build(max_gas_amount)

    async def _simulate_unsigned(
        self,
        raw_transaction: RawTransaction,
        to_signed: Callable[[RawTransaction], SignedTransaction],
    ) -> dict[str, Any]:
        """Simulates the transaction that `to_signed` builds from `raw_transaction`.

        The signed transaction is made here and discarded, so `simulate_transaction`, which replaces the signatures of
        the object it is given, cannot affect a transaction of the caller.
        """
        try:
            return await self.simulate_transaction(to_signed(raw_transaction))
        except ApiError as error:
            raise MaxGasEstimationError(
                f"Simulation of the transaction to estimate max gas failed: {error}; set max_gas_amount"
            ) from error

    async def _estimate_max_gas_amount(
        self,
        sender_address: AccountAddress,
        gas_payer: AccountAddress,
        gas_unit_price: int,
        build: Callable[[int, int | None], RawTransaction],
        to_signed: Callable[[RawTransaction], SignedTransaction] | None,
    ) -> int:
        try:
            balance = await self.account_supra_balance(gas_payer)
        except ApiError as error:
            raise MaxGasEstimationError(
                f"Could not read the SUPRA balance of {gas_payer} to estimate max gas: {error}; "
                "set max_gas_amount"
            ) from error
        affordable = affordable_gas_amount(balance, gas_unit_price)
        if affordable == 0:
            raise MaxGasEstimationError(
                f"The SUPRA balance of {gas_payer} ({balance} quants) does not pay for one unit of gas at the gas "
                f"unit price of {gas_unit_price} quants"
            )
        if to_signed is None:
            return min(FALLBACK_MAX_GAS_AMOUNT, affordable)
        raw_transaction = build(affordable, None)
        simulation = await self._simulate_unsigned(raw_transaction, to_signed)
        if not is_sequence_number_too_new(simulation):
            return max_gas_from_simulation(simulation, affordable)

        # A transaction sent behind uncommitted ones of the same account: the simulation runs on committed state, so
        # it is repeated at the account's sequence number on the chain. The submitted transaction keeps its own.
        try:
            chain_sequence_number = await self.account_sequence_number(sender_address)
        except ApiError as error:
            raise MaxGasEstimationError(
                f"The sequence number {raw_transaction.sequence_number} is ahead of the account's, and reading the "
                f"account's sequence number failed: {error}; set max_gas_amount"
            ) from error
        simulation = await self._simulate_unsigned(
            build(affordable, chain_sequence_number), to_signed
        )
        try:
            return max_gas_from_simulation(simulation, affordable)
        except MaxGasEstimationError as error:
            raise MaxGasEstimationError(
                f"The sequence number {raw_transaction.sequence_number} is ahead of the account's on the chain "
                f"({chain_sequence_number}) and the simulation at the chain's number did not succeed "
                f"(status: {error.status}, vm_status: {error.vm_status}); if the transaction depends on an "
                "uncommitted transaction, set max_gas_amount",
                error.status,
                error.vm_status,
                error.simulation,
            ) from error

    async def _expiration_timestamp(self) -> int:
        ttl = self.transaction_config.expiration_ttl
        if ttl is not None:
            return int(time.time()) + ttl
        return default_expiration_timestamp(
            int(time.time()), await self.max_transaction_time_to_live()
        )

    async def create_signed_transaction(
        self,
        sender: Account,
        transaction_payload: TransactionPayload,
        sequence_number: int | None = None,
        max_gas_amount: int | None = None,
    ) -> SignedTransaction:
        """Creates a signed transaction.

        This method builds a raw transaction, signs it using the sender's key, wraps it in an authenticator,
        and generates signed transaction payload.

        The max gas amount and the expiration time follow `create_raw_transaction`: an explicit `max_gas_amount` (here
        or in `TransactionConfig`) is used as given, otherwise it is estimated by a simulation, which needs the sender's
        SUPRA balance to cover the gas used times the gas unit price.

        Args:
            sender (Account): The account signing the transaction.
            transaction_payload (TransactionPayload): The transaction payload.
            sequence_number (int | None): The sequence number to use. If not provided, the current sequence number will
                be fetched; 0 is used as given. Default to None.
            max_gas_amount (int | None): Max gas units for this transaction. `None` uses the config value or the
                estimate. Default to None.

        Returns:
            SignedTransaction: The constructed signed transaction object.

        Raises:
            MaxGasEstimationError: If the max gas amount has to be estimated and that fails.

        """
        to_signed = _single_signer(sender)
        raw_transaction = await self._build_raw_transaction(
            sender, transaction_payload, sequence_number, max_gas_amount, to_signed
        )
        return to_signed(raw_transaction)

    async def create_fee_payer_transaction(
        self,
        sender: Account,
        fee_payer: Account,
        secondary_accounts: list[Account],
        transaction_payload: TransactionPayload,
        max_gas_amount: int | None = None,
    ) -> SignedTransaction:
        """Creates a fee-payer authenticator type signed transaction.

        This method builds and signs a fee-payer authenticator type transaction, where the main sender, fee payer and
        one or more secondary accounts sign the same raw transaction.

        An explicit `max_gas_amount` (here or in `TransactionConfig`) is used as given, otherwise it is estimated by
        simulating the fee-payer transaction. The fee payer pays for gas, so the estimate needs the fee payer's SUPRA
        balance to cover the gas used times the gas unit price. See `create_raw_transaction`.

        Args:
            sender (Account): The primary account sending the transaction.
            fee_payer (Account): The fee payer account to pay transaction fee.
            secondary_accounts (list[Account]): The secondary accounts that also authorize the transaction.
            transaction_payload (TransactionPayload): The transaction payload.
            max_gas_amount (int | None): Max gas units for this transaction. `None` uses the config value or the
                estimate. Default to None.

        Returns:
            SignedTransaction: The constructed multi-agent authenticator type signed transaction.

        Raises:
            MaxGasEstimationError: If the max gas amount has to be estimated and that fails.

        """
        to_signed = _fee_payer_signer(sender, fee_payer, secondary_accounts)
        raw_transaction = await self._build_raw_transaction(
            sender,
            transaction_payload,
            None,
            max_gas_amount,
            to_signed,
            fee_payer.address(),
        )
        return to_signed(raw_transaction)

    async def create_multi_agent_transaction(
        self,
        sender: Account,
        secondary_accounts: list[Account],
        transaction_payload: TransactionPayload,
        max_gas_amount: int | None = None,
    ) -> SignedTransaction:
        """Creates a multi-agent authenticator type signed transaction.

        This method builds and signs a multi-agent authenticator type transaction, where the main sender and one or
        more secondary accounts sign the same raw transaction.

        An explicit `max_gas_amount` (here or in `TransactionConfig`) is used as given, otherwise it is estimated by
        simulating the multi-agent transaction, which needs the sender's SUPRA balance to cover the gas used times the
        gas unit price. See `create_raw_transaction`.

        Args:
            sender (Account): The primary account sending the transaction.
            secondary_accounts (list[Account]): The secondary accounts that also authorize the transaction.
            transaction_payload (TransactionPayload): The transaction payload.
            max_gas_amount (int | None): Max gas units for this transaction. `None` uses the config value or the
                estimate. Default to None.

        Returns:
            SignedTransaction: The constructed multi-agent authenticator type signed transaction.

        Raises:
            MaxGasEstimationError: If the max gas amount has to be estimated and that fails.

        """
        to_signed = _multi_agent_signer(sender, secondary_accounts)
        raw_transaction = await self._build_raw_transaction(
            sender, transaction_payload, None, max_gas_amount, to_signed
        )
        return to_signed(raw_transaction)

    async def register_automation_task(
        self,
        owner_account: Account,
        automated_function: EntryFunction,
        automation_max_gas_amount: int,
        automation_gas_price_cap: int,
        automation_fee_cap_for_epoch: int,
        automation_expiration_timestamp_secs: int,
        automation_aux_data: list[bytes],
        automation_task_type: AutomationTaskType | None = None,
        automation_priority: int | None = None,
    ) -> str:
        """Registers Supra automation task.

        With neither ``automation_task_type`` nor ``automation_priority`` the task is
        registered with version 1 of the registration parameters. With either, version 2
        is used, and a missing task type is ``AutomationTaskType.USER``.

        Args:
            owner_account (Account): Account registering an automation task.
                It will be eligible to cancel or stop task.
            automated_function (str): Automated entry function payload.
            automation_max_gas_amount (int): Max gas allowed for automation.
            automation_gas_price_cap (int): Gas price cap for automation execution.
            automation_fee_cap_for_epoch (int): Maximum total fee for the epoch.
            automation_expiration_timestamp_secs (int): Expiration time for automation.
            automation_aux_data (list[bytes]): Auxiliary data for automation.
            automation_task_type (AutomationTaskType | None): ``USER`` or ``SYSTEM``.
                A ``SYSTEM`` task can only be registered by an account the registry has
                authorised for system tasks; other accounts' registrations abort.
                Defaults to version 1 parameters (a user task).
            automation_priority (int | None): Priority of the task. Without a priority,
                the registry uses the task's index as its priority.

        Returns:
            str: Transaction hash.

        Raises:
            TransactionFailedError: If waiting is enabled and the final status is not `Success`.
            TransactionWaitTimeoutReachedError: If waiting is enabled and the transaction is not final in time.

        """
        transaction_payload = TransactionPayload(
            AutomationRegistrationParams.build(
                automated_function,
                automation_max_gas_amount,
                automation_gas_price_cap,
                automation_fee_cap_for_epoch,
                automation_expiration_timestamp_secs,
                automation_aux_data,
                automation_task_type,
                automation_priority,
            )
        )
        signed_transaction = await self.create_signed_transaction(
            owner_account,
            transaction_payload,
        )
        return await self.submit_transaction(signed_transaction)

    async def cancel_automation_task(
        self,
        owner_account: Account,
        task_index: int,
    ) -> str:
        """Cancels Supra automation task.

        Args:
            owner_account (Account): Automation task owner.
            task_index (int): The ID of the automation task.

        Returns:
            str: Transaction hash.

        Raises:
            TransactionFailedError: If waiting is enabled and the final status is not `Success`.
            TransactionWaitTimeoutReachedError: If waiting is enabled and the transaction is not final in time.

        """
        transaction_arguments = [
            TransactionArgument(task_index, Serializer.u64),
        ]
        transaction_payload = EntryFunction.natural(
            "0x1::automation_registry",
            "cancel_task",
            [],
            transaction_arguments,
        )
        signed_transaction = await self.create_signed_transaction(
            owner_account,
            TransactionPayload(transaction_payload),
        )
        return await self.submit_transaction(signed_transaction)

    async def stop_automation_tasks(
        self,
        owner_account: Account,
        task_ids: list[int],
    ) -> str:
        """Stops list of Supra automation tasks.

        Args:
            owner_account (Account): Automation task owner.
            task_ids (list[int]): List of automation task IDs.

        Returns:
            str: Transaction hash.

        Raises:
            TransactionFailedError: If waiting is enabled and the final status is not `Success`.
            TransactionWaitTimeoutReachedError: If waiting is enabled and the transaction is not final in time.

        """
        transaction_arguments = [
            TransactionArgument(
                task_ids, Serializer.sequence_serializer(Serializer.u64)
            ),
        ]
        transaction_payload = EntryFunction.natural(
            "0x1::automation_registry",
            "stop_tasks",
            [],
            transaction_arguments,
        )
        signed_transaction = await self.create_signed_transaction(
            owner_account,
            TransactionPayload(transaction_payload),
        )
        return await self.submit_transaction(signed_transaction)

    async def transfer_supra_coin(
        self,
        sender: Account,
        recipient: AccountAddress,
        amount: int,
        sequence_number: int | None = None,
        max_gas_amount: int | None = None,
    ) -> str:
        """Transfers given amount of SupraCoin to a given recipient.

        This method builds an `EntryFunction` payload for transferring the `SupraCoin`, signs it with the sender's
        account, and submits it to the network.

        Without a `max_gas_amount` (here or in `TransactionConfig`) the max gas is estimated by a simulation, which
        needs the sender's balance to cover the maximum gas deposit, in addition to the transferred amount. A transfer
        that creates the recipient uses about 1,000 units, so at the minimum gas unit price of 100,000 quants the
        gas costs 10^8 quants (1 SUPRA, where 1 SUPRA = 10^8 quants), and the max gas of about 1,500 units (the gas
        used times 1.5) is a deposit of about 1.5 SUPRA.

        Args:
            sender (Account): Sender account.
            recipient (AccountAddress): Recipient account address.
            amount (int): The amount of coins to transfer.
            sequence_number (int | None): The sender's sequence number. If not provided, it will be fetched
                automatically. Default to None.
            max_gas_amount (int | None): Max gas units for this transaction. `None` uses the config value or the
                estimate. Default to None.

        Returns:
            str: Transaction hash.

        Raises:
            TransactionFailedError: If waiting is enabled and the final status is not `Success`.
            TransactionWaitTimeoutReachedError: If waiting is enabled and the transaction is not final in time.

        """
        return await self.transfer_coins(
            sender,
            recipient,
            "0x1::supra_coin::SupraCoin",
            amount,
            sequence_number,
            max_gas_amount,
        )

    async def transfer_coins(
        self,
        sender: Account,
        recipient: AccountAddress,
        coin_type: str,
        amount: int,
        sequence_number: int | None = None,
        max_gas_amount: int | None = None,
    ) -> str:
        """Transfer a given coin type coins to a recipient.

        This method builds a coin transfer payload for any supported coin type, signs it with the sender's account,
        and submits it to the network.

        Gas is paid in SUPRA whatever the coin type. Without a `max_gas_amount` (here or in `TransactionConfig`) the max
        gas is estimated by a simulation, which needs the sender's SUPRA balance to cover the gas used times the gas unit
        price.

        Args:
            sender (Account): Sender account.
            recipient (AccountAddress): Recipient account address.
            coin_type (str): The fully-qualified coin type tag e.g. '0x1::supra_coin::SupraCoin'.
            amount (int): The amount of coins to transfer.
            sequence_number (int | None): The sender's sequence number. If not provided, it will be fetched
                automatically. Default to None.
            max_gas_amount (int | None): Max gas units for this transaction. `None` uses the config value or the
                estimate. Default to None.

        Returns:
            str: Transaction hash.

        Raises:
            TransactionFailedError: If waiting is enabled and the final status is not `Success`.
            TransactionWaitTimeoutReachedError: If waiting is enabled and the transaction is not final in time.

        """
        transaction_arguments = [
            TransactionArgument(recipient, Serializer.struct),
            TransactionArgument(amount, Serializer.u64),
        ]
        transaction_payload = EntryFunction.natural(
            "0x1::supra_account",
            "transfer_coins",
            [TypeTag(StructTag.from_str(coin_type))],
            transaction_arguments,
        )
        signed_transaction = await self.create_signed_transaction(
            sender,
            TransactionPayload(transaction_payload),
            sequence_number,
            max_gas_amount,
        )
        return await self.submit_transaction(signed_transaction)

    async def transfer_fungible_asset(
        self,
        sender: Account,
        recipient: AccountAddress,
        amount: int,
        metadata_address: AccountAddress | str = SUPRA_FA_METADATA_ADDRESS,
        sequence_number: int | None = None,
        max_gas_amount: int | None = None,
    ) -> str:
        """Transfers a fungible asset from the sender's primary store to the recipient's primary store.

        This method builds a `0x1::primary_fungible_store::transfer` payload, signs it with the sender's account, and
        submits it to the network. The recipient's primary store is created when it does not exist.

        Only the sender's fungible store is debited. SUPRA that the sender holds in a `CoinStore` (Testnet and Mainnet
        until a migration) is not moved, and the transaction aborts when the fungible store holds less than `amount`;
        without a `max_gas_amount` the abort is reported by the gas estimation as a `MaxGasEstimationError`, and with
        one as a `TransactionFailedError`. Check `account_fa_balance` first, call `migrate_coin_to_fungible_store` to
        move the coin balance into the fungible store, or use `transfer_supra_coin`, which moves SUPRA held in either
        form.

        Gas is paid in SUPRA whatever the asset, and the gas estimation described at `transfer_supra_coin` applies.

        Args:
            sender (Account): Sender account.
            recipient (AccountAddress): Recipient account address.
            amount (int): The amount to transfer, in the asset's smallest unit (quants for SUPRA).
            metadata_address (AccountAddress | str): Address of the fungible asset's metadata object. Default to
                `SUPRA_FA_METADATA_ADDRESS` (`0xa`, SUPRA).
            sequence_number (int | None): The sender's sequence number. If not provided, it will be fetched
                automatically. Default to None.
            max_gas_amount (int | None): Max gas units for this transaction. `None` uses the config value or the
                estimate. Default to None.

        Returns:
            str: Transaction hash.

        Raises:
            ValueError: If `metadata_address` is not a valid account address.
            TransactionFailedError: If waiting is enabled and the final status is not `Success`.
            TransactionWaitTimeoutReachedError: If waiting is enabled and the transaction is not final in time.

        """
        transaction_arguments = [
            TransactionArgument(
                to_account_address(metadata_address, "metadata_address"),
                Serializer.struct,
            ),
            TransactionArgument(recipient, Serializer.struct),
            TransactionArgument(amount, Serializer.u64),
        ]
        transaction_payload = EntryFunction.natural(
            "0x1::primary_fungible_store",
            "transfer",
            [TypeTag(StructTag.from_str(FUNGIBLE_ASSET_METADATA_TYPE))],
            transaction_arguments,
        )
        signed_transaction = await self.create_signed_transaction(
            sender,
            TransactionPayload(transaction_payload),
            sequence_number,
            max_gas_amount,
        )
        return await self.submit_transaction(signed_transaction)

    async def migrate_coin_to_fungible_store(
        self,
        sender: Account,
        coin_type: str = "0x1::supra_coin::SupraCoin",
        sequence_number: int | None = None,
        max_gas_amount: int | None = None,
    ) -> str:
        """Moves the sender's balance of a coin type from its `CoinStore` to its primary fungible store.

        This method builds a `0x1::coin::migrate_to_fungible_store` payload, signs it with the sender's account, and
        submits it to the network. The `CoinStore` resource is removed, its balance is deposited in the primary store
        of the coin's paired fungible asset (`0xa` for SUPRA), which is created if needed, and the account then
        holds the coin as a fungible asset only. The sum that `account_supra_balance` reads does not change; the
        balance that `account_fa_balance` reads becomes that sum.

        Migration is meaningful only where the account has a `CoinStore`: Testnet and Mainnet accounts that have not
        migrated. On a Devnet whose SUPRA is held as a fungible asset from genesis there is no `CoinStore` to move,
        and the transaction changes no balance but still costs gas. The transaction aborts when the framework's
        coin-to-fungible-asset migration feature is not enabled. The migration cannot be undone.

        Args:
            sender (Account): The account whose balance is migrated.
            coin_type (str): The fully-qualified coin type tag. Default to '0x1::supra_coin::SupraCoin'.
            sequence_number (int | None): The sender's sequence number. If not provided, it will be fetched
                automatically. Default to None.
            max_gas_amount (int | None): Max gas units for this transaction. `None` uses the config value or the
                estimate. Default to None.

        Returns:
            str: Transaction hash.

        Raises:
            TransactionFailedError: If waiting is enabled and the final status is not `Success`.
            TransactionWaitTimeoutReachedError: If waiting is enabled and the transaction is not final in time.

        """
        transaction_payload = EntryFunction.natural(
            "0x1::coin",
            "migrate_to_fungible_store",
            [TypeTag(StructTag.from_str(coin_type))],
            [],
        )
        signed_transaction = await self.create_signed_transaction(
            sender,
            TransactionPayload(transaction_payload),
            sequence_number,
            max_gas_amount,
        )
        return await self.submit_transaction(signed_transaction)

    async def transfer_object(
        self, owner: Account, object_address: AccountAddress, to: AccountAddress
    ) -> str:
        """Transfer an object to another account.

        This method builds an object transfer payload, signs it with the owner's account, and submits it to the network.

        Args:
            owner (Account): The owner account sending the object.
            object_address (AccountAddress): The address of the object to transfer.
            to (AccountAddress): The recipient's account address.

        Returns:
            str: Transaction hash.

        Raises:
            TransactionFailedError: If waiting is enabled and the final status is not `Success`.
            TransactionWaitTimeoutReachedError: If waiting is enabled and the transaction is not final in time.

        """
        transaction_arguments = [
            TransactionArgument(object_address, Serializer.struct),
            TransactionArgument(to, Serializer.struct),
        ]
        payload = EntryFunction.natural(
            "0x1::object",
            "transfer_call",
            [],
            transaction_arguments,
        )
        signed_transaction = await self.create_signed_transaction(
            owner,
            TransactionPayload(payload),
        )
        return await self.submit_transaction(signed_transaction)

    async def publish_package(
        self, module_publisher: Account, package_metadata: bytes, modules: list[bytes]
    ) -> str:
        """Publishes package on a given module publisher account.

        Args:
            module_publisher (Account): Module publisher account.
            package_metadata (bytes): Metadata of the package, generated after package compilation.
            modules (list[bytes]): List of package's module bytecode .

        Returns:
            str: Transaction hash.

        Raises:
            TransactionFailedError: If waiting is enabled and the final status is not `Success`.
            TransactionWaitTimeoutReachedError: If waiting is enabled and the transaction is not final in time.

        """
        transaction_arguments = [
            TransactionArgument(package_metadata, Serializer.to_bytes),
            TransactionArgument(
                modules, Serializer.sequence_serializer(Serializer.to_bytes)
            ),
        ]
        payload = EntryFunction.natural(
            "0x1::code",
            "publish_package_txn",
            [],
            transaction_arguments,
        )
        signed_transaction = await self.create_signed_transaction(
            module_publisher, TransactionPayload(payload)
        )
        return await self.submit_transaction(signed_transaction)

    async def faucet(
        self, address: AccountAddress | str, wait_for_faucet: bool = True
    ) -> str | None:
        """Requests faucet funds to be sent to the given account address.

        Args:
            address (AccountAddress | str): The target account address to receive funds, as an `AccountAddress` or a
                hex string.
            wait_for_faucet (bool): Flag indicates whether wait for faucet should be done or not. Default to True.

        Returns:
            str | None: Faucet transaction hash if faucet request is accepted else None.

        Raises:
            FaucetRequestNotAcceptedError: If waiting is requested and the faucet did not accept the request.
            TransactionFailedError: If waiting is requested and the final status of the faucet transaction is not
                `Success`.
            TransactionWaitTimeoutReachedError: If waiting is requested and the faucet transaction is not final within
                `TransactionConfig.transaction_wait_time_in_seconds`.

        """
        may_be_tx_hash = await super().faucet(address)
        if wait_for_faucet:
            if not may_be_tx_hash:
                raise FaucetRequestNotAcceptedError
            _raise_if_not_successful(
                may_be_tx_hash, await self.wait_for_faucet(may_be_tx_hash)
            )
        return may_be_tx_hash

    async def wait_for_faucet(self, faucet_tx_hash: str) -> dict[str, Any]:
        """Waits until a faucet transaction is final and returns its data.

        Note: This method is similar to the `SupraClient.wait_for_transaction`, this method uses
        `FaucetClient.faucet_transaction_by_hash` method to get transaction data of the faucet transaction, it uses that
        method because, there is different endpoint meant in rpc node to get the transaction details of the pending
        faucet transactions. It polls under the same rules as `wait_for_transaction`: it keeps polling until the status
        is `Success`, `Fail` or `Invalid`, treats only the node's "transaction not found" 404 as "not seen yet", and
        returns the final data whatever the status is.

        Args:
            faucet_tx_hash (str): The hash of the faucet transaction to wait for.

        Returns:
            dict[str, Any]: The final transaction data.

        Raises:
            TransactionWaitTimeoutReachedError: If the transaction is not final within
                `TransactionConfig.transaction_wait_time_in_seconds`.

        """
        return await self._wait_until_final(
            faucet_tx_hash, self.faucet_transaction_by_hash
        )


# The only statuses after which the node will not change the outcome of a transaction.
_FINAL_STATUSES = frozenset({"Success", "Fail", "Invalid"})

# Fragments of the body the node's rpc transaction-by-hash endpoints return with a 404 when they do not know the hash.
_TRANSACTION_NOT_FOUND_MESSAGES = (
    "Information not available for",
    "Cannot find transaction",
)


def _is_transaction_not_found(error: ApiError) -> bool:
    """Whether the error is the node saying it does not know the transaction, rather than any other 404."""
    if error.status_code != HTTPStatus.NOT_FOUND:
        return False
    try:
        message = json.loads(error.message).get("message")
    except (ValueError, AttributeError):
        return False
    return isinstance(message, str) and any(
        fragment in message for fragment in _TRANSACTION_NOT_FOUND_MESSAGES
    )


def _raise_if_not_successful(tx_hash: str, transaction_data: dict[str, Any]) -> None:
    status = transaction_data.get("status")
    if status == "Success":
        return
    vm_status = None
    output = transaction_data.get("output")
    if isinstance(output, dict) and isinstance(output.get("Move"), dict):
        vm_status = output["Move"].get("vm_status")
    raise TransactionFailedError(tx_hash, status, vm_status, transaction_data)


class TransactionWaitTimeoutReachedError(Exception):
    """Exception raised when the transaction is not final even after max transaction wait time.

    Attributes:
        tx_hash (str): Transaction hash.
        last_status (str | None): Last status the node reported for the transaction, `None` if the node never knew the
            transaction.

    """

    def __init__(
        self,
        tx_hash: str,
        transaction_wait_time_in_seconds: float,
        last_status: str | None = None,
    ):
        """Initializes the exception with transaction hash, wait time and the last status seen.

        Args:
            tx_hash (str): Transaction hash
            transaction_wait_time_in_seconds (float): Transaction wait time.
            last_status (str | None): Last status the node reported for the transaction. Default to None.

        """
        self.tx_hash = tx_hash
        self.last_status = last_status
        super().__init__(
            f"{tx_hash} transaction was not final within {transaction_wait_time_in_seconds} seconds "
            f"(last status: {last_status})"
        )


class TransactionFailedError(Exception):
    """Exception raised when a submitted transaction reached a final status other than `Success`.

    Attributes:
        tx_hash (str): Transaction hash.
        status (str | None): Final status of the transaction, e.g. `Fail` or `Invalid`.
        vm_status (str | None): Message of the Move VM, e.g. the abort location and code. `None` if the node reported
            no Move output, as for a transaction that failed validation.
        transaction_data (dict[str, Any]): The transaction data as returned by the node.

    """

    def __init__(
        self,
        tx_hash: str,
        status: str | None,
        vm_status: str | None,
        transaction_data: dict[str, Any] | None = None,
    ):
        """Initializes the exception with the transaction hash, status and VM status.

        Args:
            tx_hash (str): Transaction hash.
            status (str | None): Final status of the transaction.
            vm_status (str | None): Message of the Move VM, if any.
            transaction_data (dict[str, Any] | None): The transaction data as returned by the node. Default to None.

        """
        self.tx_hash = tx_hash
        self.status = status
        self.vm_status = vm_status
        self.transaction_data = transaction_data or {}
        super().__init__(
            f"{tx_hash} transaction failed with status {status} (vm_status: {vm_status})"
        )


class FaucetRequestNotAcceptedError(Exception):
    """Exception raised when faucet request is not accepted by the faucet rpc node."""

    def __init__(self):
        """Initializes the exception with a default message."""
        super().__init__("Faucet request is not accepted by the rpc node")
