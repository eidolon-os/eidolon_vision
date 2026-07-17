from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from eidolon_vision.core import auth


def _keypair() -> tuple[object, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    from cryptography.hazmat.primitives import serialization

    pub_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return key, pub_pem


def _token(key, *, triggers=("fatigue_sample",), exp_delta=300, aud="eidolon_vision") -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": "atk-1",
            "companion": "guard-owner-1",
            "owner": "manson",
            "epoch": 3,
            "triggers": list(triggers),
            "aud": aud,
            "iat": now,
            "exp": now + exp_delta,
        },
        key,
        algorithm="RS256",
    )


def test_valid_token_yields_grant() -> None:
    key, pub = _keypair()
    grant = auth.verify_upload_token(_token(key), hub_public_key=pub)
    assert grant.device_id == "atk-1"
    assert grant.guard_companion_id == "guard-owner-1"
    assert "fatigue_sample" in grant.authorized_triggers
    auth.authorize_trigger(grant, "fatigue_sample")  # no raise


def test_unauthorized_trigger_rejected() -> None:
    key, pub = _keypair()
    grant = auth.verify_upload_token(_token(key, triggers=("fatigue_sample",)), hub_public_key=pub)
    with pytest.raises(auth.TokenError):
        auth.authorize_trigger(grant, "user_look")


def test_expired_token_rejected() -> None:
    key, pub = _keypair()
    with pytest.raises(auth.TokenError):
        auth.verify_upload_token(_token(key, exp_delta=-10), hub_public_key=pub)


def test_wrong_audience_rejected() -> None:
    key, pub = _keypair()
    with pytest.raises(auth.TokenError):
        auth.verify_upload_token(_token(key, aud="something_else"), hub_public_key=pub)


def test_wrong_key_rejected() -> None:
    key, _pub = _keypair()
    _other, other_pub = _keypair()
    with pytest.raises(auth.TokenError):
        auth.verify_upload_token(_token(key), hub_public_key=other_pub)
