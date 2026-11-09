# SQL Helper

A small desktop app for practicing entry-level SQL interview questions.
Write a query on the left, and the results table on the right updates as you type.

- **Live preview:** results refresh about a third of a second after you stop typing.
  Half-written SQL doesn't clear the grid. The last valid result stays on screen
  and the error appears in the status bar.
- **23 built-in questions** covering `SELECT`, `WHERE`, `ORDER BY`, `LIMIT`,
  `DISTINCT`, `LIKE`, `IN`, `BETWEEN`, `NULL`, aggregates, `GROUP BY`,
  `HAVING`, `INNER`/`LEFT`/self `JOIN`, subqueries and `CASE`.
- **Run** a correct answer and the question is marked done. Use **Check
  Answer** to grade any attempt and get an explanation of what's wrong: column
  count, missing or extra rows, or wrong order.
- After you complete a question, **Next >** turns blue with a ✓ so you know
  where to go.
- **Expected Result** stays hidden until you press **Show Expected Result**, so
  you can try first. It's revealed automatically once you get the answer right.
- **Question generator:** choose a difficulty (Easy, Medium, Hard or Mixed) and
  how many questions, press **Randomise**, then save the set.
- **Reset progress** for one question or for everything. A backup is kept.
- **Tables** tab lets you browse every practice table and its columns.
- **Your own questions:** create, edit and delete them. They're saved as JSON
  files in `user_data/questions/`.
- **Attempt history:** every checked attempt goes to `user_data/history.jsonl`.
  Solved questions show `[done]` in the picker.
- **Free practice mode:** run any query with no question selected.

It uses only the Python standard library (`tkinter`, `sqlite3`, `json`), so
there's nothing to `pip install`.

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

1. Pick a question from the drop-down at the top, or step through with **< Prev / Next >**.
2. Type SQL in the editor. With **Live preview** on, **Your Result** updates as you type.
3. Press **Run** (`Cmd+Enter`). If your result is right, the question is marked
   `[done]` and **Next >** lights up. Press **Check Answer** (`Cmd+Shift+Enter`)
   when you want feedback on a wrong answer.
4. Stuck? Use **Show Hint**, then **Show Expected Result**, then **Reveal Solution**.

| Shortcut | Action |
|---|---|
| `Cmd+Enter` (⌘↵) | Run query |
| `Cmd+Shift+Enter` (⌘⇧↵) | Check answer |
| `Cmd+N` | New question |
| `Cmd+G` | Generate questions |
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

- **Reset This Question** clears that question's attempts, its `[done]` mark and
  the answer you typed.
- **Reset All Progress…** does the same for every question. It asks you to
  confirm first.

Your questions are never deleted by a reset. The history file is copied to
`user_data/history_backups/` before every reset, so you can always get it back.

### Generating questions

Press **Generate…** (or `Cmd+G`):

1. Pick **Easy**, **Medium**, **Hard** or **Mixed**.
2. Pick how many questions, from 1 to 20.
3. Press **Randomise** to get a new set. Click a row to read the full question.
4. Press **Save N Questions**. They appear in the list marked `(generated)`.

Generated questions are built from templates using values that really exist in
the practice data (real salaries, categories, statuses and names). Every
solution is run before it's offered, and kept only if it works and returns
rows. Duplicates of questions you already have are skipped. Roughly, the levels
cover:

| Level | Topics |
|---|---|
| Easy | choosing columns, `WHERE` with numbers and text, `IS NULL`, `ORDER BY` + `LIMIT`, `COUNT`, `DISTINCT`, `LIKE` |
| Medium | `GROUP BY` with `COUNT`/`AVG`/`MIN`/`MAX`/`SUM`, `HAVING`, `JOIN`, `LEFT JOIN` with zero counts, `IN`, `BETWEEN`, `CASE` |
| Hard | subqueries against the average, top row per group, three-table `JOIN` + `HAVING`, `NOT IN`, self joins, Nth-highest value, revenue by category |

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
│   ├── generator.py             random question templates + validation
│   ├── grader.py                compares results and writes feedback
│   ├── questions.py             Question model, custom-question files, history
│   └── data/builtin_questions.json
├── sql_helper/assets/            app icon (icon.png for the window/Dock, icon.icns for the .app)
├── tools/make_icon.py           redraws the icon (developer-only, needs Pillow)
├── tests/test_core.py           unit tests for everything except the UI
├── SQL Helper.app               built by make_mac_app.sh (not committed)
└── user_data/                   created on first use (your questions, history, launch.log)
```

## Running the tests

```bash
python3 -m unittest discover -s tests
```

The tests cover the database safety rules, the grader (including the hidden
expected-result mode), custom-question storage, history and resets, and the
generator. They also run every built-in solution and every generator template
against the practice data.

## License

Copyright (c) 2026 Harkey. All rights reserved. This repository is public so
the code can be viewed, but it is **not open source**: you may not use, copy,
modify or distribute it without permission. See [LICENSE](LICENSE).
