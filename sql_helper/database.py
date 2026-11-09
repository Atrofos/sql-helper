"""Practice database: schema, seed data, and safe read-only query execution.

The practice data lives in an in-memory SQLite database that is rebuilt every
time the app starts. Once seeded, an SQLite *authorizer* only allows read
operations, and a progress handler stops runaway queries, so nothing a user
types can change the data or freeze the app.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field

SCHEMA_SQL = """
CREATE TABLE departments (
    dept_id   INTEGER PRIMARY KEY,
    name      TEXT NOT NULL,
    location  TEXT NOT NULL
);

CREATE TABLE employees (
    emp_id      INTEGER PRIMARY KEY,
    first_name  TEXT NOT NULL,
    last_name   TEXT NOT NULL,
    email       TEXT,
    dept_id     INTEGER REFERENCES departments(dept_id),
    manager_id  INTEGER REFERENCES employees(emp_id),
    salary      INTEGER NOT NULL,
    hire_date   TEXT NOT NULL
);

CREATE TABLE customers (
    customer_id  INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    city         TEXT,
    country      TEXT NOT NULL,
    signup_date  TEXT NOT NULL
);

CREATE TABLE products (
    product_id  INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL,
    price       REAL NOT NULL
);

CREATE TABLE orders (
    order_id     INTEGER PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES customers(customer_id),
    product_id   INTEGER NOT NULL REFERENCES products(product_id),
    quantity     INTEGER NOT NULL,
    order_date   TEXT NOT NULL,
    status       TEXT NOT NULL
);
"""

# Small, hand-written data set. It deliberately includes a few edge cases that
# interviewers like to probe: NULLs, a department with no employees, an
# employee with no department, and customers with no orders.
SEED_SQL = """
INSERT INTO departments VALUES
    (1, 'Engineering', 'San Francisco'),
    (2, 'Sales',       'New York'),
    (3, 'Marketing',   'New York'),
    (4, 'HR',          'Chicago'),
    (5, 'Legal',       'Boston');

INSERT INTO employees VALUES
    (1,  'Alice',  'Chen',     'alice.chen@example.com',    1, NULL, 145000, '2018-03-15'),
    (2,  'Bob',    'Martinez', 'bob.martinez@example.com',  1, 1,    115000, '2019-07-01'),
    (3,  'Carol',  'Johnson',  'carol.johnson@example.com', 1, 1,     98000, '2021-01-10'),
    (4,  'David',  'Kim',      'david.kim@example.com',     2, NULL, 120000, '2017-11-20'),
    (5,  'Emma',   'Wilson',   'emma.wilson@example.com',   2, 4,     72000, '2020-05-18'),
    (6,  'Frank',  'Brown',    'frank.brown@example.com',   2, 4,     68000, '2022-02-28'),
    (7,  'Grace',  'Lee',      'grace.lee@example.com',     3, NULL, 105000, '2019-09-09'),
    (8,  'Henry',  'Davis',    NULL,                        3, 7,     64000, '2023-04-03'),
    (9,  'Isabel', 'Garcia',   'isabel.garcia@example.com', 4, NULL,  88000, '2016-06-12'),
    (10, 'Jack',   'Taylor',   NULL,                        NULL, NULL, 55000, '2024-01-08'),
    (11, 'Karen',  'Patel',    'karen.patel@example.com',   1, 2,    102000, '2022-08-15'),
    (12, 'Liam',   'O''Brien', 'liam.obrien@example.com',   2, 4,     75000, '2021-10-04');

INSERT INTO customers VALUES
    (1, 'Acme Corp',    'New York',      'USA',    '2020-01-15'),
    (2, 'Blue Sky Ltd', 'London',        'UK',     '2020-03-22'),
    (3, 'Cedar Labs',   'San Francisco', 'USA',    '2021-06-30'),
    (4, 'Delta Foods',  'Toronto',       'Canada', '2021-09-12'),
    (5, 'Evergreen Co', NULL,            'USA',    '2022-02-01'),
    (6, 'Fjord Design', 'Oslo',          'Norway', '2022-11-19'),
    (7, 'Granite Inc',  'Chicago',       'USA',    '2023-05-07'),
    (8, 'Harbor Goods', 'London',        'UK',     '2024-01-25');

INSERT INTO products VALUES
    (1, 'Laptop',        'Electronics', 1200.00),
    (2, 'Monitor',       'Electronics',  300.00),
    (3, 'Keyboard',      'Accessories',   80.00),
    (4, 'Mouse',         'Accessories',   25.00),
    (5, 'Desk Chair',    'Furniture',    250.00),
    (6, 'Standing Desk', 'Furniture',    600.00),
    (7, 'USB Cable',     'Accessories',   10.00),
    (8, 'Webcam',        'Electronics',   90.00);

INSERT INTO orders VALUES
    (1,  1, 1, 2,  '2024-01-05', 'delivered'),
    (2,  1, 3, 5,  '2024-01-05', 'delivered'),
    (3,  2, 2, 3,  '2024-02-11', 'delivered'),
    (4,  3, 1, 1,  '2024-02-20', 'shipped'),
    (5,  3, 4, 10, '2024-03-02', 'delivered'),
    (6,  4, 5, 4,  '2024-03-15', 'cancelled'),
    (7,  4, 6, 1,  '2024-04-01', 'shipped'),
    (8,  5, 7, 20, '2024-04-18', 'pending'),
    (9,  5, 8, 2,  '2024-05-03', 'delivered'),
    (10, 6, 2, 1,  '2024-05-21', 'pending'),
    (11, 1, 6, 2,  '2024-06-09', 'shipped'),
    (12, 2, 4, 6,  '2024-06-30', 'delivered');
"""

# SQLite action codes a read-only query needs. SQLITE_RECURSIVE (33) covers
# WITH RECURSIVE; older Python builds may not export the constant.
_ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    getattr(sqlite3, "SQLITE_RECURSIVE", 33),
}

DEFAULT_TIMEOUT_S = 2.0
DEFAULT_MAX_ROWS = 1000


def _read_only_authorizer(action: int, *_args) -> int:
    """Allow reads; deny anything that writes, attaches files, or runs PRAGMAs."""
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


@dataclass
class QueryResult:
    """Outcome of running one SQL statement."""

    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    error: str | None = None
    truncated: bool = False
    elapsed_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None


def friendly_error(exc: Exception, timeout_s: float) -> str:
    """Translate raw sqlite3 errors into beginner-friendly messages."""
    text = str(exc)
    lowered = text.lower()
    if "not authorized" in lowered:
        return ("Only read-only queries (SELECT / WITH) are allowed here, "
                "so the practice data always stays the same.")
    if "interrupted" in lowered:
        return f"The query ran longer than {timeout_s:g}s and was stopped."
    if "one statement at a time" in lowered:
        return "Run one statement at a time (remove everything after the first ';')."
    return text


class PracticeDatabase:
    """In-memory, read-only SQLite database seeded with practice data."""

    def __init__(self, timeout_s: float = DEFAULT_TIMEOUT_S,
                 max_rows: int = DEFAULT_MAX_ROWS) -> None:
        self.timeout_s = timeout_s
        self.max_rows = max_rows
        self._conn = sqlite3.connect(":memory:")
        self._conn.executescript(SCHEMA_SQL + SEED_SQL)
        # Cache the schema before locking the database down (PRAGMAs are denied afterwards).
        self._schema = self._read_schema()
        self._conn.set_authorizer(_read_only_authorizer)

    def _read_schema(self) -> dict[str, list[tuple[str, str]]]:
        tables = [r[0] for r in self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY rowid")]
        return {
            t: [(col[1], col[2]) for col in self._conn.execute(f'PRAGMA table_info("{t}")')]
            for t in tables
        }

    def table_names(self) -> list[str]:
        return list(self._schema)

    def table_columns(self, table: str) -> list[tuple[str, str]]:
        """Return (column_name, declared_type) pairs for a table."""
        return list(self._schema.get(table, []))

    def run(self, sql: str) -> QueryResult:
        """Run one statement and return its rows, or a friendly error."""
        if not sql.strip():
            return QueryResult(error="Type a query to see results.")

        deadline = time.monotonic() + self.timeout_s
        self._conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
        start = time.perf_counter()
        try:
            cursor = self._conn.execute(sql)
            rows = cursor.fetchmany(self.max_rows + 1)
            columns = [d[0] for d in cursor.description] if cursor.description else []
        except (sqlite3.Error, sqlite3.Warning, ValueError, OverflowError) as exc:
            return QueryResult(error=friendly_error(exc, self.timeout_s))
        finally:
            self._conn.set_progress_handler(None, 0)
            if self._conn.in_transaction:
                self._conn.rollback()

        truncated = len(rows) > self.max_rows
        return QueryResult(
            columns=columns,
            rows=rows[: self.max_rows],
            truncated=truncated,
            elapsed_ms=(time.perf_counter() - start) * 1000,
        )

    def close(self) -> None:
        self._conn.close()
