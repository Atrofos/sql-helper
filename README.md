# SQL Helper

A small desktop app for practicing entry-level **SQL** and **Python** interview
questions. Pick a mode with the **SQL | Python** switch at the top. Write code
on the left, and the results on the right update as you type.

Both modes share the same features (below), plus:

- **Lesson cards:** every topic has a short illustrated lesson, e.g. how a JOIN
  matches rows, how GROUP BY buckets them, or how slicing counts positions.
  Open it with the **Lesson** button or tab.
- **Python mode** has two question styles, *write a function* and *predict the
  output*, and a **Visualise** tab that steps through your code line by line
  (see [Python mode](#python-mode)).

Shared features:

- **Live preview:** results refresh about a third of a second after you stop typing.
  Half-written SQL doesn't clear the grid. The last valid result stays on screen
  and the error appears in the status bar.
- **Built-in questions:** 23 for SQL (`SELECT`, `WHERE`, `ORDER BY`, `LIMIT`,
  `DISTINCT`, `LIKE`, `IN`, `BETWEEN`, `NULL`, aggregates, `GROUP BY`,
  `HAVING`, `INNER`/`LEFT`/self `JOIN`, subqueries and `CASE`) and 29 for
  Python (functions, strings, slicing, lists, loops, conditionals,
  dictionaries, sets, comprehensions, sorting, `try`/`except`).
- **Run** a correct answer and the question is marked done. Use **Check
  Answer** to grade any attempt and get an explanation of what's wrong: column
  count, missing or extra rows, or wrong order.
- After you complete a question, **Next ›** turns blue with a ✓ so you know
  where to go.
- **Expected Result** stays hidden until you press **Show Expected Result**, so
  you can try first. It's revealed automatically once you get the answer right.
- **Question generator:** choose a difficulty (Easy, Medium, Hard or Mixed) and
  how many questions, press **Randomise**, then save the set.
- **Reset progress** for one question or for everything in the current mode.
  A backup is kept.
- **Tables** tab (SQL) lets you browse every practice table and its columns.
- **Your own questions:** create, edit and delete them. They're saved as JSON
  files in `user_data/questions/`.
- **Attempt history:** every checked attempt goes to `user_data/history.jsonl`.
  Solved questions get a ✓ in the sidebar.
- **Question sidebar:** every question is listed down the left, grouped into
  Easy / Medium / Hard with a solved count per group. Search by title or
  topic. **‹ Prev / Next ›** are at the bottom of the sidebar. The sidebar icon
  at the top left hides or shows it; while it's hidden, **‹ Prev / Next ›** move
  to the bottom right of the window, and the dividers stop before any pane gets
  too narrow to use.
- **Progress report:** **Report…** explains where you went wrong on the
  questions you made or generated (or all questions), and saves it as a web
  page (see [Progress report](#progress-report)).
- **Free practice:** run any query or Python code with no question selected.

It uses only the Python standard library (`tkinter`, `sqlite3`, `json`,
`subprocess`), so there's nothing to `pip install`.

## Quick start

Download the project, go into its folder, and start the app:

```bash
git clone https://github.com/Atrofos/sql-helper.git
cd sql-helper
./run.sh
```

If it says Python or Tk is missing, see [Requirements](#requirements). For a
double-click app on a Mac, see [Running](#running).

## Requirements

- macOS (it should also run on Windows/Linux, but it's only been tested on macOS)
- Python 3.10 or newer, with Tk support

Check that Tk is available:

```bash
python3 -c "import tkinter; print(tkinter.TkVersion)"
```

If that fails, install Python from [python.org](https://www.python.org/downloads/)
(its installer includes Tk), or with Homebrew run `brew install python-tk`.

## Running

**Easiest (Terminal, works from wherever you cloned the project):**

```bash
./run.sh
```

`run.sh` finds a suitable Python on its own, so you don't need to activate
anything first. It looks for Python 3.10 or newer with Tk 8.6 or newer, and
checks your `PATH`, your login shell, Homebrew, python.org and Anaconda/Miniconda
installs. It skips macOS's built-in `/usr/bin/python3` if that copy is too old
(it often ships an outdated Tk 8.5). To force a specific Python:
`SQL_HELPER_PYTHON=/path/to/python3 ./run.sh`.

**Double-click on a Mac:** build the launcher app once after cloning:

```bash
./make_mac_app.sh
```

This creates **`SQL Helper.app`** in the project folder. Double-click it to
start, or drag it onto the Dock to pin it. Keep the app inside the project
folder, because it runs `run.sh` from next to itself. The first time, macOS may
ask whether SQL Helper can access the folder the project is in (for example
Documents). Click **Allow**.

When started from the app there's no Terminal window, so any startup errors go
to `user_data/launch.log`.

The app uses its own icon (`sql_helper/assets/`) in the Dock and in Finder.
`run.sh` starts Python through a link called `.launcher/SQL Helper`, so the
macOS menu bar shows "SQL Helper". The Dock's hover label still shows the
Python version (for example "python3.14"), because macOS takes that name from
the real Python program.

If you rebuild `SQL Helper.app`, macOS treats it as a new app and may ask for
folder access again.

**Manually**, from the project folder:

```bash
python3 -m sql_helper
```

## Using it

1. Click a question in the sidebar on the left, or step through with **‹ Prev / Next ›**
   (they follow the sidebar's order: Easy, then Medium, then Hard).
2. Type SQL in the editor. With **Live preview** on, **Your Result** updates as you type.
3. Press **Run** (`Cmd+Enter`). If your result is right, the question is marked
   done (✓ in the sidebar) and **Next ›** lights up. Press **Check Answer** (`Cmd+Shift+Enter`)
   when you want feedback on a wrong answer.
4. Stuck? On the question card use **Hint**, then **Show Expected**, then **Solution**.
   **Lesson** opens the illustrated lesson for the topic.

| Shortcut | Action |
|---|---|
| `Cmd+Enter` (⌘↵) | Run query |
| `Cmd+Shift+Enter` (⌘⇧↵) | Check answer |
| `Cmd+[` / `Cmd+]` | Previous / next question (works with the sidebar hidden) |
| `Cmd+N` | New question |
| `Cmd+G` | Generate questions (for the current mode) |
| `Cmd+Z` | Undo in the editor |

### How answers are graded

- **Values** are compared, not column names, so `COUNT(*) AS total` and
  `COUNT(*)` both pass. You'll get a tip if your names differ.
- **Row order is ignored** unless the question says *"row order matters"*
  (questions that ask for sorting).
- **Duplicates count:** returning a row twice when it's expected once is wrong.
- **Decimals** are compared to 2 places, so `98333.3333` matches `98333.33`.
- **Feedback doesn't spoil a hidden answer.** While the expected result is
  hidden, feedback only gives counts ("expected 2 columns", "missing 3 rows").
  It quotes the expected rows and column names only once you've revealed them.
  Extra rows that you returned are always shown, since they're your own output.

### Showing the expected result

Each question starts with its expected output hidden. Press **Show Expected
Result**, either on the question card or at the top of the **Expected Result**
tab, to see it. Press it again to hide it. It hides again whenever you move to
another question.

### Resetting progress

Press **Reset…** in the toolbar, or use **Questions → Reset Progress…**:

- **Reset This Question** clears that question's attempts, its ✓ in the sidebar and
  the answer you typed.
- **Reset All Progress…** does the same for every question. It asks you to
  confirm first.

Your questions are never deleted by a reset. The history file is copied to
`user_data/history_backups/` before every reset, so you can always get it back.

### Generating questions

Press **Generate…** (or `Cmd+G`). It generates questions for the mode you're
in:

1. Pick **Easy**, **Medium**, **Hard** or **Mixed**.
2. Pick how many questions, from 1 to 20.
3. Press **Randomise** to get a new set. Click a row to read the full question.
4. Press **Save N Questions**. They appear in the sidebar marked `· generated`.

SQL questions are built from templates using values that really exist in the
practice data (real salaries, categories, statuses and names). Python
questions pick random numbers, words and letters, and mix both question
styles. Every solution is run before it's offered and kept only if it works.
Duplicates of questions you already have are skipped. Roughly, the SQL levels
cover:

| Level | Topics |
|---|---|
| Easy | choosing columns, `WHERE` with numbers and text, `IS NULL`, `ORDER BY` + `LIMIT`, `COUNT`, `DISTINCT`, `LIKE` |
| Medium | `GROUP BY` with `COUNT`/`AVG`/`MIN`/`MAX`/`SUM`, `HAVING`, `JOIN`, `LEFT JOIN` with zero counts, `IN`, `BETWEEN`, `CASE` |
| Hard | subqueries against the average, top row per group, three-table `JOIN` + `HAVING`, `NOT IN`, self joins, Nth-highest value, revenue by category |

Python levels cover: Easy, small functions (multiply, add a suffix, slicing,
comparisons, list indexing) and predicting `//`, `%` and slicing; Medium,
loops with counters, comprehensions, `range`, string methods, FizzBuzz
variants, dictionary lookups and list methods; Hard, running totals, longest
word, inverting a dict, splitting into chunks, digit sums with `while`, and
`split`/`join`.

The number of different questions per level is limited, because the data set is
small. If you ask for more than are left, the dialog says how many it found.
Remove all generated questions at once with **Questions → Delete All Generated
Questions…**.

### Creating your own questions

Use **+ New Question** or **Questions → New Question…**. Fill in a title, the
question text and a solution query. **Test Solution** runs the solution so you
can check its output. The question can only be saved once the solution runs.

**Questions → New Question from Current Query…** starts the dialog with
whatever is in the editor. Built-in questions are read-only, so this is how you
make a variation of one.

## Python mode

Switch to **Python** at the top left. Each mode keeps its own questions and
`Solved X / Y` count.

### Two question styles

- **Write a function**, e.g. *"Write `reverse_string(s)`..."*. The editor
  starts with the function's outline. Your function is called with several
  hidden test inputs and compared with the reference answer.
- **Predict the output**: the question shows a short program and you type
  exactly what it prints.

### While you type

The **Test Results** tab shows what your function returns for each test
input, and **Output** shows anything you `print` and any errors (with a
plain-English hint). Pass/fail isn't shown live, so it doesn't give the answer
away. Press **Run** to complete the question once it's right, or **Check
Answer** to see which tests pass (✓ / ✗).

The editor indents for you: pressing Return after a line ending in `:` indents
the next line, and Tab inserts 4 spaces.

### Visualise: step through your code

The **Visualise** tab runs your code and records every step:

- the line about to run is highlighted, with a sentence explaining what's
  happening ("Calling `double(n=4)`", "`double` returns 8");
- every variable is drawn, with lists and strings as numbered boxes and
  dictionaries as key → value pairs; values that just changed are
  highlighted;
- **< Step / Step >** or the slider move through the run, and "Printed so far"
  shows the output up to that point.

For function questions, pick which test call to trace. For *predict the
output* questions, Visualise unlocks once you've answered correctly or pressed
**Show Expected Result**, since stepping through would show the answer.

### How Python answers are graded

- Return values are compared, so `return` the answer rather than `print` it.
  The feedback points this out if your function returns `None`.
- Sets and dictionaries are compared ignoring order, and floats are compared
  to 9 decimal places.
- *Predict the output* answers ignore trailing spaces and blank lines at the
  end.

### Is running Python safe?

SQL mode can lock the practice data so nothing changes. Python can't be fully
locked down without installing extra tools, so here's exactly what the app
does:

- Your code runs in a **separate Python process**, so it can't crash or freeze
  the app.
- It's **stopped after 3 seconds** (1.5 seconds for the live preview), so
  infinite loops are harmless.
- It runs in isolated mode (`python -I`) inside a **new, empty temporary
  folder**, with its CPU time capped and its printed output size-limited.

What it doesn't do is stop code that *deliberately* reads or deletes files
elsewhere on your computer. That's the same as running code in any Python
editor. Only run code you've written or understand.

### Writing your own Python questions

**+ New** in Python mode opens the Python question dialog. Choose the style,
then:

- **Write a function:** give the function name, a reference solution, and
  test inputs, one call per line, written as you'd put them inside the
  brackets (e.g. `'hello', 3` or `[1, 2, 3]`). The expected answers come from
  running your solution. The editor starter is made from your function's
  signature.
- **Predict the output:** give the code. Its printed output is the answer.

**Test Solution** runs it. A question only saves once it runs cleanly.

## Progress report

Press **Report…** in the toolbar (or **Questions → Progress Report…**):

1. Choose the set: **Questions I made or generated** (the default when you
   have some) or **All questions** in the current mode.
2. Tick **Include hints and correct answers** only if you've finished trying
   them. Otherwise the report doesn't give the answers away.
3. Press **Generate Report**. It opens in your web browser and is saved in
   `user_data/reports/`.

The report shows:

- **Totals:** solved, not solved yet, not tried, attempts, and how often you
  solved a question on the first try.
- **By topic:** solved count, wrong attempts, and the lesson to review,
  weakest topics first.
- **Where you went wrong:** for every question with a wrong attempt, your
  last wrong answer and what was wrong with it, e.g. "expected 2 columns, you
  returned 1", a syntax error, "your function returned None every time. Did
  you forget `return`?", or the first line of output that differs. The app
  re-checks the saved answer to work this out.
- **Everything else:** questions you solved without a mistake, or haven't
  tried.

The page follows your light or dark mode, and prints cleanly too.

## Lessons

The **Lesson** tab (and the **Lesson** button on the question card) shows the
lesson for the current question's topic. You can also browse every lesson in
the mode from its drop-down. Each lesson has a short explanation, an example,
and a diagram:

| Mode | Lessons |
|---|---|
| SQL | SELECT, WHERE, ORDER BY, LIMIT/OFFSET, DISTINCT, NULL, LIKE, IN/BETWEEN, aggregates, GROUP BY, HAVING, INNER JOIN, LEFT JOIN, self JOIN, subqueries, correlated subqueries, CASE |
| Python | variables, strings and indexes, slicing, string methods, lists, for loops, while loops, range, if/elif/else, functions, dictionaries, sets, comprehensions, sorting, try/except |

Diagrams follow your Mac's light or dark mode.

## The practice data

Five small tables are rebuilt in memory every time the app starts:

| Table | Columns |
|---|---|
| `departments` | dept_id, name, location |
| `employees` | emp_id, first_name, last_name, email, dept_id, manager_id, salary, hire_date |
| `customers` | customer_id, name, city, country, signup_date |
| `products` | product_id, name, category, price |
| `orders` | order_id, customer_id, product_id, quantity, order_date, status |

The data includes common interview edge cases on purpose: `NULL` emails and
cities, an employee with no department, a department with no employees, and
customers with no orders. Dates are stored as `'YYYY-MM-DD'` text, which is how
SQLite usually stores dates.

**The data can't be changed.** Only read queries (`SELECT` / `WITH`) are
allowed. `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `DROP`, `ATTACH` and `PRAGMA`
are rejected with a friendly message. Queries that run longer than 2 seconds
are stopped, and grids show at most 500 rows.

### A note on the SQL dialect

The app runs **SQLite**. Most entry-level SQL is the same everywhere, but some
things differ from MySQL, PostgreSQL or SQL Server. For example, SQLite uses
`LIMIT` where SQL Server uses `TOP`, and date functions differ between
databases. If your interview uses a specific database, check that database's
documentation for those details.

## Where your data is stored

```
user_data/
├── questions/              one JSON file per question you created
│   └── custom-<slug>-<id>.json
├── history.jsonl           one line per checked attempt
├── history_backups/        automatic copies made before each reset
├── reports/                progress reports made with Report… (HTML)
└── launch.log              startup output when launched from SQL Helper.app
```

**Questions → Open Data Folder** opens this folder in Finder. To back up or
share your questions, copy the `.json` files. Files that can't be read are
skipped, and the app tells you which ones.

Set `SQL_HELPER_DATA_DIR=/some/path` to store data somewhere else.

A question file looks like this:

```json
{
  "id": "custom-pricey-products-0c06df",
  "title": "Pricey products",
  "prompt": "Show the name of every product that costs more than 500.",
  "solution": "SELECT name FROM products WHERE price > 500;",
  "difficulty": "Easy",
  "topic": "WHERE",
  "hint": "",
  "order_matters": false,
  "generated": false
}
```

A Python question file has `"mode": "python"` plus a few extra fields:

```json
{
  "id": "custom-triple-it-1a2b3c",
  "mode": "python",
  "kind": "function",
  "title": "Triple it",
  "prompt": "Write triple(n) that returns n multiplied by 3.",
  "function_name": "triple",
  "starter": "def triple(n):\n    pass\n",
  "solution": "def triple(n):\n    return n * 3\n",
  "tests": [[2], [-1], [0]],
  "difficulty": "Easy",
  "topic": "Functions",
  "hint": ""
}
```

For *predict the output* questions, `kind` is `"output"` and `solution` holds
the code whose printed output is the answer.

## Project layout

```
SQL Helper/
├── CLAUDE.md                    guidance for AI-assisted changes
├── LICENSE                      all rights reserved (not open source)
├── README.md                    this file
├── run.sh                       starts the app (finds a suitable Python)
├── make_mac_app.sh              builds SQL Helper.app (double-click launcher)
├── sql_helper/
│   ├── __main__.py              entry point (python3 -m sql_helper)
│   ├── app.py                   Tkinter UI (the only module that imports tkinter)
│   ├── database.py              practice schema, seed data, safe read-only execution
│   ├── generator.py             random SQL question templates + validation
│   ├── lessons.py               lesson cards (text, examples, diagram data) for both modes
│   ├── lesson_view.py           draws lesson diagrams and visualiser values (Tk canvas)
│   ├── python_runner.py         runs Python in a separate, time-limited process (+ tracing)
│   ├── python_grader.py         grades Python answers, plain-English error hints
│   ├── python_generator.py      random Python question templates + validation
│   ├── python_view.py           Python mode tabs, Visualise tab, Python question dialog
│   ├── report.py                progress report: re-checks wrong answers, writes HTML
│   ├── grader.py                compares results and writes feedback
│   ├── questions.py             Question model, custom-question files, history
│   └── data/                    built-in questions (builtin_questions.json = SQL,
│                                builtin_python_questions.json = Python)
├── sql_helper/assets/            app icon (icon.png for the window/Dock, icon.icns for the .app)
├── tools/make_icon.py           redraws the icon (developer-only, needs Pillow)
├── tests/                       unit tests for everything except the UI
├── SQL Helper.app               built by make_mac_app.sh (not committed)
└── user_data/                   created on first use (your questions, history, launch.log)
```

## Running the tests

```bash
python3 -m unittest discover -s tests
```

The tests cover the database safety rules, both graders (including the hidden
expected-result mode), the Python runner (timeouts, errors, tracing),
custom-question storage, history and resets, both generators, and the lessons.
They also run every built-in solution and every generator template, and check
that every topic maps to a lesson.

## License

Copyright (c) 2026 Harkey. All rights reserved. This repository is public so
the code can be viewed, but it is **not open source**: you may not use, copy,
modify or distribute it without permission. See [LICENSE](LICENSE).
