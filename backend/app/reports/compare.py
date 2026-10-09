"""Compare one report at two dates. Rows are matched on the report's identity columns (project and URL, project and
query, ...). Each output row says what happened between A and B:

    new      only present at B (a new problem URL, a new alert, a page that started ranking)
    gone     only present at A (a fixed URL, a cleared alert, a page that stopped ranking)
    changed  present at both and at least one value differs
    same     present at both and identical

Numeric columns also get a `_delta` (B minus A); for positions a negative delta means the page moved up."""
from datetime import date, datetime
from typing import Any

from app.reports.builders import Report

STATUSES = ("new", "gone", "changed", "same")
EPSILON = 1e-9


def _numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _same(a: Any, b: Any) -> bool:
    if _numeric(a) and _numeric(b):
        return abs(a - b) < EPSILON
    return a == b


def _delta(a: Any, b: Any) -> Any:
    if _numeric(a) and _numeric(b):
        d = b - a
        return round(d, 4) if isinstance(d, float) else d
    return None


def compare_reports(a: Report, b: Report, keys: tuple[str, ...], changed_only: bool = False) -> dict[str, Any]:
    key_idx = [a.columns.index(k) for k in keys]
    value_cols = [c for c in a.columns if c not in keys]
    val_idx = [a.columns.index(c) for c in value_cols]

    def index(report: Report) -> dict[tuple, list]:
        return {tuple(row[i] for i in key_idx): row for row in report.rows}

    rows_a, rows_b = index(a), index(b)
    numeric_cols = {
        c for c, i in zip(value_cols, val_idx)
        if any(_numeric(r[i]) for r in [*a.rows, *b.rows])
    }
    columns = [*keys, "change"]
    for c in value_cols:
        columns += [f"{c}_a", f"{c}_b"] + ([f"{c}_delta"] if c in numeric_cols else [])

    out: list[list[Any]] = []
    counts = {s: 0 for s in STATUSES}
    for key in sorted({*rows_a, *rows_b}, key=lambda k: tuple("" if v is None else str(v) for v in k)):
        ra, rb = rows_a.get(key), rows_b.get(key)
        if ra is None:
            status = "new"
        elif rb is None:
            status = "gone"
        else:
            status = "same" if all(_same(ra[i], rb[i]) for i in val_idx) else "changed"
        counts[status] += 1
        if changed_only and status == "same":
            continue
        row: list[Any] = [*key, status]
        for c, i in zip(value_cols, val_idx):
            va = ra[i] if ra is not None else None
            vb = rb[i] if rb is not None else None
            row += [va, vb]
            if c in numeric_cols:
                row.append(_delta(va, vb))
        out.append(row)
    return {"name": a.name, "columns": columns, "rows": out, "summary": counts}


def serialisable(value: Any) -> Any:
    return value.isoformat() if isinstance(value, (date, datetime)) else value
