import csv
import io
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from typing import Any

# A cell starting with one of these is evaluated as a formula by Excel/Sheets. Page titles and search
# queries come from the open web, so they are prefixed with a quote to keep them as plain text.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if text.startswith(FORMULA_PREFIXES) and not _is_plain_number(text):
        return "'" + text
    return text


def _is_plain_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def to_csv(columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_cell(v) for v in row])
    return buffer.getvalue()
