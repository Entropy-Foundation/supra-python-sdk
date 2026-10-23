# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

"""Defaults and helpers for the max gas amount and the expiration time of a transaction."""

EXPIRATION_MARGIN_SECONDS = 5
"""Seconds subtracted from the node's maximum transaction time-to-live in the default expiration time. The node refuses
a transaction that expires after its own clock plus the maximum TTL, so a node whose clock is up to this many seconds
behind the client's still accepts the transaction."""


def default_expiration_timestamp(now: int, max_ttl: int) -> int:
    """Returns the expiration time of a transaction built without an explicit `expiration_ttl`.

    It is `max_ttl - EXPIRATION_MARGIN_SECONDS` seconds after `now`, never before `now + 1`.
    """
    return now + max(max_ttl - EXPIRATION_MARGIN_SECONDS, 1)
