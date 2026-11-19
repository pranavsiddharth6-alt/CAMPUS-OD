"""Argon2id password hashing for college-managed accounts."""

from argon2 import Type, extract_parameters
from argon2.exceptions import HashingError, InvalidHashError, VerificationError
from pwdlib.exceptions import PwdlibError
from pwdlib.hashers.argon2 import Argon2Hasher

MAX_PASSWORD_BYTES = 1024
MIN_NEW_PASSWORD_LENGTH = 15
_MAX_HASH_LENGTH = 255
_ARGON2_VERSION = 19
_MEMORY_COST = 64 * 1024  # KiB
_TIME_COST = 3
_PARALLELISM = 4

_hasher = Argon2Hasher(
    memory_cost=_MEMORY_COST, time_cost=_TIME_COST, parallelism=_PARALLELISM, type=Type.ID
)


def _password_bytes(plain_password: str) -> bytes:
    error = f"Password must contain 1 to {MAX_PASSWORD_BYTES} UTF-8 bytes."
    if not isinstance(plain_password, str) or not 1 <= len(plain_password) <= MAX_PASSWORD_BYTES:
        raise ValueError(error)

    try:
        encoded = plain_password.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(error) from None
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError(error)
    return encoded


def hash_password(plain_password: str) -> str:
    """Hash a password with Argon2id and a fresh, random salt."""
    password = _password_bytes(plain_password)
    try:
        return _hasher.hash(password)
    except (HashingError, PwdlibError):
        raise RuntimeError("Password hashing failed.") from None


def hash_new_password(plain_password: str) -> str:
    if len(plain_password) < MIN_NEW_PASSWORD_LENGTH:
        raise ValueError("Use a password of at least 15 characters.")
    return hash_password(plain_password)


def verify_password(plain_password: str, stored_hash: str | None) -> bool:
    """Return False for invalid inputs, unsupported hashes, or a mismatch."""
    if (
        not isinstance(stored_hash, str)
        or not 1 <= len(stored_hash) <= _MAX_HASH_LENGTH
        or not stored_hash.isascii()
        or "\x00" in stored_hash
    ):
        return False

    try:
        parameters = extract_parameters(stored_hash)
        # A malformed hash must not request more work than a newly generated hash.
        if not (
            parameters.type is Type.ID
            and parameters.version == _ARGON2_VERSION
            and 0 < parameters.memory_cost <= _MEMORY_COST
            and 0 < parameters.time_cost <= _TIME_COST
            and 0 < parameters.parallelism <= _PARALLELISM
        ):
            return False
        return _hasher.verify(_password_bytes(plain_password), stored_hash)
    except (InvalidHashError, VerificationError, PwdlibError, ValueError):
        return False
