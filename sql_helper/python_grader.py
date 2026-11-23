"""Grade Python-mode answers.

* "function" questions: the learner's function is called with each test's
  arguments and compared with the reference solution's results. Values are
  compared in an order-insensitive form for sets and dicts (see ``canon`` in
  python_runner), and floats are rounded to 9 places.
* "output" questions: the learner types what a snippet prints. It's compared
  with what the snippet really prints, ignoring trailing spaces and blank lines.

Like the SQL grader, ``show_examples=False`` keeps feedback from quoting the
expected answers while the Expected tab is still hidden.
"""

from __future__ import annotations

from .grader import GradeResult
from .python_runner import RunResult

MAX_FAILURES_SHOWN = 4

# Plain-English hints for the errors beginners hit most.
ERROR_HINTS = {
    "SyntaxError": "Python couldn't read this line. Look for a missing ':' , bracket or quote.",
    "IndentationError": "Code inside a def, if, for or while must be indented (4 spaces).",
    "NameError": "A name isn't defined. Check the spelling, and define variables before using them.",
    "TypeError": "A value is the wrong type for this operation, e.g. adding a str to an int, "
                 "or calling a function with the wrong number of arguments.",
    "IndexError": "You asked for a position that doesn't exist. Remember indexes start at 0.",
    "KeyError": "That key isn't in the dictionary. Use `key in d` or d.get(key) to check first.",
    "ZeroDivisionError": "Dividing by zero isn't allowed. Check the divisor first.",
    "AttributeError": "That type doesn't have this method or attribute. Check the spelling, "
                      "and what type the value really is.",
    "ValueError": "The value has the right type but an unusable content, e.g. int('abc').",
    "UnboundLocalError": "A variable is used before it's given a value inside the function.",
    "RecursionError": "A function keeps calling itself without stopping.",
}


def hint_for(error_text: str | None) -> str:
    if not error_text:
        return ""
    name = error_text.split(":", 1)[0].strip()
    return ERROR_HINTS.get(name, "")


def normalize_output(text: str) -> list[str]:
    """Lines with trailing spaces removed and blank lines trimmed from both ends."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    while lines and not lines[0]:
        lines.pop(0)
    return lines


def _with_hint(error: str) -> list[str]:
    hint = hint_for(error)
    return [error] + ([f"Hint: {hint}"] if hint else [])


def grade_function(user: RunResult, expected: RunResult, function: str,
                   show_examples: bool = True) -> GradeResult:
    if not expected.ok or any(not c.ok for c in expected.calls):
        problem = expected.error or next((c.error for c in expected.calls if not c.ok), "")
        return GradeResult(False, "This question's reference solution has an error, "
                                  "so it can't be checked.", [problem or ""])
    if not user.ok:
        return GradeResult(False, "Your code has an error.", _with_hint(user.error or ""))

    failures = []
    for mine, theirs in zip(user.calls, expected.calls):
        call = f"{function}({mine.args})"
        if not mine.ok:
            failures.append(f"{call} raised {mine.error}")
        elif mine.canon != theirs.canon:
            if show_examples:
                failures.append(f"{call} returned {mine.value}, expected {theirs.value}")
            else:
                failures.append(f"{call} returned {mine.value}, which isn't right")
    total = len(expected.calls)
    if not failures:
        return GradeResult(True, f"Correct! All {total} tests passed.")

    details = failures[:MAX_FAILURES_SHOWN]
    if len(failures) > MAX_FAILURES_SHOWN:
        details.append(f"...and {len(failures) - MAX_FAILURES_SHOWN} more.")
    first_error = next((c.error for c in user.calls if not c.ok), None)
    if hint_for(first_error):
        details.append(f"Hint: {hint_for(first_error)}")
    if all(c.ok and c.value == "None" for c in user.calls):
        details.append("Your function returned None every time. Did you forget `return`? "
                       "(print() shows a value but doesn't return it.)")
    return GradeResult(False, f"Not quite: {total - len(failures)} of {total} tests passed.",
                       details)


def grade_output(answer: str, expected: RunResult, show_examples: bool = True) -> GradeResult:
    if not expected.ok:
        return GradeResult(False, "This question's code has an error, so it can't be checked.",
                           [expected.error or ""])
    mine, theirs = normalize_output(answer), normalize_output(expected.module_out)
    if not mine:
        return GradeResult(False, "Type what you think the code prints.")
    if mine == theirs:
        return GradeResult(True, "Correct! That's exactly what it prints.")

    details = []
    if len(mine) != len(theirs):
        details.append(f"The code prints {len(theirs)} line(s); your answer has {len(mine)}. "
                       "Each print() call starts a new line.")
    for i, (a, b) in enumerate(zip(mine, theirs), start=1):
        if a != b:
            if show_examples:
                details.append(f"Line {i}: you wrote {a!r}, it prints {b!r}.")
            else:
                details.append(f"Line {i} ({a!r}) isn't right.")
            break
    if [m.replace(" ", "") for m in mine] == [t.replace(" ", "") for t in theirs]:
        details.append("Very close: only the spacing differs. print(a, b) puts one space "
                       "between values.")
    return GradeResult(False, "Not quite.", details)
