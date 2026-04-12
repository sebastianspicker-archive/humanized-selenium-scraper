from __future__ import annotations

import re

# Constants for phone number validation
MIN_PHONE_DIGITS = 7  # Minimum digits for a valid phone number
MAX_PHONE_DIGITS = 15  # Maximum digits for a valid phone number (E.164 standard)

_NORMAL_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-\(\)]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.MULTILINE,
)

_OBF_EMAIL_RE = re.compile(
    r"([a-zA-Z0-9._%+\-]+)\s?(\(|\[)?at(\)|\])?\s?([a-zA-Z0-9.\-]+)\s?"
    r"(\(|\[)?(dot|punkt)(\)|\])?\s?([a-zA-Z]{2,})",
    re.IGNORECASE,
)

_PHONE_PREFIX_RE = re.compile(
    r"(?:tel|phone|call)[:\s]*(\+?\d{2,4}\(?\d{1,4}\)?\s?\d{3,}[\d\s/\-]*)",
    re.IGNORECASE,
)

_PHONE_SIMPLE_RE = re.compile(
    r"\+?\d{2,4}[\s./-]*\(?\d{1,4}\)?[\s./-]*\d{3,}[\d\s./-]*",
    re.IGNORECASE,
)


def decode_antispam_mail(encoded_string: str) -> str:
    def _decode_char(ch: str) -> str:
        if ord(ch) >= 1:
            return chr(ord(ch) - 1)
        return ch

    return "".join(_decode_char(ch) for ch in encoded_string)


def parse_less_generous_phones(text: str) -> set[str]:
    phones: set[str] = set()

    for match in _PHONE_PREFIX_RE.finditer(text):
        candidate = match.group(1).strip()
        digit_count = len(re.sub(r"\D", "", candidate))
        if MIN_PHONE_DIGITS <= digit_count <= MAX_PHONE_DIGITS:
            phones.add(candidate)

    for match in _PHONE_SIMPLE_RE.finditer(text):
        candidate = match.group(0).strip()
        digit_count = len(re.sub(r"\D", "", candidate))
        if MIN_PHONE_DIGITS <= digit_count <= MAX_PHONE_DIGITS:
            phones.add(candidate)

    return phones


def parse_phone_and_email_obfuscated(big_source: str) -> tuple[set[str], set[str]]:
    phones = {phone.strip() for phone in parse_less_generous_phones(big_source)}

    mails: set[str] = set()
    for match in _NORMAL_EMAIL_RE.findall(big_source):
        mails.add(match.strip())

    for match in _OBF_EMAIL_RE.finditer(big_source):
        user = match.group(1)
        dom = match.group(4)
        tld = match.group(8)
        mails.add(f"{user}@{dom}.{tld}".strip())

    return phones, mails
