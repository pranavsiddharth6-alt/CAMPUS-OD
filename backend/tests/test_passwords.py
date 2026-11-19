import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from argon2.exceptions import HashingError
from pwdlib.exceptions import PwdlibError

from app.core.passwords import MAX_PASSWORD_BYTES, hash_password, verify_password
from app.models.enums import UserRole
from app.schemas.user import UserCreate, UserResponse


class PasswordTests(unittest.TestCase):
    password = "a synthetic password for unit tests"

    @classmethod
    def setUpClass(cls):
        cls.stored_hash = hash_password(cls.password)

    def test_correct_password(self):
        self.assertTrue(self.stored_hash.startswith("$argon2id$"))
        self.assertLessEqual(len(self.stored_hash), 255)
        self.assertTrue(verify_password(self.password, self.stored_hash))

    def test_incorrect_password(self):
        self.assertFalse(verify_password("different password", self.stored_hash))

    def test_hashing_uses_a_fresh_salt(self):
        second_hash = hash_password(self.password)
        self.assertNotEqual(self.stored_hash.split("$")[4], second_hash.split("$")[4])
        self.assertNotEqual(self.stored_hash, second_hash)
        self.assertTrue(verify_password(self.password, second_hash))

    def test_malformed_or_unsupported_hashes(self):
        malformed_hashes = (
            "",
            "not a password hash",
            "$argon2id$v=19$m=broken,t=3,p=4$bad$bad",
            "$argon2id$v=19$m=65536,t=3,p=4$invalid!$invalid!",
            self.stored_hash.replace("$argon2id$", "$argon2i$"),
            self.stored_hash + "\x00suffix",
            self.stored_hash + "é",
        )
        for case, malformed in enumerate(malformed_hashes):
            with self.subTest(case=case):
                self.assertFalse(verify_password(self.password, malformed))

    def test_excessive_hash_cost_is_rejected_before_native_verification(self):
        excessive_hash = self.stored_hash.replace("m=65536,", "m=1073741824,")
        with patch("app.core.passwords._hasher.verify") as native_verify:
            self.assertFalse(verify_password(self.password, excessive_hash))
            native_verify.assert_not_called()

    def test_unicode_passwords(self):
        password = "கல்லூரி–café–🔐"
        self.assertTrue(verify_password(password, hash_password(password)))

    def test_password_input_limits_are_measured_in_utf8_bytes(self):
        password = "é" * (MAX_PASSWORD_BYTES // 2)
        stored_hash = hash_password(password)
        self.assertTrue(verify_password(password, stored_hash))

        for invalid in ("", password + "a", "\ud800"):
            with self.subTest(length=len(invalid)):
                with self.assertRaises(ValueError):
                    hash_password(invalid)
                self.assertFalse(verify_password(invalid, stored_hash))

    def test_helpers_do_not_emit_passwords_or_hashes(self):
        output = io.StringIO()
        with self.assertNoLogs(level="DEBUG"), redirect_stdout(output), redirect_stderr(output):
            self.assertNotIn(self.password, hash_password(self.password))
            self.assertFalse(verify_password(self.password, self.password))
        self.assertEqual(output.getvalue(), "")

    def test_hashing_failure_has_a_safe_message(self):
        for error_type in (HashingError, PwdlibError):
            with self.subTest(error_type=error_type.__name__):
                with patch("app.core.passwords._hasher.hash", side_effect=error_type(self.password)):
                    with self.assertRaisesRegex(RuntimeError, r"^Password hashing failed\.$"):
                        hash_password(self.password)

    def test_user_schemas_mask_input_and_omit_credentials_from_responses(self):
        user_input = UserCreate(
            email="student@example.com", role=UserRole.STUDENT, password=self.password
        )
        self.assertNotIn(self.password, repr(user_input))
        self.assertNotIn(self.password, user_input.model_dump_json())

        now = datetime.now(timezone.utc)
        user = SimpleNamespace(
            id=uuid4(), email=user_input.email, role=user_input.role, is_active=True,
            created_at=now, updated_at=now, password=self.password, hashed_password=self.stored_hash,
        )
        response = UserResponse.model_validate(user)
        self.assertNotIn("password", response.model_dump())
        self.assertNotIn("hashed_password", response.model_dump())
        self.assertNotIn(self.stored_hash, response.model_dump_json())
