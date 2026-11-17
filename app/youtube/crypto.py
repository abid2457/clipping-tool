"""Machine-bound symmetric encryption for OAuth tokens and sensitive credentials."""

from __future__ import annotations

import base64
import os
import platform
import uuid
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Fixed application-level salt ensuring stable machine-derived key
_APP_SALT = b"clipforge-v2-secure-token-vault-2026"


def _get_machine_id() -> bytes:
    """Derive stable hardware identity from node MAC address and platform."""
    node = uuid.getnode()
    system = platform.node() or platform.system()
    raw = f"{node}:{system}".encode("utf-8")
    return raw


def _get_cipher() -> Fernet:
    """Generate Fernet cipher instance derived from machine identity."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_APP_SALT,
        iterations=100_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(_get_machine_id()))
    return Fernet(key)


def encrypt_token(plain_token: str) -> str:
    """Encrypt plaintext OAuth token into secure ciphertext string."""
    if not plain_token:
        return ""
    cipher = _get_cipher()
    encrypted = cipher.encrypt(plain_token.encode("utf-8"))
    return encrypted.decode("utf-8")


def decrypt_token(encrypted_token: str) -> str:
    """Decrypt ciphertext string back into original plaintext token."""
    if not encrypted_token:
        return ""
    cipher = _get_cipher()
    decrypted = cipher.decrypt(encrypted_token.encode("utf-8"))
    return decrypted.decode("utf-8")
