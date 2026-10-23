# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

"""Offline tests of the automation registration parameters (versions 1 and 2)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from supra_sdk.account import Account
from supra_sdk.account_address import AccountAddress
from supra_sdk.bcs import MAX_U64, Deserializer, Serializer
from supra_sdk.clients.rest import SupraClient
from supra_sdk.transactions import (
    AutomationRegistrationParams,
    AutomationRegistrationParamsV1,
    AutomationRegistrationParamsV2,
    AutomationTaskType,
    EntryFunction,
    TransactionArgument,
    TransactionPayload,
)

# The version 2 fixtures were produced by the TypeScript SDK's encoder (the `AutomationRegistrationParamsV2` class
# of its 2.0.0 line, run with tsx) for `0x1::supra_account::transfer(<0xcd * 32>, 1000)`, max gas 500, gas price cap
# 200000, fee cap 1000000000, expiration 1800000000 and no aux data. Each is the whole enum: the variant, the version 1
# fields, the task type and the optional priority.
HEAD = (
    "01"  # variant 1 of the registration parameters
    + "00" * 31
    + "01"  # module address 0x1
    + "0d73757072615f6163636f756e74"  # "supra_account"
    + "087472616e73666572"  # "transfer"
    + "00"  # no type arguments
    + "02"  # two arguments
    + "20"
    + "cd" * 32
    + "08e803000000000000"
)
FIELDS_TAIL = (
    "f401000000000000"  # max_gas_amount 500
    "400d030000000000"  # gas_price_cap 200000
    "00ca9a3b00000000"  # automation_fee_cap_for_epoch 1000000000
    "00d2496b00000000"  # expiration_timestamp_secs 1800000000
    "00"  # aux_data: empty vector
)
V2_USER_NONE = HEAD + FIELDS_TAIL + "00" + "00"
V2_USER_10 = HEAD + FIELDS_TAIL + "00" + "01" + "0a00000000000000"
V2_SYSTEM_MAX = HEAD + FIELDS_TAIL + "01" + "01" + "ffffffffffffffff"
# The encoder's output, verbatim, for the three version 2 cases; the constants above are assembled from named parts.
TS_OUTPUT = {
    "v2_user_none": "0100000000000000000000000000000000000000000000000000000000000000010d73757072615f6163636f756e74087472616e73666572000220cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd08e803000000000000f401000000000000400d03000000000000ca9a3b0000000000d2496b00000000000000",
    "v2_user_10": "0100000000000000000000000000000000000000000000000000000000000000010d73757072615f6163636f756e74087472616e73666572000220cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd08e803000000000000f401000000000000400d03000000000000ca9a3b0000000000d2496b000000000000010a00000000000000",
    "v2_system_max": "0100000000000000000000000000000000000000000000000000000000000000010d73757072615f6163636f756e74087472616e73666572000220cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd08e803000000000000f401000000000000400d03000000000000ca9a3b0000000000d2496b00000000000101ffffffffffffffff",
}
# The version 1 encoding is variant 0 and the same fields, without the trailing task type and priority.
FIELDS = V2_USER_NONE[2:-4]
V1 = "00" + FIELDS


def entry_function() -> EntryFunction:
    return EntryFunction.natural(
        "0x1::supra_account",
        "transfer",
        [],
        [
            TransactionArgument(AccountAddress(bytes([0xCD] * 32)), Serializer.struct),
            TransactionArgument(1000, Serializer.u64),
        ],
    )


def build(**kwargs) -> AutomationRegistrationParams:
    return AutomationRegistrationParams.build(
        entry_function(), 500, 200_000, 1_000_000_000, 1_800_000_000, [], **kwargs
    )


def encode(params: AutomationRegistrationParams) -> str:
    serializer = Serializer()
    params.serialize(serializer)
    return serializer.output().hex()


class TestAutomationRegistrationParamsBcs(unittest.TestCase):
    def test_fixtures_match_the_typescript_encoder_output(self):
        self.assertEqual(V2_USER_NONE, TS_OUTPUT["v2_user_none"])
        self.assertEqual(V2_USER_10, TS_OUTPUT["v2_user_10"])
        self.assertEqual(V2_SYSTEM_MAX, TS_OUTPUT["v2_system_max"])

    def test_v1_is_unchanged(self):
        params = build()
        self.assertEqual(params.variant, AutomationRegistrationParams.V1)
        self.assertIsInstance(
            params.registration_params, AutomationRegistrationParamsV1
        )
        self.assertEqual(encode(params), V1)

    def test_v2_user_without_priority(self):
        self.assertEqual(encode(build(task_type=AutomationTaskType.USER)), V2_USER_NONE)

    def test_v2_user_with_priority(self):
        params = build(task_type=AutomationTaskType.USER, priority=10)
        self.assertEqual(params.variant, AutomationRegistrationParams.V2)
        self.assertEqual(encode(params), V2_USER_10)

    def test_v2_system_with_largest_priority(self):
        params = build(task_type=AutomationTaskType.SYSTEM, priority=MAX_U64)
        self.assertEqual(encode(params), V2_SYSTEM_MAX)

    def test_round_trip(self):
        for hex_bytes, task_type, priority in [
            (V1, None, None),
            (V2_USER_NONE, AutomationTaskType.USER, None),
            (V2_USER_10, AutomationTaskType.USER, 10),
            (V2_SYSTEM_MAX, AutomationTaskType.SYSTEM, MAX_U64),
        ]:
            with self.subTest(hex_bytes=hex_bytes):
                params = AutomationRegistrationParams.deserialize(
                    Deserializer(bytes.fromhex(hex_bytes))
                )
                self.assertEqual(encode(params), hex_bytes)
                inner = params.registration_params
                self.assertEqual(inner.max_gas_amount, 500)
                self.assertEqual(inner.expiration_timestamp_secs, 1_800_000_000)
                self.assertEqual(inner.automated_function, entry_function())
                if task_type is None:
                    self.assertIsInstance(inner, AutomationRegistrationParamsV1)
                else:
                    self.assertIsInstance(inner, AutomationRegistrationParamsV2)
                    self.assertEqual(inner.task_type, task_type)
                    self.assertEqual(inner.priority, priority)

    def test_unknown_task_type_is_rejected(self):
        bad = bytes.fromhex("01" + FIELDS + "02" + "00")
        with self.assertRaises(Exception):
            AutomationRegistrationParams.deserialize(Deserializer(bad))

    def test_unknown_variant_is_rejected(self):
        with self.assertRaises(Exception):
            AutomationRegistrationParams.deserialize(
                Deserializer(bytes.fromhex("02" + FIELDS))
            )

    def test_priority_out_of_range_is_rejected(self):
        with self.assertRaises(ValueError):
            build(priority=MAX_U64 + 1)
        with self.assertRaises(ValueError):
            build(priority=-1)


class TestAutomationRegistrationParamsBuilder(unittest.TestCase):
    def test_neither_argument_is_v1(self):
        self.assertEqual(build().variant, AutomationRegistrationParams.V1)

    def test_task_type_alone_is_v2(self):
        params = build(task_type=AutomationTaskType.SYSTEM)
        self.assertEqual(params.variant, AutomationRegistrationParams.V2)
        self.assertEqual(
            params.registration_params.task_type, AutomationTaskType.SYSTEM
        )
        self.assertIsNone(params.registration_params.priority)

    def test_priority_alone_is_a_user_task(self):
        params = build(priority=0)
        self.assertEqual(params.variant, AutomationRegistrationParams.V2)
        self.assertEqual(params.registration_params.task_type, AutomationTaskType.USER)
        self.assertEqual(params.registration_params.priority, 0)


class TestRegisterAutomationTask(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = SupraClient("http://127.0.0.1:1")
        self.client.create_signed_transaction = AsyncMock(return_value="signed")
        self.client.submit_transaction = AsyncMock(return_value="0xhash")

    async def asyncTearDown(self):
        await self.client.close()

    async def register(self, **kwargs) -> AutomationRegistrationParams:
        tx_hash = await self.client.register_automation_task(
            Account.generate(),
            entry_function(),
            500,
            200_000,
            1_000_000_000,
            1_800_000_000,
            [],
            **kwargs,
        )
        self.assertEqual(tx_hash, "0xhash")
        payload = self.client.create_signed_transaction.call_args.args[1]
        self.assertIsInstance(payload, TransactionPayload)
        return payload.value

    async def test_default_is_v1(self):
        params = await self.register()
        self.assertEqual(encode(params), V1)

    async def test_task_type_and_priority_select_v2(self):
        params = await self.register(
            automation_task_type=AutomationTaskType.SYSTEM,
            automation_priority=MAX_U64,
        )
        self.assertEqual(encode(params), V2_SYSTEM_MAX)

    async def test_priority_alone_is_a_user_task(self):
        params = await self.register(automation_priority=10)
        self.assertEqual(encode(params), V2_USER_10)


if __name__ == "__main__":
    unittest.main()
