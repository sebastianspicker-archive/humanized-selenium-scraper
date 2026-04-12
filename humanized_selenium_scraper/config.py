from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Allowed Google domains to prevent redirection to malicious sites
ALLOWED_GOOGLE_DOMAINS = frozenset(
    {
        "google.com",
        "google.de",
        "google.at",
        "google.ch",
        "google.co.uk",
        "google.fr",
        "google.es",
        "google.it",
        "google.nl",
        "google.be",
        "google.pl",
        "google.cz",
        "google.se",
        "google.dk",
        "google.no",
        "google.fi",
        "google.pt",
        "google.ro",
        "google.hu",
        "google.sk",
        "google.si",
        "google.hr",
        "google.bg",
        "google.gr",
        "google.ie",
        "google.lu",
        "google.lt",
        "google.lv",
        "google.ee",
    }
)


def _validate_google_domain(domain: str) -> str:
    """Validate that the domain is an allowed Google domain.

    Raises ValueError if the domain is not in the allowlist.
    """
    # Normalize: lowercase, strip whitespace and leading/trailing dots
    normalized = domain.lower().strip().strip(".")
    if normalized not in ALLOWED_GOOGLE_DOMAINS:
        allowed = ", ".join(sorted(ALLOWED_GOOGLE_DOMAINS))
        raise ValueError(
            f"Invalid Google domain: {domain!r}.\n"
            f"Use --google-domain with one of these: {allowed}"
        )
    return normalized


@dataclass(frozen=True)
class ScraperConfig:
    google_domain: str = "google.com"
    restart_threshold: int = 30
    max_retries: int = 3

    user_agents: list[str] = field(
        default_factory=lambda: [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/110.0.5481.100 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; rv:117.0) Gecko/20100101 Firefox/117.0",
            "Mozilla/5.0 (X11; Linux i686; rv:88.0) Gecko/20100101 Firefox/88.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_2) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/16.0 Safari/605.1.15",
        ]
    )
    window_sizes: list[tuple[int, int]] = field(
        default_factory=lambda: [
            (1280, 720),
            (1366, 768),
            (1920, 1080),
            (1536, 864),
            (1440, 900),
            (1600, 900),
        ]
    )

    chrome_profile_root: Path = Path("chrome_profile")
    page_load_timeout_s: int = 20
    implicit_wait_s: int = 5

    # Configurable WebDriverWait timeouts (previously hardcoded)
    element_wait_timeout_s: int = 10  # For waiting on elements to be clickable/present
    search_results_timeout_s: int = 8  # For waiting on Google search results

    def __post_init__(self) -> None:
        # Validate google_domain on instantiation
        _validate_google_domain(self.google_domain)

    def validate(self) -> None:
        """Re-validate fields set via dataclasses.replace (which skips __post_init__)."""
        _validate_google_domain(self.google_domain)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> ScraperConfig:
        if not data:
            return cls()
        defaults = cls()

        def _clamp_int(val: int, low: int, high: int) -> int:
            return max(low, min(high, val))

        def _int(key: str, default: int, min_val: int = 1, max_val: int = 3600) -> int:
            val = data.get(key, default)
            if isinstance(val, int) and not isinstance(val, bool):
                out = val
            else:
                try:
                    out = int(val) if val is not None else default
                except (TypeError, ValueError):
                    out = default
            return _clamp_int(out, min_val, max_val)

        def _path(key: str) -> Path | None:
            if key not in data:
                return None
            val = data[key]
            if isinstance(val, (str, Path)) or (hasattr(val, "__fspath__")):
                return Path(val)
            return None

        chrome_root = _path("chrome_profile_root")
        google_domain = str(data.get("google_domain", defaults.google_domain))
        # Validate will happen in __post_init__
        return cls(
            google_domain=google_domain,
            restart_threshold=_int(
                "restart_threshold",
                defaults.restart_threshold,
                min_val=0,
                max_val=1000,
            ),
            max_retries=_int("max_retries", defaults.max_retries, max_val=100),
            chrome_profile_root=chrome_root
            if chrome_root is not None
            else defaults.chrome_profile_root,
            page_load_timeout_s=_int("page_load_timeout_s", defaults.page_load_timeout_s),
            implicit_wait_s=_int("implicit_wait_s", defaults.implicit_wait_s),
            element_wait_timeout_s=_int("element_wait_timeout_s", defaults.element_wait_timeout_s),
            search_results_timeout_s=_int(
                "search_results_timeout_s", defaults.search_results_timeout_s
            ),
        )
