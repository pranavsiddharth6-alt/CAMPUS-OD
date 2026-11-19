import os
import secrets
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

import jwt
from pydantic import SecretStr

from app.core.access_tokens import (
    InvalidAccessTokenError,
    JWTConfigurationError,
    create_access_token,
    verify_access_token,
)
from app.core.config import Settings


class AccessTokenTests(unittest.TestCase):
    def setUp(self):
        self.secret = secrets.token_urlsafe(48)
        self.settings = Settings(
            _env_file=None,
            JWT_SIGNING_SECRET=self.secret,
            JWT_ISSUER="campus-od-test",
            JWT_AUDIENCE="campus-od-test-api",
            JWT_ALGORITHM="HS256",
            JWT_ACCESS_TOKEN_MINUTES=10,
        )
        config = patch("app.core.access_tokens.settings", self.settings)
        config.start()
        self.addCleanup(config.stop)

        self.user_id, self.session_id = uuid4(), uuid4()
        self.now = int(time.time())
        self.payload = {
            "sub": str(self.user_id), "sid": str(self.session_id), "jti": str(uuid4()),
            "iss": self.settings.JWT_ISSUER, "aud": self.settings.JWT_AUDIENCE,
            "iat": self.now - 20, "nbf": self.now - 15, "exp": self.now + 600,
        }

    def sign(self, payload=None, *, secret=None, algorithm="HS256", token_type="at+jwt"):
        key = None if algorithm == "none" else secret or self.secret
        return jwt.encode(
            self.payload if payload is None else payload, key,
            algorithm=algorithm, headers={"typ": token_type},
        )

    def assert_invalid(self, token):
        with self.assertRaisesRegex(InvalidAccessTokenError, r"^Invalid access token\.$"):
            verify_access_token(token)

    def test_creates_and_verifies_expected_claims(self):
        token = create_access_token(self.user_id, self.session_id)
        claims = verify_access_token(token)

        self.assertEqual((claims.sub, claims.sid), (self.user_id, self.session_id))
        self.assertEqual((claims.iss, claims.aud), (self.settings.JWT_ISSUER, self.settings.JWT_AUDIENCE))
        self.assertEqual(claims.iat, claims.nbf)
        self.assertEqual(claims.exp - claims.iat, 600)
        self.assertEqual(claims.jti.version, 4)
        self.assertEqual(jwt.get_unverified_header(token), {"alg": "HS256", "typ": "at+jwt"})

    def test_configured_lifetime_is_used(self):
        custom = self.settings.model_copy(update={"JWT_ACCESS_TOKEN_MINUTES": "15"})
        with patch("app.core.access_tokens.settings", custom):
            claims = verify_access_token(create_access_token(self.user_id, self.session_id))
        self.assertEqual(claims.exp - claims.iat, 900)

    def test_invalid_signature_is_rejected(self):
        self.assert_invalid(self.sign(secret=secrets.token_urlsafe(48)))

    def test_expired_token_is_rejected(self):
        self.assert_invalid(self.sign(self.payload | {"exp": self.now - 1}))

    def test_future_not_before_is_rejected(self):
        self.assert_invalid(self.sign(self.payload | {"nbf": self.now + 120}))

    def test_future_issued_at_and_invalid_chronology_are_rejected(self):
        for timestamps in ({"iat": self.now + 60, "nbf": self.now + 60}, {"iat": self.now - 1}):
            with self.subTest(timestamps=timestamps):
                self.assert_invalid(self.sign(self.payload | timestamps))

    def test_wrong_issuer_or_audience_is_rejected(self):
        for claim, value in (("iss", "other-issuer"), ("aud", "other-api"), ("aud", [self.settings.JWT_AUDIENCE])):
            with self.subTest(claim=claim):
                self.assert_invalid(self.sign(self.payload | {claim: value}))

    def test_all_claims_are_required(self):
        for claim in self.payload:
            with self.subTest(claim=claim):
                self.assert_invalid(self.sign({key: value for key, value in self.payload.items() if key != claim}))

    def test_invalid_uuids_are_rejected(self):
        for claim in ("sub", "sid", "jti"):
            for value in ("not-a-uuid", 123, None):
                with self.subTest(claim=claim, value=value):
                    self.assert_invalid(self.sign(self.payload | {claim: value}))

    def test_timestamp_claims_must_be_integers(self):
        for claim in ("iat", "nbf", "exp"):
            for value in (str(self.payload[claim]), float(self.payload[claim]), True, None):
                with self.subTest(claim=claim, value=value):
                    self.assert_invalid(self.sign(self.payload | {claim: value}))

    def test_unsigned_tokens_and_unexpected_algorithms_are_rejected(self):
        self.assert_invalid(self.sign(algorithm="none"))
        self.assert_invalid(self.sign(algorithm="HS512"))

    def test_wrong_token_type_is_rejected(self):
        self.assert_invalid(self.sign(token_type="JWT"))

    def test_malformed_jwt_returns_generic_error(self):
        for malformed in ("not-a-token", "a.b.c", "a.b.", "a.b.c=", "a.b." + "c" * 4096):
            with self.subTest(length=len(malformed)):
                self.assert_invalid(malformed)

    def test_separately_issued_tokens_have_distinct_jtis(self):
        first = verify_access_token(create_access_token(self.user_id, self.session_id))
        second = verify_access_token(create_access_token(self.user_id, self.session_id))
        self.assertNotEqual(first.jti, second.jti)

    def test_payload_contains_only_identity_and_lifecycle_claims(self):
        token = create_access_token(self.user_id, self.session_id)
        payload = jwt.decode(
            token, self.secret, algorithms=["HS256"],
            issuer=self.settings.JWT_ISSUER, audience=self.settings.JWT_AUDIENCE,
        )
        self.assertEqual(set(payload), {"sub", "sid", "iss", "aud", "iat", "nbf", "exp", "jti"})
        for extra in ("role", "password", "refresh_token", "documents", "gps"):
            with self.subTest(extra=extra):
                self.assert_invalid(self.sign(self.payload | {extra: "disallowed"}))

    def test_rejects_invalid_configuration_for_signing_and_verification(self):
        token = self.sign()
        configurations = (
            ("JWT_SIGNING_SECRET", None),
            ("JWT_SIGNING_SECRET", SecretStr("short")),
            ("JWT_SIGNING_SECRET", SecretStr(" " * 32)),
            ("JWT_ISSUER", ""),
            ("JWT_AUDIENCE", "invalid audience"),
            ("JWT_ALGORITHM", "HS512"),
            ("JWT_ACCESS_TOKEN_MINUTES", "invalid"),
            ("JWT_ACCESS_TOKEN_MINUTES", 0),
            ("JWT_ACCESS_TOKEN_MINUTES", 61),
        )
        for setting, value in configurations:
            with self.subTest(setting=setting):
                config = self.settings.model_copy(update={setting: value})
                with patch("app.core.access_tokens.settings", config):
                    with self.assertRaises(JWTConfigurationError):
                        create_access_token(self.user_id, self.session_id)
                    with self.assertRaises(JWTConfigurationError):
                        verify_access_token(token)

    def test_backend_settings_load_without_valid_jwt_configuration(self):
        with patch.dict(os.environ, {"JWT_ACCESS_TOKEN_MINUTES": "invalid"}, clear=True):
            config = Settings(_env_file=None)
        self.assertIsNone(config.JWT_SIGNING_SECRET)
        self.assertEqual(config.JWT_ACCESS_TOKEN_MINUTES, "invalid")
        self.assertFalse(self.secret in repr(self.settings))
        self.assertFalse(self.secret in self.settings.model_dump_json())
