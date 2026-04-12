from __future__ import annotations

import argparse
import csv
import logging
import sys
import threading
from dataclasses import replace
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

from .config import ScraperConfig
from .exceptions import SkipEntryError
from .human import random_pause
from .io import parse_columns_arg, read_csv_rows
from .logging_utils import redact_query
from .scraper import Session
from .spec import SearchSpec, clamp_navigation, render_template


def _get_version() -> str:
    try:
        return _pkg_version("humanized-selenium-scraper")
    except PackageNotFoundError:
        return "0.1.0"


write_lock = threading.Lock()
_header_written = False  # Module-level flag; run() must not be called concurrently

# Characters that can trigger formula interpretation in Excel/LibreOffice
_CSV_FORMULA_PREFIX = ("=", "+", "-", "@", "\t", "\r")


def _safe_csv_cell(value: str) -> str:
    """Escape cell so it is not interpreted as a formula (e.g. =CMD|...)."""
    if not value:
        return value
    if value.startswith(_CSV_FORMULA_PREFIX):
        return "'" + value
    return value


def _ensure_output_header(path: Path, header: list[str]) -> None:
    """Write the CSV header only if not yet written (thread-safe)."""
    global _header_written
    with write_lock:
        if not _header_written:
            with path.open("w", encoding="utf-8", newline="") as handle:
                csv.writer(handle).writerow(header)
            _header_written = True


def _write_row(path: Path, *, header: list[str], row: list[str]) -> None:
    """Write a row to the CSV file, writing header only once (thread-safe).

    Uses module-level _header_written flag protected by write_lock to ensure
    header is written exactly once even in multi-threaded scenarios.
    """
    global _header_written
    with write_lock:
        mode = "w" if not _header_written else "a"
        with path.open(mode, encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            if not _header_written:
                writer.writerow(header)
                _header_written = True
            writer.writerow(row)


def run(
    *,
    input_file: Path,
    output_file: Path,
    config: ScraperConfig,
    spec: SearchSpec,
    delimiter: str,
    has_header: bool,
    columns: list[str] | None,
) -> int:
    global _header_written
    _header_written = False  # Reset for each run
    input_columns = columns or []
    if has_header:
        with input_file.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            header = next(reader, None)
            if not header:
                raise ValueError(
                    f"Input CSV file is empty: {input_file}\n"
                    "The file must contain at least a header row when --header is used."
                )
            raw_columns = [h.strip() for h in header if h.strip()]
            if not raw_columns:
                raise ValueError(
                    f"Header row in {input_file} contains no column names.\n"
                    "Check that the file is not blank and uses the correct delimiter "
                    f"(current delimiter: {delimiter!r})."
                )
            input_columns = list(dict.fromkeys(raw_columns))

    out_header = [*input_columns, "Website", "Phone", "Email"]
    session = None
    try:
        session = Session.create(config, profile_dir=config.chrome_profile_root)
        for row in read_csv_rows(
            input_file, delimiter=delimiter, has_header=has_header, columns=input_columns or columns
        ):
            try:
                query = render_template(spec.query_template, row).strip()
                if not query:
                    raise ValueError(
                        f"The query template '{spec.query_template}' produced an empty "
                        "query for this row. Check that the template references columns "
                        "that exist in your CSV and that the row is not blank."
                    )
                logging.info("Processing query => %s", redact_query(query))

                found_url, phone, email = session.search(query=query, row=row, spec=spec)
                row_out = [
                    *(_safe_csv_cell(str(row.get(col, ""))) for col in input_columns),
                    _safe_csv_cell(found_url or ""),
                    _safe_csv_cell(phone or ""),
                    _safe_csv_cell(email or ""),
                ]
            except SkipEntryError as exc:
                logging.warning("SKIP => %s", exc)
                row_out = [
                    *(_safe_csv_cell(str(row.get(col, ""))) for col in input_columns),
                    "",
                    "",
                    "",
                ]
            except Exception as exc:
                logging.warning("process_row failed: %s", exc)
                row_out = [
                    *(_safe_csv_cell(str(row.get(col, ""))) for col in input_columns),
                    "",
                    "",
                    "",
                ]

            _write_row(
                output_file,
                header=out_header,
                row=row_out,
            )
            random_pause(1, 2)
    finally:
        if session is not None:
            session.close()

    # When there are zero data rows, output file was never created; write header only
    if not _header_written:
        _ensure_output_header(output_file, out_header)

    logging.info("All rows done => %s", output_file)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Search Google for each row in a CSV and extract website, phone, and email.\n"
            "Uses a real Chrome browser with human-like behavior to reduce blocking."
        ),
        epilog=(
            "Examples:\n"
            "  python -m humanized_selenium_scraper --header --input companies.csv --output results.csv\n"
            "  python -m humanized_selenium_scraper --spec my_spec.toml --header --input in.csv\n"
            "\n"
            "See example_search_spec.toml for a full configuration template."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_get_version()}",
    )
    parser.add_argument("--input", default="input.csv", help="Path to the input CSV file (default: input.csv).")
    parser.add_argument("--output", default="output.csv", help="Path for the output CSV file (default: output.csv).")
    parser.add_argument("--google-domain", help="Google country domain to search, e.g. google.de (default: google.com).")
    parser.add_argument("--delimiter", default=",", help="CSV field delimiter, e.g. ';' for European CSVs (default: ',').")
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
        help="Built-in configuration preset: 'contact' (find company websites) or 'keywords' (search by keyword).",
    )
    parser.add_argument("--spec", help="Path to a TOML configuration file (see example_search_spec.toml).")
    parser.add_argument(
        "--query-template",
        help="How to build the Google search query from CSV columns, e.g. '{name} {city} contact'.",
    )
    parser.add_argument(
        "--keyword-template",
        action="append",
        default=[],
        help="Word(s) the page must contain to be considered relevant. Can be repeated, e.g. --keyword-template '{name}' --keyword-template 'contact'.",
    )
    parser.add_argument(
        "--min-keyword-hits",
        type=int,
        help="How many times the keywords must appear on a page in total (default: 6 for contact preset, 1 for keywords preset).",
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
    parser.add_argument("--street-field", help="CSV column name that contains the street (default: 'street').")
    parser.add_argument("--zip-field", help="CSV column name that contains the zip/postal code (default: 'plz').")
    parser.add_argument("--city-field", help="CSV column name that contains the city (default: 'city').")
    parser.add_argument("--address-min-score", type=int, help="Minimum address match score to accept a page (default: 2). Higher = stricter.")
    parser.add_argument(
        "--domain-match",
        choices=["query_part", "any"],
        help=(
            "How to filter Google result URLs. 'query_part' (default): the domain must "
            "contain a word from the search query. 'any': accept any domain that passes "
            "TLD and blacklist checks."
        ),
    )
    parser.add_argument(
        "--allowed-tld",
        action="append",
        default=[],
        help="Only visit sites with this TLD. Can be repeated, e.g. --allowed-tld .de --allowed-tld .com",
    )
    parser.add_argument(
        "--blacklist-domain-keyword",
        action="append",
        default=[],
        help="Skip sites whose domain contains this word. Can be repeated, e.g. --blacklist-domain-keyword facebook",
    )
    parser.add_argument(
        "--min-domain-query-part-len",
        type=int,
        help="Minimum word length when matching query parts against domains (default: 3). Only used with --domain-match query_part.",
    )
    parser.add_argument(
        "--max-google-results", type=int, help="How many Google result links to evaluate per search (default: 20)."
    )
    parser.add_argument(
        "--max-links-per-page", type=int, help="How many links to follow on each visited page (default: 30)."
    )
    parser.add_argument("--subpage-depth", type=int, help="How many levels of subpages to explore on a site. 0 disables subpage search (default: 2).")
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


def _apply_cli_args_to_spec(
    args: argparse.Namespace,
    spec: SearchSpec,
    config: ScraperConfig,
) -> tuple[SearchSpec, ScraperConfig]:
    """Apply parsed CLI arguments to spec and config; return updated (spec, config)."""
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
        mg = args.max_google_results
        max_gr = mg if mg is not None else nav.max_google_results
        ml = args.max_links_per_page
        max_lp = ml if ml is not None else nav.max_links_per_page
        sd = args.subpage_depth
        sub_d = sd if sd is not None else nav.subpage_depth
        spec = replace(spec, navigation=clamp_navigation(max_gr, max_lp, sub_d))

    if args.no_phone:
        spec = replace(spec, extract_phone=False)
    if args.no_email:
        spec = replace(spec, extract_email=False)

    return spec, config


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.INFO
    log_fmt = "%(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(
        level=log_level,
        format=log_fmt,
        handlers=[
            logging.FileHandler(args.log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )

    spec = SearchSpec.presets()[args.preset]
    config = ScraperConfig(google_domain=args.google_domain or "google.com")

    if args.spec:
        spec, config_from_spec = SearchSpec.from_toml(Path(args.spec))
        config = replace(
            config_from_spec, google_domain=args.google_domain or config_from_spec.google_domain
        )

    spec, config = _apply_cli_args_to_spec(args, spec, config)
    config.validate()

    columns = parse_columns_arg(args.columns) if not args.header else None
    return run(
        input_file=Path(args.input),
        output_file=Path(args.output),
        config=config,
        spec=spec,
        delimiter=args.delimiter,
        has_header=args.header,
        columns=columns,
    )
