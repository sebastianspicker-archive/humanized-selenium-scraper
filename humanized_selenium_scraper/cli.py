from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

from .batch import run_batch
from .config import ScraperConfig
from .csv_io import parse_columns_arg
from .spec import SearchSpec, clamp_navigation


def _get_version() -> str:
    try:
        return _pkg_version("humanized-selenium-scraper")
    except PackageNotFoundError:
        return "0.1.0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Search Google for each row in a CSV and extract website, phone, and email.\n"
            "Uses a real Chrome browser with human-like behavior to reduce blocking."
        ),
        epilog=(
            "Examples:\n"
            "  python -m humanized_selenium_scraper --header --input companies.csv"
            " --output results.csv\n"
            "  python -m humanized_selenium_scraper --spec my_spec.toml --header --input in.csv\n"
            "\n"
            "See example_search_spec.toml for a full configuration template."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_get_version()}")
    parser.add_argument(
        "--input", default="input.csv", help="Path to the input CSV file (default: input.csv)."
    )
    parser.add_argument(
        "--output", default="output.csv", help="Path for the output CSV file (default: output.csv)."
    )
    parser.add_argument(
        "--google-domain",
        help="Google country domain to search, e.g. google.de (default: google.com).",
    )
    parser.add_argument(
        "--delimiter",
        default=",",
        help="CSV field delimiter, e.g. ';' for European CSVs (default: ',').",
    )
    parser.add_argument(
        "--header",
        action="store_true",
        help="The first row of the input CSV is a header with column names.",
    )
    parser.add_argument(
        "--columns",
        default="name,street,plz,city",
        help="Column names for headerless CSVs, comma-separated (default: name,street,plz,city).",
    )
    parser.add_argument(
        "--preset",
        choices=sorted(SearchSpec.presets().keys()),
        default="contact",
        help="Built-in preset: 'contact' (find sites) or 'keywords' (search by keyword).",
    )
    parser.add_argument(
        "--spec", help="Path to a TOML configuration file (see example_search_spec.toml)."
    )
    parser.add_argument(
        "--query-template",
        help="How to build the Google query from CSV columns, e.g. '{name} {city} contact'.",
    )
    parser.add_argument(
        "--keyword-template",
        action="append",
        default=[],
        help=(
            "Word(s) the page must contain to be relevant. Repeatable, e.g. "
            "--keyword-template '{name}' --keyword-template 'contact'."
        ),
    )
    parser.add_argument(
        "--min-keyword-hits",
        type=int,
        help="Total keyword occurrences required on a page (default: 6 contact, 1 keywords).",
    )
    parser.add_argument(
        "--require-address",
        action="store_true",
        default=None,
        help="Only accept pages that also mention the street, zip, or city from the CSV row.",
    )
    parser.add_argument(
        "--no-require-address",
        action="store_false",
        dest="require_address",
        default=None,
        help="Accept pages based on keywords alone, without checking for address matches.",
    )
    parser.add_argument(
        "--street-field", help="CSV column name that contains the street (default: 'street')."
    )
    parser.add_argument(
        "--zip-field", help="CSV column name that contains the zip/postal code (default: 'plz')."
    )
    parser.add_argument(
        "--city-field", help="CSV column name that contains the city (default: 'city')."
    )
    parser.add_argument(
        "--address-min-score",
        type=int,
        help="Minimum address match score to accept a page (default: 2). Higher = stricter.",
    )
    parser.add_argument(
        "--domain-match",
        choices=["query_part", "any"],
        help=(
            "How to filter Google result URLs. 'query_part' (default): the domain must "
            "contain a word from the query. 'any': accept any domain that passes the "
            "TLD and blacklist checks."
        ),
    )
    parser.add_argument(
        "--allowed-tld",
        action="append",
        default=[],
        help="Only visit these TLDs. Repeatable, e.g. --allowed-tld .de --allowed-tld .com.",
    )
    parser.add_argument(
        "--blacklist-domain-keyword",
        action="append",
        default=[],
        help="Skip domains with this word. Repeatable, e.g. --blacklist-domain-keyword ebay.",
    )
    parser.add_argument(
        "--min-domain-query-part-len",
        type=int,
        help="Minimum query word length when matching domains (default: 3, query_part mode).",
    )
    parser.add_argument(
        "--max-google-results",
        type=int,
        help="How many Google result links to evaluate per search (default: 20).",
    )
    parser.add_argument(
        "--max-links-per-page",
        type=int,
        help="How many links to follow on each visited page (default: 30).",
    )
    parser.add_argument(
        "--subpage-depth",
        type=int,
        help="How many levels of subpages to explore per site. 0 disables (default: 2).",
    )
    parser.add_argument("--no-phone", action="store_true", help="Skip phone number extraction.")
    parser.add_argument("--no-email", action="store_true", help="Skip email address extraction.")
    parser.add_argument(
        "--log-file",
        default="scraper.log",
        help="Where to write the log file (default: scraper.log).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed debug output (useful for troubleshooting).",
    )
    return parser


def _apply_cli_overrides(args: argparse.Namespace, spec: SearchSpec) -> SearchSpec:
    """Return ``spec`` with any CLI flags supplied on the command line applied."""
    if args.query_template:
        spec = replace(spec, query_template=args.query_template)

    if args.keyword_template:
        spec = replace(
            spec, relevance=replace(spec.relevance, keyword_templates=tuple(args.keyword_template))
        )

    if args.min_keyword_hits is not None:
        spec = replace(
            spec,
            relevance=replace(spec.relevance, min_total_keyword_hits=args.min_keyword_hits),
        )

    if args.domain_match is not None:
        spec = replace(spec, url_filter=replace(spec.url_filter, domain_match=args.domain_match))

    if args.require_address is not None:
        spec = replace(
            spec, relevance=replace(spec.relevance, require_address=args.require_address)
        )

    if args.street_field or args.zip_field or args.city_field or args.address_min_score is not None:
        address = spec.relevance.address
        address = replace(
            address,
            street_field=args.street_field or address.street_field,
            zip_field=args.zip_field or address.zip_field,
            city_field=args.city_field or address.city_field,
            min_score=args.address_min_score
            if args.address_min_score is not None
            else address.min_score,
        )
        spec = replace(spec, relevance=replace(spec.relevance, address=address))

    if args.allowed_tld:
        spec = replace(
            spec, url_filter=replace(spec.url_filter, allowed_tlds=tuple(args.allowed_tld))
        )
    if args.blacklist_domain_keyword:
        spec = replace(
            spec,
            url_filter=replace(
                spec.url_filter, domain_keyword_blacklist=tuple(args.blacklist_domain_keyword)
            ),
        )
    if args.min_domain_query_part_len is not None:
        spec = replace(
            spec,
            url_filter=replace(spec.url_filter, min_query_part_len=args.min_domain_query_part_len),
        )

    if (
        args.max_google_results is not None
        or args.max_links_per_page is not None
        or args.subpage_depth is not None
    ):
        nav = spec.navigation
        max_google_results = (
            args.max_google_results
            if args.max_google_results is not None
            else nav.max_google_results
        )
        max_links = (
            args.max_links_per_page
            if args.max_links_per_page is not None
            else nav.max_links_per_page
        )
        subpage_depth = args.subpage_depth if args.subpage_depth is not None else nav.subpage_depth
        spec = replace(
            spec, navigation=clamp_navigation(max_google_results, max_links, subpage_depth)
        )

    if args.no_phone:
        spec = replace(spec, extract_phone=False)
    if args.no_email:
        spec = replace(spec, extract_email=False)

    return spec


def _configure_logging(*, log_file: str, verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _configure_logging(log_file=args.log_file, verbose=args.verbose)

    spec = SearchSpec.presets()[args.preset]
    config = ScraperConfig(google_domain=args.google_domain or "google.com")

    if args.spec:
        spec, config_from_spec = SearchSpec.from_toml(Path(args.spec))
        config = replace(
            config_from_spec,
            google_domain=args.google_domain or config_from_spec.google_domain,
        )

    spec = _apply_cli_overrides(args, spec)
    # dataclasses.replace() skips __post_init__, so re-validate the final domain.
    config.validate()

    columns = parse_columns_arg(args.columns) if not args.header else None
    return run_batch(
        input_file=Path(args.input),
        output_file=Path(args.output),
        config=config,
        spec=spec,
        delimiter=args.delimiter,
        has_header=args.header,
        columns=columns,
    )
