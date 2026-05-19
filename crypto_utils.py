"""
crypto_utils.py — InfoCord Note Encryption Layer
=================================================
Provides AES-256-GCM encryption/decryption for note content.

Design principles:
  - The database NEVER stores plaintext note content.
  - Each note gets a unique 12-byte IV (nonce), generated with
    cryptographically secure randomness.
  - The encryption key is loaded from the environment (NOTE_ENCRYPTION_KEY)
    and never hardcoded.
  - AES-GCM provides authenticated encryption: tampering with ciphertext
    is detected and raises an error before any data is returned.

Why AES-GCM?
  - Authenticated encryption: guarantees both confidentiality AND integrity.
    If ciphertext is tampered with, decryption raises InvalidTag — not
    silently returning garbage data the way CBC/ECB would.
  - GCM (Galois/Counter Mode) is parallelizable and fast.
  - 256-bit key provides strong security margin.
  - Widely audited; used in TLS 1.3, Signal, and most modern E2EE systems.

Why must IVs/nonces be unique?
  - AES-GCM security completely breaks down if the same (key, IV) pair is
    ever reused. An attacker who observes two ciphertexts encrypted with the
    same key + IV can XOR them to eliminate the keystream and recover both
    plaintexts. Always generate a fresh random IV per encryption operation.

What to store in the database:
  ✅ Store:  ciphertext (base64), IV/nonce (base64)
  ❌ Never:  plaintext, encryption key, derived key material, passwords
"""

import base64
import logging
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

IV_LENGTH_BYTES = 12       # 96-bit nonce — NIST recommended size for AES-GCM
KEY_ENV_VAR     = "NOTE_ENCRYPTION_KEY"


# ── Key loading ───────────────────────────────────────────────────────────────

def _load_key() -> bytes:
    """
    Load and validate the AES-256 encryption key from the environment.

    The key must be a 32-byte (256-bit) value stored as a base64 string
    in the NOTE_ENCRYPTION_KEY environment variable.

    Raises:
        EnvironmentError: If the variable is missing or the key is the
                          wrong length after decoding.
    """
    raw = os.environ.get(KEY_ENV_VAR)

    if not raw:
        raise EnvironmentError(
            f"Missing required environment variable: {KEY_ENV_VAR}. "
            "Run: python -c \"import secrets, base64; "
            "print(base64.b64encode(secrets.token_bytes(32)).decode())\" "
            "to generate one."
        )

    try:
        key_bytes = base64.b64decode(raw)
    except Exception:
        raise EnvironmentError(
            f"{KEY_ENV_VAR} is not valid base64."
        )

    if len(key_bytes) != 32:
        raise EnvironmentError(
            f"{KEY_ENV_VAR} must decode to exactly 32 bytes (AES-256). "
            f"Got {len(key_bytes)} bytes."
        )

    return key_bytes


# ── Core functions ────────────────────────────────────────────────────────────

def generate_iv() -> str:
    """
    Generate a cryptographically secure 12-byte IV suitable for AES-GCM.

    Returns:
        str: Base64-encoded IV string (stored in the `iv` column).

    Notes:
        - os.urandom() uses the OS CSPRNG (/dev/urandom on Linux/macOS,
          CryptGenRandom on Windows). It is safe for cryptographic use.
        - 12 bytes (96 bits) is the NIST-recommended nonce size for GCM.
          Other sizes require GHASH computation and are less efficient.
        - Never reuse an IV with the same key. Each encrypt_note() call
          must generate a fresh IV.
    """
    iv_bytes = os.urandom(IV_LENGTH_BYTES)
    return base64.b64encode(iv_bytes).decode("utf-8")


def encrypt_note(plaintext: str) -> tuple[str, str]:
    """
    Encrypt a plaintext note using AES-256-GCM.

    Args:
        plaintext: The raw note content to encrypt.

    Returns:
        tuple[str, str]: (ciphertext_b64, iv_b64)
            - ciphertext_b64: Base64-encoded encrypted content (store in `content` column).
            - iv_b64:         Base64-encoded IV/nonce (store in `iv` column).

    Raises:
        EnvironmentError: If NOTE_ENCRYPTION_KEY is missing or malformed.
        TypeError:        If plaintext is not a string.

    Security notes:
        - A fresh IV is generated on every call. Never pass your own IV in.
        - AES-GCM appends a 16-byte authentication tag to the ciphertext
          automatically. The `cryptography` library handles this transparently.
        - The returned ciphertext includes the tag; do not strip it.
    """
    if not isinstance(plaintext, str):
        raise TypeError(f"encrypt_note() expects a str, got {type(plaintext).__name__}")

    key     = _load_key()
    iv_b64  = generate_iv()
    iv_bytes = base64.b64decode(iv_b64)

    aesgcm = AESGCM(key)
    ciphertext_bytes = aesgcm.encrypt(iv_bytes, plaintext.encode("utf-8"), None)

    ciphertext_b64 = base64.b64encode(ciphertext_bytes).decode("utf-8")
    return ciphertext_b64, iv_b64


def decrypt_note(ciphertext_b64: str, iv_b64: str) -> str:
    """
    Decrypt an AES-256-GCM encrypted note.

    Args:
        ciphertext_b64: Base64-encoded ciphertext (from `content` column).
        iv_b64:         Base64-encoded IV/nonce (from `iv` column).

    Returns:
        str: The original plaintext note content.

    Raises:
        EnvironmentError:   If NOTE_ENCRYPTION_KEY is missing or malformed.
        ValueError:         If ciphertext or IV are missing, not valid base64,
                            or the ciphertext has been tampered with (InvalidTag).

    Security notes:
        - AES-GCM authentication tag verification happens automatically.
          If the ciphertext was altered in any way, InvalidTag is raised
          and no data is returned. This protects against bit-flipping attacks.
        - Never log or expose the raw exception message to end users —
          return a generic error instead (see route handler below).
    """
    if not ciphertext_b64 or not iv_b64:
        raise ValueError("decrypt_note() requires both ciphertext and IV.")

    try:
        ciphertext_bytes = base64.b64decode(ciphertext_b64)
        iv_bytes         = base64.b64decode(iv_b64)
    except Exception:
        raise ValueError("ciphertext or IV is not valid base64.")

    key = _load_key()
    aesgcm = AESGCM(key)

    try:
        plaintext_bytes = aesgcm.decrypt(iv_bytes, ciphertext_bytes, None)
    except InvalidTag:
        # Log server-side for monitoring, but never expose internals to callers.
        logger.error(
            "AES-GCM authentication tag verification failed. "
            "The ciphertext may have been tampered with or the key has changed."
        )
        raise ValueError(
            "Note decryption failed: invalid or tampered ciphertext."
        )

    return plaintext_bytes.decode("utf-8")
