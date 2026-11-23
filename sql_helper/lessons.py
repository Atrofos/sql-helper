"""Illustrated lesson cards for every SQL and Python topic.

Each Lesson has a short explanation, a small code example, and a ``diagram``:
a plain dict that describes a picture. The UI (lesson_view.py) draws it on a
Tk canvas. Keeping the diagrams as data means this module has no UI code and
is easy to test and extend.

Diagram types (``diagram["type"]``):

* ``panels``    tables left-to-right with arrows between them. Rows can be
                "keep" / "drop" / "new", or coloured by group number; columns
                can be highlighted. Optional ``links`` draw JOIN lines between
                rows of the first two panels.
* ``sequence``  rows of indexed boxes (strings, lists, ranges). Each row can
                highlight a range of boxes and show negative indexes.
* ``kv``        a dictionary drawn as key -> value pairs.
* ``flow``      a flowchart of boxes top-to-bottom; ``loop_to`` draws an arrow
                back up for loops.
* ``venn``      two overlapping sets.
* ``refs``      variable names with arrows to the values they point at.

Lessons are matched to questions by the question's ``lesson`` field, or else
by keywords in its topic (see ``lesson_for``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .questions import MODE_PYTHON, MODE_SQL, Question


@dataclass
class Lesson:
    id: str
    mode: str
    title: str
    summary: str
    example: str
    diagram: dict
    keywords: tuple[str, ...] = field(default_factory=tuple)


def table(name, columns, rows, states=None, groups=None, highlight_cols=None):
    return {"name": name, "columns": columns, "rows": rows, "states": states,
            "groups": groups, "highlight_cols": highlight_cols or []}


EMP_COLS = ["first_name", "dept_id", "salary"]
EMP_ROWS = [["Alice", 1, 145000], ["Emma", 2, 72000], ["Grace", 3, 105000],
            ["Henry", 3, 64000], ["Jack", None, 55000]]

SQL_LESSONS = [
    Lesson("sql_select", MODE_SQL, "SELECT: choose columns",
           "SELECT picks which columns you want; FROM says which table. SELECT * means every "
           "column. The result always has one row per row in the table (until you filter).",
           "SELECT first_name, salary\nFROM employees;",
           {"type": "panels", "panels": [
               table("employees", EMP_COLS, EMP_ROWS[:4], highlight_cols=[0, 2]),
               table("result", ["first_name", "salary"], [[r[0], r[2]] for r in EMP_ROWS[:4]])],
            "caption": "Only the highlighted columns are kept."},
           ("SELECT",)),
    Lesson("sql_where", MODE_SQL, "WHERE: keep matching rows",
           "WHERE tests every row against a condition and keeps only the rows where it's true. "
           "Text goes in single quotes. Combine conditions with AND / OR.",
           "SELECT first_name, salary\nFROM employees\nWHERE salary > 100000;",
           {"type": "panels", "panels": [
               table("employees", EMP_COLS, EMP_ROWS, states=["keep", "drop", "keep", "drop", "drop"]),
               table("result", EMP_COLS, [EMP_ROWS[0], EMP_ROWS[2]])],
            "caption": "Rows failing salary > 100000 are dropped (greyed out)."},
           ("WHERE",)),
    Lesson("sql_order_by", MODE_SQL, "ORDER BY: sort the rows",
           "Without ORDER BY, rows come back in no guaranteed order. ORDER BY col sorts "
           "ascending (smallest first); add DESC for largest first. You can sort by several columns.",
           "SELECT first_name, salary\nFROM employees\nORDER BY salary DESC;",
           {"type": "panels", "panels": [
               table("before", ["first_name", "salary"], [[r[0], r[2]] for r in EMP_ROWS]),
               table("ORDER BY salary DESC", ["first_name", "salary"],
                     [[r[0], r[2]] for r in sorted(EMP_ROWS, key=lambda r: -r[2])],
                     highlight_cols=[1])],
            "caption": "Same rows, new order."},
           ("ORDER BY",)),
    Lesson("sql_limit", MODE_SQL, "LIMIT and OFFSET: keep the first rows",
           "LIMIT n keeps only the first n rows of the result, so it's almost always used after "
           "ORDER BY ('top 3'). OFFSET k skips k rows first, e.g. the 2nd highest is "
           "ORDER BY x DESC LIMIT 1 OFFSET 1. SQL Server uses TOP instead of LIMIT.",
           "SELECT first_name, salary\nFROM employees\nORDER BY salary DESC\nLIMIT 2;",
           {"type": "panels", "panels": [
               table("sorted", ["first_name", "salary"],
                     [[r[0], r[2]] for r in sorted(EMP_ROWS, key=lambda r: -r[2])],
                     states=["keep", "keep", "drop", "drop", "drop"]),
               table("LIMIT 2", ["first_name", "salary"], [["Alice", 145000], ["Grace", 105000]])],
            "caption": "Sort first, then cut."},
           ("LIMIT", "OFFSET")),
    Lesson("sql_distinct", MODE_SQL, "DISTINCT: remove duplicates",
           "SELECT DISTINCT removes rows that are exact copies of an earlier row in the result. "
           "It looks at all selected columns together.",
           "SELECT DISTINCT location\nFROM departments;",
           {"type": "panels", "panels": [
               table("location", ["location"], [["San Francisco"], ["New York"], ["New York"],
                                               ["Chicago"], ["Boston"]],
                     states=["keep", "keep", "drop", "keep", "keep"]),
               table("DISTINCT", ["location"], [["San Francisco"], ["New York"], ["Chicago"],
                                               ["Boston"]])],
            "caption": "The second 'New York' is a duplicate."},
           ("DISTINCT",)),
    Lesson("sql_null", MODE_SQL, "NULL: a missing value",
           "NULL means 'unknown'. Any comparison with NULL (even = NULL) is not true, so use "
           "IS NULL / IS NOT NULL. COUNT(col) skips NULLs; COUNT(*) counts every row.",
           "SELECT first_name\nFROM employees\nWHERE email IS NULL;",
           {"type": "panels", "panels": [
               table("employees", ["first_name", "email"],
                     [["Alice", "alice.chen@..."], ["Henry", None], ["Jack", None], ["Karen", "karen.patel@..."]],
                     states=["drop", "keep", "keep", "drop"]),
               table("IS NULL", ["first_name"], [["Henry"], ["Jack"]])],
            "caption": "WHERE email = NULL would return nothing at all."},
           ("NULL",)),
    Lesson("sql_like", MODE_SQL, "LIKE: match a text pattern",
           "LIKE compares text with a pattern. % matches any number of characters (including none) "
           "and _ matches exactly one. In SQLite, LIKE ignores upper/lower case for A-Z.",
           "SELECT name\nFROM products\nWHERE name LIKE '%Desk%';",
           {"type": "panels", "panels": [
               table("products", ["name"], [["Laptop"], ["Desk Chair"], ["Standing Desk"], ["Mouse"]],
                     states=["drop", "keep", "keep", "drop"]),
               table("LIKE '%Desk%'", ["name"], [["Desk Chair"], ["Standing Desk"]])],
            "caption": "'%Desk%' = anything, then Desk, then anything."},
           ("LIKE",)),
    Lesson("sql_in_between", MODE_SQL, "IN and BETWEEN: shortcuts for conditions",
           "x IN ('a', 'b') is short for x = 'a' OR x = 'b'. x BETWEEN 1 AND 5 is short for "
           "x >= 1 AND x <= 5: both ends are included. NOT IN excludes a list of values.",
           "SELECT order_id, status\nFROM orders\nWHERE status IN ('shipped', 'pending');",
           {"type": "panels", "panels": [
               table("orders", ["order_id", "status"],
                     [[1, "delivered"], [4, "shipped"], [6, "cancelled"], [8, "pending"]],
                     states=["drop", "keep", "drop", "keep"]),
               table("IN (...)", ["order_id", "status"], [[4, "shipped"], [8, "pending"]])],
            "caption": "Keep rows whose status is in the list."},
           ("BETWEEN", "NOT IN", " IN", "IN")),
    Lesson("sql_aggregates", MODE_SQL, "Aggregates: many rows to one value",
           "COUNT, SUM, AVG, MIN and MAX squash a column into a single value. Without GROUP BY "
           "they summarise the whole table, so the result has one row.",
           "SELECT COUNT(*), AVG(salary)\nFROM employees;",
           {"type": "panels", "panels": [
               table("employees", ["salary"], [[r[2]] for r in EMP_ROWS], highlight_cols=[0]),
               table("result", ["COUNT(*)", "AVG(salary)"], [[5, 88200]])],
            "caption": "Five rows go in, one row comes out."},
           ("Aggregate", "COUNT", "SUM", "AVG")),
    Lesson("sql_group_by", MODE_SQL, "GROUP BY: one row per group",
           "GROUP BY puts rows with the same value into buckets, then aggregates run once per "
           "bucket. Every selected column must be grouped or aggregated. All NULLs form one group.",
           "SELECT dept_id, COUNT(*), AVG(salary)\nFROM employees\nGROUP BY dept_id;",
           {"type": "panels", "panels": [
               table("employees", EMP_COLS, sorted(EMP_ROWS[:4], key=lambda r: r[1]),
                     groups=[0, 1, 2, 2], highlight_cols=[1]),
               table("GROUP BY dept_id", ["dept_id", "COUNT(*)", "AVG(salary)"],
                     [[1, 1, 145000], [2, 1, 72000], [3, 2, 84500]], groups=[0, 1, 2])],
            "caption": "Each colour is one group; each group becomes one result row."},
           ("GROUP BY",)),
    Lesson("sql_having", MODE_SQL, "HAVING: filter the groups",
           "WHERE filters rows before grouping. HAVING filters groups after grouping, so it can "
           "use aggregates like COUNT(*) > 2. Order: FROM, WHERE, GROUP BY, HAVING, SELECT, ORDER BY.",
           "SELECT dept_id, COUNT(*)\nFROM employees\nGROUP BY dept_id\nHAVING COUNT(*) > 2;",
           {"type": "panels", "panels": [
               table("groups", ["dept_id", "COUNT(*)"], [[1, 4], [2, 4], [3, 2], [4, 1]],
                     states=["keep", "keep", "drop", "drop"], groups=[0, 1, 2, 3]),
               table("HAVING COUNT(*) > 2", ["dept_id", "COUNT(*)"], [[1, 4], [2, 4]], groups=[0, 1])],
            "caption": "Whole groups are kept or dropped."},
           ("HAVING",)),
    Lesson("sql_join", MODE_SQL, "INNER JOIN: match rows across tables",
           "JOIN combines each row of one table with the rows of another where the ON condition "
           "matches, usually a shared id. Rows with no match on either side are left out.",
           "SELECT e.first_name, d.name\nFROM employees e\nJOIN departments d\n  ON e.dept_id = d.dept_id;",
           {"type": "panels", "panels": [
               table("employees", ["first_name", "dept_id"], [["Alice", 1], ["Emma", 2], ["Jack", None]],
                     states=["keep", "keep", "drop"]),
               table("departments", ["dept_id", "name"], [[1, "Engineering"], [2, "Sales"], [5, "Legal"]],
                     states=["keep", "keep", "drop"]),
               table("result", ["first_name", "name"], [["Alice", "Engineering"], ["Emma", "Sales"]])],
            "links": [[0, 0], [1, 1]],
            "caption": "Lines show matching dept_id values. Jack and Legal have no match."},
           ("JOIN",)),
    Lesson("sql_left_join", MODE_SQL, "LEFT JOIN: keep every left row",
           "LEFT JOIN keeps every row from the left table. Where there's no match, the right "
           "table's columns are NULL. 'Find X with no Y' = LEFT JOIN, then WHERE y.id IS NULL.",
           "SELECT d.name, COUNT(e.emp_id)\nFROM departments d\nLEFT JOIN employees e\n"
           "  ON e.dept_id = d.dept_id\nGROUP BY d.name;",
           {"type": "panels", "panels": [
               table("departments", ["dept_id", "name"], [[1, "Engineering"], [2, "Sales"], [5, "Legal"]]),
               table("employees", ["first_name", "dept_id"], [["Alice", 1], ["Emma", 2]]),
               table("result", ["name", "first_name"],
                     [["Engineering", "Alice"], ["Sales", "Emma"], ["Legal", None]],
                     states=[None, None, "new"])],
            "links": [[0, 0], [1, 1]],
            "caption": "Legal has no employees but is still kept, with NULL."},
           ("LEFT JOIN",)),
    Lesson("sql_self_join", MODE_SQL, "Self JOIN: a table joined to itself",
           "When a column points at another row of the same table (like manager_id), join the "
           "table to itself with two aliases, e.g. e for the employee and m for the manager.",
           "SELECT e.first_name, m.first_name AS manager\nFROM employees e\nJOIN employees m\n"
           "  ON e.manager_id = m.emp_id;",
           {"type": "panels", "panels": [
               table("employees e", ["first_name", "manager_id"], [["Bob", 1], ["Carol", 1], ["Emma", 4]]),
               table("employees m", ["emp_id", "first_name"], [[1, "Alice"], [4, "David"]]),
               table("result", ["employee", "manager"], [["Bob", "Alice"], ["Carol", "Alice"], ["Emma", "David"]])],
            "links": [[0, 0], [1, 0], [2, 1]],
            "caption": "Two copies of the same table, matched on manager_id = emp_id."},
           ("Self JOIN",)),
    Lesson("sql_subquery", MODE_SQL, "Subqueries: a query inside a query",
           "A subquery in brackets runs first and its result is used by the outer query. A common "
           "use: compare against an aggregate, since WHERE salary > AVG(salary) isn't allowed.",
           "SELECT first_name, salary\nFROM employees\nWHERE salary > (SELECT AVG(salary) FROM employees);",
           {"type": "panels", "panels": [
               table("(SELECT AVG(salary))", ["AVG(salary)"], [[92250]]),
               table("employees", ["first_name", "salary"], [["Alice", 145000], ["Emma", 72000], ["Carol", 98000]],
                     states=["keep", "drop", "keep"]),
               table("result", ["first_name", "salary"], [["Alice", 145000], ["Carol", 98000]])],
            "caption": "Step 1: the inner query gives 92250. Step 2: the outer query filters with it."},
           ("Subquery",)),
    Lesson("sql_correlated", MODE_SQL, "Correlated subqueries: per-row lookups",
           "A correlated subquery refers to the outer row (e.g. x.dept_id = e.dept_id), so it "
           "runs once per row. Classic use: 'the top earner in each department'.",
           "SELECT dept_id, first_name, salary\nFROM employees e\nWHERE salary = (\n"
           "  SELECT MAX(salary) FROM employees x\n  WHERE x.dept_id = e.dept_id);",
           {"type": "panels", "panels": [
               table("employees", EMP_COLS, sorted(EMP_ROWS[:4], key=lambda r: r[1]),
                     groups=[0, 1, 2, 2], states=["keep", "keep", "keep", "drop"]),
               table("result", EMP_COLS, [EMP_ROWS[0], EMP_ROWS[1], EMP_ROWS[2]], groups=[0, 1, 2])],
            "caption": "Each row is compared with the MAX of its own group (colour)."},
           ("Correlated",)),
    Lesson("sql_case", MODE_SQL, "CASE: if/else inside a query",
           "CASE WHEN condition THEN value ... ELSE value END makes a new column from rules. "
           "Conditions are checked top to bottom and the first match wins.",
           "SELECT first_name,\n  CASE WHEN salary >= 100000 THEN 'High'\n"
           "       WHEN salary >= 70000 THEN 'Medium'\n       ELSE 'Low' END AS band\nFROM employees;",
           {"type": "panels", "panels": [
               table("employees", ["first_name", "salary"], [[r[0], r[2]] for r in EMP_ROWS[:4]]),
               table("with CASE", ["first_name", "band"],
                     [["Alice", "High"], ["Emma", "Medium"], ["Grace", "High"], ["Henry", "Low"]],
                     groups=[0, 1, 0, 2], highlight_cols=[1])],
            "caption": "Each row gets a label from the first rule it matches."},
           ("CASE",)),
]

PY_LESSONS = [
    Lesson("py_variables", MODE_PYTHON, "Variables: names for values",
           "A variable is a name that points at a value. `=` makes the name point at a new value. "
           "y = x makes y point at x's current value; numbers and strings can't be changed in "
           "place, so later reassigning x doesn't affect y.",
           "x = 5\ny = x\nx = 10\nprint(x, y)   # 10 5",
           {"type": "refs", "names": [["x", 1], ["y", 0]], "values": ["5", "10"],
            "caption": "After x = 10, x points at a new value; y still points at 5."},
           ("Variables",)),
    Lesson("py_strings", MODE_PYTHON, "Strings and indexes",
           "A string is a sequence of characters. s[0] is the first character and s[-1] the last. "
           "len(s) is the length. Strings can't be changed in place: methods return new strings.",
           's = "PYTHON"\nprint(s[0], s[-1])   # P N\nprint(len(s))        # 6',
           {"type": "sequence", "rows": [{"label": 's = "PYTHON"', "items": list("PYTHON"),
                                          "negative": True, "highlight": [0, 1]}],
            "caption": "Top numbers count from the front (0..5); bottom from the back (-6..-1)."},
           ("Strings",)),
    Lesson("py_slicing", MODE_PYTHON, "Slicing: take part of a sequence",
           "s[start:stop] takes items from start up to, but not including, stop. Leave one out "
           "to go to the edge. A third number is the step: s[::-1] walks backwards (reverses).",
           's = "PYTHON"\nprint(s[1:4])   # YTH\nprint(s[:2])    # PY\nprint(s[::-1])  # NOHTYP',
           {"type": "sequence", "rows": [
               {"label": "s[1:4]", "items": list("PYTHON"), "highlight": [1, 4]},
               {"label": "s[:2]", "items": list("PYTHON"), "highlight": [0, 2]},
               {"label": "s[-2:]", "items": list("PYTHON"), "highlight": [4, 6], "negative": True}],
            "caption": "The stop index is never included."},
           ("Slicing",)),
    Lesson("py_string_methods", MODE_PYTHON, "String methods",
           "Strings come with methods: .upper(), .lower(), .strip(), .split(), .replace(a, b), "
           ".count(x), .startswith(x). They return new values; the original string is unchanged. "
           '" ".join(words) glues a list of strings back together.',
           'name = "  Ada Lovelace "\nprint(name.strip().upper())   # ADA LOVELACE\n'
           'print("a,b,c".split(","))       # [\'a\', \'b\', \'c\']',
           {"type": "panels", "panels": [
               table('s = "Hello World"', ["call", "result"],
                     [["s.upper()", "'HELLO WORLD'"], ["s.lower()", "'hello world'"],
                      ["s.split()", "['Hello', 'World']"], ["s.count('o')", "2"],
                      ["s.replace('World', 'Py')", "'Hello Py'"]], highlight_cols=[1])],
            "caption": "Each method gives back a new value."},
           ("String method",)),
    Lesson("py_lists", MODE_PYTHON, "Lists: ordered, changeable collections",
           "A list holds items in order: nums = [3, 1, 4]. Index and slice like strings. Unlike "
           "strings, lists change in place: .append(x) adds to the end, .pop() removes the last "
           "item (pop(0) the first). Two names can point at the same list.",
           "nums = [3, 1, 4]\nnums.append(1)\nfirst = nums.pop(0)\nprint(first, nums)   # 3 [1, 4, 1]",
           {"type": "sequence", "rows": [
               {"label": "nums = [3, 1, 4]", "items": ["3", "1", "4"]},
               {"label": ".append(1)", "items": ["3", "1", "4", "1"], "highlight": [3, 4]},
               {"label": ".pop(0) -> 3", "items": ["1", "4", "1"]}],
            "caption": "The list itself changes after each method call."},
           ("List",)),
    Lesson("py_loops", MODE_PYTHON, "for loops: repeat for each item",
           "for item in sequence: runs the indented block once per item, with item set to each "
           "value in turn. A running total starts before the loop and is updated inside it.",
           "total = 0\nfor n in [4, 2, 5]:\n    total += n\nprint(total)   # 11",
           {"type": "panels", "panels": [
               table("each pass of the loop", ["pass", "n", "total after"],
                     [[1, 4, 4], [2, 2, 6], [3, 5, 11]], highlight_cols=[2])],
            "caption": "Trace the variables pass by pass. Try the Visualise tab to step through yours."},
           ("Loop",)),
    Lesson("py_while", MODE_PYTHON, "while loops: repeat while a condition is true",
           "while condition: repeats the block as long as the condition is True. Something inside "
           "must eventually make it False, or the loop never ends.",
           "n = 20\nsteps = 0\nwhile n > 1:\n    n //= 2\n    steps += 1\nprint(n, steps)   # 1 4",
           {"type": "flow", "steps": [
               {"text": "n = 20, steps = 0", "kind": "action"},
               {"text": "n > 1 ?", "kind": "decision", "no": "exit loop"},
               {"text": "n //= 2;  steps += 1", "kind": "action"}],
            "loop_to": 1, "caption": "After each pass, the condition is checked again."},
           ("While",)),
    Lesson("py_range", MODE_PYTHON, "range(): sequences of numbers",
           "range(stop) counts 0 up to stop - 1. range(start, stop) starts somewhere else, and "
           "range(start, stop, step) jumps by step. The stop value is never included.",
           "print(list(range(4)))         # [0, 1, 2, 3]\nprint(list(range(2, 10, 3)))  # [2, 5, 8]",
           {"type": "sequence", "rows": [
               {"label": "range(4)", "items": ["0", "1", "2", "3"], "no_index": True},
               {"label": "range(2, 10, 3)", "items": [str(i) for i in range(2, 11)],
                "picks": [0, 3, 6], "no_index": True}],
            "caption": "Highlighted numbers are produced; 10 is the stop, so it's not included."},
           ("Range",)),
    Lesson("py_conditionals", MODE_PYTHON, "if / elif / else: making decisions",
           "if runs its block only when the condition is True. elif checks another condition if "
           "the earlier ones were False, and else catches everything left. Only one branch runs, "
           "so put the most specific check first.",
           'if n % 15 == 0:\n    return "FizzBuzz"\nelif n % 3 == 0:\n    return "Fizz"\nelse:\n    return str(n)',
           {"type": "flow", "steps": [
               {"text": "n % 15 == 0 ?", "kind": "decision", "yes": '"FizzBuzz"'},
               {"text": "n % 3 == 0 ?", "kind": "decision", "yes": '"Fizz"'},
               {"text": "else: str(n)", "kind": "action"}],
            "caption": "The first condition that's True wins; the rest are skipped."},
           ("Conditional",)),
    Lesson("py_functions", MODE_PYTHON, "Functions: def, parameters and return",
           "def name(params): defines a reusable block. Calling it passes values in as the "
           "parameters. return sends a value back to the caller; print only shows it on screen. "
           "A function without return gives back None. Variables inside are local.",
           "def double(n):\n    return n * 2\n\nresult = double(4)   # 8",
           {"type": "flow", "steps": [
               {"text": "double(4)   (call with 4)", "kind": "action"},
               {"text": "def double(n):   n = 4 inside", "kind": "action"},
               {"text": "return n * 2   ->  8", "kind": "action"},
               {"text": "result = 8   (back in the caller)", "kind": "action"}],
            "caption": "Values go in through parameters and come out through return."},
           ("Function",)),
    Lesson("py_dicts", MODE_PYTHON, "Dictionaries: look up values by key",
           "A dict maps keys to values: d = {'apple': 3}. d[key] reads a value (KeyError if "
           "missing); d.get(key, default) is safe. d[key] = value adds or updates. "
           "Counting pattern: d[w] = d.get(w, 0) + 1.",
           'counts = {}\nfor w in "a b a".split():\n    counts[w] = counts.get(w, 0) + 1\nprint(counts)   # {\'a\': 2, \'b\': 1}',
           {"type": "kv", "label": "counts", "pairs": [["'a'", "2"], ["'b'", "1"]],
            "caption": "Each key appears once and points at its value."},
           ("Dictionar",)),
    Lesson("py_sets", MODE_PYTHON, "Sets: unique items",
           "A set holds each value at most once, with no order: set([3, 1, 3]) is {1, 3}. It's "
           "the quickest way to remove duplicates, and supports & (in both), | (in either) and "
           "- (in one but not the other).",
           "a = {1, 2, 3}\nb = {2, 3, 4}\nprint(a & b)   # {2, 3}\nprint(a | b)   # {1, 2, 3, 4}",
           {"type": "venn", "left": ["1"], "both": ["2", "3"], "right": ["4"],
            "labels": ["a", "b"], "caption": "a & b is the middle; a | b is everything."},
           ("Set",)),
    Lesson("py_comprehensions", MODE_PYTHON, "List comprehensions",
           "[expression for item in sequence if condition] builds a new list in one line. It's "
           "the same as a for loop that appends, with an optional filter.",
           "nums = [1, 2, 3, 4, 5]\nevens_squared = [n * n for n in nums if n % 2 == 0]\nprint(evens_squared)   # [4, 16]",
           {"type": "sequence", "rows": [
               {"label": "nums", "items": ["1", "2", "3", "4", "5"], "picks": [1, 3], "no_index": True},
               {"label": "if n % 2 == 0", "items": ["2", "4"], "no_index": True},
               {"label": "n * n", "items": ["4", "16"], "no_index": True, "highlight": [0, 2]}],
            "caption": "Filter first (if), then transform (expression)."},
           ("Comprehension",)),
    Lesson("py_sorting", MODE_PYTHON, "Sorting with sorted() and key",
           "sorted(items) returns a new sorted list; items.sort() sorts in place. key= is a "
           "function used to compare items, e.g. key=len sorts by length. reverse=True flips it. "
           "Python's sort is stable: equal items keep their order.",
           'words = ["banana", "fig", "apple"]\nprint(sorted(words, key=len))   # [\'fig\', \'apple\', \'banana\']',
           {"type": "sequence", "rows": [
               {"label": "words", "items": ["banana", "fig", "apple"], "no_index": True},
               {"label": "key=len", "items": ["6", "3", "5"], "no_index": True},
               {"label": "sorted", "items": ["fig", "apple", "banana"], "no_index": True,
                "highlight": [0, 3]}],
            "caption": "Items are ordered by their key values (3, 5, 6)."},
           ("Sort",)),
    Lesson("py_errors", MODE_PYTHON, "try / except: handling errors",
           "Code that might fail goes in try. If an error happens, Python jumps to the matching "
           "except block instead of crashing. Catch specific errors (like ZeroDivisionError), "
           "not everything.",
           "try:\n    result = a / b\nexcept ZeroDivisionError:\n    result = None",
           {"type": "flow", "steps": [
               {"text": "try:  result = a / b", "kind": "decision", "yes": "worked: carry on",
                "question": "error?"},
               {"text": "except ZeroDivisionError:  result = None", "kind": "action"}],
            "caption": "Only when an error happens does the except block run."},
           ("Error",)),
]

ALL_LESSONS = SQL_LESSONS + PY_LESSONS
BY_ID = {lesson.id: lesson for lesson in ALL_LESSONS}


def lessons_for_mode(mode: str) -> list[Lesson]:
    return [lesson for lesson in ALL_LESSONS if lesson.mode == mode]


def lesson_for(question: Question | None, mode: str) -> Lesson:
    """The lesson for a question: its ``lesson`` field, else the best keyword match on its topic.

    Longer keywords are tried first, so "LEFT JOIN" beats "JOIN" and "GROUP BY + ORDER BY"
    goes to GROUP BY rather than ORDER BY (the first keyword found in the topic wins).
    """
    options = lessons_for_mode(mode)
    if question is None:
        return options[0]
    if question.lesson in BY_ID:
        return BY_ID[question.lesson]
    topic = question.topic.lower()
    best: tuple[int, int, Lesson] | None = None
    for lesson in options:
        for kw in lesson.keywords:
            at = topic.find(kw.lower().strip())
            if at == -1:
                continue
            # Prefer the match that starts earliest in the topic, then the longest keyword.
            rank = (at, -len(kw.strip()))
            if best is None or rank < best[:2]:
                best = (*rank, lesson)
    return best[2] if best else options[0]
