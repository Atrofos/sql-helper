# CLAUDE.md: SQL Helper (SQL + Python practice)

Read this before changing anything in this project. `README.md` covers features
and usage. This file covers **why** the project is built the way it is and the
rules for extending it.

## What this project is for

A lightweight desktop app that helps people prepare for **entry-level SQL and
Python interviews**. The owner's original requirements:

1. **Visual and interactive.** Users write SQL on one side and see the result on
   the other side *while they build the statement* (live preview).
2. **Tests basic SQL knowledge** with questions that are checked automatically.
3. **Users can create their own questions.** Created questions and past
   attempts are **saved in a local folder inside the project** (`user_data/`).
4. **Lightweight and runs on a Mac.**
5. **Documented.** Keep `README.md` and this file accurate.

Added later (v1.2), also the owner's requirements:

6. **Python mode** in the same app, switched with **SQL | Python** at the top.
   It tests basic Python skills with **both** question styles: *write a
   function* (graded against hidden test inputs) and *predict the output*.
7. **Full parity** with SQL mode: built-in questions, generator, custom
   questions, history, reset (scoped to the current mode), hidden expected
   result, Run-completes / Next highlight.
8. **Live preview in Python shows the learner's own outputs, not pass/fail.**
   ✓/✗ only appear after Check Answer, and Run completes the question when
   everything passes.
9. **Visual learning:** a step-through **Visualise** tab for Python, and an
   illustrated **lesson card** for every topic in **both** modes.

The audience is beginners, so every change should make the app clearer, not
more powerful. If a feature mainly helps advanced users, ask the owner first.

## Hard constraints

- **Standard library only at runtime:** `tkinter`, `sqlite3`, `json`, `pathlib`,
  `subprocess`, `threading` and so on. The one exception is the developer-only `tools/make_icon.py`,
  which needs Pillow. Its outputs are committed, so users never run it.
  Don't add third-party dependencies (pip packages, web frameworks, Electron,
  etc.) without the owner's explicit approval. "Lightweight on a Mac" means it
  starts with `python3 -m sql_helper` and nothing else.
- **Python 3.10+.** The code uses `X | None` type hints and other 3.10 syntax.
  It was developed on Python 3.14 with Tk 8.6 on macOS.
- **Python runs out of process.** `python_runner` runs learner code with
  `sys.executable -I` in a fresh temp folder, with a wall-clock timeout, a CPU
  rlimit set by the child (not `preexec_fn`, which isn't thread-safe), and
  size-capped output. The result comes back as one marked JSON line on the
  real stdout, while learner prints are captured separately. This is **not**
  a security sandbox, and README says so honestly. Never claim it is one, and
  never run learner code in the app's own process.
- **The practice database is read-only and in-memory.** `PracticeDatabase` uses
  an SQLite authorizer that only allows read actions, plus a progress-handler
  timeout. Never weaken this. User SQL must never be able to change the seed
  data, touch the filesystem (`ATTACH`), or hang the UI.
- **User data lives only in `user_data/`** (or `$SQL_HELPER_DATA_DIR`). Don't
  write anywhere else. Don't commit `user_data/` contents as project files.
- **Built-in questions are read-only.** Users make variations through
  "New Question from Current Query".

## Architecture

| Module | Responsibility | May import tkinter? |
|---|---|---|
| `database.py` | Schema, seed data, `PracticeDatabase.run()` → `QueryResult` | No |
| `grader.py` | `grade(user, expected, order_matters, show_examples)` → `GradeResult` | No |
| `generator.py` | Random SQL question templates → validated `Question`s | No |
| `questions.py` | `Question` dataclass, `QuestionStore` (JSON files + history) | No |
| `python_runner.py` | Run Python in a subprocess; results, errors, trace steps | No |
| `python_grader.py` | Grade function / output answers; error hints | No |
| `python_generator.py` | Random Python question templates → validated `Question`s | No |
| `lessons.py` | Lesson cards as data (text, example, diagram spec) | No |
| `report.py` | Progress report: re-grade wrong answers, topic stats, HTML | No |
| `app.py` | Main window, SQL tabs, mode switch, shared dialogs | Yes |
| `python_view.py` | Python tabs, Visualise tab, Python question dialog, worker thread | Yes |
| `lesson_view.py` | Draws lesson diagrams and visualiser values on a canvas | Yes |

- **Questions are chosen from `QuestionSidebar`** (in app.py): a Treeview
  grouped by difficulty. `self.visible` is sorted in the same order, so Prev/Next
  match what the sidebar shows. Programmatic highlighting goes through
  `sidebar.select()`, which doesn't fire a "pick".
- **Pane widths are clamped** in `_clamp_sashes` (ttk.PanedWindow has no
  per-pane minimum): sidebar between `SIDEBAR_MIN` and `SIDEBAR_MAX`, editor and
  results at least `WORK_MIN`. It runs after drag steps and window resizes.
  Keep the window's `minsize` at least `SIDEBAR_MIN + 2 * WORK_MIN` plus padding.
- Icon-only buttons (like the sidebar toggle) must have a `Tooltip` naming
  the action, and the actions they trigger need a keyboard route too (⌘[ / ⌘]
  for Prev/Next).
- **Prev/Next must always be on screen**: in the sidebar, or in the bottom row
  (`bottom_nav`) while the sidebar is hidden. Change the Next highlight only via
  `_set_next()`, which updates both copies.
- **Keep the UI thin.** Logic that could be tested without a window belongs in
  the non-UI modules and gets a unit test. The three UI modules should only
  translate between widgets and those modules.
- **Python runs on a worker thread** (`python_view.Worker`) so the window never
  freezes. Results come back through a queue polled with `after()`. Only the
  newest result per channel ("run", "expected", "visualise") is applied.
  Never touch Tk widgets from the worker thread.
- **Errors are values.** `PracticeDatabase.run()` never raises for bad SQL. It
  returns `QueryResult(error=...)` with a beginner-friendly message (see
  `friendly_error`). Follow that pattern rather than letting exceptions reach
  the UI.
- **Live preview** is debounced (`LIVE_DELAY_MS`) and runs on the Tk main
  thread. That's fine because the data is tiny and queries time out after 2
  seconds. Only consider threads if that changes, and remember that Tk widgets
  must only be touched from the main thread.

## Data formats (treat as a public contract)

- Custom question: `user_data/questions/<id>.json` with the fields `id, title,
  prompt, solution, difficulty, topic, hint, order_matters, generated`
  (`generated` was added in v1.1 and defaults to false), plus the v1.2 fields
  `mode` ("sql" default / "python"), `kind` ("function" / "output", Python
  only), `function_name`, `starter`, `tests` (list of argument lists) and
  `lesson` (optional lesson id). Files without the new fields load as SQL
  questions. For "output" questions, `solution` is the code whose printed
  output is the answer. `source` is *not*
  stored. It's derived from where the question was loaded from.
- History: `user_data/history.jsonl`, one object per line:
  `timestamp, question_id, sql, correct`.
- Resets copy the history to `user_data/history_backups/history-<timestamp>.jsonl`
  before changing it. Keep this: a reset should never lose data for good.

Rules for changing these formats:

- **Add fields with defaults. Never rename or remove fields** without writing a
  migration. Users' existing files must keep loading.
  `Question.from_dict` ignores unknown keys, so newer files still load in older
  versions.
- **Writes are atomic** (temp file + `os.replace`) for question files.
  History is append-only.
- **Damaged files must not crash the app.** Skip them and report through
  `QuestionStore.warnings`.

## Adding or changing built-in questions

Built-in questions are in `sql_helper/data/builtin_questions.json`.

- Each one needs a unique `id`, a clear `prompt` that names the exact columns
  expected, a `hint`, and a `solution`.
- Set `order_matters: true` **only** when the prompt asks for a sort order, and
  make sure the sort has no ties. Otherwise the expected order is ambiguous.
- Run the tests. `BuiltinQuestionTests` runs every solution and fails if one
  errors or returns no rows.
- If you change the seed data in `database.py`, re-run the tests and re-read
  the prompts. Answers that the prompts or tests describe (for example "2
  customers have no orders") may change.

## Python question rules

- Built-in Python questions are in `sql_helper/data/builtin_python_questions.json`
  (JSON: use `true`/`false`/`null`, not Python's `True`/`False`/`None`).
- *Function* prompts must name the function and say to **return** (not print).
  The starter must not pass the tests (`PythonBuiltinTests` checks this).
- Test arguments must be JSON-friendly (numbers, strings, bools, lists,
  dicts). They're passed to the child process as JSON.
- Grading compares `canon(value)` (sets/dicts order-insensitive, floats to 9
  places). Tuples and lists are different types: prompts should say which to
  return.
- *Output* questions: the Visualise tab stays locked until solved or revealed,
  because stepping through would show the answer.

## Report rules

- History stores answers, not feedback, so `report.build_report` re-grades the
  **last wrong answer** per question with the same graders. Keep it using the
  graders (don't duplicate grading logic).
- **Hints and correct answers stay out unless `include_answers`** is ticked,
  because hints can give the answer away (same rule as the hidden expected
  result).
- HTML is standalone: inline CSS, no scripts, no external requests, light/dark
  via `prefers-color-scheme`. **Escape all learner text** with `html.escape`
  (`ReportTests.test_html_escapes_learner_text`).
- SQL reports run on the Tk thread (SQLite connections are tied to their
  thread). Python reports run on the worker, because they start subprocesses.
- Reports are saved in `user_data/reports/` via `QuestionStore.save_report`.

## Lesson rules

- Lessons live in `lessons.py` as data. Diagrams use one of the drawing types
  in `lesson_view.Painter.draw` (panels, sequence, kv, flow, venn, refs). Add
  a new drawing type there, not ad-hoc canvas code elsewhere.
- Every question topic must map to a lesson by keyword (`lesson_for`).
  `LessonTests.test_every_topic_maps_to_a_real_lesson` fails if a built-in or
  generator topic falls back to the default lesson. Add a keyword or a lesson.
- Lesson text must be accurate. Check any claim about SQLite or Python
  behaviour before writing it (e.g. SQLite's LIKE is case-insensitive for
  ASCII only).
- Diagram colours come from `lesson_view.palette()`, which follows light/dark
  mode. Don't hard-code colours in drawing code.

## Run vs Check Answer (owner's requirement)

Pressing **Run** with a correct result counts as solving the question: it's
recorded, the expected result is revealed, and **Next ›** (bottom of the
sidebar) is highlighted (the
blue default button with a ✓). Run never shows "wrong" feedback, so
half-finished queries aren't marked down. **Check Answer** always grades and
explains. A successful run clears a stale error message.

## Hidden expected result (owner's requirement)

The expected output must stay hidden until the user presses **Show Expected
Result**. It hides again on every question change, and is revealed
automatically only after a correct answer. Anything that would leak it while
it's hidden breaks this requirement: feedback that quotes expected rows or
column names, tooltips, previews. That's why `grade()` takes
`show_examples=False` while the result is hidden. Hints and Reveal Solution are
explicit user choices and are fine.

## Question generator rules

- Templates live in `generator.py` (`TEMPLATES`, grouped by Easy/Medium/Hard).
  A template takes `(rng, data)` and returns a `Draft`, or `None` to decline
  (for example when ties would make an ordered answer ambiguous).
- **Pick parameters from the real data** (`_Data.column(...)` etc.), never
  hard-coded values, so questions stay valid if the seed data changes.
- **Prompts must name the exact columns expected.** The grader compares values
  by position.
- Set `order_matters=True` only when the prompt asks for an order, and only when
  the ordering has no ties (see `easy_top_k`).
- `generate_questions` runs every solution and rejects errors, empty results
  and duplicates. `GeneratorTests` runs every template over many seeds, so add
  a template to `TEMPLATES` and the tests cover it automatically.

## Design principles

These are standard practices, applied to this project:

- **KISS / YAGNI.** Build the simplest thing that meets the requirement. Don't
  add configuration, plugin systems or abstractions for hypothetical future
  needs.
- **Separation of concerns and single responsibility.** One reason to change
  per module (see the architecture table).
- **Fail safely and explain.** Every error a user can trigger should produce a
  plain-English message that says what to do next, not a stack trace.
- **Don't lose user data.** Atomic writes, append-only history, a confirmation
  before deleting anything, and tolerant loading.
- **Least privilege.** User SQL gets only the database permissions it needs
  (read).
- **Accessibility.** Don't rely on color alone. Correct/incorrect feedback also
  has text, and solved questions show a ✓ in the sidebar. Every main action has a button,
  and the frequent ones also have keyboard shortcuts.
- **Respect the platform.** Use `Cmd` shortcuts on macOS (`MOD` in `app.py`),
  native ttk widgets, and system fonts. Avoid hard-coded background colors
  because they break macOS dark mode.
- **Small, readable code.** Use type hints and short docstrings that explain
  *why*. Use named constants instead of magic numbers.

## Honesty and accuracy rules (for Claude and other contributors)

- **Don't make things up.** If you aren't sure how an SQLite feature, Tk
  behavior or macOS detail works, check it: run a quick snippet, read the
  official docs, or ask. Say so when something is unverified.
- SQL taught here is **SQLite**. When a question or hint depends on dialect
  differences (date functions, `TOP` vs `LIMIT`, string concatenation,
  `RIGHT`/`FULL JOIN` support in older SQLite versions), say so in the hint or
  avoid it. Entry-level questions should use portable SQL wherever possible.
- **Verify before reporting done.** Run `python3 -m unittest discover -s tests`.
  For UI changes, also launch the app (`python3 -m sql_helper`) and check the
  affected flow, or state clearly that the UI wasn't checked.
- Keep `README.md` and this file up to date in the same change that alters
  behavior, file formats or project layout.

## Commands

```bash
./run.sh                                # run the app (finds a suitable Python)
./make_mac_app.sh                       # build the double-click SQL Helper.app
python3 -m sql_helper                   # run the app with the current python3
python3 -m unittest discover -s tests   # run tests
```

## macOS launcher notes (learned the hard way; keep these in mind)

- `run.sh` is the single place that picks a Python. The `.app` only calls it.
  Don't duplicate Python-discovery logic elsewhere.
- Apps opened from Finder don't inherit the shell's `PATH`. That's why
  `run.sh` asks the login shell (`zsh -lic`) and checks known install paths.
- macOS's `/usr/bin/python3` can be Python 3.9 with Tk 8.5. Require 3.10+ and
  Tk 8.6+.
- A `.app` whose executable is a plain shell script gets
  `Operation not permitted` when the project is in Documents, Desktop or
  Downloads, and macOS shows no prompt. The AppleScript applet built by
  `osacompile` does get the normal "allow access" prompt, so keep using
  `make_mac_app.sh`.
- The applet quits right after starting `run.sh`, so the Tk window has to bring
  itself to the front (`bring_to_front` in `app.py`).
- `SQL Helper.app` is built per machine and is git-ignored. `make_mac_app.sh`
  copies `sql_helper/assets/icon.icns` into it and re-signs it ad hoc.
  Re-signing changes the app's identity, so macOS asks for folder access again.
- Dock/menu name: `run.sh` runs Python through a symlink
  `.launcher/SQL Helper` (git-ignored). This changes the **menu bar** name, but
  the **Dock hover label still says "python3.x"**. It's verified on macOS
  that the symlink alone doesn't fix the Dock label.
- The Dock **icon** comes from `set_app_icon()` in `app.py`
  (`iconphoto(True, ...)` with `assets/icon.png`). This is verified working.
- When something needs checking on the owner's screen (the Dock, a permission
  prompt), ask them to look or send a screenshot. Hidden macOS prompts can make
  shell commands hang.

## Verifying UI changes

`screencapture` needs the Screen Recording permission for Claude. macOS can
revoke it after an OS update (a black screenshot or "could not create image"
means it's off). If so, drive the UI with a script (no screenshots) and ask the
owner to re-enable the permission or send a screenshot. Don't work around it.

## Ideas the owner may want later (not built yet; confirm before starting)

- Import/export question packs (a folder of question JSON files).
- Per-topic progress stats from `history.jsonl`.
- Multiple practice datasets (an extra schema selector).
