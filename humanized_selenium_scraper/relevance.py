from __future__ import annotations


def normalize_address_part(text: str) -> str:
    """Lowercase and normalize for matching (umlauts, German street variants)."""
    normalized = text.lower()
    normalized = normalized.replace("ü", "u").replace("ö", "o").replace("ä", "a").replace("ß", "ss")
    normalized = (
        normalized.replace("str.", "str").replace("strasse", "str").replace("strass", "str")
    )
    return normalized


def tokenize_address_component(text: str) -> list[str]:
    normalized = normalize_address_part(text)
    return [part.strip() for part in normalized.replace("-", " ").split() if part.strip()]


def _address_score_normalized(page_normalized: str, street: str, plz: str, city: str) -> int:
    street_tokens = tokenize_address_component(street)
    zip_tokens = tokenize_address_component(plz)
    city_tokens = tokenize_address_component(city)

    score = 0
    if (
        zip_tokens
        and city_tokens
        and all(token in page_normalized for token in zip_tokens)
        and all(token in page_normalized for token in city_tokens)
    ):
        score += 2
    if street_tokens and all(token in page_normalized for token in street_tokens):
        score += 1
    return score


def address_score(page_source: str, street: str, plz: str, city: str) -> int:
    return _address_score_normalized(normalize_address_part(page_source), street, plz, city)


def _keyword_hits_normalized(page_normalized: str, keywords: list[str]) -> int:
    # Normalize keywords the same way as the page so umlauts/diacritics match.
    return sum(page_normalized.count(normalize_address_part(kw)) for kw in keywords if kw)


def keyword_hits(page_source: str, keywords: list[str]) -> int:
    return _keyword_hits_normalized(normalize_address_part(page_source), keywords)


def evaluate_page(
    page_source: str,
    *,
    keywords: list[str],
    min_keyword_hits: int,
    require_address: bool,
    street: str = "",
    plz: str = "",
    city: str = "",
    address_min_score: int = 2,
) -> bool:
    # Normalize the (potentially large) page source once and share it between the
    # keyword and address checks; each helper used to normalize it again.
    page_normalized = normalize_address_part(page_source)
    if _keyword_hits_normalized(page_normalized, keywords) < min_keyword_hits:
        return False
    if not require_address:
        return True
    return _address_score_normalized(page_normalized, street, plz, city) >= address_min_score
