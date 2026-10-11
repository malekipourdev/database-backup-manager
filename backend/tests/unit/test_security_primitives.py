import logging

import pytest
from cryptography.fernet import Fernet

from mbp.logging import SecretRedactionFilter, register_secret
from mbp.security import crypto
from mbp.security.passwords import hash_password, needs_rehash, verify_password


def test_hash_and_verify_round_trip():
    hashed = hash_password("s3cret-Pass")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "s3cret-Pass")
    assert not needs_rehash(hashed)


def test_wrong_password_returns_false():
    assert verify_password(hash_password("right"), "wrong") is False


def test_garbage_hash_returns_false():
    assert verify_password("not-a-hash", "anything") is False


@pytest.mark.parametrize("plain", ["simple", "رمز-عبور-۱۲۳", "p@ss w0rd 🔐"])
def test_encrypt_decrypt_round_trip(plain):
    token = crypto.encrypt(plain)
    assert plain not in token
    assert crypto.decrypt(token) == plain


def test_decrypt_with_rotation_key():
    old_key = Fernet.generate_key()
    token = Fernet(old_key).encrypt(b"legacy").decode()
    rotated = crypto._build(f"{Fernet.generate_key().decode()},{old_key.decode()}")
    assert rotated.decrypt(token.encode()).decode() == "legacy"


@pytest.mark.parametrize("raw", ["", "not-a-key", " , "])
def test_invalid_key_raises(raw):
    with pytest.raises(RuntimeError, match="MBP_ENCRYPTION_KEY"):
        crypto._build(raw)


def test_log_filter_redacts_registered_secret_and_secret_keys():
    register_secret("Hunter2-Secret")
    record = logging.LogRecord(
        "t", logging.INFO, __file__, 1, "connecting with %s", ("Hunter2-Secret",), None
    )
    SecretRedactionFilter().filter(record)
    assert "Hunter2-Secret" not in record.getMessage()

    record = logging.LogRecord(
        "t", logging.INFO, __file__, 1, "payload %(password)s", ({"password": "abc"},), None
    )
    SecretRedactionFilter().filter(record)
    assert "abc" not in record.getMessage()
