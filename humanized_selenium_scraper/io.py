from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path


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
            if dict_reader.fieldnames is None:
                raise ValueError(
                    f"No header row found in {path}. "
                    "If your CSV has no header, remove the --header flag and use --columns instead."
                )
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
