from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import ScraperConfig
from .url_filter import DEFAULT_ALLOWED_TLDS, DEFAULT_DOMAIN_KEYWORD_BLACKLIST

# Limit spec file size to avoid DoS from huge/malicious files
MAX_SPEC_FILE_BYTES = 2 * 1024 * 1024  # 2 MiB

# Navigation bounds to prevent excessive iteration/recursion from spec or CLI
MAX_GOOGLE_RESULTS = 500
MAX_LINKS_PER_PAGE = 500
MAX_SUBPAGE_DEPTH = 10


@dataclass(frozen=True)
class AddressSpec:
    street_field: str = "street"
    zip_field: str = "plz"
    city_field: str = "city"
    min_score: int = 2


@dataclass(frozen=True)
class UrlFilterSpec:
    domain_match: str = "query_part"  # "query_part" | "any"
    allowed_tlds: tuple[str, ...] = DEFAULT_ALLOWED_TLDS
    domain_keyword_blacklist: tuple[str, ...] = DEFAULT_DOMAIN_KEYWORD_BLACKLIST
    min_query_part_len: int = 3


@dataclass(frozen=True)
class NavigationSpec:
    max_google_results: int = 20
    max_links_per_page: int = 30
    subpage_depth: int = 2


@dataclass(frozen=True)
class RelevanceSpec:
    keyword_templates: tuple[str, ...] = ("{name}", "contact", "address")
    min_total_keyword_hits: int = 6
    require_address: bool = True
    address: AddressSpec = field(default_factory=AddressSpec)


@dataclass(frozen=True)
class SearchSpec:
    query_template: str = "{name} {street} {plz} {city}"
    relevance: RelevanceSpec = field(default_factory=RelevanceSpec)
    url_filter: UrlFilterSpec = field(default_factory=UrlFilterSpec)
    navigation: NavigationSpec = field(default_factory=NavigationSpec)
    extract_phone: bool = True
    extract_email: bool = True

    @staticmethod
    def presets() -> dict[str, SearchSpec]:
        return {
            "contact": SearchSpec(),
            "keywords": SearchSpec(
                query_template="{query}",
                relevance=RelevanceSpec(
                    keyword_templates=("{keyword}",),
                    min_total_keyword_hits=1,
                    require_address=False,
                ),
                url_filter=UrlFilterSpec(domain_match="any"),
            ),
        }

    @classmethod
    def from_toml(cls, path: Path) -> tuple[SearchSpec, ScraperConfig]:
        if not path.exists():
            raise ValueError(
                f"Spec file not found: {path}\n"
                "Check the path passed to --spec. You can copy example_search_spec.toml as a starting point."
            )
        try:
            size = path.stat().st_size
        except OSError as e:
            raise ValueError(f"Cannot read spec file (permission denied or disk error): {path}") from e
        if size > MAX_SPEC_FILE_BYTES:
            raise ValueError(
                f"Spec file is too large ({size:,} bytes, maximum is {MAX_SPEC_FILE_BYTES:,} bytes): {path}"
            )
        try:
            raw = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise ValueError(
                f"Spec file is not valid UTF-8 text: {path}\n"
                "TOML files must be saved with UTF-8 encoding."
            ) from e
        try:
            data = tomllib.loads(raw)
        except tomllib.TOMLDecodeError as e:
            raise ValueError(
                f"Spec file contains invalid TOML syntax: {path}\n"
                f"Parser error: {e}\n"
                "See example_search_spec.toml for the expected format."
            ) from e
        defaults = cls()
        search_data = _as_dict(data.get("search", {}))
        relevance_data = _as_dict(search_data.pop("relevance", data.get("relevance", {})))
        url_filter_data = _as_dict(search_data.pop("url_filter", data.get("url_filter", {})))
        navigation_data = _as_dict(search_data.pop("navigation", data.get("navigation", {})))

        address_data = _as_dict(relevance_data.pop("address", data.get("address", {})))

        spec = cls(
            query_template=str(search_data.get("query_template", defaults.query_template)),
            relevance=RelevanceSpec(
                keyword_templates=_ensure_str_tuple(
                    relevance_data.get("keyword_templates"),
                    defaults.relevance.keyword_templates,
                ),
                min_total_keyword_hits=_safe_int(
                    relevance_data.get("min_total_keyword_hits"),
                    defaults.relevance.min_total_keyword_hits,
                ),
                require_address=_safe_bool(
                    relevance_data.get("require_address"),
                    defaults.relevance.require_address,
                ),
                address=AddressSpec(
                    street_field=str(
                        address_data.get("street_field", defaults.relevance.address.street_field)
                    ),
                    zip_field=str(
                        address_data.get("zip_field", defaults.relevance.address.zip_field)
                    ),
                    city_field=str(
                        address_data.get("city_field", defaults.relevance.address.city_field)
                    ),
                    min_score=_safe_int(
                        address_data.get("min_score"),
                        defaults.relevance.address.min_score,
                    ),
                ),
            ),
            url_filter=UrlFilterSpec(
                domain_match=str(
                    url_filter_data.get("domain_match", defaults.url_filter.domain_match)
                ),
                allowed_tlds=_ensure_str_tuple(
                    url_filter_data.get("allowed_tlds"),
                    defaults.url_filter.allowed_tlds,
                ),
                domain_keyword_blacklist=_ensure_str_tuple(
                    url_filter_data.get("domain_keyword_blacklist"),
                    defaults.url_filter.domain_keyword_blacklist,
                ),
                min_query_part_len=_safe_int(
                    url_filter_data.get("min_query_part_len"),
                    defaults.url_filter.min_query_part_len,
                ),
            ),
            navigation=NavigationSpec(
                max_google_results=_clamp(
                    _safe_int(
                        navigation_data.get("max_google_results"),
                        defaults.navigation.max_google_results,
                    ),
                    1,
                    MAX_GOOGLE_RESULTS,
                ),
                max_links_per_page=_clamp(
                    _safe_int(
                        navigation_data.get("max_links_per_page"),
                        defaults.navigation.max_links_per_page,
                    ),
                    1,
                    MAX_LINKS_PER_PAGE,
                ),
                subpage_depth=_clamp(
                    _safe_int(
                        navigation_data.get("subpage_depth"),
                        defaults.navigation.subpage_depth,
                    ),
                    0,
                    MAX_SUBPAGE_DEPTH,
                ),
            ),
            extract_phone=_safe_bool(
                search_data.get("extract_phone"),
                defaults.extract_phone,
            ),
            extract_email=_safe_bool(
                search_data.get("extract_email"),
                defaults.extract_email,
            ),
        )

        scraper_cfg = ScraperConfig.from_mapping(_as_dict(data.get("selenium", {})))
        return spec, scraper_cfg


def render_template(template: str, row: dict[str, str]) -> str:
    try:
        return template.format_map(row)
    except KeyError as exc:
        available = ", ".join(sorted(row.keys()))
        raise ValueError(
            f"Template placeholder {exc!s} not found in your CSV columns.\n"
            f"  Template:          {template}\n"
            f"  Available columns: {available}\n"
            "Check that the placeholder name matches a column in your CSV. "
            "If your CSV has no header, use --columns to define column names."
        ) from exc


def render_templates(templates: tuple[str, ...], row: dict[str, str]) -> list[str]:
    return [render_template(t, row) for t in templates]


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def clamp_navigation(
    max_google_results: int,
    max_links_per_page: int,
    subpage_depth: int,
) -> NavigationSpec:
    """Return a NavigationSpec with values clamped to allowed bounds."""
    return NavigationSpec(
        max_google_results=_clamp(max_google_results, 1, MAX_GOOGLE_RESULTS),
        max_links_per_page=_clamp(max_links_per_page, 1, MAX_LINKS_PER_PAGE),
        subpage_depth=_clamp(subpage_depth, 0, MAX_SUBPAGE_DEPTH),
    )


def _safe_int(value: Any, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    try:
        return bool(value)
    except (TypeError, ValueError):
        return default


def _ensure_str_tuple(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    """Normalize TOML value to tuple[str]: single string -> one-element tuple, list -> tuple."""
    if value is None or (isinstance(value, (list, tuple)) and len(value) == 0):
        return default
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(x) for x in value)
    return (str(value),)
