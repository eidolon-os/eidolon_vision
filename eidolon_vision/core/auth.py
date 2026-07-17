"""Verify Hub-signed scoped upload tokens.

The device never authenticates to the worker directly. The Hub issues a
short-lived token (like a LiveKit token: Hub signs, the service verifies
offline) scoped to a binding + owner + the set of authorized triggers. The
worker verifies the signature with the Hub public key and enforces the trigger
scope — no per-request call back to the Hub.
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt

from .types import BurstContext

_ALGORITHMS = ["EdDSA", "ES256", "RS256"]
_AUDIENCE = "eidolon_vision"


class TokenError(Exception):
    """Raised when an upload token is missing, malformed, expired, or out of scope."""


@dataclass(frozen=True, slots=True)
class UploadGrant:
    guard_companion_id: str
    device_id: str
    owner_id: str
    guard_epoch: int
    authorized_triggers: frozenset[str]


def verify_upload_token(token: str, *, hub_public_key: str) -> UploadGrant:
    """Verify a Hub-issued upload token; raise :class:`TokenError` on any failure."""
    try:
        claims = jwt.decode(
            token,
            hub_public_key,
            algorithms=_ALGORITHMS,
            audience=_AUDIENCE,
            options={"require": ["exp", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:  # expired, bad signature, missing claim, wrong aud
        raise TokenError(str(exc)) from exc

    triggers = claims.get("triggers")
    if not isinstance(triggers, list) or not all(isinstance(t, str) for t in triggers):
        raise TokenError("token missing well-formed 'triggers' scope")

    try:
        return UploadGrant(
            guard_companion_id=str(claims["companion"]),
            device_id=str(claims["sub"]),
            owner_id=str(claims["owner"]),
            guard_epoch=int(claims["epoch"]),
            authorized_triggers=frozenset(triggers),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise TokenError(f"token missing/invalid claim: {exc}") from exc


def authorize_trigger(grant: UploadGrant, trigger: str) -> None:
    """Enforce use-level authorization: the trigger must be in the token scope."""
    if trigger not in grant.authorized_triggers:
        raise TokenError(f"trigger {trigger!r} not authorized by token")


def context_from_grant(
    grant: UploadGrant, *, trigger: str, correlation_id: str, ts_ms: int
) -> BurstContext:
    return BurstContext(
        guard_companion_id=grant.guard_companion_id,
        device_id=grant.device_id,
        guard_epoch=grant.guard_epoch,
        trigger=trigger,
        correlation_id=correlation_id,
        ts_ms=ts_ms,
    )
