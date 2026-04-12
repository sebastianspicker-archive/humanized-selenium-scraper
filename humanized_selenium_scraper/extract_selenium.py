from __future__ import annotations

import re
from typing import Any

from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.by import By

from .extract_text import (
    MAX_PHONE_DIGITS,
    MIN_PHONE_DIGITS,
    decode_antispam_mail,
    parse_less_generous_phones,
    parse_phone_and_email_obfuscated,
)


def _parse_meta_tags(driver: Any) -> str:
    metas = driver.find_elements(By.TAG_NAME, "meta")
    lines: list[str] = []
    for meta in metas:
        content = meta.get_attribute("content") or ""
        if content.strip():
            lines.append(content.strip())
    return "\n".join(lines)


def _parse_hidden_inputs(driver: Any) -> str:
    hiddens = driver.find_elements(By.CSS_SELECTOR, "input[type='hidden']")
    values: list[str] = []
    for hidden in hiddens:
        value = hidden.get_attribute("value") or ""
        if value.strip():
            values.append(value.strip())
    return "\n".join(values)


def parse_phone_email_deep(driver: Any) -> tuple[str | None, str | None]:
    page_src = driver.page_source
    meta_txt = _parse_meta_tags(driver)
    hidden_txt = _parse_hidden_inputs(driver)
    combined = "\n".join([page_src, meta_txt, hidden_txt])

    phone_set: set[str] = set()
    mail_set: set[str] = set()

    # 1. Prioritize explicit links
    links = driver.find_elements(By.TAG_NAME, "a")
    for link in links:
        try:
            href = (link.get_attribute("href") or "").strip()
            txt = (link.text or "").strip()

            if href.lower().startswith("tel:"):
                candidate = href[4:].strip()
                digits = re.sub(r"\D", "", candidate)
                if MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS:
                    phone_set.add(candidate)
            elif href.lower().startswith("mailto:"):
                candidate = href[7:].split("?")[0].strip()
                if "@" in candidate and "." in candidate:
                    mail_set.add(candidate)
            elif "linkdecrypt" in href.lower():
                encs = re.findall(r"linkDecrypt\('([^']+)'\)", href, re.IGNORECASE)
                for enc in encs:
                    dec = decode_antispam_mail(enc)
                    if dec.startswith("mailto:"):
                        candidate = dec[7:].split("?")[0].strip()
                        if "@" in candidate and "." in candidate:
                            mail_set.add(candidate)

            if "telefon:" in txt.lower() or "tel." in txt.lower():
                for p in parse_less_generous_phones(txt):
                    digits = re.sub(r"\D", "", p)
                    if MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS:
                        phone_set.add(p.strip())
        except StaleElementReferenceException:
            continue

    # 2. Fallback to regex on whole page source
    phs, ems = parse_phone_and_email_obfuscated(combined)
    for p in phs:
        digits = re.sub(r"\D", "", p)
        if MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS:
            phone_set.add(p.strip())
    for e in ems:
        if "@" in e and "." in e and len(e) > 5:
            mail_set.add(e.strip())

    # Return first best candidates
    phone = next(iter(sorted(phone_set, key=len, reverse=True)), None)
    email = next(iter(sorted(mail_set, key=len, reverse=True)), None)
    return phone, email
