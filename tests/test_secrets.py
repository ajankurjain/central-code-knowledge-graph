"""Fernet wrapper round-trips and rejects tampered ciphertext."""

from __future__ import annotations

import os

from cryptography.fernet import Fernet


def _setup_key() -> None:
    os.environ["CKG_SECRET_KEY"] = Fernet.generate_key().decode()
    # The settings object is lru_cached — clear it so the new key is picked up.
    from ckg.config import get_settings

    get_settings.cache_clear()
    from ckg.secrets import _fernet

    _fernet.cache_clear()


def test_encrypt_decrypt_roundtrip():
    _setup_key()
    from ckg.secrets import decrypt, encrypt

    # Fake placeholder used only as round-trip input (audit-script allowlisted).
    plain = "ghp_REPLACE_WITH_REAL_TOKEN_placeholder_value_for_test"
    enc = encrypt(plain)
    assert enc != plain
    assert decrypt(enc) == plain


def test_encrypt_empty_returns_empty():
    _setup_key()
    from ckg.secrets import decrypt, encrypt

    assert encrypt("") == ""
    assert decrypt("") == ""


def test_decrypt_rejects_garbage():
    _setup_key()
    from ckg.secrets import decrypt

    try:
        decrypt("not-fernet")
    except ValueError:
        return
    raise AssertionError("expected ValueError on invalid token")
