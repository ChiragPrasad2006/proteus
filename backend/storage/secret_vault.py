"""At-rest protection for mailbox secrets (Windows DPAPI first, local fallbacks next).

The Gmail app password captured by the connect-app-password endpoint must never
be stored in plaintext and must never be printed or returned by any API
endpoint. ``protect_secret`` writes an opaque, scheme-tagged blob into the
account's own directory using the strongest scheme available on the machine:

1. ``dpapi:``  - Windows DPAPI (CryptProtectData, user-scoped) via ``ctypes``.
   No third-party dependency; the blob only decrypts under the same Windows
   user profile that created it.
2. ``fernet:`` - ``cryptography`` Fernet with a per-account random key file.

If neither Windows DPAPI nor Fernet is available, storage fails closed rather
than downgrading a mailbox password to reversible obfuscation.

``reveal_secret`` reverses whichever scheme produced the token. Neither
function logs or returns intermediate secrets.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import os
import sys
from pathlib import Path

# App-specific entropy so DPAPI blobs cannot be decrypted by another
# application running under the same Windows user.
_DPAPI_ENTROPY = b"Proteus/app-password/v1"
_KEY_FILENAME = "app_password.key"

PREFIX_DPAPI = "dpapi:"
PREFIX_FERNET = "fernet:"

_CRYPTPROTECT_UI_FORBIDDEN = 0x1


# --- Windows DPAPI via ctypes (no third-party dependency) -------------------

class _DataBlob(ctypes.Structure):
    """CRYPTOAPI BLOB: ``{ DWORD cbData; BYTE* pbData; }``."""

    _fields_ = [
        ("cbData", ctypes.c_uint),
        ("pbData", ctypes.c_void_p),
    ]


def _blob_in(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    """Wrap ``data`` in a BLOB; the buffer must be kept alive by the caller."""
    buffer = ctypes.create_string_buffer(data, len(data))
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.c_void_p))
    return blob, buffer


def _dpapi_protect(secret: str) -> str:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),      # pDataIn
        ctypes.c_wchar_p,               # szDataDescr
        ctypes.POINTER(_DataBlob),      # pOptionalEntropy
        ctypes.c_void_p,                # pvReserved
        ctypes.c_void_p,                # pPromptStruct
        ctypes.c_uint,                  # dwFlags
        ctypes.POINTER(_DataBlob),      # pDataOut
    ]
    crypt32.CryptProtectData.restype = ctypes.c_int

    plain_blob, plain_keep = _blob_in(secret.encode("utf-8"))
    entropy_blob, entropy_keep = _blob_in(_DPAPI_ENTROPY)
    out_blob = _DataBlob(0, None)
    try:
        ok = crypt32.CryptProtectData(
            ctypes.byref(plain_blob),
            None,
            ctypes.byref(entropy_blob),
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        if not ok:
            raise OSError(f"CryptProtectData failed (GetLastError={kernel32.GetLastError()})")
        data = ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(ctypes.c_void_p(out_blob.pbData))
    return PREFIX_DPAPI + base64.b64encode(data).decode("ascii")


def _dpapi_reveal(token: str) -> str:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),      # pDataIn
        ctypes.POINTER(ctypes.c_void_p),  # ppszDataDescr
        ctypes.POINTER(_DataBlob),      # pOptionalEntropy
        ctypes.c_void_p,                # pvReserved
        ctypes.c_void_p,                # pPromptStruct
        ctypes.c_uint,                  # dwFlags
        ctypes.POINTER(_DataBlob),      # pDataOut
    ]
    crypt32.CryptUnprotectData.restype = ctypes.c_int

    raw = base64.b64decode(token[len(PREFIX_DPAPI):])
    cipher_blob, cipher_keep = _blob_in(raw)
    entropy_blob, entropy_keep = _blob_in(_DPAPI_ENTROPY)
    out_blob = _DataBlob(0, None)
    descr = ctypes.c_void_p()
    try:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(cipher_blob),
            ctypes.byref(descr),
            ctypes.byref(entropy_blob),
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        if not ok:
            raise OSError(f"CryptUnprotectData failed (GetLastError={kernel32.GetLastError()})")
        data = ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(ctypes.c_void_p(out_blob.pbData))
        if descr.value:
            kernel32.LocalFree(ctypes.c_void_p(descr.value))
    return data.decode("utf-8")


# --- Shared per-account key handling ----------------------------------------

def _harden_file(path: Path) -> None:
    """Best-effort restrictive permissions (no-op semantics on Windows FAT/NTFS ACLs)."""
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _load_or_create_key(key_file: Path) -> bytes:
    if key_file.exists():
        try:
            key = base64.b64decode(key_file.read_text(encoding="ascii").strip())
            if len(key) >= 16:
                return key
        except Exception:
            pass  # Corrupt key file: rotate it below.
    key = os.urandom(32)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(base64.b64encode(key).decode("ascii"), encoding="ascii")
    _harden_file(key_file)
    return key


# --- Fernet tier (needs `cryptography`) --------------------------------------

def _protect_fernet(secret: str, key_file: Path) -> str:
    from cryptography.fernet import Fernet

    key = _load_or_create_key(key_file)
    token = Fernet(key).encrypt(secret.encode("utf-8"))
    return PREFIX_FERNET + token.decode("ascii")


def _reveal_fernet(token: str, key_file: Path) -> str:
    from cryptography.fernet import Fernet, InvalidToken

    key = _load_or_create_key(key_file)
    try:
        plain = Fernet(key).decrypt(token[len(PREFIX_FERNET):].encode("ascii"))
    except InvalidToken as exc:
        raise ValueError("Stored app password cannot be decrypted with this account key.") from exc
    return plain.decode("utf-8")


# --- Public API ---------------------------------------------------------------

def protect_secret(secret: str, key_dir: Path) -> str:
    """Protect ``secret`` at rest and return an opaque scheme-tagged token.

    ``key_dir`` is the directory holding the per-account key file for the
    file-based tiers (the account root for app passwords).
    """
    key_dir = Path(key_dir)
    key_dir.mkdir(parents=True, exist_ok=True)
    key_file = key_dir / _KEY_FILENAME

    failures: list[str] = []
    if sys.platform == "win32":
        try:
            return _dpapi_protect(secret)
        except Exception as exc:  # DPAPI can fail on odd profiles; fall through.
            failures.append(f"dpapi unavailable: {exc}")
    try:
        return _protect_fernet(secret, key_file)
    except Exception as exc:
        failures.append(f"fernet unavailable: {exc}")
    raise RuntimeError("No encryption scheme available: " + "; ".join(failures))


def reveal_secret(token: str, key_dir: Path) -> str:
    """Reveal a secret protected by :func:`protect_secret`."""
    key_dir = Path(key_dir)
    key_file = key_dir / _KEY_FILENAME
    if token.startswith(PREFIX_DPAPI):
        return _dpapi_reveal(token)
    if token.startswith(PREFIX_FERNET):
        return _reveal_fernet(token, key_file)
    raise ValueError("Unknown secret blob scheme.")
