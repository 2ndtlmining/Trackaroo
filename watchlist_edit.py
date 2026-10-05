"""Pure text edits for db/watchlist.csv and db/generations.toml (#19).

Every function is str -> str: no I/O, so manage_watchlist.py can show a diff
before it writes anything. Edits touch only the lines they must; comments,
ordering and the file's own line endings (LF or CRLF) are left alone.
"""
from __future__ import annotations

import csv
import difflib
import io
from typing import List, Optional, Set, Tuple

from db.generations import line_id as make_line_id

CSV_COLUMNS = ("category", "brand", "model", "spec", "series", "status")


def _eol(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _strip_eol(line: str) -> Tuple[str, str]:
    body = line.rstrip("\r\n")
    return body, line[len(body):]


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def insert_series(toml_text: str, line_id: str, key: str, label: str, chips: List[str]) -> str:
    """Insert a series as the FIRST entry of ``line_id``'s ``series = [`` list.

    Raises:
        ValueError: if the line is missing or the key is already in the file.
    """
    lines = toml_text.splitlines(True)
    if any(l.strip().startswith("{") and f'key = "{key}"' in l for l in lines):
        raise ValueError(f"series key {key!r} already exists in generations.toml")
    start = None
    for i, l in enumerate(lines):
        if l.strip() == f'id = "{line_id}"':
            start = i
            break
    if start is None:
        raise ValueError(f"line {line_id!r} not found in generations.toml")
    for j in range(start + 1, len(lines)):
        if lines[j].strip() == "[[line]]":
            break
        if lines[j].strip().startswith("series") and lines[j].rstrip().endswith("["):
            chip_list = ", ".join(_quote(c) for c in chips)
            entry = f"  {{ key = {_quote(key)}, label = {_quote(label)}, chips = [{chip_list}] }},"
            lines.insert(j + 1, entry + _eol(toml_text))
            return "".join(lines)
    raise ValueError(f"line {line_id!r} has no 'series = [' list")


def _data_rows(csv_text: str):
    """Yield (index, fields, line) for each data row (not comments, blanks or the header)."""
    header_seen = False
    for i, line in enumerate(csv_text.splitlines(True)):
        if line.startswith("#") or not line.strip():
            continue
        if not header_seen:
            header_seen = True
            continue
        yield i, next(csv.reader([line.rstrip("\r\n")])), line


def _format(fields: List[str], eol: str) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator=eol).writerow(fields)
    return buf.getvalue()


def set_status(csv_text: str, models: Set[str], status: str) -> Tuple[str, List[str]]:
    """Set ``status`` on rows whose model is in ``models`` (case-insensitive, exact).

    Returns the new text and the models actually changed (rows already at
    ``status`` are left alone and not reported).
    """
    wanted = {m.strip().lower() for m in models}
    lines = csv_text.splitlines(True)
    changed: List[str] = []
    status_col = CSV_COLUMNS.index("status")
    model_col = CSV_COLUMNS.index("model")
    for i, fields, line in _data_rows(csv_text):
        if len(fields) <= status_col or fields[model_col].strip().lower() not in wanted:
            continue
        if fields[status_col].strip().lower() == status:
            continue
        fields[status_col] = status
        lines[i] = _format(fields, _strip_eol(line)[1])
        changed.append(fields[model_col])
    return "".join(lines), changed


def append_row(csv_text: str, row: List[str], after_series: Optional[str], line_id: str) -> str:
    """Insert ``row`` after the last row of ``after_series``, else of ``line_id``, else at the end."""
    eol = _eol(csv_text)
    lines = csv_text.splitlines(True)
    last_series = last_line = last_any = None
    for i, fields, _ in _data_rows(csv_text):
        last_any = i
        if len(fields) < len(CSV_COLUMNS):
            continue
        if after_series and fields[4].strip() == after_series:
            last_series = i
        if make_line_id(fields[1], fields[0]) == line_id:
            last_line = i
    at = next((x for x in (last_series, last_line, last_any) if x is not None), None)
    if at is None:
        at = len(lines) - 1
    if lines and not _strip_eol(lines[at])[1]:  # target is an unterminated last line
        lines[at] += eol
    lines.insert(at + 1, _format(row, eol))
    return "".join(lines)


def unified(old: str, new: str, name: str) -> str:
    """A unified diff of old -> new, labelled ``name`` (empty string when unchanged)."""
    return "".join(
        difflib.unified_diff(
            old.splitlines(True), new.splitlines(True), fromfile=f"a/{name}", tofile=f"b/{name}"
        )
    )
