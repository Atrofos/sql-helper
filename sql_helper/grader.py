"""Compare a user's query result with the expected result and explain differences."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .database import QueryResult

FLOAT_PLACES = 2   # 98333.333 and 98333.33 count as the same answer
MAX_EXAMPLES = 3   # how many missing/extra rows to show in feedback


@dataclass
class GradeResult:
    correct: bool
    message: str
    details: list[str] = field(default_factory=list)


def _normalize_value(value):
    if isinstance(value, float):
        rounded = round(value, FLOAT_PLACES)
        return int(rounded) if rounded.is_integer() else rounded
    return value


def _normalize(rows: list[tuple]) -> list[tuple]:
    return [tuple(_normalize_value(v) for v in row) for row in rows]


def _format_row(row: tuple) -> str:
    return "(" + ", ".join("NULL" if v is None else repr(v) for v in row) + ")"


def grade(user: QueryResult, expected: QueryResult, order_matters: bool = False,
          show_examples: bool = True) -> GradeResult:
    """Grade by comparing values, not column names, so aliases never cost points.

    Row order is ignored unless ``order_matters`` is True (the question asks for
    a specific ORDER BY). With ``show_examples`` False, feedback gives counts
    only and never quotes expected rows or column names, so it can't give away
    a hidden expected result.
    """
    if not expected.ok:
        return GradeResult(False, "This question's saved solution has an error, "
                                  "so it can't be checked.", [expected.error or ""])
    if not user.ok:
        return GradeResult(False, "Your query has an error.", [user.error or ""])
    if not user.columns:
        return GradeResult(False, "Your statement didn't return any columns.")

    details: list[str] = []
    if len(user.columns) != len(expected.columns):
        names = f" ({', '.join(expected.columns)})" if show_examples else ""
        details.append(f"Expected {len(expected.columns)} column(s){names}, "
                       f"you returned {len(user.columns)} ({', '.join(user.columns)}).")
        return GradeResult(False, "Not quite: the number of columns is different.", details)

    user_rows, expected_rows = _normalize(user.rows), _normalize(expected.rows)
    user_count, expected_count = Counter(user_rows), Counter(expected_rows)

    if user_count == expected_count:
        if order_matters and user_rows != expected_rows:
            return GradeResult(False, "Right rows, wrong order. Check your ORDER BY.")
        tips = []
        if show_examples and [c.lower() for c in user.columns] != [c.lower() for c in expected.columns]:
            tips.append("Tip: your column names differ from the expected ones "
                        f"({', '.join(expected.columns)}). That's fine here, but "
                        "interviewers sometimes ask for specific aliases.")
        return GradeResult(True, "Correct! Nice work.", tips)

    if len(user_rows) != len(expected_rows):
        details.append(f"Expected {len(expected_rows)} row(s), you returned {len(user_rows)}.")
    missing = list((expected_count - user_count).elements())
    extra = list((user_count - expected_count).elements())
    if missing:
        examples = (", e.g. " + ", ".join(_format_row(r) for r in missing[:MAX_EXAMPLES])
                    if show_examples else ".")
        details.append(f"Missing {len(missing)} row(s){examples}")
    if extra:
        details.append(f"{len(extra)} unexpected row(s), e.g. "
                       + ", ".join(_format_row(r) for r in extra[:MAX_EXAMPLES]))
    if extra and missing and len(user_rows) == len(expected_rows):
        details.append("Same row count but different values. Check column order, "
                       "filters, and calculations.")
    return GradeResult(False, "Not quite: the rows don't match.", details)
