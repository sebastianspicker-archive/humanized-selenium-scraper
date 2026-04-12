from __future__ import annotations


def normalize_address_part(text: str) -> str:
    """Lowercase and normalize for matching (umlauts, German street variants)."""
    normalized = text.lower()
    normalized = normalized.replace("ü", "u").replace("ö", "o").replace("ä", "a").replace("ß", "ss")
    normalized = (
        normalized.replace("str.", "str")
        .replace("strasse", "str")
        .replace("strass", "str")
        .replace("straße", "str")
    )
    return normalized


def tokenize_address_component(text: str) -> list[str]:
    normalized = normalize_address_part(text)
    return [part.strip() for part in normalized.replace("-", " ").split() if part.strip()]


def address_score(page_source: str, street: str, plz: str, city: str) -> int:
    page_normalized = normalize_address_part(page_source)
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


def is_address_present(
    page_source: str,
    street: str,
    plz: str,
    city: str,
    *,
    min_score: int = 2,
) -> bool:
    return address_score(page_source, street, plz, city) >= min_score


def keyword_hits(page_source: str, keywords: list[str]) -> int:
    page_normalized = normalize_address_part(page_source)
    return sum(page_normalized.count(kw.lower()) for kw in keywords if kw)


def has_min_keyword_hits(page_source: str, keywords: list[str], *, min_total_hits: int) -> bool:
    return keyword_hits(page_source, keywords) >= min_total_hits


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
    if not has_min_keyword_hits(page_source, keywords, min_total_hits=min_keyword_hits):
        return False
    if not require_address:
        return True
    return is_address_present(page_source, street, plz, city, min_score=address_min_score)
