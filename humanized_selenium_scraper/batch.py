from __future__ import annotations

import csv
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .config import ScraperConfig
from .csv_io import CsvResultWriter, read_csv_rows, sanitize_cell
from .exceptions import SkipEntryError
from .human import random_pause
from .logging_utils import redact_query
from .scraper import Session
from .spec import SearchSpec, render_template

# Columns appended to the input columns in the output CSV.
RESULT_COLUMNS = ("Website", "Phone", "Email")


class RowSearcher(Protocol):
    """The engine surface the batch runner needs (implemented by scraper.Session)."""

    def search(
        self, *, query: str, row: dict[str, str], spec: SearchSpec
    ) -> tuple[str | None, str | None, str | None]: ...

    def close(self) -> None: ...


SessionFactory = Callable[[], RowSearcher]


def _default_session_factory(config: ScraperConfig) -> RowSearcher:
    return Session.create(config, profile_dir=config.chrome_profile_root)


def resolve_input_columns(
    input_file: Path,
    *,
    delimiter: str,
    has_header: bool,
    columns: list[str] | None,
) -> list[str]:
    """Return the ordered input column names used for the output header.

    For headerless CSVs these are the ``--columns`` names. For CSVs with a header
    the header row is read; column names must be unique, so duplicates are
    rejected (matching the ``--columns`` policy) rather than silently dropped.
    """
    if not has_header:
        if not columns:
            raise ValueError(
                "Column names are required for a CSV without a header; pass --columns."
            )
        return list(columns)

    with input_file.open("r", encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle, delimiter=delimiter), None)
    if not header:
        raise ValueError(
            f"Input CSV file is empty: {input_file}\n"
            "The file must contain at least a header row when --header is used."
        )
    raw_columns = [name.strip() for name in header if name.strip()]
    if not raw_columns:
        raise ValueError(
            f"Header row in {input_file} contains no column names.\n"
            "Check that the file is not blank and uses the correct delimiter "
            f"(current delimiter: {delimiter!r})."
        )
    duplicates = sorted({name for name in raw_columns if raw_columns.count(name) > 1})
    if duplicates:
        raise ValueError(
            f"Header row in {input_file} contains duplicate column name(s): "
            f"{', '.join(duplicates)}. Each column name must be unique; rename or "
            "remove the duplicate columns."
        )
    return raw_columns


def process_row(
    session: RowSearcher,
    spec: SearchSpec,
    row: dict[str, str],
    input_columns: list[str],
) -> list[str]:
    """Render the query, run one search, and build the sanitized output row.

    Every failure path (skip or unexpected error) yields a row with empty result
    columns so the batch continues and the input row is preserved.
    """
    values = ["", "", ""]
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
        values = [found_url or "", phone or "", email or ""]
    except SkipEntryError as exc:
        logging.warning("SKIP => %s", exc)
    except Exception as exc:
        logging.warning("process_row failed: %s", exc)

    input_cells = [sanitize_cell(str(row.get(col, ""))) for col in input_columns]
    return [*input_cells, *(sanitize_cell(value) for value in values)]


def run_batch(
    *,
    input_file: Path,
    output_file: Path,
    config: ScraperConfig,
    spec: SearchSpec,
    delimiter: str,
    has_header: bool,
    columns: list[str] | None,
    session_factory: SessionFactory | None = None,
) -> int:
    """Process every input row, writing one output row each, and return exit code 0.

    ``session_factory`` overrides how the engine is built (used by tests).
    """
    input_columns = resolve_input_columns(
        input_file, delimiter=delimiter, has_header=has_header, columns=columns
    )
    writer = CsvResultWriter(output_file, [*input_columns, *RESULT_COLUMNS])
    factory = session_factory or (lambda: _default_session_factory(config))

    session = factory()
    try:
        for row in read_csv_rows(
            input_file,
            delimiter=delimiter,
            has_header=has_header,
            columns=input_columns,
        ):
            writer.write_row(process_row(session, spec, row, input_columns))
            random_pause(1, 2)
    finally:
        session.close()

    writer.finish()
    logging.info("All rows done => %s", output_file)
    return 0
