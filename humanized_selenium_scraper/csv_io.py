from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

# Leading characters a spreadsheet may interpret as the start of a formula.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_cell(value: str) -> str:
    """Prefix a cell that a spreadsheet could interpret as a formula.

    Prevents CSV/formula injection (e.g. ``=CMD|...``) when the output is opened
    in Excel or LibreOffice.
    """
    if value and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def read_csv_rows(
    path: Path,
    *,
    delimiter: str = ",",
    has_header: bool = False,
    columns: list[str] | None = None,
) -> Iterable[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        if has_header:
            dict_reader = csv.DictReader(handle, delimiter=delimiter)
            fieldnames = dict_reader.fieldnames
            if fieldnames is None:
                raise ValueError(
                    f"No header row found in {path}. "
                    "If your CSV has no header, remove the --header flag and use --columns instead."
                )
            # Normalize once so keys match the stripped output/header names.
            dict_reader.fieldnames = [name.strip() for name in fieldnames]
            for row_dict in dict_reader:
                yield {k: (v or "") for k, v in row_dict.items() if k is not None}
            return

        row_reader = csv.reader(handle, delimiter=delimiter)
        for row_list in row_reader:
            if columns is None:
                cols = [f"col{i + 1}" for i in range(len(row_list))]
            else:
                if len(row_list) != len(columns):
                    raise ValueError(
                        f"Row has {len(row_list)} field(s) but --columns specifies "
                        f"{len(columns)} ({', '.join(columns)}). "
                        "Check that the CSV delimiter matches (use --delimiter if needed) "
                        "or adjust --columns to match your data."
                    )
                cols = columns
            yield {cols[i]: (row_list[i] or "") for i in range(len(cols))}


def parse_columns_arg(value: str) -> list[str]:
    cols = [c.strip() for c in value.split(",") if c.strip()]
    if not cols:
        raise ValueError(
            "--columns must not be empty. Provide comma-separated column names, "
            "e.g. --columns name,street,plz,city"
        )
    if len(set(cols)) != len(cols):
        duplicates = [c for c in cols if cols.count(c) > 1]
        raise ValueError(
            f"--columns contains duplicate name(s): {', '.join(sorted(set(duplicates)))}. "
            "Each column name must be unique."
        )
    return cols


class CsvResultWriter:
    """Append result rows under a header written exactly once.

    One instance owns one run. The output file is truncated when the first row
    (or :meth:`finish`) is written, so re-running replaces previous output. Each
    row is opened, written, and closed immediately, so an interrupted run still
    leaves complete rows on disk.
    """

    def __init__(self, path: Path, header: list[str]) -> None:
        self._path = path
        self._header = list(header)
        self._started = False

    def write_row(self, row: list[str]) -> None:
        if not self._started:
            self._write_header()
        with self._path.open("a", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerow(row)

    def finish(self) -> None:
        """Ensure the file exists with its header even when no rows were written."""
        if not self._started:
            self._write_header()

    def _write_header(self) -> None:
        with self._path.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerow(self._header)
        self._started = True
