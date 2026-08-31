"""Symmetric encryption for secrets at rest (user-supplied provider API keys).

Derives a Fernet key from SECRET_KEY so no extra secret needs to be managed —
rotating SECRET_KEY invalidates previously-stored keys, same as it invalidates
existing JWTs.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from settings import settings

_derived = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
_fernet = Fernet(_derived)


def encrypt_secret(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str | None:
    try:
        return _fernet.decrypt(token.encode()).decode()
    except InvalidToken:
        return None


def mask_last4(plaintext: str) -> str:
    tail = plaintext[-4:] if len(plaintext) >= 4 else plaintext
    return f"••••••••••••{tail}"
