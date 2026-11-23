"""Progress report: where the learner went wrong on a set of questions.

History only stores each attempt's answer and whether it was correct, not why
it was wrong. So the report re-grades the most recent wrong answer for each
question with the same graders the app uses, which gives the same feedback the
learner saw (or would have seen with Check Answer).

Hints and correct answers stay out of the report unless ``include_answers`` is True,
in line with the app's rule that expected results stay hidden until asked for.

``build_report`` returns plain data; ``to_html`` turns it into a standalone page
that follows the system's light/dark mode. All learner text is escaped.
"""

from __future__ import annotations

import html
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from .database import PracticeDatabase
from .grader import grade
from .lessons import lesson_for
from .python_grader import grade_function, grade_output
from .python_runner import run_function, run_script
from .questions import DIFFICULTIES, KIND_FUNCTION, KIND_OUTPUT, MODE_PYTHON, Question

STATUS_SOLVED, STATUS_STRUGGLING, STATUS_UNTRIED = "Solved", "Not solved yet", "Not tried"


@dataclass
class QuestionReport:
    question: Question
    attempts: int
    wrong: int
    solved: bool
    first_try: bool                       # solved on the very first attempt
    last_wrong_answer: str | None = None
    problem: str | None = None            # what was wrong with that answer
    problem_details: list[str] = field(default_factory=list)
    lesson_title: str = ""

    @property
    def status(self) -> str:
        if self.solved:
            return STATUS_SOLVED
        return STATUS_STRUGGLING if self.attempts else STATUS_UNTRIED


@dataclass
class TopicStat:
    topic: str
    questions: int
    solved: int
    wrong_attempts: int
    lesson_title: str


@dataclass
class Report:
    title: str
    mode: str
    created: str
    include_answers: bool
    items: list[QuestionReport]
    topics: list[TopicStat]

    @property
    def solved(self) -> int:
        return sum(1 for i in self.items if i.solved)

    @property
    def attempted(self) -> int:
        return sum(1 for i in self.items if i.attempts)

    @property
    def total_attempts(self) -> int:
        return sum(i.attempts for i in self.items)

    @property
    def first_try_rate(self) -> float | None:
        solved = [i for i in self.items if i.solved]
        return (sum(i.first_try for i in solved) / len(solved)) if solved else None

    def summary_lines(self) -> list[str]:
        """Short plain-text summary for the in-app preview."""
        lines = [f"{len(self.items)} questions: {self.solved} solved, "
                 f"{self.attempted - self.solved} not solved yet, "
                 f"{len(self.items) - self.attempted} not tried.",
                 f"{self.total_attempts} checked attempts in total."]
        if self.first_try_rate is not None:
            lines.append(f"Solved on the first try: {self.first_try_rate:.0%} of solved questions.")
        weak = [t for t in self.topics if t.wrong_attempts][:3]
        if weak:
            lines.append("Topics to review: " + ", ".join(
                f"{t.topic} ({t.wrong_attempts} wrong)" for t in weak) + ".")
        return lines


def _regrade(q: Question, answer: str, db: PracticeDatabase, show_examples: bool):
    """Grade an old answer again to recover what was wrong with it."""
    if q.mode == MODE_PYTHON:
        if q.kind == KIND_OUTPUT:
            return grade_output(answer, run_script(q.solution), show_examples)
        return grade_function(run_function(answer, q.function_name, q.tests),
                              run_function(q.solution, q.function_name, q.tests),
                              q.function_name, show_examples)
    return grade(db.run(answer), db.run(q.solution), q.order_matters, show_examples)


def build_report(questions: list[Question], history: list[dict], db: PracticeDatabase,
                 title: str, mode: str, include_answers: bool = False) -> Report:
    by_question: dict[str, list[dict]] = defaultdict(list)
    for entry in history:                      # history is in time order (append-only file)
        by_question[entry.get("question_id")].append(entry)

    items = []
    for q in questions:
        entries = by_question.get(q.id, [])
        solved_at = next((n for n, e in enumerate(entries) if e.get("correct")), None)
        wrong_entries = [e for e in entries if not e.get("correct")]
        item = QuestionReport(
            question=q, attempts=len(entries), wrong=len(wrong_entries),
            solved=solved_at is not None, first_try=solved_at == 0,
            lesson_title=lesson_for(q, q.mode).title,
        )
        if wrong_entries:
            answer = str(wrong_entries[-1].get("sql", ""))
            item.last_wrong_answer = answer
            try:
                outcome = _regrade(q, answer, db, show_examples=include_answers)
                item.problem, item.problem_details = outcome.message, list(outcome.details)
            except Exception as exc:   # a report should never crash on one odd answer
                item.problem = f"Couldn't re-check this answer ({exc})."
        items.append(item)

    rank = {level: n for n, level in enumerate(DIFFICULTIES)}
    items.sort(key=lambda i: (i.solved, -i.wrong, rank.get(i.question.difficulty, 9)))

    grouped: dict[str, list[QuestionReport]] = defaultdict(list)
    for item in items:
        grouped[item.question.topic].append(item)
    topics = sorted(
        (TopicStat(topic, len(group), sum(i.solved for i in group), sum(i.wrong for i in group),
                   group[0].lesson_title) for topic, group in grouped.items()),
        key=lambda t: (-t.wrong_attempts, t.solved - t.questions, t.topic))
    return Report(title=title, mode=mode, created=datetime.now().strftime("%d %B %Y, %H:%M"),
                  include_answers=include_answers, items=items, topics=topics)


# ---------------------------------------------------------------------------
# HTML output
# ---------------------------------------------------------------------------
CSS = """
:root { --bg:#ffffff; --fg:#1f2328; --muted:#656d76; --card:#f6f8fa; --line:#d0d7de;
        --good:#1a7f37; --bad:#cf222e; --warn:#9a6700; --code:#f0f3f6; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#0d1117; --fg:#e6edf3; --muted:#8d96a0; --card:#161b22; --line:#30363d;
          --good:#3fb950; --bad:#f85149; --warn:#d29922; --code:#1c2128; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
       font:15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
main { max-width: 920px; margin: 0 auto; padding: 32px 20px 60px; }
h1 { font-size: 26px; margin: 0 0 4px; } h2 { font-size: 19px; margin: 36px 0 12px; }
.muted { color: var(--muted); }
.stats { display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap:12px; margin-top:20px; }
.stat { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px; }
.stat b { display:block; font-size:24px; }
table { width:100%; border-collapse: collapse; }
th, td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); vertical-align: top; }
th { color:var(--muted); font-weight:600; font-size:13px; }
.q { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px 18px; margin:12px 0; }
.q h3 { margin:0 0 4px; font-size:17px; }
.pill { display:inline-block; font-size:12px; padding:1px 8px; border-radius:999px;
        border:1px solid var(--line); margin-right:6px; }
.Solved { color:var(--good); border-color:var(--good); }
.struggling { color:var(--bad); border-color:var(--bad); }
.untried { color:var(--muted); }
pre { background:var(--code); border:1px solid var(--line); border-radius:8px; padding:10px 12px;
      overflow-x:auto; font:13px/1.45 Menlo, Consolas, monospace; white-space: pre-wrap; }
.problem { color:var(--bad); font-weight:600; margin: 10px 0 4px; }
ul { margin: 4px 0 0 20px; padding: 0; }
.bar { height:8px; background:var(--line); border-radius:4px; overflow:hidden; min-width:80px; }
.bar span { display:block; height:100%; background:var(--good); }
@media print { body { background:#fff; color:#000; } .q { break-inside: avoid; } }
"""


def _e(text) -> str:
    return html.escape(str(text))


def _status_class(item: QuestionReport) -> str:
    return {STATUS_SOLVED: "Solved", STATUS_STRUGGLING: "struggling"}.get(item.status, "untried")


def to_html(report: Report) -> str:
    rate = report.first_try_rate
    stats = [("Questions", len(report.items)), ("Solved", report.solved),
             ("Not solved yet", report.attempted - report.solved),
             ("Not tried", len(report.items) - report.attempted),
             ("Checked attempts", report.total_attempts),
             ("First-try success", "–" if rate is None else f"{rate:.0%}")]
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
             f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
             f"<title>{_e(report.title)}</title><style>{CSS}</style></head><body><main>",
             f"<h1>{_e(report.title)}</h1>",
             f"<div class='muted'>Created {_e(report.created)} by SQL Helper. "
             + ("Hints and correct answers are included." if report.include_answers else
                "Hints and correct answers are hidden, so you can still try the questions yourself.")
             + "</div><div class='stats'>"]
    parts += [f"<div class='stat'><span class='muted'>{_e(k)}</span><b>{_e(v)}</b></div>" for k, v in stats]
    parts.append("</div>")

    if report.topics:
        parts.append("<h2>By topic</h2><table><tr><th>Topic</th><th>Solved</th><th></th>"
                     "<th>Wrong attempts</th><th>Lesson to review</th></tr>")
        for t in report.topics:
            pct = int(100 * t.solved / t.questions) if t.questions else 0
            parts.append(f"<tr><td>{_e(t.topic)}</td><td>{t.solved} / {t.questions}</td>"
                         f"<td><div class='bar'><span style='width:{pct}%'></span></div></td>"
                         f"<td>{t.wrong_attempts}</td><td>{_e(t.lesson_title)}</td></tr>")
        parts.append("</table>")

    wrong = [i for i in report.items if i.wrong]
    parts.append("<h2>Where you went wrong</h2>")
    if not wrong:
        parts.append("<p class='muted'>No wrong answers recorded for this set. "
                     "Nice work!</p>" if report.attempted else
                     "<p class='muted'>You haven't checked any answers in this set yet.</p>")
    for item in wrong:
        q = item.question
        style = {KIND_FUNCTION: "write a function", KIND_OUTPUT: "predict the output"}.get(q.kind, "SQL")
        parts.append(
            f"<div class='q'><h3>{_e(q.title)}</h3>"
            f"<span class='pill {_status_class(item)}'>{_e(item.status)}</span>"
            f"<span class='pill'>{_e(q.difficulty)}</span><span class='pill'>{_e(q.topic)}</span>"
            f"<span class='pill'>{_e(style)}</span>"
            f"<span class='muted'>{item.wrong} wrong of {item.attempts} attempt(s)</span>"
            f"<p>{_e(q.prompt)}</p>")
        if q.kind == KIND_OUTPUT:
            parts.append(f"<div class='muted'>The code:</div><pre>{_e(q.solution.rstrip())}</pre>")
        parts.append(f"<div class='muted'>Your last wrong answer:</div>"
                     f"<pre>{_e((item.last_wrong_answer or '').rstrip() or '(empty)')}</pre>")
        if item.problem:
            parts.append(f"<div class='problem'>{_e(item.problem)}</div>")
            if item.problem_details:
                parts.append("<ul>" + "".join(f"<li>{_e(d)}</li>" for d in item.problem_details) + "</ul>")
        if q.hint and report.include_answers:   # hints can give the answer away
            parts.append(f"<p><b>Hint:</b> {_e(q.hint)}</p>")
        parts.append(f"<p class='muted'>Lesson to review in the app: {_e(item.lesson_title)}</p>")
        if report.include_answers:
            label = "What it prints" if q.kind == KIND_OUTPUT else "One possible solution"
            answer = q.solution
            if q.kind == KIND_OUTPUT:
                answer = run_script(q.solution).module_out
            parts.append(f"<div class='muted'>{label}:</div><pre>{_e(answer.rstrip())}</pre>")
        parts.append("</div>")

    others = [i for i in report.items if not i.wrong]
    if others:
        parts.append("<h2>Everything else in this set</h2><table><tr><th>Question</th>"
                     "<th>Difficulty</th><th>Status</th></tr>")
        for item in others:
            note = " (first try)" if item.first_try else ""
            parts.append(f"<tr><td>{_e(item.question.title)}</td><td>{_e(item.question.difficulty)}</td>"
                         f"<td><span class='pill {_status_class(item)}'>{_e(item.status)}{note}</span></td></tr>")
        parts.append("</table>")
    parts.append("</main></body></html>")
    return "".join(parts)
