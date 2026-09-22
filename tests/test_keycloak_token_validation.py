"""Token-verification contract tests for `src.keycloak_auth.validator`.

WHY THIS FILE EXISTS. `validate_token` was the only place this repository used `python-jose`,
and `python-jose` is the sole parent of `ecdsa`, whose PYSEC-2026-1325 has **no fix version** --
so `pip-audit` could never go green while it stayed. Dropping it in favour of PyJWT (already a
direct dependency, already used in `src/auth.py`) is mechanical, but the Keycloak auth path
carried **zero** test coverage: nothing in CI could tell a correct swap from one that silently
stopped verifying. A quietly accepted bad token is the worst outcome this service can produce,
so the swap ships with the tests that would catch it.

The four cases are chosen to fail if the migration went wrong in the four ways it could:

  1. a valid RS256 token is still accepted and its claims returned;
  2. an expired token still raises -- `options["verify_exp"]` is still honoured;
  3. a token signed by a DIFFERENT key raises -- signature verification is not skipped;
  4. an HS256 token signed with the PUBLIC key as its secret raises `InvalidAlgorithmError` --
     the classic algorithm confusion attack, which `algorithms=["RS256"]` is what prevents;
  5. a token whose `iat` is in the FUTURE is still ACCEPTED -- jose never verified `iat`, PyJWT
     does by default, and that divergence would turn one second of Keycloak clock skew into a
     total auth outage (see the comment on `verify_iat` in validator.py);
  6. the PEM shape production actually builds -- a single-line base64 body, not the 64-column
     wrapping a test would naturally produce -- is accepted.

All four were verified by mutation, not by inspection: flipping `verify_signature` to False fails
2 of them, `verify_exp` to False fails 1, and widening the allow-list to include HS256 fails case
4 (which is why that case asserts the specific exception -- see its own docstring). `pyjwt[crypto]`
is declared with its extra for the same reason: without `cryptography` PyJWT cannot verify RS256
at all, so case 1 fails loudly rather than the service failing silently in production.
"""

import asyncio
import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import InvalidAlgorithmError, PyJWTError

from src.keycloak_auth.validator import KeycloakTokenValidator


def _keypair() -> tuple[str, str]:
    """Return (private PEM, public PEM) for a throwaway RS256 key."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def _validator_for(public_pem: str) -> KeycloakTokenValidator:
    """A validator pinned to `public_pem`, so nothing reaches out to Keycloak."""
    validator = KeycloakTokenValidator()
    validator._public_key = public_pem
    return validator


def _claims(**overrides) -> dict:
    now = datetime.now(UTC)
    claims = {
        "sub": "00000000-0000-0000-0000-000000000001",
        "preferred_username": "contract-test-user",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    return claims


def test_valid_rs256_token_is_accepted_and_claims_returned():
    private_pem, public_pem = _keypair()
    token = jwt.encode(_claims(), private_pem, algorithm="RS256")

    payload = asyncio.run(_validator_for(public_pem).validate_token(token))

    assert payload["preferred_username"] == "contract-test-user"
    assert payload["sub"] == "00000000-0000-0000-0000-000000000001"


def test_expired_token_is_rejected():
    private_pem, public_pem = _keypair()
    expired = datetime.now(UTC) - timedelta(minutes=5)
    token = jwt.encode(
        _claims(iat=expired - timedelta(minutes=5), exp=expired),
        private_pem,
        algorithm="RS256",
    )

    with pytest.raises(PyJWTError):
        asyncio.run(_validator_for(public_pem).validate_token(token))


def test_token_signed_by_a_different_key_is_rejected():
    attacker_private_pem, _ = _keypair()
    _, public_pem = _keypair()
    token = jwt.encode(_claims(), attacker_private_pem, algorithm="RS256")

    with pytest.raises(PyJWTError):
        asyncio.run(_validator_for(public_pem).validate_token(token))


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _forge_hs256(claims: dict, secret: str) -> str:
    """Hand-roll an HS256 token.

    `jwt.encode` refuses to HMAC with a PEM (`InvalidKeyError`), which is a guardrail on the
    SIGNING side. An attacker does not use our library's signer, so forging the token by hand is
    what actually puts the question to the DECODER -- which is the side under test here.
    """
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    epoch_claims = {
        k: int(v.timestamp()) if isinstance(v, datetime) else v
        for k, v in claims.items()
    }
    payload = _b64(json.dumps(epoch_claims).encode())
    signing_input = f"{header}.{payload}".encode()
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64(signature)}"


def test_hs256_token_signed_with_the_public_key_is_rejected_by_the_allow_list():
    """Algorithm confusion, and the assertion is deliberately narrow.

    `pytest.raises(PyJWTError)` is NOT enough here, and a mutation probe proved it: adding
    "HS256" to the allow-list still raised -- PyJWT has its own guard that refuses a PEM as an
    HMAC secret (`InvalidKeyError`), so a broad assertion passes while the allow-list is gone.
    Asserting `InvalidAlgorithmError` is what makes this test fail when the allow-list widens,
    which is the property actually worth defending.
    """
    _, public_pem = _keypair()
    token = _forge_hs256(_claims(), public_pem)

    with pytest.raises(InvalidAlgorithmError):
        asyncio.run(_validator_for(public_pem).validate_token(token))


def test_future_iat_is_accepted_because_keycloak_stamps_it_from_its_own_clock():
    """The regression this file exists to prevent, and it is not a hypothetical.

    `python-jose` did not verify `iat`; PyJWT verifies it by default and raises
    `ImmatureSignatureError` for an `iat` in the future. Keycloak stamps `iat` from its own wall
    clock, so at PyJWT's default ONE SECOND of skew between the Keycloak pod and this service 401s
    every request from every user. This test pins the parity explicitly, because a future reader
    tidying the options dict has no other way to learn that `verify_iat: False` is load-bearing.
    """
    private_pem, public_pem = _keypair()
    now = datetime.now(UTC)
    token = jwt.encode(
        _claims(iat=now + timedelta(seconds=60), exp=now + timedelta(minutes=5)),
        private_pem,
        algorithm="RS256",
    )

    payload = asyncio.run(_validator_for(public_pem).validate_token(token))

    assert payload["preferred_username"] == "contract-test-user"


def test_the_single_line_pem_production_builds_is_accepted():
    """Production does not use a 64-column PEM.

    `KeycloakTokenValidator.get_public_key` concatenates Keycloak's `public_key()` -- one
    unwrapped base64 line -- between the BEGIN/END markers. A test that only ever feeds a
    conventionally wrapped PEM would not notice a library that rejected that shape.
    """
    private_pem, public_pem = _keypair()
    body = "".join(
        line for line in public_pem.splitlines() if not line.startswith("-----")
    )
    single_line_pem = f"-----BEGIN PUBLIC KEY-----\n{body}\n-----END PUBLIC KEY-----"
    token = jwt.encode(_claims(), private_pem, algorithm="RS256")

    payload = asyncio.run(_validator_for(single_line_pem).validate_token(token))

    assert payload["sub"] == "00000000-0000-0000-0000-000000000001"
