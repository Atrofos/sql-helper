"""Python mode UI: result tabs, the step-through visualiser, and the question dialog.

``PythonPanel`` is the right-hand side of the window in Python mode. The main
window (app.py) owns the question, editor and feedback, and calls into this
panel to run code. Code runs in a worker thread (each run is a separate Python
process, see python_runner), so the window never freezes. Results come back to
the Tk thread through a queue that's polled with ``after()``, because Tk
widgets may only be touched from the main thread.
"""

from __future__ import annotations

import ast
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Callable

from .lesson_view import LessonView, ScrollCanvas, mono
from .python_grader import grade_function, grade_output, hint_for
from .python_runner import LIVE_TIMEOUT_S, RunResult, run_function, run_script
from .questions import DIFFICULTIES, KIND_FUNCTION, KIND_OUTPUT, MODE_PYTHON, Question

if TYPE_CHECKING:
    from .app import SqlHelperApp

GOOD = "#1a7f37"
BAD = "#cf222e"
POLL_MS = 40


class Worker:
    """Runs functions off the Tk thread; delivers only the newest result per channel."""

    def __init__(self, root: tk.Misc) -> None:
        self.root = root
        self.results: queue.Queue = queue.Queue()
        self.latest: dict[str, int] = {}
        self.counter = 0
        self.pending = 0          # jobs submitted whose results haven't been collected yet
        self.polling = False

    def submit(self, channel: str, job: Callable[[], object], done: Callable[[object], None]) -> None:
        self.counter += 1
        ticket = self.counter
        self.latest[channel] = ticket
        self.pending += 1

        def run() -> None:
            try:
                value = job()
            except Exception as exc:  # report, never kill the worker silently
                value = RunResult(ok=False, error=f"Internal error: {exc}")
            self.results.put((channel, ticket, value, done))

        threading.Thread(target=run, daemon=True).start()
        if not self.polling:
            self.polling = True
            self.root.after(POLL_MS, self._poll)

    def _poll(self) -> None:
        while True:
            try:
                channel, ticket, value, done = self.results.get_nowait()
            except queue.Empty:
                break
            self.pending -= 1
            if self.latest.get(channel) == ticket:   # ignore results superseded by newer runs
                done(value)
        if self.pending > 0:
            self.root.after(POLL_MS, self._poll)
        else:
            self.polling = False


def readonly_text(master, height: int = 8) -> tk.Text:
    text = tk.Text(master, height=height, font=mono(12), wrap="word", borderwidth=0,
                   relief="flat", highlightthickness=1, highlightbackground="#8c959f",
                   padx=10, pady=6, state="disabled")
    return text


def set_text(widget: tk.Text, content: str) -> None:
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", content)
    widget.configure(state="disabled")


class VisualiserView(ttk.Frame):
    """Step through code line by line, showing the current line and every variable."""

    def __init__(self, master, panel: "PythonPanel") -> None:
        super().__init__(master, padding=(6, 6))
        self.panel = panel
        self.steps: list[dict] = []
        self.code_lines: list[str] = []
        self.index = 0

        bar = ttk.Frame(self)
        bar.pack(fill="x")
        self.call_label = ttk.Label(bar, text="Test call:")
        self.call_label.pack(side="left")
        self.call_picker = ttk.Combobox(bar, state="readonly", width=28)
        self.call_picker.pack(side="left", padx=(4, 8))
        self.go_btn = ttk.Button(bar, text="Visualise my code", command=self.start)
        self.go_btn.pack(side="left")

        nav = ttk.Frame(self)
        nav.pack(fill="x", pady=(8, 4))
        ttk.Button(nav, text="< Step", width=7, command=lambda: self.move(-1)).pack(side="left")
        ttk.Button(nav, text="Step >", width=7, command=lambda: self.move(1)).pack(side="left", padx=4)
        self.scale = ttk.Scale(nav, from_=0, to=0, orient="horizontal", command=self._scaled)
        self.scale.pack(side="left", fill="x", expand=True, padx=8)
        self.step_label = ttk.Label(nav, text="")
        self.step_label.pack(side="left")

        self.explain = ttk.Label(self, text="Press 'Visualise my code' to step through it.",
                                 wraplength=520, justify="left")
        self.explain.pack(fill="x", pady=(0, 6))

        panes = ttk.PanedWindow(self, orient="vertical")
        panes.pack(fill="both", expand=True)
        self.code = tk.Text(panes, height=8, font=mono(12), wrap="none", borderwidth=0,
                            relief="flat", highlightthickness=1, highlightbackground="#8c959f",
                            padx=8, pady=4, state="disabled")
        # Explicit foreground + background keep the highlight readable in light and dark mode.
        self.code.tag_configure("current", background="#ffe58f", foreground="#1f2328")
        self.code.tag_configure("lineno", foreground="#8c959f")
        panes.add(self.code, weight=2)
        self.vars = ScrollCanvas(panes, height=180)
        panes.add(self.vars, weight=3)
        out_frame = ttk.Frame(panes)
        ttk.Label(out_frame, text="Printed so far").pack(anchor="w")
        self.output = readonly_text(out_frame, height=3)
        self.output.pack(fill="both", expand=True)
        panes.add(out_frame, weight=1)
        self.bind("<Configure>", lambda e: self.explain.configure(wraplength=max(e.width - 20, 240)))

    # ---- setup -------------------------------------------------------------
    def configure_for(self, question: Question | None) -> None:
        self.steps = []
        self._render_empty("Press 'Visualise my code' to step through it.")
        if question and question.kind == KIND_FUNCTION:
            fn = question.function_name
            self.call_picker["values"] = [f"{fn}({_args_text(a)})" for a in question.tests]
            self.call_picker.current(0)
            self.call_picker.configure(state="readonly")
            self.call_label.configure(text="Test call:")
        else:
            self.call_picker.set("")
            self.call_picker["values"] = []
            self.call_picker.configure(state="disabled")
            self.call_label.configure(text="Runs the whole code:")

    def _render_empty(self, message: str) -> None:
        self.explain.configure(text=message)
        self.step_label.configure(text="")
        self.scale.configure(to=0)
        set_text(self.code, "")
        set_text(self.output, "")
        self.vars.start()
        self.vars.finish()

    def start(self) -> None:
        q = self.panel.app.current
        code = self.panel.code_to_visualise()
        if code is None:
            return
        self.code_lines = code.split("\n")
        self.explain.configure(text="Running your code...")
        if q is not None and q.kind == KIND_FUNCTION:
            idx = max(self.call_picker.current(), 0)
            job = lambda: run_function(code, q.function_name, q.tests[idx: idx + 1], trace_call=0)  # noqa: E731
        else:
            job = lambda: run_script(code, trace=True)  # noqa: E731
        self.panel.worker.submit("visualise", job, self._show_trace)

    def _show_trace(self, result: RunResult) -> None:
        self.steps = result.steps
        if not self.steps:
            msg = result.error or "Nothing to step through (no lines of your code ran)."
            hint = hint_for(result.error)
            self._render_empty(msg + (f"\nHint: {hint}" if hint else ""))
            return
        self.scale.configure(to=len(self.steps) - 1)
        self.index = 0
        if result.trace_truncated:
            self.steps.append({"line": self.steps[-1]["line"], "event": "truncated",
                               "vars": self.steps[-1]["vars"], "out": self.steps[-1]["out"],
                               "depth": 0, "func": ""})
            self.scale.configure(to=len(self.steps) - 1)
        self._render()

    # ---- navigation -----------------------------------------------------------
    def move(self, delta: int) -> None:
        if self.steps:
            self.index = max(0, min(len(self.steps) - 1, self.index + delta))
            self._render()

    def _scaled(self, value: str) -> None:
        if self.steps:
            new = int(float(value) + 0.5)
            if new != self.index:
                self.index = new
                self._render()

    def _render(self) -> None:
        step = self.steps[self.index]
        prev = self.steps[self.index - 1] if self.index > 0 else {"vars": {}}
        self.scale.set(self.index)
        self.step_label.configure(text=f"Step {self.index + 1} of {len(self.steps)}")
        self.explain.configure(text=_describe(step, self.code_lines))

        self.code.configure(state="normal")
        self.code.delete("1.0", "end")
        width = len(str(len(self.code_lines)))
        for n, line in enumerate(self.code_lines, start=1):
            self.code.insert("end", f"{n:>{width}}  ", "lineno")
            self.code.insert("end", line + "\n", "current" if n == step["line"] else ())
        self.code.configure(state="disabled")
        self.code.see(f"{step['line']}.0")

        painter = self.vars.start()
        y = 10
        variables = step["vars"]
        if not variables:
            painter.text(12, y, "(no variables yet)", fill=painter.p["muted"])
        for name, snap in variables.items():
            changed = prev["vars"].get(name) != snap
            y += painter.value(12, y, name, snap, changed) + 6
        if step.get("ret") is not None:
            painter.text(12, y + 6, "returns:", font=mono(12, "bold"), fill=painter.p["link"])
            painter.value(12, y + 18, "  ", step["ret"], True)
        self.vars.finish()
        set_text(self.output, step.get("out", ""))


def _args_text(args: list) -> str:
    return ", ".join(repr(a) for a in args)


def _describe(step: dict, lines: list[str]) -> str:
    n = step["line"]
    src = lines[n - 1].strip() if 0 < n <= len(lines) else ""
    event = step["event"]
    if event == "call":
        if step["func"] == "<module>":
            return "The program starts. Variables changed since the last step are highlighted."
        params = ", ".join(f"{k}={v.get('repr', '[...]')}" for k, v in step["vars"].items())
        return f"Calling {step['func']}({params}). The parameters get the values passed in."
    if event == "return":
        if step["func"] == "<module>":
            return "The program has finished."
        ret = step.get("ret") or {}
        value = ret.get("repr") or "[...]"
        return f"{step['func']} returns {value} to whoever called it."
    if event == "exception":
        return f"An error happened on line {n}: {src}"
    if event == "truncated":
        return "Stopped recording here: the code ran for too many steps (is a loop running forever?)."
    return f"About to run line {n}:  {src}"


class PythonPanel(ttk.Frame):
    """Right-hand side of the window in Python mode."""

    def __init__(self, master, app: "SqlHelperApp") -> None:
        super().__init__(master)
        self.app = app
        self.worker = Worker(app.root)
        self.expected_cache: dict[str, RunResult] = {}
        self.last_user: RunResult | None = None

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True)

        # Output tab
        out = ttk.Frame(self.tabs, padding=(6, 6))
        self.out_caption = ttk.Label(out, text="Anything your code prints, and any errors, appear here.",
                                     wraplength=520, justify="left")
        self.out_caption.pack(anchor="w")
        self.output = readonly_text(out, height=12)
        self.output.tag_configure("error", foreground=BAD)
        self.output.tag_configure("muted", foreground="#8c959f")
        self.output.pack(fill="both", expand=True, pady=(4, 0))
        self.tabs.add(out, text="Output")

        # Test results tab
        tests = ttk.Frame(self.tabs, padding=(6, 6))
        self.tests_caption = ttk.Label(tests, text="", wraplength=520, justify="left")
        self.tests_caption.pack(anchor="w")
        self.tests_tree = ttk.Treeview(tests, show="headings", selectmode="browse")
        self.tests_tree.pack(fill="both", expand=True, pady=(4, 0))
        self.tabs.add(tests, text="Test Results")
        self.tests_tab = tests

        # Expected tab
        exp = ttk.Frame(self.tabs, padding=(6, 6))
        bar = ttk.Frame(exp)
        bar.pack(fill="x")
        self.expected_btn = ttk.Button(bar, text="Show Expected Result", command=app.toggle_expected)
        self.expected_btn.pack(side="left")
        self.expected_caption = ttk.Label(exp, text="", wraplength=520, justify="left")
        self.expected_caption.pack(anchor="w", pady=(6, 0))
        self.expected_tree = ttk.Treeview(exp, show="headings", columns=("call", "expected"), height=6)
        for cid, text, w in (("call", "Call", 260), ("expected", "Expected result", 240)):
            self.expected_tree.heading(cid, text=text, anchor="w")
            self.expected_tree.column(cid, width=w, anchor="w")
        self.expected_text = readonly_text(exp, height=8)
        self.tabs.add(exp, text="Expected")
        self.expected_tab = exp

        # Visualise + Lesson tabs
        self.visualiser = VisualiserView(self.tabs, self)
        self.tabs.add(self.visualiser, text="Visualise")
        self.lesson_view = LessonView(self.tabs)
        self.tabs.add(self.lesson_view, text="Lesson")
        self.bind("<Configure>", self._wrap)

    def _wrap(self, event) -> None:
        for label in (self.out_caption, self.tests_caption, self.expected_caption):
            label.configure(wraplength=max(event.width - 40, 240))

    # ---- question display ---------------------------------------------------
    def show_question(self, q: Question | None) -> None:
        self.last_user = None
        self.visualiser.configure_for(q)
        set_text(self.output, "")
        self._setup_tests_tree(q, checked=False)
        if q is None:
            self.out_caption.configure(text="Free practice: write any Python and press Run. "
                                            "print() output appears here.")
            self.tests_caption.configure(text="No tests in free practice.")
        elif q.kind == KIND_OUTPUT:
            self.out_caption.configure(text="Type what you think the code prints in the editor, "
                                            "then press Run to check.")
            self.tests_caption.configure(text="Predict-the-output questions have no tests: "
                                              "your typed answer is compared with the real output.")
        else:
            self.out_caption.configure(text="Anything your code prints, and any errors, appear here.")
            self.tests_caption.configure(text="Your function is called with each test input. "
                                              "Your results update as you type.")
            for args in q.tests:
                self.tests_tree.insert("", "end", values=(f"{q.function_name}({_args_text(args)})", "", ""))

    def _setup_tests_tree(self, q: Question | None, checked: bool) -> None:
        tree = self.tests_tree
        tree.delete(*tree.get_children())
        cols = ["call", "yours", "printed"]
        if checked:
            cols.insert(0, "pass")
            if self.app.expected_revealed:
                cols.insert(3, "expected")
        tree["columns"] = cols
        headings = {"pass": ("", 34), "call": ("Call", 200), "yours": ("Your result", 170),
                    "expected": ("Expected", 150), "printed": ("Printed", 140)}
        for c in cols:
            text, w = headings[c]
            tree.heading(c, text=text, anchor="w")
            tree.column(c, width=w, anchor="w", stretch=c in ("call", "yours"))

    def render_expected(self, q: Question | None, revealed: bool) -> None:
        label = "Hide Expected Result" if revealed else "Show Expected Result"
        self.expected_btn.configure(text=label, state="normal" if q else "disabled")
        self.expected_tree.pack_forget()
        self.expected_text.pack_forget()
        if q is None:
            self.expected_caption.configure(text="No expected result in free practice.")
            return
        if not revealed:
            self.expected_caption.configure(text="Hidden so you can try first. Press the button "
                                                 "above to compare.")
            return
        self.expected_caption.configure(text="Working it out...")
        self.worker.submit("expected", lambda: self.expected_for(q),
                           lambda res: self._fill_expected(q, res))

    def _fill_expected(self, q: Question, expected: RunResult) -> None:
        if not expected.ok:
            self.expected_caption.configure(text=f"The reference solution has an error: {expected.error}")
            return
        if q.kind == KIND_OUTPUT:
            self.expected_caption.configure(text="This is exactly what the code prints:")
            set_text(self.expected_text, expected.module_out)
            self.expected_text.pack(fill="both", expand=True, pady=(4, 0))
            return
        self.expected_caption.configure(text="What the function should return for each test:")
        self.expected_tree.delete(*self.expected_tree.get_children())
        for call in expected.calls:
            self.expected_tree.insert("", "end", values=(f"{q.function_name}({call.args})", call.value))
        self.expected_tree.pack(fill="both", expand=True, pady=(4, 0))

    # ---- running --------------------------------------------------------------
    def expected_for(self, q: Question) -> RunResult:
        """Reference result for a question (cached; questions don't change while open)."""
        key = f"{q.id}:{hash(q.solution)}:{hash(str(q.tests))}"
        if key not in self.expected_cache:
            if q.kind == KIND_FUNCTION:
                self.expected_cache[key] = run_function(q.solution, q.function_name, q.tests)
            else:
                self.expected_cache[key] = run_script(q.solution)
        return self.expected_cache[key]

    def code_to_visualise(self) -> str | None:
        q = self.app.current
        if q is not None and q.kind == KIND_OUTPUT:
            if not (self.app.expected_revealed or self.app.store_solved(q)):
                self.visualiser._render_empty(
                    "Stepping through this code would show its output, so it unlocks once you've "
                    "answered correctly or pressed Show Expected Result.")
                return None
            return q.solution
        code = self.app.editor.get()
        if not code.strip():
            self.visualiser._render_empty("Write some code first.")
            return None
        return code

    def live(self) -> None:
        q = self.app.current
        code = self.app.editor.get()
        if q is not None and q.kind == KIND_OUTPUT:
            return   # the editor holds a typed prediction, not code
        if not code.strip():
            set_text(self.output, "")
            return
        if q is None:
            job = lambda: run_script(code, timeout=LIVE_TIMEOUT_S)  # noqa: E731
        else:
            job = lambda: run_function(code, q.function_name, q.tests, timeout=LIVE_TIMEOUT_S)  # noqa: E731
        self.worker.submit("run", job, lambda res: self._show_run(q, res, None, live=True))

    def run(self, check: bool) -> None:
        """Run (and grade) the editor contents for the current question."""
        q = self.app.current
        code = self.app.editor.get()
        if q is None:
            self.worker.submit("run", lambda: run_script(code),
                               lambda res: self._show_run(None, res, None, live=False))
            return
        if q.kind == KIND_OUTPUT:
            self.worker.submit("run", lambda: self.expected_for(q),
                               lambda exp: self._grade_output(q, code, exp, check))
            return
        if not code.strip():
            self.app._set_feedback("Write some code first.", BAD)
            return

        def job():
            return run_function(code, q.function_name, q.tests), self.expected_for(q)

        self.worker.submit("run", job, lambda pair: self._finish_function(q, pair, check))

    def _finish_function(self, q: Question, pair, check: bool) -> None:
        if isinstance(pair, RunResult):          # the worker reported an internal error
            self.app._set_feedback(pair.error or "Something went wrong.", BAD, is_error=True)
            return
        user, expected = pair
        outcome = grade_function(user, expected, q.function_name,
                                 show_examples=self.app.expected_revealed)
        self._show_run(q, user, expected if check or outcome.correct else None, live=False)
        self.app.python_graded(q, outcome, check, user_ok=user.ok)

    def _grade_output(self, q: Question, answer: str, expected: RunResult, check: bool) -> None:
        if isinstance(expected, RunResult) and expected.error and expected.error.startswith("Internal"):
            self.app._set_feedback(expected.error, BAD, is_error=True)
            return
        outcome = grade_output(answer, expected, show_examples=self.app.expected_revealed)
        if outcome.correct:
            set_text(self.output, expected.module_out)
            self.out_caption.configure(text="Correct! This is what the code prints:")
        self.app.python_graded(q, outcome, check, user_ok=True)

    def _show_run(self, q: Question | None, user: RunResult, expected: RunResult | None,
                  live: bool) -> None:
        self.last_user = user
        out = self.output
        out.configure(state="normal")
        out.delete("1.0", "end")
        if user.module_out:
            out.insert("end", user.module_out)
        for call in user.calls:
            if call.out:
                out.insert("end", f"--- printed during {q.function_name if q else ''}({call.args}) ---\n",
                           "muted")
                out.insert("end", call.out)
        if user.error:
            out.insert("end", ("\n" if out.get("1.0", "end-1c") else "") + user.error + "\n", "error")
            hint = hint_for(user.error)
            if hint:
                out.insert("end", f"Hint: {hint}\n", "muted")
        if not out.get("1.0", "end-1c").strip():
            out.insert("end", "(nothing printed)", "muted")
        out.configure(state="disabled")

        if q is None or q.kind != KIND_FUNCTION:
            if user.error:
                self.tabs.select(0)
            return
        checked = expected is not None
        self._setup_tests_tree(q, checked)
        expected_calls = expected.calls if expected else []
        passed = 0
        for i, args in enumerate(q.tests):
            call_text = f"{q.function_name}({_args_text(args)})"
            mine = user.calls[i] if i < len(user.calls) else None
            yours = "" if mine is None else (mine.value if mine.ok else f"error: {mine.error}")
            printed = "" if mine is None else mine.out.strip().replace("\n", " | ")
            row = {"call": call_text, "yours": yours, "printed": printed}
            if checked:
                theirs = expected_calls[i] if i < len(expected_calls) else None
                ok = bool(mine and mine.ok and theirs and mine.canon == theirs.canon)
                passed += ok
                row["pass"] = "✓" if ok else "✗"
                if self.app.expected_revealed:
                    row["expected"] = theirs.value if theirs else ""
            self.tests_tree.insert("", "end", values=[row[c] for c in self.tests_tree["columns"]])
        if not user.ok:
            self.tests_caption.configure(text="Your code has an error, so the tests couldn't run. "
                                              "See the Output tab.")
            self.tabs.select(0)
        elif checked:
            self.tests_caption.configure(text=f"{passed} of {len(q.tests)} tests passed.")
            self.tabs.select(self.tests_tab)
        else:
            self.tests_caption.configure(text=("Live: " if live else "") +
                                         "your function's results for each test input. "
                                         "Press Check Answer to see which are right.")
            if not live:
                self.tabs.select(self.tests_tab)


class PythonQuestionDialog(tk.Toplevel):
    """Create or edit a custom Python question (either style)."""

    def __init__(self, app: "SqlHelperApp", question: Question | None = None,
                 starter_code: str = "") -> None:
        super().__init__(app.root)
        self.app = app
        self.editing = question
        self.title("Edit Python Question" if question else "New Python Question")
        self.transient(app.root)
        self.geometry("640x720")
        self.minsize(560, 600)

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        q = question
        self.title_var = tk.StringVar(value=q.title if q else "")
        self.topic_var = tk.StringVar(value=q.topic if q else "Functions")
        self.diff_var = tk.StringVar(value=q.difficulty if q else "Easy")
        self.kind_var = tk.StringVar(value=q.kind if q else KIND_FUNCTION)
        self.fn_var = tk.StringVar(value=q.function_name if q else "")
        self.hint_var = tk.StringVar(value=q.hint if q else "")

        row = 0
        kinds = ttk.Frame(body)
        ttk.Radiobutton(kinds, text="Write a function", value=KIND_FUNCTION, variable=self.kind_var,
                        command=self._kind_changed).pack(side="left")
        ttk.Radiobutton(kinds, text="Predict the output", value=KIND_OUTPUT, variable=self.kind_var,
                        command=self._kind_changed).pack(side="left", padx=12)
        for label, widget in (
            ("Style", kinds),
            ("Title", ttk.Entry(body, textvariable=self.title_var)),
            ("Topic", ttk.Entry(body, textvariable=self.topic_var)),
            ("Difficulty", ttk.Combobox(body, textvariable=self.diff_var, values=DIFFICULTIES,
                                        state="readonly", width=10)),
        ):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=3)
            widget.grid(row=row, column=1, sticky="w" if label in ("Difficulty", "Style") else "ew", pady=3)
            row += 1

        ttk.Label(body, text="Question").grid(row=row, column=0, sticky="nw", pady=3)
        self.prompt_text = tk.Text(body, height=3, wrap="word", padx=6, pady=6)
        self.prompt_text.grid(row=row, column=1, sticky="ew", pady=3)
        self.prompt_text.insert("1.0", q.prompt if q else "")
        row += 1

        self.fn_label = ttk.Label(body, text="Function name")
        self.fn_label.grid(row=row, column=0, sticky="w", pady=3)
        self.fn_entry = ttk.Entry(body, textvariable=self.fn_var, width=24)
        self.fn_entry.grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        self.solution_label = ttk.Label(body, text="Reference solution")
        self.solution_label.grid(row=row, column=0, sticky="nw", pady=3)
        self.solution_text = tk.Text(body, height=8, wrap="none", font=mono(12), padx=6, pady=6)
        self.solution_text.grid(row=row, column=1, sticky="nsew", pady=3)
        self.solution_text.insert("1.0", q.solution if q else starter_code)
        body.rowconfigure(row, weight=1)
        row += 1

        self.tests_label = ttk.Label(body, text="Test inputs\n(one call per line)")
        self.tests_label.grid(row=row, column=0, sticky="nw", pady=3)
        self.tests_text = tk.Text(body, height=5, wrap="none", font=mono(12), padx=6, pady=6)
        self.tests_text.grid(row=row, column=1, sticky="nsew", pady=3)
        if q and q.tests:
            self.tests_text.insert("1.0", "\n".join(_args_text(a) for a in q.tests))
        row += 1
        self.tests_help = ttk.Label(body, wraplength=440, justify="left", text=(
            "Write each test's arguments as you would inside the brackets of a call, e.g. "
            "'hello', 3  or  [1, 2, 3]. The expected answers come from running your reference "
            "solution."))
        self.tests_help.grid(row=row, column=1, sticky="w")
        row += 1

        ttk.Label(body, text="Hint (optional)").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(body, textvariable=self.hint_var).grid(row=row, column=1, sticky="ew", pady=3)
        row += 1

        self.status = ttk.Label(body, text="Press Test Solution to check it runs.", wraplength=520)
        self.status.grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 4))
        row += 1
        buttons = ttk.Frame(body)
        buttons.grid(row=row, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(buttons, text="Test Solution", command=self._test).pack(side="left", padx=4)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="left", padx=4)
        ttk.Button(buttons, text="Save", command=self._save).pack(side="left", padx=4)
        self.bind("<Escape>", lambda _e: self.destroy())
        self._kind_changed()

    def _kind_changed(self) -> None:
        function = self.kind_var.get() == KIND_FUNCTION
        state = "normal" if function else "disabled"
        self.fn_entry.configure(state=state)
        self.tests_text.configure(state=state)
        self.solution_label.configure(text="Reference solution" if function else "Code to predict")

    def _parse_tests(self) -> list[list]:
        tests = []
        for n, line in enumerate(self.tests_text.get("1.0", "end-1c").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = ast.literal_eval(f"({line},)")
            except (ValueError, SyntaxError) as exc:
                raise ValueError(f"Test line {n} isn't valid Python values: {line!r}") from exc
            tests.append(list(value))
        return tests

    def _build(self) -> Question | None:
        title = self.title_var.get().strip()
        prompt = self.prompt_text.get("1.0", "end-1c").strip()
        solution = self.solution_text.get("1.0", "end-1c").rstrip() + "\n"
        kind = self.kind_var.get()
        fn = self.fn_var.get().strip()
        if not title or not prompt or not solution.strip():
            self.status.configure(foreground=BAD, text="Title, question and code are required.")
            return None
        tests: list = []
        if kind == KIND_FUNCTION:
            if not fn.isidentifier():
                self.status.configure(foreground=BAD, text="Enter a valid function name, e.g. count_words.")
                return None
            try:
                tests = self._parse_tests()
            except ValueError as exc:
                self.status.configure(foreground=BAD, text=str(exc))
                return None
            if not tests:
                self.status.configure(foreground=BAD, text="Add at least one test input.")
                return None
        q = self.editing
        return Question(
            id=q.id if q else self.app.store.new_id(title), title=title, prompt=prompt,
            solution=solution, difficulty=self.diff_var.get(),
            topic=self.topic_var.get().strip() or "General", hint=self.hint_var.get().strip(),
            mode=MODE_PYTHON, kind=kind, function_name=fn if kind == KIND_FUNCTION else "",
            starter=_outline(solution, fn) if kind == KIND_FUNCTION else "", tests=tests,
            generated=bool(q and q.generated),
        )

    def _test(self) -> bool:
        q = self._build()
        if q is None:
            return False
        if q.kind == KIND_FUNCTION:
            res = run_function(q.solution, q.function_name, q.tests)
            bad = next((c for c in res.calls if not c.ok), None)
            if not res.ok or bad or len(res.calls) != len(q.tests):
                self.status.configure(foreground=BAD, text=f"Solution error: {res.error or bad.error}")
                return False
            preview = "; ".join(f"{q.function_name}({c.args}) -> {c.value}" for c in res.calls[:3])
            self.status.configure(foreground=GOOD, text=f"Works. {preview}")
            return True
        res = run_script(q.solution)
        if not res.ok or not res.module_out.strip():
            self.status.configure(foreground=BAD, text=res.error or "The code must print something.")
            return False
        self.status.configure(foreground=GOOD, text=f"Works. It prints: {res.module_out.strip()[:120]}")
        return True

    def _save(self) -> None:
        if not self._test():
            return
        q = self._build()
        try:
            self.app.store.save_custom(q)
        except OSError as exc:
            messagebox.showerror("Could not save", str(exc), parent=self)
            return
        self.destroy()
        self.app.reload_questions(select_id=q.id)


def _outline(solution: str, fn: str) -> str:
    """Editor starter: everything before the function, then its signature and `pass`."""
    marker = f"def {fn}("
    if marker not in solution:
        return f"def {fn}():\n    pass\n"
    head, rest = solution.split(marker, 1)
    params = rest.split(")", 1)[0]
    return f"{head}{marker}{params}):\n    pass\n"
