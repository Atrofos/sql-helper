"""Generate random practice questions from templates and the real practice data.

Each template picks random parameters (a table, a column, a threshold, a
category...) from values that actually exist in the practice database, builds a
prompt plus a solution query, and returns it. ``generate_questions`` then runs
every candidate solution and keeps it only if it works, returns rows, isn't
trivial, and doesn't duplicate an existing question. Generated questions are
therefore always answerable.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Callable

from .database import PracticeDatabase
from .questions import Question

MIXED = "Mixed"
GENERATOR_DIFFICULTIES = ("Easy", "Medium", "Hard", MIXED)
MAX_COUNT = 20
ATTEMPTS_PER_QUESTION = 40   # give up after this many rejected candidates per question


@dataclass
class Draft:
    """A candidate question before it's validated and given an id."""

    title: str
    prompt: str
    solution: str
    topic: str
    hint: str
    order_matters: bool = False


# Human-friendly names and the column that identifies a row in a sentence.
ENTITIES = {
    "employees": ("employee", "employees", "first_name"),
    "products": ("product", "products", "name"),
    "customers": ("customer", "customers", "name"),
    "departments": ("department", "departments", "name"),
    "orders": ("order", "orders", "order_id"),
}
NUMERIC = [("employees", "salary"), ("products", "price"), ("orders", "quantity")]
TEXT_FILTER = [("departments", "location"), ("customers", "country"), ("customers", "city"),
               ("products", "category"), ("orders", "status")]
NULLABLE = [("employees", "email", "an email address"), ("employees", "dept_id", "a department"),
            ("employees", "manager_id", "a manager"), ("customers", "city", "a city")]
GROUPABLE = [("products", "category"), ("orders", "status"), ("customers", "country"),
             ("departments", "location")]
GROUP_NUMERIC = [("employees", "dept_id", "salary"), ("products", "category", "price"),
                 ("orders", "status", "quantity"), ("orders", "customer_id", "quantity")]
AGGREGATES = [("AVG", "average"), ("MIN", "lowest"), ("MAX", "highest"), ("SUM", "total")]


def sql_literal(value) -> str:
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return fmt(value)


def fmt(value) -> str:
    """Show 250.0 as 250 so prompts read naturally."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


class _Data:
    """Read-only helpers for looking at the practice data."""

    def __init__(self, db: PracticeDatabase) -> None:
        self.db = db

    def column(self, table: str, col: str, distinct: bool = True) -> list:
        kw = "DISTINCT " if distinct else ""
        rows = self.db.run(f"SELECT {kw}{col} FROM {table} WHERE {col} IS NOT NULL ORDER BY {col}").rows
        return [r[0] for r in rows]

    def columns(self, table: str) -> list[str]:
        return [name for name, _type in self.db.table_columns(table)]

    def group_counts(self, table: str, col: str) -> list[int]:
        rows = self.db.run(f"SELECT COUNT(*) FROM {table} WHERE {col} IS NOT NULL "
                           f"GROUP BY {col}").rows
        return [r[0] for r in rows]


def _inner(values: list) -> list:
    """Drop the smallest and largest so filters keep some rows but not all."""
    return values[1:-1] if len(values) > 2 else values


# ---------------------------------------------------------------------------
# Easy templates
# ---------------------------------------------------------------------------
def easy_select_columns(rng: random.Random, d: _Data) -> Draft:
    table = rng.choice(list(ENTITIES))
    singular = ENTITIES[table][0]
    cols = d.columns(table)
    picked = sorted(rng.sample(cols, rng.choice((2, 3))), key=cols.index)
    listed = ", ".join(picked[:-1]) + " and " + picked[-1]
    return Draft(f"{table.title()}: {', '.join(picked)}",
                 f"List the {listed} of every {singular}.",
                 f"SELECT {', '.join(picked)} FROM {table};",
                 "SELECT", "Name the columns you want after SELECT, separated by commas.")


def easy_numeric_filter(rng: random.Random, d: _Data) -> Draft:
    table, col = rng.choice(NUMERIC)
    singular, plural, label = ENTITIES[table]
    value = rng.choice(_inner(d.column(table, col)))
    op, words = rng.choice([(">", "greater than"), ("<", "less than"),
                            (">=", "at least"), ("<=", "at most")])
    return Draft(f"{plural.title()} with {col} {op} {fmt(value)}",
                 f"Show the {label} and {col} of every {singular} whose {col} is {words} {fmt(value)}.",
                 f"SELECT {label}, {col} FROM {table} WHERE {col} {op} {fmt(value)};",
                 "WHERE", f"Filter with WHERE {col} {op} ...")


def easy_text_filter(rng: random.Random, d: _Data) -> Draft:
    table, col = rng.choice(TEXT_FILTER)
    singular, plural, label = ENTITIES[table]
    value = rng.choice(d.column(table, col))
    return Draft(f"{plural.title()} where {col} is {value}",
                 f"Show the {label} of every {singular} whose {col} is '{value}'.",
                 f"SELECT {label} FROM {table} WHERE {col} = {sql_literal(value)};",
                 "WHERE", "Text values go in single quotes.")


def easy_null_check(rng: random.Random, d: _Data) -> Draft:
    table, col, desc = rng.choice(NULLABLE)
    singular, plural, label = ENTITIES[table]
    missing = rng.random() < 0.5
    cond = "IS NULL" if missing else "IS NOT NULL"
    phrase = f"have no {desc.split(' ', 1)[1]}" if missing else f"have {desc}"
    return Draft(f"{plural.title()} that {phrase}",
                 f"Show the {label} of every {singular} that {phrase} (the {col} column).",
                 f"SELECT {label} FROM {table} WHERE {col} {cond};",
                 "NULL", "Comparing with = NULL never matches. Use IS NULL / IS NOT NULL.")


def easy_top_k(rng: random.Random, d: _Data) -> Draft | None:
    table, col = rng.choice(NUMERIC)
    _singular, plural, label = ENTITIES[table]
    desc = rng.random() < 0.5
    k = rng.randint(2, 4)
    values = sorted(d.column(table, col, distinct=False), reverse=desc)
    # Only usable if the first k values (and the cut-off) have no ties,
    # otherwise more than one answer would be "correct".
    if len(values) <= k or len(set(values[:k + 1])) != k + 1:
        return None
    word = "highest" if desc else "lowest"
    return Draft(f"Top {k} {plural} by {word} {col}",
                 f"Show the {label} and {col} of the {k} {plural} with the {word} {col}, "
                 f"{word} first.",
                 f"SELECT {label}, {col} FROM {table} ORDER BY {col} {'DESC' if desc else 'ASC'} "
                 f"LIMIT {k};",
                 "ORDER BY + LIMIT", "Sort with ORDER BY, then keep the first rows with LIMIT.",
                 order_matters=True)


def easy_count_where(rng: random.Random, d: _Data) -> Draft:
    table, col = rng.choice(TEXT_FILTER)
    _singular, plural, _label = ENTITIES[table]
    value = rng.choice(d.column(table, col))
    return Draft(f"Count {plural} where {col} is {value}",
                 f"How many {plural} have {col} '{value}'? Return a single number.",
                 f"SELECT COUNT(*) AS {plural}_count FROM {table} WHERE {col} = {sql_literal(value)};",
                 "COUNT", "COUNT(*) counts the rows that pass the WHERE filter.")


def easy_distinct(rng: random.Random, d: _Data) -> Draft:
    table, col = rng.choice(GROUPABLE)
    return Draft(f"Distinct {col} values in {table}",
                 f"List each different {col} from the {table} table, once each.",
                 f"SELECT DISTINCT {col} FROM {table};",
                 "DISTINCT", "SELECT DISTINCT removes duplicate rows.")


def easy_starts_with(rng: random.Random, d: _Data) -> Draft:
    table = rng.choice(["employees", "products", "customers", "departments"])
    singular, plural, label = ENTITIES[table]
    letter = rng.choice(d.column(table, label))[0].upper()
    return Draft(f"{plural.title()} starting with {letter}",
                 f"Show the {label} of every {singular} whose {label} starts with '{letter}'.",
                 f"SELECT {label} FROM {table} WHERE {label} LIKE '{letter}%';",
                 "LIKE", "In LIKE patterns, % matches any number of characters.")


# ---------------------------------------------------------------------------
# Medium templates
# ---------------------------------------------------------------------------
def medium_group_count(rng: random.Random, d: _Data) -> Draft:
    table, col = rng.choice(GROUPABLE)
    _singular, plural, _label = ENTITIES[table]
    return Draft(f"Number of {plural} per {col}",
                 f"For each {col}, show the {col} and how many {plural} have it.",
                 f"SELECT {col}, COUNT(*) AS {plural}_count FROM {table} GROUP BY {col};",
                 "GROUP BY", f"GROUP BY {col}, then COUNT(*).")


def medium_group_aggregate(rng: random.Random, d: _Data) -> Draft:
    table, group, num = rng.choice(GROUP_NUMERIC)
    _singular, plural, _label = ENTITIES[table]
    func, word = rng.choice(AGGREGATES)
    expr = f"ROUND(AVG({num}), 2)" if func == "AVG" else f"{func}({num})"
    extra = " rounded to 2 decimal places" if func == "AVG" else ""
    where = f" WHERE {group} IS NOT NULL" if table == "employees" else ""
    note = " Leave out employees with no department." if where else ""
    return Draft(f"{word.title()} {num} per {group}",
                 f"For each {group} in {table}, show the {group} and the {word} {num}{extra}.{note}",
                 f"SELECT {group}, {expr} AS {word}_{num} FROM {table}{where} GROUP BY {group};",
                 "GROUP BY", f"Use {func}({num}) together with GROUP BY {group}.")


def medium_having(rng: random.Random, d: _Data) -> Draft | None:
    table, col = rng.choice(GROUPABLE + [("employees", "dept_id"), ("orders", "customer_id")])
    singular, plural, _label = ENTITIES[table]
    counts = sorted(set(d.group_counts(table, col)))
    if len(counts) < 2:
        return None
    threshold = rng.choice(counts[:-1])   # at least one group passes, at least one doesn't
    where = f" WHERE {col} IS NOT NULL" if col == "dept_id" else ""
    noun = singular if threshold == 1 else plural
    return Draft(f"Each {col} with more than {threshold} {noun}",
                 f"Show each {col} that has more than {threshold} {noun}, along with its count.",
                 f"SELECT {col}, COUNT(*) AS {plural}_count FROM {table}{where} "
                 f"GROUP BY {col} HAVING COUNT(*) > {threshold};",
                 "HAVING", "WHERE filters rows before grouping. HAVING filters the groups.")


def medium_join(rng: random.Random, d: _Data) -> Draft:
    variant = rng.choice(["emp_dept", "order_customer", "order_product"])
    if variant == "emp_dept":
        locations = [r[0] for r in d.db.run(
            "SELECT DISTINCT d.location FROM departments d JOIN employees e ON e.dept_id = d.dept_id").rows]
        loc = rng.choice(locations)
        return Draft(f"Employees in {loc} departments",
                     f"Show the first_name of each employee and the name of their department, "
                     f"for departments located in '{loc}'.",
                     "SELECT e.first_name, d.name AS department FROM employees e "
                     f"JOIN departments d ON e.dept_id = d.dept_id WHERE d.location = {sql_literal(loc)};",
                     "JOIN", "Join employees to departments on dept_id, then filter on location.")
    if variant == "order_customer":
        status = rng.choice(d.column("orders", "status"))
        return Draft(f"Customer names on {status} orders",
                     f"Show the order_id and the customer's name for every order with status '{status}'.",
                     "SELECT o.order_id, c.name FROM orders o "
                     f"JOIN customers c ON o.customer_id = c.customer_id WHERE o.status = {sql_literal(status)};",
                     "JOIN", "Join orders to customers on customer_id.")
    category = rng.choice(d.column("products", "category"))
    return Draft(f"Orders for {category} products",
                 f"Show the order_id, product name and quantity of every order for a product "
                 f"in the '{category}' category.",
                 "SELECT o.order_id, p.name, o.quantity FROM orders o "
                 f"JOIN products p ON o.product_id = p.product_id WHERE p.category = {sql_literal(category)};",
                 "JOIN", "Join orders to products on product_id, then filter on category.")


def medium_left_join_count(rng: random.Random, d: _Data) -> Draft:
    if rng.random() < 0.5:
        return Draft("Employees per department (including empty ones)",
                     "Show every department name and how many employees it has. "
                     "Include departments with 0 employees.",
                     "SELECT d.name, COUNT(e.emp_id) AS employee_count FROM departments d "
                     "LEFT JOIN employees e ON e.dept_id = d.dept_id GROUP BY d.dept_id, d.name;",
                     "LEFT JOIN", "Start FROM departments and LEFT JOIN employees. COUNT(e.emp_id) skips NULLs.")
    return Draft("Orders per customer (including customers with none)",
                 "Show every customer name and how many orders they placed. "
                 "Include customers with 0 orders.",
                 "SELECT c.name, COUNT(o.order_id) AS order_count FROM customers c "
                 "LEFT JOIN orders o ON o.customer_id = c.customer_id GROUP BY c.customer_id, c.name;",
                 "LEFT JOIN", "Start FROM customers and LEFT JOIN orders. COUNT(o.order_id) skips NULLs.")


def medium_in_list(rng: random.Random, d: _Data) -> Draft | None:
    table, col = rng.choice(TEXT_FILTER)
    singular, plural, label = ENTITIES[table]
    values = d.column(table, col)
    if len(values) < 3:
        return None
    picked = sorted(rng.sample(values, 2))
    return Draft(f"{plural.title()} where {col} is {picked[0]} or {picked[1]}",
                 f"Show the {label} and {col} of every {singular} whose {col} is "
                 f"'{picked[0]}' or '{picked[1]}'.",
                 f"SELECT {label}, {col} FROM {table} WHERE {col} IN "
                 f"({', '.join(sql_literal(v) for v in picked)});",
                 "IN", "WHERE col IN ('a', 'b') is shorter than two ORs.")


def medium_between(rng: random.Random, d: _Data) -> Draft | None:
    table, col = rng.choice(NUMERIC + [("employees", "hire_date"), ("orders", "order_date")])
    singular, plural, label = ENTITIES[table]
    values = d.column(table, col)
    if len(values) < 4:
        return None
    lo, hi = sorted(rng.sample(_inner(values), 2))
    show = lambda v: f"'{v}'" if isinstance(v, str) else fmt(v)  # noqa: E731
    return Draft(f"{plural.title()} with {col} between {fmt(lo)} and {fmt(hi)}",
                 f"Show the {label} and {col} of every {singular} whose {col} is between "
                 f"{show(lo)} and {show(hi)} (inclusive).",
                 f"SELECT {label}, {col} FROM {table} WHERE {col} BETWEEN "
                 f"{sql_literal(lo)} AND {sql_literal(hi)};",
                 "BETWEEN", "BETWEEN includes both end values.")


def medium_case_bands(rng: random.Random, d: _Data) -> Draft | None:
    table, col = rng.choice([("employees", "salary"), ("products", "price")])
    singular, _plural, label = ENTITIES[table]
    values = _inner(d.column(table, col))
    if len(values) < 2:
        return None
    t1, t2 = sorted(rng.sample(values, 2))
    return Draft(f"{col.title()} bands at {fmt(t1)} / {fmt(t2)}",
                 f"Show every {singular}'s {label} and a {col}_band column: 'High' when {col} is "
                 f"{fmt(t2)} or more, 'Medium' when it is {fmt(t1)} or more, and 'Low' otherwise.",
                 f"SELECT {label}, CASE WHEN {col} >= {fmt(t2)} THEN 'High' "
                 f"WHEN {col} >= {fmt(t1)} THEN 'Medium' ELSE 'Low' END AS {col}_band FROM {table};",
                 "CASE", "CASE checks its WHEN conditions top to bottom and stops at the first match.")


# ---------------------------------------------------------------------------
# Hard templates
# ---------------------------------------------------------------------------
def hard_vs_average(rng: random.Random, d: _Data) -> Draft:
    table, col = rng.choice(NUMERIC)
    singular, plural, label = ENTITIES[table]
    above = rng.random() < 0.6
    op, word = (">", "more") if above else ("<", "less")
    return Draft(f"{plural.title()} {'above' if above else 'below'} average {col}",
                 f"Show the {label} and {col} of every {singular} whose {col} is {word} than "
                 f"the average {col} of all {plural}.",
                 f"SELECT {label}, {col} FROM {table} WHERE {col} {op} (SELECT AVG({col}) FROM {table});",
                 "Subquery", f"Aggregates can't go straight into WHERE. Compare with (SELECT AVG({col}) ...).")


def hard_top_per_group(rng: random.Random, d: _Data) -> Draft:
    if rng.random() < 0.5:
        return Draft("Top earner in each department",
                     "For each department, show the dept_id, first_name and salary of the employee "
                     "with the highest salary in that department. Ignore employees with no department.",
                     "SELECT dept_id, first_name, salary FROM employees e WHERE dept_id IS NOT NULL "
                     "AND salary = (SELECT MAX(salary) FROM employees x WHERE x.dept_id = e.dept_id);",
                     "Correlated subquery",
                     "For each row, compare salary with the MAX(salary) of the same dept_id.")
    return Draft("Most expensive product in each category",
                 "For each category, show the category, name and price of its most expensive product.",
                 "SELECT category, name, price FROM products p "
                 "WHERE price = (SELECT MAX(price) FROM products x WHERE x.category = p.category);",
                 "Correlated subquery",
                 "For each row, compare price with the MAX(price) of the same category.")


def hard_spend_having(rng: random.Random, d: _Data) -> Draft | None:
    totals = sorted(r[0] for r in d.db.run(
        "SELECT SUM(o.quantity * p.price) FROM orders o JOIN products p "
        "ON p.product_id = o.product_id GROUP BY o.customer_id").rows)
    if len(totals) < 3:
        return None
    threshold = rng.choice(totals[:-1])
    return Draft(f"Customers who spent more than {fmt(threshold)}",
                 "Show the name and total amount spent (quantity x price, all orders) of every "
                 f"customer whose total is more than {fmt(threshold)}.",
                 "SELECT c.name, SUM(o.quantity * p.price) AS total_spent FROM customers c "
                 "JOIN orders o ON o.customer_id = c.customer_id "
                 "JOIN products p ON p.product_id = o.product_id "
                 f"GROUP BY c.customer_id, c.name HAVING SUM(o.quantity * p.price) > {fmt(threshold)};",
                 "JOIN + HAVING", "Join three tables, GROUP BY customer, then filter the groups with HAVING.")


def hard_never_status(rng: random.Random, d: _Data) -> Draft:
    status = rng.choice(d.column("orders", "status"))
    return Draft(f"Customers with no {status} orders",
                 f"Show the name of every customer who has never had an order with status '{status}' "
                 "(customers with no orders at all count too).",
                 "SELECT name FROM customers WHERE customer_id NOT IN "
                 f"(SELECT customer_id FROM orders WHERE status = {sql_literal(status)});",
                 "NOT IN", "Find the customers who DO have such an order, then exclude them with NOT IN.")


def hard_reports_to(rng: random.Random, d: _Data) -> Draft | None:
    managers = [r[0] for r in d.db.run(
        "SELECT DISTINCT m.first_name FROM employees e JOIN employees m ON e.manager_id = m.emp_id").rows]
    if not managers:
        return None
    name = rng.choice(managers)
    return Draft(f"Who reports to {name}",
                 f"Show the first_name and salary of every employee whose manager is {name}. "
                 "(manager_id points to another row in employees.)",
                 "SELECT e.first_name, e.salary FROM employees e "
                 f"JOIN employees m ON e.manager_id = m.emp_id WHERE m.first_name = {sql_literal(name)};",
                 "Self JOIN", "Join employees to itself: employees e JOIN employees m ON e.manager_id = m.emp_id.")


def hard_nth_highest(rng: random.Random, d: _Data) -> Draft:
    table, col = rng.choice(NUMERIC)
    n = rng.randint(2, 4)
    nth = {2: "2nd", 3: "3rd", 4: "4th"}[n]
    return Draft(f"{nth} highest {col} in {table}",
                 f"What is the {nth} highest distinct {col} in the {table} table? Return a single value.",
                 f"SELECT DISTINCT {col} FROM {table} ORDER BY {col} DESC LIMIT 1 OFFSET {n - 1};",
                 "ORDER BY + OFFSET", "Use DISTINCT, sort descending, then skip rows with OFFSET.")


def hard_revenue_by_category(rng: random.Random, d: _Data) -> Draft:
    excluded = rng.choice(d.column("orders", "status"))
    return Draft(f"Revenue per category (excluding {excluded})",
                 "For each product category, show the category and its total revenue "
                 f"(quantity x price), leaving out orders with status '{excluded}'.",
                 "SELECT p.category, SUM(o.quantity * p.price) AS revenue FROM orders o "
                 f"JOIN products p ON p.product_id = o.product_id WHERE o.status <> {sql_literal(excluded)} "
                 "GROUP BY p.category;",
                 "JOIN + GROUP BY", "Filter rows with WHERE before GROUP BY, then SUM(quantity * price).")


TEMPLATES: dict[str, list[Callable[[random.Random, _Data], Draft | None]]] = {
    "Easy": [easy_select_columns, easy_numeric_filter, easy_text_filter, easy_null_check,
             easy_top_k, easy_count_where, easy_distinct, easy_starts_with],
    "Medium": [medium_group_count, medium_group_aggregate, medium_having, medium_join,
               medium_left_join_count, medium_in_list, medium_between, medium_case_bands],
    "Hard": [hard_vs_average, hard_top_per_group, hard_spend_having, hard_never_status,
             hard_reports_to, hard_nth_highest, hard_revenue_by_category],
}


def normalize_sql(sql: str) -> str:
    """Whitespace/case/semicolon-insensitive form, used to spot duplicates."""
    return re.sub(r"\s+", " ", sql.strip().rstrip(";")).lower()


def generate_questions(db: PracticeDatabase, difficulty: str, count: int,
                       id_factory: Callable[[str], str],
                       existing_solutions: set[str] | None = None,
                       rng: random.Random | None = None) -> list[Question]:
    """Return up to ``count`` new, validated questions.

    ``difficulty`` is Easy/Medium/Hard, or Mixed for a random mix. Fewer than
    ``count`` questions come back only if the templates run out of unique
    variations (the caller should say so).
    """
    if difficulty not in GENERATOR_DIFFICULTIES:
        raise ValueError(f"unknown difficulty: {difficulty}")
    count = max(1, min(int(count), MAX_COUNT))
    rng = rng or random.Random()
    data = _Data(db)
    seen = {normalize_sql(s) for s in (existing_solutions or set())}
    questions: list[Question] = []

    attempts = 0
    while len(questions) < count and attempts < count * ATTEMPTS_PER_QUESTION:
        attempts += 1
        level = rng.choice(("Easy", "Medium", "Hard")) if difficulty == MIXED else difficulty
        draft = rng.choice(TEMPLATES[level])(rng, data)
        if draft is None or normalize_sql(draft.solution) in seen:
            continue
        result = db.run(draft.solution)
        if not result.ok or not result.rows:
            continue
        seen.add(normalize_sql(draft.solution))
        questions.append(Question(
            id=id_factory(draft.title), title=draft.title, prompt=draft.prompt,
            solution=draft.solution, difficulty=level, topic=draft.topic, hint=draft.hint,
            order_matters=draft.order_matters, generated=True,
        ))
    return questions
