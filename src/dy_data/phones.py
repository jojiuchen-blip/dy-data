"""Shared phone value classification and normalization helpers.

The clue worker and API must agree on what is safe to treat as a Chinese
mobile number.  In particular, an online ``Enc.`` value is source material
for decryption, not a phone number containing a few usable digits.
"""

from __future__ import annotations

from hashlib import sha256
import re


_PHONE_ALLOWED_RE = re.compile(r"^[+0-9() .\-\t]+$")
_MASKED_PHONE_RE = re.compile(r"^1[3-9]\d\*{4}\d{4}$")
_MOBILE_RE = re.compile(r"^1[3-9]\d{9}$")
_COUNTRY_PREFIX_RE = re.compile(r"^(?:\+86|0086)")


def is_online_cipher(value: object) -> bool:
    """Return whether *value* is an online encrypted phone payload."""

    return isinstance(value, str) and value.strip().startswith("Enc.")


def normalize_phone(value: object) -> str:
    """Normalize a formatted Chinese mobile number to eleven digits.

    Only a complete Chinese mobile number is accepted.  Formatting characters
    commonly emitted by upstream systems are ignored; arbitrary text,
    encrypted payloads, masked values, and digit substrings are rejected.
    """

    if value is None or is_online_cipher(value):
        return ""
    text = str(value).strip()
    if not text or _MASKED_PHONE_RE.fullmatch(text) or not _PHONE_ALLOWED_RE.fullmatch(text):
        return ""

    compact = re.sub(r"[\s().\-]", "", text)
    prefix = _COUNTRY_PREFIX_RE.match(compact)
    if prefix:
        compact = compact[prefix.end() :]
    if not _MOBILE_RE.fullmatch(compact):
        return ""
    return compact


def mask_phone(value: object) -> str:
    """Return the stable dashboard mask for a valid Chinese mobile number."""

    if isinstance(value, str):
        text = value.strip()
        if _MASKED_PHONE_RE.fullmatch(text):
            return text
    phone = normalize_phone(value)
    if not phone:
        return ""
    return f"{phone[:3]}****{phone[-4:]}"


def phone_source_fingerprint(
    *,
    plain_phone: object | None = None,
    cipher_text: object | None = None,
) -> str | None:
    """Return a non-reversible fingerprint for the selected phone source.

    A valid plaintext source takes precedence when both arguments are given.
    Cipher text is included verbatim only as hash input and is never returned
    or logged.  Invalid or masked values have no verified source fingerprint.
    """

    normalized = normalize_phone(plain_phone)
    if normalized:
        return sha256(f"plain:v1:{normalized}".encode("utf-8")).hexdigest()
    if is_online_cipher(cipher_text):
        source = str(cipher_text).strip()
        return sha256(f"cipher:v1:{source}".encode("utf-8")).hexdigest()
    return None
