"""Tkinter user interface for SQL Helper.

Layout: the left side holds the question and the SQL editor; the right side
shows results as tables (your live result, the expected result, and a browser
for the practice tables). All SQL and file logic lives in the other modules;
this file only wires widgets to them.
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
from .questions import DIFFICULTIES, Question, QuestionStore

IS_MAC = sys.platform == "darwin"
MOD = "Command" if IS_MAC else "Control"      # Tk event modifier name
MOD_LABEL = "Cmd" if IS_MAC else "Ctrl"       # what we show to the user
RUN_KEYS = "\u2318\u21b5" if IS_MAC else "Ctrl+Enter"            # ⌘↵
CHECK_KEYS = "\u2318\u21e7\u21b5" if IS_MAC else "Ctrl+Shift+Enter"  # ⌘⇧↵
LIVE_DELAY_MS = 350                           # pause after typing before live preview runs
MAX_DISPLAY_ROWS = 500                        # rows drawn in a grid (Treeview gets slow beyond this)
FREE_PRACTICE = "Free practice (no question)"
PANE_WIDTH, PANE_HEIGHT = 600, 560            # starting size of each half; both stretch equally

GOOD = "#1a7f37"
BAD = "#cf222e"

SQL_KEYWORDS = (
    "SELECT FROM WHERE AND OR NOT IN IS NULL LIKE BETWEEN AS ON JOIN INNER LEFT RIGHT "
    "FULL OUTER CROSS GROUP BY HAVING ORDER ASC DESC LIMIT OFFSET DISTINCT UNION ALL "
    "INTERSECT EXCEPT CASE WHEN THEN ELSE END WITH RECURSIVE EXISTS COUNT SUM AVG MIN "
    "MAX ROUND COALESCE IFNULL CAST LOWER UPPER LENGTH SUBSTR TRIM"
).split()
KEYWORD_RE = re.compile(r"\b(?:" + "|".join(SQL_KEYWORDS) + r")\b", re.IGNORECASE)
STRING_RE = re.compile(r"'(?:[^']|'')*'?")
COMMENT_RE = re.compile(r"--[^\n]*")


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
                            padx=8, pady=8, borderwidth=1, relief="solid")
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
        self.text.bind("<<Modified>>", self._modified)

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
        for tag, pattern in (("kw", KEYWORD_RE), ("str", STRING_RE), ("cmt", COMMENT_RE)):
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

        cols = ("when", "question", "result", "sql")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings")
        for cid, text, width in (("when", "When", 150), ("question", "Question", 220),
                                 ("result", "Result", 80), ("sql", "Query", 360)):
            self.tree.heading(cid, text=text, anchor="w")
            self.tree.column(cid, width=width, anchor="w", stretch=cid == "sql")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True, pady=(8, 0))
        scroll.pack(side="right", fill="y", pady=(8, 0))

        titles = {q.id: q.title for q in app.questions}
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
            "Resetting clears your saved attempts (the [done] marks and attempt history) "
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
        ttk.Button(buttons, text="Reset All Progress...",
                   command=lambda: self._reset(None)).pack(side="left", padx=4)
        self.bind("<Escape>", lambda _e: self.destroy())

    def _reset(self, question_id: str | None) -> None:
        if question_id is None and not messagebox.askyesno(
                "Reset all progress?", "Clear progress for every question?", parent=self):
            return
        try:
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
        self.title("Generate Questions")
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
                "Each question was checked against the practice data and has a working answer."))
        if n:
            self.tree.selection_set("0")
        else:
            self.detail.configure(text="")

    def _show_selected(self) -> None:
        sel = self.tree.selection()
        if sel:
            q = self.preview[int(sel[0])]
            order = "  (row order matters)" if q.order_matters else ""
            self.detail.configure(text=f"{q.prompt}{order}")

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
                               "(generated) in the question list. Remove them any time with "
                               "Questions > Delete All Generated Questions.")


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class SqlHelperApp:
    def __init__(self, root: tk.Tk, store: QuestionStore, db: PracticeDatabase) -> None:
        self.root = root
        self.store = store
        self.db = db
        self.questions: list[Question] = []
        self.current: Question | None = None
        self.drafts: dict[str | None, str] = {}   # unsaved editor text per question (memory only)
        self._live_job: str | None = None
        self.expected_revealed = False             # expected output stays hidden until asked for
        self._feedback_is_error = False            # lets a successful run clear an old error

        root.title("SQL Helper: Interview Practice")
        root.geometry("1280x780")
        root.minsize(1120, 640)

        self.live_var = tk.BooleanVar(value=True)
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

        # Top bar: question picker and progress.
        top = ttk.Frame(outer)
        top.pack(fill="x", pady=(0, 8))
        self.progress = ttk.Label(top)
        self.progress.pack(side="right")   # packed first so it keeps its space when narrow
        ttk.Label(top, text="Question:").pack(side="left")
        self.picker = ttk.Combobox(top, state="readonly", width=34)
        self.picker.pack(side="left", padx=6)
        self.picker.bind("<<ComboboxSelected>>", lambda _e: self._picked())
        ttk.Button(top, text="< Prev", command=lambda: self._step(-1)).pack(side="left")
        self.next_btn = ttk.Button(top, text="Next >", width=9, command=lambda: self._step(1))
        self.next_btn.pack(side="left", padx=4)
        ttk.Button(top, text="+ New Question", command=self.new_question).pack(side="left", padx=4)
        ttk.Button(top, text="Generate...",
                   command=lambda: GenerateDialog(self)).pack(side="left")
        ttk.Button(top, text="Reset...", command=lambda: ResetDialog(self)).pack(side="left", padx=4)

        panes = ttk.PanedWindow(outer, orient="horizontal")
        panes.pack(fill="both", expand=True)

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
        q_buttons = ttk.Frame(card)
        q_buttons.pack(anchor="w", pady=(8, 0))
        self.hint_btn = ttk.Button(q_buttons, text="Show Hint", command=self.show_hint)
        self.hint_btn.pack(side="left")
        self.solution_btn = ttk.Button(q_buttons, text="Reveal Solution", command=self.reveal_solution)
        self.solution_btn.pack(side="left", padx=6)
        self.card_expected_btn = ttk.Button(q_buttons, text="Show Expected Result",
                                            command=lambda: self.toggle_expected(select_tab=True))
        self.card_expected_btn.pack(side="left")

        ttk.Label(left, text="Your SQL").pack(anchor="w", pady=(10, 2))
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

        self.status = ttk.Label(outer, anchor="w")
        self.status.pack(fill="x", pady=(8, 0))

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
        self._refresh_picker()
        keep = select_id or (self.current.id if self.current else None)
        index = next((i for i, q in enumerate(self.questions) if q.id == keep), 0)
        self._select(index)

    def _refresh_picker(self) -> None:
        solved = self.store.solved_ids()
        labels = [FREE_PRACTICE]
        for q in self.questions:
            mark = "[done]" if q.id in solved else "[    ]"
            custom = "  (generated)" if q.generated else ("  (yours)" if q.is_custom else "")
            labels.append(f"{mark}  {q.difficulty:<6}  {q.title}{custom}")
        self.picker["values"] = labels
        done = sum(1 for q in self.questions if q.id in solved)
        self.progress.configure(text=f"Solved {done} / {len(self.questions)}")

    def _select(self, question_index: int | None) -> None:
        """question_index None means free practice."""
        self.drafts[self.current.id if self.current else None] = self.editor.get()
        self.current = None if question_index is None or not self.questions \
            else self.questions[question_index]
        self.picker.current(0 if self.current is None else question_index + 1)
        self._show_current()

    def _picked(self) -> None:
        idx = self.picker.current()
        self._select(None if idx <= 0 else idx - 1)

    def _step(self, delta: int) -> None:
        idx = (self.picker.current() + delta) % len(self.picker["values"])
        self._select(None if idx == 0 else idx - 1)

    def _show_current(self) -> None:
        q = self.current
        self._set_feedback("")
        state = "normal" if q else "disabled"
        for btn in (self.hint_btn, self.solution_btn, self.check_btn):
            btn.configure(state=state)
        if q is None:
            self.q_title.configure(text="Free practice")
            self.q_meta.configure(text="")
            self.q_prompt.configure(text="Write any SELECT query against the practice tables. "
                                         "Browse the Tables tab to see what data is available.")
        else:
            self.q_title.configure(text=q.title)
            order = " | row order matters" if q.order_matters else ""
            source = "generated" if q.generated else ("your question" if q.is_custom else "built-in")
            self.q_meta.configure(text=f"{q.difficulty} | {q.topic} | {source}{order}")
            self.q_prompt.configure(text=q.prompt)
        self.expected_revealed = False
        self._render_expected()
        self.next_btn.configure(default="normal", text="Next >")
        self.editor.set(self.drafts.get(q.id if q else None, ""))
        self.user_grid.clear("Start typing a query to see results here.")
        self.status.configure(text="")
        self.editor.text.focus_set()

    def toggle_expected(self, select_tab: bool = False) -> None:
        if self.current is None:
            return
        self.expected_revealed = not self.expected_revealed
        self._render_expected()
        if select_tab and self.expected_revealed:
            self.tabs.select(self.expected_tab)

    def _render_expected(self) -> None:
        q = self.current
        buttons = (self.expected_btn, self.card_expected_btn)
        if q is None:
            for b in buttons:
                b.configure(state="disabled", text="Show Expected Result")
            self.expected_grid.clear("No expected result in free practice.")
            return
        label = "Hide Expected Result" if self.expected_revealed else "Show Expected Result"
        for b in buttons:
            b.configure(state="normal", text=label)
        if not self.expected_revealed:
            self.expected_grid.clear("Hidden so you can try first. Press the button above to compare.")
            return
        expected = self.db.run(q.solution)
        if expected.ok:
            self.expected_grid.show(expected, "Target output: ")
        else:
            self.expected_grid.clear(f"This question's solution has an error: {expected.error}")

    def delete_generated(self) -> None:
        generated = [q for q in self.questions if q.generated]
        if not generated:
            messagebox.showinfo("Delete generated questions", "There are no generated questions.")
            return
        if not messagebox.askyesno(
                "Delete generated questions?",
                f"Delete all {len(generated)} generated questions? Their files are removed from "
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
            self.drafts.clear()
        else:
            self.drafts.pop(question_id, None)
        affected = question_id is None or (self.current and self.current.id == question_id)
        self._refresh_picker()
        self.picker.current(0 if self.current is None else self.questions.index(self.current) + 1)
        if affected:
            self.drafts[self.current.id if self.current else None] = ""
            self._show_current()
        where = (f" A backup of the old history was saved as history_backups/{backup.name} "
                 "in the data folder.") if backup else ""
        self._set_feedback(("All progress reset." if question_id is None
                            else "Progress for this question reset.") + where)

    def show_hint(self) -> None:
        if self.current:
            self._set_feedback(f"Hint: {self.current.hint or 'No hint for this question.'}")

    def reveal_solution(self) -> None:
        if self.current and messagebox.askyesno(
                "Reveal solution?", "Show one possible solution below the editor? "
                                    "Your own query is left untouched."):
            self._set_feedback(f"One possible solution:\n{self.current.solution}")

    def new_question(self, from_editor: bool = False) -> None:
        QuestionDialog(self, starter_sql=self.editor.get() if from_editor else "")

    def edit_question(self) -> None:
        if not self.current or not self.current.is_custom:
            messagebox.showinfo("Edit question", "Only questions you created can be edited. "
                                "Use 'New Question from Current Query' to build on a built-in one.")
            return
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
        index = next((i for i, q in enumerate(self.questions) if q.id == question_id), None)
        self._select(index)
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

    def _on_correct(self, q: Question, outcome) -> None:
        """Mark the question solved, show the answer, and point the user at Next."""
        if not self.expected_revealed:
            self.expected_revealed = True   # nothing left to give away
            self._render_expected()
        text = outcome.message
        if outcome.details:
            text += "\n" + "\n".join(f"- {d}" for d in outcome.details)
        self._set_feedback(text + "\nPress Next > for the next question.", GOOD)
        self._record(q, correct=True)
        self.next_btn.configure(default="active")   # macOS draws this as the blue default button
        self.next_btn.configure(text="Next >  \u2713")

    def _record(self, q: Question, correct: bool) -> None:
        try:
            self.store.record_attempt(q.id, self.editor.get(), correct)
        except OSError as exc:
            self.status.configure(foreground=BAD, text=f"Couldn't save history: {exc}")
        self._refresh_picker()
        self.picker.current(self.questions.index(q) + 1)

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
