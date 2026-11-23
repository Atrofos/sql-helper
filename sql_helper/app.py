"""Tkinter user interface for SQL Helper (SQL and Python practice).

Layout: the left side holds the question and the code editor; the right side
shows results. A SQL | Python switch at the top changes mode. SQL mode's
right side is built here (your result, expected result, tables, lesson);
Python mode's right side lives in python_view.py. All SQL, Python-running and
file logic lives in the non-UI modules; this file only wires widgets to them.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from typing import Callable

from .database import PracticeDatabase, QueryResult
from .generator import GENERATOR_DIFFICULTIES, MAX_COUNT, generate_questions
from .grader import grade
from .lesson_view import LessonView
from .lessons import lesson_for, lessons_for_mode
from .python_generator import generate_python_questions
from .python_view import PythonPanel, PythonQuestionDialog
from .report import build_report, to_html
from .questions import (DIFFICULTIES, KIND_FUNCTION, KIND_OUTPUT, MODE_PYTHON, MODE_SQL,
                        Question, QuestionStore)

IS_MAC = sys.platform == "darwin"
MOD = "Command" if IS_MAC else "Control"      # Tk event modifier name
MOD_LABEL = "Cmd" if IS_MAC else "Ctrl"       # what we show to the user
RUN_KEYS = "\u2318\u21b5" if IS_MAC else "Ctrl+Enter"            # ⌘↵
CHECK_KEYS = "\u2318\u21e7\u21b5" if IS_MAC else "Ctrl+Shift+Enter"  # ⌘⇧↵
LIVE_DELAY_MS = 350                           # pause after typing before live preview runs
MAX_DISPLAY_ROWS = 500                        # rows drawn in a grid (Treeview gets slow beyond this)
FREE_PRACTICE = "Free practice (no question)"
PY_INDENT = "    "
SIDEBAR_WIDTH = 280
SIDEBAR_MIN, SIDEBAR_MAX = 190, 440   # dragging the divider can't go past these
WORK_MIN = 380                        # nor squeeze the editor or results below this
PREV_KEYS = "\u2318[" if IS_MAC else "Ctrl+["
NEXT_KEYS = "\u2318]" if IS_MAC else "Ctrl+]"
ICON_GREY = "#8c959f"                 # mid grey reads well in light and dark mode
FOCUS_BLUE = "#0a84ff"                # macOS accent blue, used for the editor's focus ring
LEVEL_COLOURS = {"Easy": "#2da44e", "Medium": "#d4a72c", "Hard": "#cf222e"}
PANE_WIDTH, PANE_HEIGHT = 600, 560            # starting size of each half; both stretch equally

GOOD = "#1a7f37"
BAD = "#cf222e"

SQL_KEYWORDS = (
    "SELECT FROM WHERE AND OR NOT IN IS NULL LIKE BETWEEN AS ON JOIN INNER LEFT RIGHT "
    "FULL OUTER CROSS GROUP BY HAVING ORDER ASC DESC LIMIT OFFSET DISTINCT UNION ALL "
    "INTERSECT EXCEPT CASE WHEN THEN ELSE END WITH RECURSIVE EXISTS COUNT SUM AVG MIN "
    "MAX ROUND COALESCE IFNULL CAST LOWER UPPER LENGTH SUBSTR TRIM"
).split()
PY_KEYWORDS = (
    "def return if elif else for while in not and or is None True False import from as class "
    "try except finally raise with lambda pass break continue global yield print len range "
    "list dict set tuple str int float sorted sum min max enumerate zip"
).split()
# (keyword, string, comment) patterns per editor language.
SYNTAX = {
    MODE_SQL: (re.compile(r"\b(?:" + "|".join(SQL_KEYWORDS) + r")\b", re.IGNORECASE),
               re.compile(r"'(?:[^']|'')*'?"), re.compile(r"--[^\n]*")),
    MODE_PYTHON: (re.compile(r"\b(?:" + "|".join(PY_KEYWORDS) + r")\b"),
                  re.compile(r"(?:\"\"\"[\s\S]*?(?:\"\"\"|$)|'[^'\n]*'?|\"[^\"\n]*\"?)"),
                  re.compile(r"#[^\n]*")),
}


def mono_font() -> tuple[str, int]:
    return ("Menlo", 13) if IS_MAC else ("Courier", 11)


def format_cell(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.2f}"
    return str(value)


# ---------------------------------------------------------------------------
# Reusable widgets
# ---------------------------------------------------------------------------
class ResultGrid(ttk.Frame):
    """A scrollable table that displays a QueryResult."""

    def __init__(self, master, placeholder: str) -> None:
        super().__init__(master, padding=(0, 4))
        self.caption = ttk.Label(self, text=placeholder)
        self.caption.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.tree = ttk.Treeview(self, show="headings", selectmode="browse")
        ys = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.tree.grid(row=1, column=0, sticky="nsew")
        ys.grid(row=1, column=1, sticky="ns")
        xs.grid(row=2, column=0, sticky="ew")
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        self._measure = tkfont.nametofont("TkDefaultFont").measure
        self._last_caption = placeholder

    def clear(self, message: str) -> None:
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = ()
        self.set_caption(message)

    def set_caption(self, text: str) -> None:
        self._last_caption = text
        self.caption.configure(text=text)

    def mark_stale(self, reason: str) -> None:
        """Keep the last good result on screen but say it's out of date."""
        self.caption.configure(text=f"Showing last valid result. {reason}")

    def show(self, result: QueryResult, label: str = "") -> None:
        tree = self.tree
        tree.delete(*tree.get_children())
        ids = [f"c{i}" for i in range(len(result.columns))]  # names can repeat, ids can't
        tree["columns"] = ids
        shown = result.rows[:MAX_DISPLAY_ROWS]
        cells = [[format_cell(v) for v in row] for row in shown]
        for i, (cid, name) in enumerate(zip(ids, result.columns)):
            sample = [name] + [r[i] for r in cells[:50]]
            width = min(max(self._measure(s) for s in sample) + 24, 320)
            tree.heading(cid, text=name, anchor="w")
            tree.column(cid, width=width, minwidth=40, stretch=False, anchor="w")
        for row in cells:
            tree.insert("", "end", values=row)

        if not result.columns:
            text = "Statement ran but returned no columns."
        else:
            n = len(result.rows)
            text = f"{n}{'+' if result.truncated else ''} row{'s' if n != 1 else ''}"
            text += f" x {len(result.columns)} column{'s' if len(result.columns) != 1 else ''}"
            if len(result.rows) > MAX_DISPLAY_ROWS:
                text += f" (showing first {MAX_DISPLAY_ROWS})"
        self.set_caption(f"{label}{text}")


class SqlEditor(ttk.Frame):
    """Monospace text box with light keyword/string/comment highlighting."""

    def __init__(self, master, on_change: Callable[[], None]) -> None:
        super().__init__(master)
        self.text = tk.Text(self, wrap="word", undo=True, height=10, font=mono_font(),
                            padx=10, pady=8, borderwidth=0, relief="flat",
                            highlightthickness=1, highlightbackground=ICON_GREY,
                            highlightcolor=FOCUS_BLUE)
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        family, size = mono_font()
        # Tags configured later win, so strings/comments override keywords inside them.
        self.text.tag_configure("kw", foreground="#3b6fd6", font=(family, size, "bold"))
        self.text.tag_configure("str", foreground="#c0600a")
        self.text.tag_configure("cmt", foreground="#888888")
        self._on_change = on_change
        self.language: str | None = MODE_SQL     # None = plain text (no highlighting)
        self.text.bind("<<Modified>>", self._modified)
        self.text.bind("<Tab>", self._tab)
        self.text.bind("<Return>", self._newline)

    def set_language(self, language: str | None) -> None:
        self.language = language
        self.highlight()

    def _tab(self, _event=None):
        """Python wants spaces, not tab characters."""
        if self.language == MODE_PYTHON:
            self.text.insert("insert", PY_INDENT)
            return "break"
        return None

    def _newline(self, _event=None):
        """Keep the indentation of the previous line, and indent after a ':' (Python)."""
        if self.language != MODE_PYTHON:
            return None
        line = self.text.get("insert linestart", "insert")
        indent = line[: len(line) - len(line.lstrip(" "))]
        if line.rstrip().endswith(":"):
            indent += PY_INDENT
        self.text.insert("insert", "\n" + indent)
        self.text.see("insert")
        return "break"

    def _modified(self, _event=None) -> None:
        if self.text.edit_modified():
            self.text.edit_modified(False)
            self.highlight()
            self._on_change()

    def get(self) -> str:
        return self.text.get("1.0", "end-1c")

    def set(self, sql: str) -> None:
        self.text.delete("1.0", "end")
        self.text.insert("1.0", sql)
        self.text.edit_reset()

    def insert_at_cursor(self, text: str) -> None:
        self.text.insert("insert", text)
        self.text.focus_set()

    def highlight(self) -> None:
        content = self.get()
        for tag in ("kw", "str", "cmt"):
            self.text.tag_remove(tag, "1.0", "end")
        if self.language not in SYNTAX:
            return
        for tag, pattern in zip(("kw", "str", "cmt"), SYNTAX[self.language]):
            for m in pattern.finditer(content):
                self.text.tag_add(tag, f"1.0+{m.start()}c", f"1.0+{m.end()}c")


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------
class QuestionDialog(tk.Toplevel):
    """Create or edit a custom question. The solution must run before saving."""

    def __init__(self, app: "SqlHelperApp", question: Question | None = None,
                 starter_sql: str = "") -> None:
        super().__init__(app.root)
        self.app = app
        self.editing = question
        self.title("Edit Question" if question else "New Question")
        self.transient(app.root)
        self.minsize(560, 560)

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        self.title_var = tk.StringVar(value=question.title if question else "")
        self.topic_var = tk.StringVar(value=question.topic if question else "General")
        self.diff_var = tk.StringVar(value=question.difficulty if question else "Easy")
        self.hint_var = tk.StringVar(value=question.hint if question else "")
        self.order_var = tk.BooleanVar(value=question.order_matters if question else False)

        row = 0
        for label, widget in (
            ("Title", ttk.Entry(body, textvariable=self.title_var)),
            ("Topic", ttk.Entry(body, textvariable=self.topic_var)),
            ("Difficulty", ttk.Combobox(body, textvariable=self.diff_var,
                                        values=DIFFICULTIES, state="readonly", width=10)),
        ):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=3)
            widget.grid(row=row, column=1, sticky="ew" if label != "Difficulty" else "w", pady=3)
            row += 1

        ttk.Label(body, text="Question").grid(row=row, column=0, sticky="nw", pady=3)
        self.prompt_text = tk.Text(body, height=4, wrap="word", padx=6, pady=6,
                                   font=tkfont.nametofont("TkDefaultFont"))
        self.prompt_text.grid(row=row, column=1, sticky="nsew", pady=3)
        if question:
            self.prompt_text.insert("1.0", question.prompt)
        row += 1

        ttk.Label(body, text="Solution SQL").grid(row=row, column=0, sticky="nw", pady=3)
        self.solution_text = tk.Text(body, height=7, wrap="word", font=mono_font(), padx=6, pady=6)
        self.solution_text.grid(row=row, column=1, sticky="nsew", pady=3)
        self.solution_text.insert("1.0", question.solution if question else starter_sql)
        body.rowconfigure(row, weight=1)
        row += 1

        ttk.Label(body, text="Hint (optional)").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(body, textvariable=self.hint_var).grid(row=row, column=1, sticky="ew", pady=3)
        row += 1

        ttk.Checkbutton(body, text="Row order matters (the solution uses ORDER BY on purpose)",
                        variable=self.order_var).grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        self.status = ttk.Label(body, text="Tip: press Test Solution to preview its output.",
                                wraplength=420)
        self.status.grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 4))
        row += 1

        buttons = ttk.Frame(body)
        buttons.grid(row=row, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(buttons, text="Test Solution", command=self._test).pack(side="left", padx=4)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="left", padx=4)
        ttk.Button(buttons, text="Save", command=self._save).pack(side="left", padx=4)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.after(50, self._grab)

    def _grab(self) -> None:
        try:
            self.grab_set()
        except tk.TclError:
            pass  # window not viewable yet on some platforms; it still works unmodal

    def _solution(self) -> str:
        return self.solution_text.get("1.0", "end-1c").strip()

    def _test(self) -> QueryResult:
        result = self.app.db.run(self._solution())
        if result.ok and result.columns:
            self.status.configure(foreground=GOOD, text=(
                f"Solution works: {len(result.rows)} row(s), columns: {', '.join(result.columns)}. "
                "The Expected Result tab will show this output."))
        elif result.ok:
            self.status.configure(foreground=BAD, text="The solution must return columns (use SELECT).")
        else:
            self.status.configure(foreground=BAD, text=f"Solution error: {result.error}")
        return result

    def _save(self) -> None:
        title = self.title_var.get().strip()
        prompt = self.prompt_text.get("1.0", "end-1c").strip()
        if not title or not prompt or not self._solution():
            self.status.configure(foreground=BAD, text="Title, question and solution are required.")
            return
        result = self._test()
        if not (result.ok and result.columns):
            return
        question = Question(
            id=self.editing.id if self.editing else self.app.store.new_id(title),
            title=title,
            prompt=prompt,
            solution=self._solution(),
            difficulty=self.diff_var.get(),
            topic=self.topic_var.get().strip() or "General",
            hint=self.hint_var.get().strip(),
            order_matters=self.order_var.get(),
        )
        try:
            self.app.store.save_custom(question)
        except OSError as exc:
            messagebox.showerror("Could not save", str(exc), parent=self)
            return
        self.destroy()
        self.app.reload_questions(select_id=question.id)


class HistoryWindow(tk.Toplevel):
    """Lists past attempts; double-click one to load its SQL into the editor."""

    def __init__(self, app: "SqlHelperApp") -> None:
        super().__init__(app.root)
        self.app = app
        self.title("Attempt History")
        self.geometry("820x420")
        self.transient(app.root)

        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Double-click an attempt to load it into the editor.").pack(anchor="w")

        cols = ("when", "question", "result", "sql")  # "sql" holds the code for both modes
        self.tree = ttk.Treeview(frame, columns=cols, show="headings")
        for cid, text, width in (("when", "When", 150), ("question", "Question", 220),
                                 ("result", "Result", 80), ("sql", "Your answer", 360)):
            self.tree.heading(cid, text=text, anchor="w")
            self.tree.column(cid, width=width, anchor="w", stretch=cid == "sql")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True, pady=(8, 0))
        scroll.pack(side="right", fill="y", pady=(8, 0))

        titles = {q.id: f"[{'Py' if q.mode == MODE_PYTHON else 'SQL'}] {q.title}" for q in app.questions}
        self.entries = list(reversed(app.store.load_history()))
        for i, e in enumerate(self.entries):
            sql = " ".join(str(e.get("sql", "")).split())
            self.tree.insert("", "end", iid=str(i), values=(
                str(e.get("timestamp", "")).replace("T", " "),
                titles.get(e.get("question_id"), f"(deleted) {e.get('question_id')}"),
                "Correct" if e.get("correct") else "Wrong",
                sql[:200],
            ))
        self.tree.bind("<Double-1>", self._load)

    def _load(self, _event=None) -> None:
        selected = self.tree.selection()
        if selected:
            entry = self.entries[int(selected[0])]
            self.app.load_attempt(entry.get("question_id"), entry.get("sql", ""))


class ResetDialog(tk.Toplevel):
    """Reset progress for the current question or for everything."""

    def __init__(self, app: "SqlHelperApp") -> None:
        super().__init__(app.root)
        self.app = app
        self.title("Reset Progress")
        self.transient(app.root)
        self.resizable(False, False)

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, wraplength=420, justify="left", text=(
            "Resetting clears your saved attempts (the \u2713 marks and attempt history) "
            "and the answer you've typed. Your questions are not deleted.\n\n"
            "A backup of the history is saved in user_data/history_backups/ first, "
            "so nothing is lost for good.")).pack(anchor="w")

        buttons = ttk.Frame(body)
        buttons.pack(anchor="e", pady=(16, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="left", padx=4)
        this_btn = ttk.Button(buttons, text="Reset This Question",
                              command=lambda: self._reset(app.current.id if app.current else None))
        this_btn.pack(side="left", padx=4)
        if app.current is None:
            this_btn.configure(state="disabled")
        mode_name = "Python" if app.mode == MODE_PYTHON else "SQL"
        ttk.Button(buttons, text=f"Reset All {mode_name} Progress...",
                   command=lambda: self._reset(None)).pack(side="left", padx=4)
        self.bind("<Escape>", lambda _e: self.destroy())

    def _reset(self, question_id: str | None) -> None:
        mode_name = "Python" if self.app.mode == MODE_PYTHON else "SQL"
        if question_id is None and not messagebox.askyesno(
                "Reset all progress?", f"Clear progress for every {mode_name} question?", parent=self):
            return
        try:
            if question_id is None:
                backup = self.app.store.reset_history(question_ids={q.id for q in self.app.visible})
            else:
                backup = self.app.store.reset_history(question_id)
        except OSError as exc:
            messagebox.showerror("Could not reset", str(exc), parent=self)
            return
        self.destroy()
        self.app.after_reset(question_id, backup)


class GenerateDialog(tk.Toplevel):
    """Pick a difficulty and a count, preview random questions, then save them."""

    def __init__(self, app: "SqlHelperApp") -> None:
        super().__init__(app.root)
        self.app = app
        self.preview: list[Question] = []
        self.title("Generate Python Questions" if app.mode == MODE_PYTHON else "Generate SQL Questions")
        self.transient(app.root)
        self.geometry("720x520")
        self.minsize(600, 420)

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)

        controls = ttk.Frame(body)
        controls.pack(fill="x")
        ttk.Label(controls, text="Difficulty:").pack(side="left")
        self.diff_var = tk.StringVar(value="Easy")
        for level in GENERATOR_DIFFICULTIES:
            ttk.Radiobutton(controls, text=level, value=level, variable=self.diff_var,
                            command=self._generate).pack(side="left", padx=(6, 0))
        ttk.Label(controls, text="Number:").pack(side="left", padx=(18, 4))
        self.count_var = tk.StringVar(value="5")
        ttk.Spinbox(controls, from_=1, to=MAX_COUNT, width=4, textvariable=self.count_var,
                    command=self._generate).pack(side="left")
        ttk.Button(controls, text="Randomise", command=self._generate).pack(side="left", padx=(12, 0))

        ttk.Label(body, text="Preview. Press Randomise for a different set. "
                             "Select a row to read the full question.").pack(anchor="w", pady=(12, 4))
        table = ttk.Frame(body)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=("difficulty", "topic", "title"),
                                 show="headings", selectmode="browse", height=8)
        for cid, text, width in (("difficulty", "Difficulty", 90), ("topic", "Topic", 150),
                                 ("title", "Title", 380)):
            self.tree.heading(cid, text=text, anchor="w")
            self.tree.column(cid, width=width, anchor="w", stretch=cid == "title")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show_selected())

        self.detail = ttk.Label(body, wraplength=660, justify="left")
        self.detail.pack(fill="x", pady=(8, 0))
        self.status = ttk.Label(body, wraplength=660, justify="left")
        self.status.pack(fill="x", pady=(6, 0))

        buttons = ttk.Frame(body)
        buttons.pack(anchor="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="left", padx=4)
        self.save_btn = ttk.Button(buttons, text="Save", command=self._save)
        self.save_btn.pack(side="left", padx=4)

        self.bind("<Escape>", lambda _e: self.destroy())
        self._generate()

    def _generate(self) -> None:
        try:
            count = int(self.count_var.get())
            if not 1 <= count <= MAX_COUNT:
                raise ValueError
        except ValueError:
            self.status.configure(foreground=BAD, text=f"Number must be between 1 and {MAX_COUNT}.")
            return
        existing = {q.solution for q in self.app.questions}
        if self.app.mode == MODE_PYTHON:
            self.preview = generate_python_questions(self.diff_var.get(), count,
                                                     self.app.store.new_id, existing)
        else:
            self.preview = generate_questions(self.app.db, self.diff_var.get(), count,
                                              self.app.store.new_id, existing)
        self.tree.delete(*self.tree.get_children())
        for i, q in enumerate(self.preview):
            self.tree.insert("", "end", iid=str(i), values=(q.difficulty, q.topic, q.title))
        n = len(self.preview)
        self.save_btn.configure(text=f"Save {n} Question{'s' if n != 1 else ''}",
                                state="normal" if n else "disabled")
        if n < count:
            self.status.configure(foreground=BAD, text=(
                f"Only found {n} new question(s) at this difficulty that aren't already in your "
                "list. Try Mixed, or a smaller number."))
        else:
            self.status.configure(foreground="", text=(
                "Each question's solution was run and checked, so every one has a working answer."))
        if n:
            self.tree.selection_set("0")
        else:
            self.detail.configure(text="")

    def _show_selected(self) -> None:
        sel = self.tree.selection()
        if sel:
            q = self.preview[int(sel[0])]
            order = "  (row order matters)" if q.order_matters else ""
            code = f"\n\n{q.solution.strip()}" if q.kind == KIND_OUTPUT else ""
            self.detail.configure(text=f"{q.prompt}{order}{code}")

    def _save(self) -> None:
        saved = 0
        for q in self.preview:
            try:
                self.app.store.save_custom(q)
                saved += 1
            except OSError as exc:
                messagebox.showerror("Could not save", f"{q.title}: {exc}", parent=self)
                break
        if not saved:
            return
        first = self.preview[0].id
        self.destroy()
        self.app.reload_questions(select_id=first)
        self.app._set_feedback(f"Added {saved} generated question(s). They're marked "
                               "'generated' in the sidebar. Remove them any time with "
                               "Questions > Delete All Generated Questions.")


class ReportDialog(tk.Toplevel):
    """Build a 'where you went wrong' report for a set of questions and save it as HTML."""

    def __init__(self, app: "SqlHelperApp") -> None:
        super().__init__(app.root)
        self.app = app
        self.path: Path | None = None
        mode_name = "Python" if app.mode == MODE_PYTHON else "SQL"
        self.title(f"{mode_name} Progress Report")
        self.transient(app.root)
        self.geometry("620x460")
        self.minsize(520, 400)
        mine = [q for q in app.visible if q.is_custom]
        self.sets = {"mine": mine, "all": list(app.visible)}

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, wraplength=560, justify="left", text=(
            "See where you went wrong: for each question, your last wrong answer is checked "
            "again and explained, with the topics and lessons worth reviewing.")).pack(anchor="w")

        ttk.Label(body, text="Questions to include:").pack(anchor="w", pady=(14, 4))
        self.scope = tk.StringVar(value="mine" if mine else "all")
        mine_btn = ttk.Radiobutton(body, variable=self.scope, value="mine",
                                   text=f"Questions I made or generated ({len(mine)})")
        mine_btn.pack(anchor="w")
        if not mine:
            mine_btn.configure(state="disabled")
        ttk.Radiobutton(body, variable=self.scope, value="all",
                        text=f"All {mode_name} questions ({len(app.visible)})").pack(anchor="w")
        self.answers = tk.BooleanVar(value=False)
        ttk.Checkbutton(body, variable=self.answers, text=(
            "Include hints and correct answers (leave off if you still want to try them)")).pack(
            anchor="w", pady=(10, 0))

        self.summary = ttk.Label(body, wraplength=560, justify="left", text=(
            "" if mine else "You haven't made or generated any questions in this mode yet, "
                            "so the report will cover all questions."))
        self.summary.pack(anchor="w", fill="x", pady=(14, 0))

        buttons = ttk.Frame(body)
        buttons.pack(side="bottom", anchor="e", pady=(12, 0))
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side="left", padx=4)
        self.finder_btn = ttk.Button(buttons, text="Show in Finder" if IS_MAC else "Show File",
                                     command=self._reveal, state="disabled")
        self.finder_btn.pack(side="left", padx=4)
        self.open_btn = ttk.Button(buttons, text="Open Report", command=self._open, state="disabled")
        self.open_btn.pack(side="left", padx=4)
        self.make_btn = ttk.Button(buttons, text="Generate Report", command=self._generate)
        self.make_btn.pack(side="left", padx=4)
        self.bind("<Escape>", lambda _e: self.destroy())

    def _generate(self) -> None:
        questions = self.sets[self.scope.get()]
        if not questions:
            self.summary.configure(foreground=BAD, text="There are no questions in this set.")
            return
        mode, include = self.app.mode, self.answers.get()
        scope_name = "My questions" if self.scope.get() == "mine" else "All questions"
        title = f"{'Python' if mode == MODE_PYTHON else 'SQL'} progress report: {scope_name.lower()}"
        history = self.app.store.load_history()
        self.make_btn.configure(state="disabled")
        self.summary.configure(foreground="", text="Checking your answers...")

        def job():
            report = build_report(questions, history, self.app.db, title, mode, include)
            return report, to_html(report)

        if mode == MODE_PYTHON:
            # Python answers are re-run in subprocesses, so do it off the Tk thread.
            self.app.py.worker.submit("report", job, self._done)
        else:
            # SQLite connections belong to the thread that made them; SQL checks are fast.
            self._done(job())

    def _done(self, result) -> None:
        if not self.winfo_exists():
            return
        self.make_btn.configure(state="normal")
        if not isinstance(result, tuple):
            self.summary.configure(foreground=BAD, text=getattr(result, "error", "Report failed."))
            return
        report, page = result
        try:
            self.path = self.app.store.save_report(report.mode, page)
        except OSError as exc:
            self.summary.configure(foreground=BAD, text=f"Couldn't save the report: {exc}")
            return
        self.summary.configure(foreground="", text="\n".join(report.summary_lines()) +
                               f"\n\nSaved as reports/{self.path.name} in your data folder.")
        self.open_btn.configure(state="normal")
        self.finder_btn.configure(state="normal")
        self._open()

    def _open(self) -> None:
        if self.path:
            opener = ["open"] if IS_MAC else (["start", ""] if sys.platform == "win32" else ["xdg-open"])
            try:
                subprocess.Popen(opener + [str(self.path)], shell=sys.platform == "win32")
            except OSError:
                messagebox.showinfo("Report saved", str(self.path), parent=self)

    def _reveal(self) -> None:
        if self.path:
            try:
                subprocess.Popen(["open", "-R", str(self.path)] if IS_MAC
                                 else (["xdg-open", str(self.path.parent)]))
            except OSError:
                messagebox.showinfo("Report saved", str(self.path), parent=self)


class Tooltip:
    """A small label that appears when the mouse rests on a widget (for icon-only buttons)."""

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget, self.text = widget, text
        self.tip: tk.Toplevel | None = None
        self.job: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def set(self, text: str) -> None:
        self.text = text

    def _schedule(self, _e=None) -> None:
        self.job = self.widget.after(500, self._show)

    def _show(self) -> None:
        x = self.widget.winfo_rootx() + 4
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        ttk.Label(self.tip, text=self.text, padding=(6, 3), relief="solid", borderwidth=1).pack()

    def _hide(self, _e=None) -> None:
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None


def sidebar_icon(filled: bool) -> tk.PhotoImage:
    """A 20x16 'sidebar' symbol: a window outline with a left panel (filled when shown)."""
    img = tk.PhotoImage(width=20, height=16)
    img.put(ICON_GREY, to=(1, 1, 19, 3))       # top edge (2px)
    img.put(ICON_GREY, to=(1, 13, 19, 15))     # bottom edge
    img.put(ICON_GREY, to=(1, 1, 3, 15))       # left edge
    img.put(ICON_GREY, to=(17, 1, 19, 15))     # right edge
    img.put(ICON_GREY, to=(7, 1, 9, 15))       # divider between panel and content
    if filled:
        img.put(ICON_GREY, to=(3, 3, 7, 13))   # the panel itself
    return img


def check_icon(colour: str = "#2da44e") -> tk.PhotoImage:
    """A 14x14 tick drawn pixel by pixel (an image keeps titles readable when selected)."""
    img = tk.PhotoImage(width=14, height=14)
    points = [(2, 7), (5, 10), (11, 3)]
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        steps = max(abs(x2 - x1), abs(y2 - y1))
        for t in range(steps + 1):
            x = round(x1 + (x2 - x1) * t / steps)
            y = round(y1 + (y2 - y1) * t / steps)
            img.put(colour, to=(x, y, x + 2, y + 2))
    return img


def dot_icon(colour: str, size: int = 10) -> tk.PhotoImage:
    img = tk.PhotoImage(width=size + 4, height=size + 4)
    r = size / 2
    for y in range(size):
        for x in range(size):
            if (x + 0.5 - r) ** 2 + (y + 0.5 - r) ** 2 <= r * r:
                img.put(colour, (x + 2, y + 2))
    return img


class QuestionSidebar(ttk.Frame):
    """The question list down the left of the window, grouped by difficulty."""

    def __init__(self, master, on_pick: Callable[[int | None], None],
                 on_step: Callable[[int], None]) -> None:
        super().__init__(master, padding=(0, 0, 8, 0), width=SIDEBAR_WIDTH, height=PANE_HEIGHT)
        self.pack_propagate(False)
        self.on_pick = on_pick
        self.questions: list[Question] = []
        self.solved: set[str] = set()
        self.current: int | None = None

        head_font = tkfont.nametofont("TkDefaultFont").copy()
        head_font.configure(weight="bold")
        ttk.Label(self, text="Questions", font=head_font).pack(anchor="w")
        self.search_var = tk.StringVar()
        search = ttk.Entry(self, textvariable=self.search_var)
        search.pack(fill="x", pady=(6, 6))
        self._placeholder(search)
        self.search_var.trace_add("write", lambda *_: self._rebuild())

        # Prev / Next sit at the bottom of the sidebar (packed before the list so
        # the list takes the remaining height).
        nav = ttk.Frame(self)
        nav.pack(side="bottom", fill="x", pady=(8, 0))
        nav.columnconfigure((0, 1), weight=1, uniform="nav")
        self.prev_btn = ttk.Button(nav, text="\u2039 Prev", command=lambda: on_step(-1))
        self.prev_btn.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.next_btn = ttk.Button(nav, text="Next \u203a", command=lambda: on_step(1))
        self.next_btn.grid(row=0, column=1, sticky="ew", padx=(3, 0))
        Tooltip(self.prev_btn, f"Previous question ({PREV_KEYS})")
        Tooltip(self.next_btn, f"Next question ({NEXT_KEYS})")

        box = ttk.Frame(self)
        box.pack(fill="both", expand=True)
        ttk.Style(self).configure("Sidebar.Treeview", rowheight=26)
        self.tree = ttk.Treeview(box, show="tree", selectmode="browse", style="Sidebar.Treeview")
        self.icons = {"done": check_icon(), "todo": tk.PhotoImage(width=14, height=14),
                      **{level: dot_icon(c) for level, c in LEVEL_COLOURS.items()}}
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.column("#0", width=SIDEBAR_WIDTH - 40)
        self.tree.tag_configure("group", font=head_font)
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        self.empty = ttk.Label(self, text="", justify="left")
        self.empty.pack(anchor="w")

    def _placeholder(self, entry: ttk.Entry) -> None:
        """Grey 'Search...' hint while the box is empty and unfocused."""
        hint = "Search questions..."

        def show(_e=None):
            if not self.search_var.get():
                entry.configure(foreground="#8c959f")
                entry.insert(0, hint)
                self._hinting = True

        def hide(_e=None):
            if getattr(self, "_hinting", False):
                self._hinting = False
                entry.delete(0, "end")
                entry.configure(foreground="")

        entry.bind("<FocusIn>", hide)
        entry.bind("<FocusOut>", show)
        self._hinting = False
        show()

    def query(self) -> str:
        return "" if getattr(self, "_hinting", False) else self.search_var.get().strip().lower()

    def populate(self, questions: list[Question], solved: set[str], current: int | None) -> None:
        self.questions, self.solved, self.current = questions, solved, current
        self._rebuild()

    def _rebuild(self) -> None:
        tree = self.tree
        tree.delete(*tree.get_children())
        text = self.query()
        tree.insert("", "end", iid="free", text="\u270e  " + FREE_PRACTICE)
        shown = 0
        for level in DIFFICULTIES:
            members = [(i, q) for i, q in enumerate(self.questions) if q.difficulty == level]
            matches = [(i, q) for i, q in members
                       if not text or text in q.title.lower() or text in q.topic.lower()]
            if not matches:
                continue
            done = sum(1 for _, q in members if q.id in self.solved)
            group = tree.insert("", "end", iid=f"g:{level}", open=True, tags=("group",),
                                image=self.icons[level], text=f" {level}    {done} / {len(members)}")
            for i, q in matches:
                solved = q.id in self.solved
                suffix = "  \u00b7 generated" if q.generated else ("  \u00b7 yours" if q.is_custom else "")
                tree.insert(group, "end", iid=f"q:{i}", image=self.icons["done" if solved else "todo"],
                            text=f" {q.title}{suffix}")
                shown += 1
        self.empty.configure(text="No questions match your search." if text and not shown else "")
        self.select(self.current)

    def select(self, index: int | None) -> None:
        """Highlight a question without treating it as a new click."""
        self.current = index
        iid = "free" if index is None else f"q:{index}"
        if self.tree.exists(iid):
            if self.tree.selection() != (iid,):
                self.tree.selection_set(iid)
            self.tree.see(iid)
        else:
            self.tree.selection_set(())

    def _selected(self, _event=None) -> None:
        sel = self.tree.selection()
        if not sel or sel[0].startswith("g:"):
            if sel:   # a group heading: put the highlight back on the current question
                self.select(self.current)
            return
        index = None if sel[0] == "free" else int(sel[0][2:])
        if index != self.current:
            self.current = index
            self.on_pick(index)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class SqlHelperApp:
    def __init__(self, root: tk.Tk, store: QuestionStore, db: PracticeDatabase) -> None:
        self.root = root
        self.store = store
        self.db = db
        self.questions: list[Question] = []        # every question, both modes
        self.visible: list[Question] = []          # just the current mode's questions
        self.mode = MODE_SQL
        self.current: Question | None = None
        self.drafts: dict[str | None, str] = {}   # unsaved editor text per question (memory only)
        self._live_job: str | None = None
        self.expected_revealed = False             # expected output stays hidden until asked for
        self._feedback_is_error = False            # lets a successful run clear an old error

        root.title("SQL Helper: SQL & Python Interview Practice")
        width = min(1500, max(1180, root.winfo_screenwidth() - 60))
        root.geometry(f"{width}x800")
        root.minsize(1120, 640)

        self.live_var = tk.BooleanVar(value=True)
        self.mode_var = tk.StringVar(value=MODE_SQL)
        self._build_menu()
        self._build_layout()
        self._bind_keys()
        self.reload_questions()

    # ---- construction --------------------------------------------------
    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        acc = "Cmd" if IS_MAC else "Ctrl"

        qmenu = tk.Menu(menubar, tearoff=False)
        qmenu.add_command(label="New Question...", accelerator=f"{acc}+N",
                          command=self.new_question)
        qmenu.add_command(label="New Question from Current Query...",
                          command=lambda: self.new_question(from_editor=True))
        qmenu.add_command(label="Generate Questions...", accelerator=f"{acc}+G",
                          command=lambda: GenerateDialog(self))
        qmenu.add_command(label="Edit This Question...", command=self.edit_question)
        qmenu.add_command(label="Delete This Question...", command=self.delete_question)
        qmenu.add_command(label="Delete All Generated Questions...",
                          command=self.delete_generated)
        qmenu.add_separator()
        qmenu.add_command(label="Reset Progress...", command=lambda: ResetDialog(self))
        qmenu.add_command(label="Progress Report...", command=lambda: ReportDialog(self))
        qmenu.add_command(label="Attempt History...", command=lambda: HistoryWindow(self))
        qmenu.add_command(label="Open Data Folder", command=self.open_data_folder)
        menubar.add_cascade(label="Questions", menu=qmenu)

        hmenu = tk.Menu(menubar, tearoff=False)
        hmenu.add_command(label="Keyboard Shortcuts", command=self.show_shortcuts)
        menubar.add_cascade(label="Help", menu=hmenu)
        self.root.configure(menu=menubar)

    def _build_layout(self) -> None:
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)

        # Top bar: sidebar toggle, mode switch, navigation and progress.
        top = ttk.Frame(outer)
        top.pack(fill="x", pady=(0, 8))
        self.progress = ttk.Label(top)
        self.progress.pack(side="right")   # packed first so it keeps its space when narrow
        self._icons = {True: sidebar_icon(True), False: sidebar_icon(False)}  # keep references
        self.sidebar_btn = ttk.Button(top, image=self._icons[True], command=self.toggle_sidebar,
                                      style="Toolbutton", takefocus=False)
        self.sidebar_btn.pack(side="left", padx=(0, 10))
        self.sidebar_tip = Tooltip(self.sidebar_btn, "Hide the question list")
        for value, label in ((MODE_SQL, "SQL"), (MODE_PYTHON, "Python")):
            ttk.Radiobutton(top, text=label, value=value, variable=self.mode_var,
                            command=self._mode_changed).pack(side="left", padx=(0, 6))
        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=(2, 10))
        ttk.Button(top, text="+ New", command=self.new_question).pack(side="left", padx=4)
        ttk.Button(top, text="Generate...",
                   command=lambda: GenerateDialog(self)).pack(side="left")
        ttk.Button(top, text="Reset...", command=lambda: ResetDialog(self)).pack(side="left", padx=4)
        ttk.Button(top, text="Report...", command=lambda: ReportDialog(self)).pack(side="left")

        panes = ttk.PanedWindow(outer, orient="horizontal")
        panes.pack(fill="both", expand=True)
        self.panes = panes
        self.sidebar = QuestionSidebar(panes, on_pick=self._select, on_step=self._step)
        panes.add(self.sidebar, weight=0)
        # ttk.PanedWindow has no minimum pane size, so clamp the dividers after
        # every drag step and resize (after_idle runs once ttk has moved them).
        self._work_ratio = 0.5        # editor's share of the editor+results width
        self._last_width = 0
        panes.bind("<B1-Motion>", lambda _e: self.root.after_idle(self._clamp_sashes), add="+")
        panes.bind("<ButtonRelease-1>", lambda _e: self.root.after_idle(self._drag_done), add="+")
        panes.bind("<Configure>", lambda _e: self.root.after_idle(self._resized), add="+")

        # Left: question + editor + feedback.
        # Both panes get a fixed requested size and don't propagate their children's
        # sizes. Otherwise a wide result table makes its pane demand more room and
        # squeezes the editor side (its buttons get cut off).
        left = ttk.Frame(panes, padding=(0, 0, 10, 0), width=PANE_WIDTH, height=PANE_HEIGHT)
        left.pack_propagate(False)
        panes.add(left, weight=1)

        card = ttk.LabelFrame(left, text="Question", padding=10)
        card.pack(fill="x")
        title_font = tkfont.nametofont("TkDefaultFont").copy()
        title_font.configure(size=15, weight="bold")
        self.q_title = ttk.Label(card, font=title_font)
        self.q_title.pack(anchor="w")
        self.q_meta = ttk.Label(card)
        self.q_meta.pack(anchor="w", pady=(2, 6))
        self.q_prompt = ttk.Label(card, wraplength=480, justify="left")
        self.q_prompt.pack(anchor="w", fill="x")
        card.bind("<Configure>", lambda e: self.q_prompt.configure(wraplength=max(e.width - 30, 200)))
        # Code shown with the question ("predict the output" questions only).
        self.q_code = tk.Text(card, height=5, font=mono_font(), wrap="none", borderwidth=0,
                              relief="flat", highlightthickness=1, highlightbackground=ICON_GREY,
                              padx=10, pady=6, state="disabled")
        q_buttons = ttk.Frame(card)
        q_buttons.pack(anchor="w", pady=(8, 0))
        self.q_buttons = q_buttons
        self.hint_btn = ttk.Button(q_buttons, text="Hint", command=self.show_hint)
        self.hint_btn.pack(side="left")
        self.solution_btn = ttk.Button(q_buttons, text="Solution", command=self.reveal_solution)
        self.solution_btn.pack(side="left", padx=6)
        self.card_expected_btn = ttk.Button(q_buttons, text="Show Expected",
                                            command=lambda: self.toggle_expected(select_tab=True))
        self.card_expected_btn.pack(side="left")
        ttk.Button(q_buttons, text="Lesson", command=self.show_lesson).pack(side="left", padx=6)

        self.editor_label = ttk.Label(left, text="Your SQL")
        self.editor_label.pack(anchor="w", pady=(10, 2))
        self.editor = SqlEditor(left, on_change=self._schedule_live_run)
        self.editor.pack(fill="both", expand=True)

        actions = ttk.Frame(left)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Checkbutton(actions, text="Live preview", variable=self.live_var,
                        command=self._schedule_live_run).pack(side="right")
        ttk.Button(actions, text=f"Run  {RUN_KEYS}", command=self.run_query).pack(side="left")
        self.check_btn = ttk.Button(actions, text=f"Check Answer  {CHECK_KEYS}",
                                    command=self.check_answer)
        self.check_btn.pack(side="left", padx=6)
        ttk.Button(actions, text="Clear", command=lambda: self.editor.set("")).pack(side="left")

        self.feedback = ttk.Label(left, wraplength=480, justify="left")
        self.feedback.pack(fill="x", pady=(10, 0))
        left.bind("<Configure>", lambda e: self.feedback.configure(wraplength=max(e.width - 20, 200)))

        # Right: result tabs.
        right = ttk.Frame(panes, width=PANE_WIDTH, height=PANE_HEIGHT)
        right.pack_propagate(False)
        panes.add(right, weight=1)
        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill="both", expand=True)
        self.py = PythonPanel(right, self)   # shown instead of self.tabs in Python mode

        self.user_grid = ResultGrid(self.tabs, "Start typing a query to see results here.")
        expected_tab = ttk.Frame(self.tabs)
        bar = ttk.Frame(expected_tab)
        bar.pack(fill="x", pady=(6, 0))
        self.expected_btn = ttk.Button(bar, text="Show Expected Result",
                                       command=self.toggle_expected)
        self.expected_btn.pack(side="left")
        self.expected_grid = ResultGrid(expected_tab, "Pick a question to see its expected output.")
        self.expected_grid.pack(fill="both", expand=True)
        self.tabs.add(self.user_grid, text="Your Result")
        self.tabs.add(expected_tab, text="Expected Result")
        self.expected_tab = expected_tab
        self.tabs.add(self._build_tables_tab(self.tabs), text="Tables")
        self.sql_lesson = LessonView(self.tabs)
        self.sql_lesson.set_lessons(lessons_for_mode(MODE_SQL))
        self.tabs.add(self.sql_lesson, text="Lesson")
        self.py.lesson_view.set_lessons(lessons_for_mode(MODE_PYTHON))

        # Bottom row: status text, plus Prev/Next while the sidebar is hidden.
        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", pady=(8, 0))
        self.bottom_nav = ttk.Frame(bottom)
        bottom_prev = ttk.Button(self.bottom_nav, text="\u2039 Prev", width=9,
                                 command=lambda: self._step(-1))
        bottom_prev.pack(side="left", padx=(0, 6))
        bottom_next = ttk.Button(self.bottom_nav, text="Next \u203a", width=9,
                                 command=lambda: self._step(1))
        bottom_next.pack(side="left")
        Tooltip(bottom_prev, f"Previous question ({PREV_KEYS})")
        Tooltip(bottom_next, f"Next question ({NEXT_KEYS})")
        self.next_btns = [self.sidebar.next_btn, bottom_next]   # kept in sync
        self.status = ttk.Label(bottom, anchor="w")
        self.status.pack(side="left", fill="x", expand=True)

    def _build_tables_tab(self, master) -> ttk.Frame:
        frame = ttk.Frame(master, padding=(0, 4))
        side = ttk.Frame(frame)
        side.pack(side="left", fill="y", padx=(0, 8))
        ttk.Label(side, text="Tables").pack(anchor="w")
        self.table_list = tk.Listbox(side, exportselection=False, width=16, activestyle="none")
        self.table_list.pack(fill="y", expand=True, pady=(4, 4))
        ttk.Label(side, text="Double-click to\ninsert the name", justify="left").pack(anchor="w")
        for name in self.db.table_names():
            self.table_list.insert("end", name)
        self.table_list.bind("<<ListboxSelect>>", lambda _e: self._show_table())
        self.table_list.bind("<Double-1>", lambda _e: self._insert_table_name())

        main = ttk.Frame(frame)
        main.pack(side="left", fill="both", expand=True)
        self.columns_label = ttk.Label(main, justify="left", font=mono_font(), wraplength=400)
        self.columns_label.pack(anchor="w", fill="x")
        main.bind("<Configure>",
                  lambda e: self.columns_label.configure(wraplength=max(e.width - 10, 200)))
        self.table_grid = ResultGrid(main, "")
        self.table_grid.pack(fill="both", expand=True)

        self.table_list.selection_set(0)
        self.root.after_idle(self._show_table)
        return frame

    def _bind_keys(self) -> None:
        # Bind on the editor too: its own binding runs before the Text class binding,
        # and returning "break" stops Return from also inserting a newline.
        for widget in (self.editor.text, self.root):
            widget.bind(f"<{MOD}-Return>", lambda _e: (self.run_query(), "break")[1])
            widget.bind(f"<{MOD}-Shift-Return>", lambda _e: (self.check_answer(), "break")[1])
        self.root.bind(f"<{MOD}-n>", lambda _e: self.new_question())
        self.root.bind(f"<{MOD}-bracketleft>", lambda _e: self._step(-1))
        self.root.bind(f"<{MOD}-bracketright>", lambda _e: self._step(1))
        self.root.bind(f"<{MOD}-g>", lambda _e: GenerateDialog(self))

    # ---- questions -----------------------------------------------------
    def reload_questions(self, select_id: str | None = None) -> None:
        try:
            self.questions = self.store.load_all()
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not load questions", str(exc))
            self.questions = []
        if self.store.warnings:
            messagebox.showwarning("Some questions were skipped", "\n".join(self.store.warnings))
        target = next((q for q in self.questions if q.id == select_id), None)
        if target is not None and target.mode != self.mode:
            self._switch_mode(target.mode)
        self._filter()
        self._refresh_list()
        keep = select_id or (self.current.id if self.current else None)
        index = next((i for i, q in enumerate(self.visible) if q.id == keep),
                     0 if self.visible else None)
        self._select(index)

    # ---- modes -----------------------------------------------------------
    def _filter(self) -> None:
        """This mode's questions, ordered Easy -> Medium -> Hard (the sidebar's order)."""
        rank = {level: i for i, level in enumerate(DIFFICULTIES)}
        self.visible = sorted((q for q in self.questions if q.mode == self.mode),
                              key=lambda q: rank.get(q.difficulty, len(rank)))

    def _draft_key(self, q: Question | None) -> str:
        return q.id if q else f"free:{self.mode}"

    def _mode_changed(self) -> None:
        if self.mode_var.get() != self.mode:
            self._switch_mode(self.mode_var.get())
            self._filter()
            self._refresh_list()
            self._select(0 if self.visible else None, save_draft=False)

    def _switch_mode(self, mode: str) -> None:
        """Swap the right-hand panel and editor language; keeps the current draft."""
        self.drafts[self._draft_key(self.current)] = self.editor.get()
        self.mode = mode
        self.mode_var.set(mode)
        self.current = None
        if mode == MODE_PYTHON:
            self.tabs.pack_forget()
            self.py.pack(fill="both", expand=True)
        else:
            self.py.pack_forget()
            self.tabs.pack(fill="both", expand=True)

    def store_solved(self, q: Question) -> bool:
        return q.id in self.store.solved_ids()

    def _current_index(self) -> int | None:
        return self.visible.index(self.current) if self.current in self.visible else None

    def _refresh_list(self) -> None:
        solved = self.store.solved_ids()
        self.sidebar.populate(self.visible, solved, self._current_index())
        done = sum(1 for q in self.visible if q.id in solved)
        self.progress.configure(text=f"Solved {done} / {len(self.visible)}")

    def sidebar_shown(self) -> bool:
        return str(self.sidebar) in [str(pane) for pane in self.panes.panes()]

    def toggle_sidebar(self) -> None:
        shown = not self.sidebar_shown()
        if shown:
            self.panes.insert(0, self.sidebar, weight=0)
            self.root.after_idle(lambda: self._set_sash(0, SIDEBAR_WIDTH))
            self.root.after_idle(self._balance)
        else:
            self.panes.forget(self.sidebar)
        # Prev/Next live in the sidebar; when it's hidden they move to the bottom row.
        if shown:
            self.bottom_nav.pack_forget()
        else:
            self.bottom_nav.pack(side="right", before=self.status)
        self.sidebar_btn.configure(image=self._icons[shown])
        self.sidebar_tip.set("Hide the question list" if shown else "Show the question list")
        self.root.after_idle(self._clamp_sashes)

    def _set_sash(self, index: int, pos: int) -> None:
        try:
            self.panes.sashpos(index, pos)
        except tk.TclError:
            pass   # not laid out yet

    def _work_sash(self) -> int:
        """Index of the divider between the editor and the results."""
        return 1 if self.sidebar_shown() else 0

    def _side_width(self) -> int:
        return self.panes.sashpos(0) if self.sidebar_shown() else 0

    def _balance(self) -> None:
        """Place the editor/results divider at the remembered ratio."""
        total = self.panes.winfo_width()
        if total < 100:
            return
        try:
            side = self._side_width()
            self.panes.sashpos(self._work_sash(), int(side + self._work_ratio * (total - side)))
        except tk.TclError:
            return
        self._clamp_sashes()

    def _resized(self) -> None:
        width = self.panes.winfo_width()
        if width != self._last_width:
            self._last_width = width
            self._balance()

    def _drag_done(self) -> None:
        """Remember the split the user chose, so resizing the window keeps it."""
        self._clamp_sashes()
        total = self.panes.winfo_width()
        try:
            side = self._side_width()
            if total - side > 0:
                self._work_ratio = (self.panes.sashpos(self._work_sash()) - side) / (total - side)
        except tk.TclError:
            pass

    def _clamp_sashes(self) -> None:
        """Keep the sidebar, editor and results panes at usable widths."""
        total = self.panes.winfo_width()
        if total < 100:
            return
        try:
            if self.sidebar_shown():
                s0 = self.panes.sashpos(0)
                side = max(SIDEBAR_MIN, min(SIDEBAR_MAX, s0, total - 2 * WORK_MIN))
                if side != s0:
                    self.panes.sashpos(0, side)
                s1 = self.panes.sashpos(1)
                mid = max(side + WORK_MIN, min(s1, total - WORK_MIN))
                if mid != s1:
                    self.panes.sashpos(1, mid)
            else:
                s0 = self.panes.sashpos(0)
                mid = max(WORK_MIN, min(s0, total - WORK_MIN))
                if mid != s0:
                    self.panes.sashpos(0, mid)
        except tk.TclError:
            pass

    def _select(self, question_index: int | None, save_draft: bool = True) -> None:
        """question_index None means free practice."""
        if save_draft:
            self.drafts[self._draft_key(self.current)] = self.editor.get()
        self.current = None if question_index is None or not self.visible \
            else self.visible[question_index]
        self.sidebar.select(self._current_index())
        self._show_current()

    def _step(self, delta: int) -> None:
        """Prev/Next in sidebar order: free practice, then Easy, Medium, Hard."""
        order: list[int | None] = [None] + list(range(len(self.visible)))
        here = order.index(self._current_index())
        self._select(order[(here + delta) % len(order)])

    def _show_current(self) -> None:
        q = self.current
        python = self.mode == MODE_PYTHON
        self._set_feedback("")
        state = "normal" if q else "disabled"
        for btn in (self.hint_btn, self.solution_btn, self.check_btn):
            btn.configure(state=state)
        if q is None:
            self.q_title.configure(text="Free practice")
            self.q_meta.configure(text="")
            self.q_prompt.configure(text=(
                "Write any Python and press Run. Use the Visualise tab to step through it "
                "line by line." if python else
                "Write any SELECT query against the practice tables. "
                "Browse the Tables tab to see what data is available."))
        else:
            self.q_title.configure(text=q.title)
            order = " | row order matters" if q.order_matters else ""
            style = {KIND_FUNCTION: " | write a function", KIND_OUTPUT: " | predict the output"}.get(q.kind, "")
            source = "generated" if q.generated else ("your question" if q.is_custom else "built-in")
            self.q_meta.configure(text=f"{q.difficulty} | {q.topic} | {source}{order}{style}")
            self.q_prompt.configure(text=q.prompt)

        output_question = q is not None and q.kind == KIND_OUTPUT
        self.q_code.pack_forget()
        if output_question:
            self.q_code.configure(state="normal", height=min(q.solution.count("\n") + 1, 10))
            self.q_code.delete("1.0", "end")
            self.q_code.insert("1.0", q.solution.rstrip())
            self.q_code.configure(state="disabled")
            self.q_code.pack(fill="x", pady=(6, 0), before=self.q_buttons)
        if not python:
            self.editor.set_language(MODE_SQL)
            self.editor_label.configure(text="Your SQL")
        elif output_question:
            self.editor.set_language(None)
            self.editor_label.configure(text="What does it print? Type the exact output:")
        else:
            self.editor.set_language(MODE_PYTHON)
            self.editor_label.configure(text="Your Python code")

        self.expected_revealed = False
        self._render_expected()
        self._set_next(done=False)
        key = self._draft_key(q)
        starter = q.starter if (q is not None and python and q.kind == KIND_FUNCTION) else ""
        self.editor.set(self.drafts.get(key) or starter)
        self.editor.highlight()
        if python:
            self.py.show_question(q)
            self.py.lesson_view.show(lesson_for(q, MODE_PYTHON))
            self._schedule_live_run()
        else:
            self.user_grid.clear("Start typing a query to see results here.")
            self.sql_lesson.show(lesson_for(q, MODE_SQL))
        self.status.configure(text="")
        self.editor.text.focus_set()

    def show_lesson(self) -> None:
        if self.mode == MODE_PYTHON:
            self.py.tabs.select(self.py.lesson_view)
        else:
            self.tabs.select(self.sql_lesson)

    def toggle_expected(self, select_tab: bool = False) -> None:
        if self.current is None:
            return
        self.expected_revealed = not self.expected_revealed
        self._render_expected()
        if select_tab and self.expected_revealed:
            if self.mode == MODE_PYTHON:
                self.py.tabs.select(self.py.expected_tab)
            else:
                self.tabs.select(self.expected_tab)

    def _render_expected(self) -> None:
        q = self.current
        short = "Hide Expected" if (q and self.expected_revealed) else "Show Expected"
        self.card_expected_btn.configure(state="normal" if q else "disabled", text=short)
        if self.mode == MODE_PYTHON:
            self.py.render_expected(q, self.expected_revealed)
            return
        if q is None:
            self.expected_btn.configure(state="disabled", text="Show Expected Result")
            self.expected_grid.clear("No expected result in free practice.")
            return
        label = "Hide Expected Result" if self.expected_revealed else "Show Expected Result"
        self.expected_btn.configure(state="normal", text=label)
        if not self.expected_revealed:
            self.expected_grid.clear("Hidden so you can try first. Press the button above to compare.")
            return
        expected = self.db.run(q.solution)
        if expected.ok:
            self.expected_grid.show(expected, "Target output: ")
        else:
            self.expected_grid.clear(f"This question's solution has an error: {expected.error}")

    def delete_generated(self) -> None:
        generated = [q for q in self.visible if q.generated]
        if not generated:
            messagebox.showinfo("Delete generated questions", "There are no generated questions.")
            return
        if not messagebox.askyesno(
                "Delete generated questions?",
                f"Delete all {len(generated)} generated {'Python' if self.mode == MODE_PYTHON else 'SQL'} "
                "questions? Their files are removed from "
                "the data folder and this can't be undone. Questions you wrote yourself and "
                "your attempt history are kept."):
            return
        for q in generated:
            try:
                self.store.delete_custom(q)
            except OSError as exc:
                messagebox.showerror("Could not delete", f"{q.title}: {exc}")
                break
            self.drafts.pop(q.id, None)
        if self.current and self.current.generated:
            self.current = None
        self.reload_questions()

    def after_reset(self, question_id: str | None, backup) -> None:
        """Clear typed answers that belonged to the reset progress and refresh the UI."""
        if question_id is None:
            for q in self.visible:
                self.drafts.pop(q.id, None)
        else:
            self.drafts.pop(question_id, None)
        affected = question_id is None or (self.current and self.current.id == question_id)
        self._refresh_list()
        if affected:
            self.drafts.pop(self._draft_key(self.current), None)
            self._show_current()
        where = (f" A backup of the old history was saved as history_backups/{backup.name} "
                 "in the data folder.") if backup else ""
        self._set_feedback(("All progress in this mode reset." if question_id is None
                            else "Progress for this question reset.") + where)

    def show_hint(self) -> None:
        if self.current:
            self._set_feedback(f"Hint: {self.current.hint or 'No hint for this question.'}")

    def reveal_solution(self) -> None:
        q = self.current
        if not q or not messagebox.askyesno(
                "Reveal solution?", "Show the answer below the editor? "
                                    "What you've typed is left untouched."):
            return
        if q.kind == KIND_OUTPUT:
            printed = self.py.expected_for(q).module_out.rstrip()
            self._set_feedback(f"The code prints:\n{printed}\n\nTip: step through it in the "
                               "Visualise tab to see why.")
            self.expected_revealed = True
            self._render_expected()
        else:
            self._set_feedback(f"One possible solution:\n{q.solution.rstrip()}")

    def new_question(self, from_editor: bool = False) -> None:
        starter = self.editor.get() if from_editor else ""
        if self.mode == MODE_PYTHON:
            PythonQuestionDialog(self, starter_code=starter)
        else:
            QuestionDialog(self, starter_sql=starter)

    def edit_question(self) -> None:
        if not self.current or not self.current.is_custom:
            messagebox.showinfo("Edit question", "Only questions you created can be edited. "
                                "Use 'New Question from Current Query' to build on a built-in one.")
            return
        if self.current.mode == MODE_PYTHON:
            PythonQuestionDialog(self, question=self.current)
        else:
            QuestionDialog(self, question=self.current)

    def delete_question(self) -> None:
        q = self.current
        if not q or not q.is_custom:
            messagebox.showinfo("Delete question", "Only questions you created can be deleted.")
            return
        if messagebox.askyesno("Delete question?",
                               f"Delete '{q.title}'? This removes its file from the data "
                               "folder and can't be undone. Your attempt history is kept."):
            try:
                self.store.delete_custom(q)
            except OSError as exc:
                messagebox.showerror("Could not delete", str(exc))
                return
            self.drafts.pop(q.id, None)
            self.current = None
            self.reload_questions()

    def load_attempt(self, question_id: str | None, sql: str) -> None:
        target = next((q for q in self.questions if q.id == question_id), None)
        if target is not None and target.mode != self.mode:
            self._switch_mode(target.mode)
            self._filter()
            self._refresh_list()
        index = next((i for i, q in enumerate(self.visible) if q.id == question_id), None)
        self._select(index, save_draft=target is None or target.mode == self.mode)
        self.editor.set(sql)
        self.root.lift()

    # ---- running and checking ------------------------------------------
    def _schedule_live_run(self) -> None:
        if self._live_job:
            self.root.after_cancel(self._live_job)
            self._live_job = None
        if self.live_var.get():
            self._live_job = self.root.after(LIVE_DELAY_MS, self._live_run)

    def _live_run(self) -> None:
        self._live_job = None
        if self.mode == MODE_PYTHON:
            self.py.live()
            return
        sql = self.editor.get()
        if not sql.strip():
            self.user_grid.clear("Start typing a query to see results here.")
            self.status.configure(text="")
            return
        result = self.db.run(sql)
        if result.ok:
            self.user_grid.show(result, "Live: ")
            self.status.configure(foreground="", text=f"Live preview ran in {result.elapsed_ms:.1f} ms.")
        else:
            # Half-typed SQL is usually invalid; keep the last good grid and explain gently.
            self.user_grid.mark_stale("Your current text doesn't run yet.")
            self.status.configure(foreground=BAD, text=f"Live preview: {result.error}")

    def _execute(self) -> QueryResult:
        """Run the editor's SQL and show it in Your Result."""
        result = self.db.run(self.editor.get())
        self.tabs.select(self.user_grid)
        if result.ok:
            self.user_grid.show(result)
            self.status.configure(foreground="", text=f"Ran in {result.elapsed_ms:.1f} ms.")
            if self._feedback_is_error:
                self._set_feedback("")   # the earlier error no longer applies
        else:
            self.user_grid.clear("Your query has an error. See the message below the editor.")
            self.status.configure(foreground=BAD, text="")
            self._set_feedback(f"Error: {result.error}", BAD, is_error=True)
        return result

    def run_query(self) -> QueryResult:
        """Run the query. If it already answers the current question, count it as solved.

        Wrong answers are not graded here (that's what Check Answer is for), so
        running a half-finished query never shows a "wrong" message.
        """
        if self.mode == MODE_PYTHON:
            self.py.run(check=False)
            return None
        result = self._execute()
        q = self.current
        if result.ok and result.columns and q is not None:
            outcome = grade(result, self.db.run(q.solution), q.order_matters,
                            show_examples=self.expected_revealed)
            if outcome.correct:
                self._on_correct(q, outcome)
        return result

    def check_answer(self) -> None:
        q = self.current
        if q is None:
            return
        if self.mode == MODE_PYTHON:
            self.py.run(check=True)
            return
        if not self.editor.get().strip():
            self._set_feedback("Write a query first.", BAD)
            return
        user = self._execute()
        outcome = grade(user, self.db.run(q.solution), q.order_matters,
                        show_examples=self.expected_revealed)
        if outcome.correct:
            self._on_correct(q, outcome)
            return
        text = outcome.message
        if outcome.details:
            text += "\n" + "\n".join(f"- {d}" for d in outcome.details)
        if user.ok:
            text += ("\nCompare with the Expected Result tab." if self.expected_revealed
                     else "\nStuck? Press 'Show Expected Result' to see the target output.")
        self._set_feedback(text, BAD, is_error=not user.ok)
        self._record(q, correct=False)

    def python_graded(self, q: Question, outcome, check: bool, user_ok: bool) -> None:
        """Called by the Python panel when a Run or Check finishes."""
        if q is not self.current:
            return   # the user moved to another question while it was running
        if outcome.correct:
            self._on_correct(q, outcome)
            return
        details = "\n".join(f"- {d}" for d in outcome.details)
        if check:
            text = outcome.message + (f"\n{details}" if details else "")
            if user_ok:
                text += ("\nCompare with the Expected tab." if self.expected_revealed
                         else "\nStuck? Press 'Show Expected Result' to see the target output.")
            self._set_feedback(text, BAD, is_error=not user_ok)
            self._record(q, correct=False)
        elif not user_ok:
            self._set_feedback(outcome.message + (f"\n{details}" if details else ""), BAD, is_error=True)
        elif q.kind == KIND_OUTPUT:
            self._set_feedback("Not quite yet. Press Check Answer for details.", BAD)
        elif self._feedback_is_error:
            self._set_feedback("")

    def _on_correct(self, q: Question, outcome) -> None:
        """Mark the question solved, show the answer, and point the user at Next."""
        if not self.expected_revealed:
            self.expected_revealed = True   # nothing left to give away
            self._render_expected()
        text = outcome.message
        if outcome.details:
            text += "\n" + "\n".join(f"- {d}" for d in outcome.details)
        where = "in the sidebar" if self.sidebar_shown() else "at the bottom"
        self._set_feedback(text + f"\nPress Next \u203a ({where}) for the next question.", GOOD)
        self._record(q, correct=True)
        self._set_next(done=True)

    def _set_next(self, done: bool) -> None:
        """Highlight every Next button (sidebar + bottom row) after a correct answer."""
        for btn in self.next_btns:
            # default="active" is drawn by macOS as the blue default button.
            btn.configure(default="active" if done else "normal",
                          text="Next \u203a  \u2713" if done else "Next \u203a")

    def _record(self, q: Question, correct: bool) -> None:
        try:
            self.store.record_attempt(q.id, self.editor.get(), correct)
        except OSError as exc:
            self.status.configure(foreground=BAD, text=f"Couldn't save history: {exc}")
        self._refresh_list()

    # ---- tables tab ----------------------------------------------------
    def _selected_table(self) -> str | None:
        sel = self.table_list.curselection()
        return self.table_list.get(sel[0]) if sel else None

    def _show_table(self) -> None:
        table = self._selected_table()
        if not table:
            return
        cols = self.db.table_columns(table)
        self.columns_label.configure(
            text=f"{table}(" + ", ".join(f"{n} {t}" for n, t in cols) + ")")
        self.table_grid.show(self.db.run(f'SELECT * FROM "{table}"'))

    def _insert_table_name(self) -> None:
        table = self._selected_table()
        if table:
            self.editor.insert_at_cursor(table)

    # ---- misc ----------------------------------------------------------
    def _set_feedback(self, text: str, color: str = "", is_error: bool = False) -> None:
        self.feedback.configure(text=text, foreground=color)
        self._feedback_is_error = is_error

    def open_data_folder(self) -> None:
        folder = self.store.data_dir
        folder.mkdir(parents=True, exist_ok=True)
        opener = ["open"] if IS_MAC else (["explorer"] if sys.platform == "win32" else ["xdg-open"])
        try:
            subprocess.Popen(opener + [str(folder)])
        except OSError:
            messagebox.showinfo("Data folder", str(folder))

    def show_shortcuts(self) -> None:
        messagebox.showinfo("Keyboard shortcuts", "\n".join((
            f"{MOD_LABEL}+Enter            Run query",
            f"{MOD_LABEL}+Shift+Enter    Check answer",
            f"{MOD_LABEL}+[  /  {MOD_LABEL}+]       Previous / next question",
            f"{MOD_LABEL}+N                  New question",
            f"{MOD_LABEL}+G                  Generate questions",
            f"{MOD_LABEL}+Z                  Undo in editor",
        )))


def main() -> None:
    root = tk.Tk()
    try:
        store = QuestionStore()
        db = PracticeDatabase()
    except Exception as exc:  # show startup failures instead of a silent exit
        root.withdraw()
        messagebox.showerror("SQL Helper could not start", str(exc))
        raise
    set_app_icon(root)
    SqlHelperApp(root, store, db)
    bring_to_front(root)
    root.mainloop()


ICON_FILE = Path(__file__).resolve().parent / "assets" / "icon.png"


def set_app_icon(root: tk.Tk) -> None:
    """Use our icon for every window (on macOS this also sets the Dock icon)."""
    try:
        root._icon = tk.PhotoImage(file=str(ICON_FILE))  # keep a reference or Tk drops it
        root.iconphoto(True, root._icon)
    except tk.TclError:
        pass  # missing/unreadable icon is cosmetic, never fatal


def bring_to_front(root: tk.Tk) -> None:
    """Show the window above other apps on launch.

    When started from SQL Helper.app, the launcher quits immediately, so macOS
    doesn't treat our window as the active app and it would open behind
    whatever was in front. Briefly making it topmost brings it forward.
    """
    root.lift()
    root.attributes("-topmost", True)
    root.after(500, lambda: root.attributes("-topmost", False))
    root.focus_force()
