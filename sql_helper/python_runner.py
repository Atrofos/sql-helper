"""Run a learner's Python code in a separate, time-limited process.

Unlike SQL mode (where an SQLite authorizer makes the data read-only), plain
Python can't be fully sandboxed with the standard library. What this module
does guarantee:

* the code runs in its own process, so a crash or infinite loop can't take the
  app down, and it's killed after a time limit;
* it runs with ``python -I`` (isolated mode: no user site-packages, no
  PYTHON* environment variables) in a fresh, empty temporary folder;
* CPU time is capped (by the child, with ``resource.setrlimit``) where the OS
  supports it;
* printed output is captured and size-limited.

It does NOT stop code that deliberately touches files elsewhere. That's the
same as running code in any Python editor on your own machine, and the README
says so.

The child process gets a JSON payload on stdin and prints one JSON result line
(prefixed with RESULT_MARKER) on its real stdout. The learner's prints are
captured separately, so they can't corrupt the result.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

DEFAULT_TIMEOUT_S = 3.0
LIVE_TIMEOUT_S = 1.5         # shorter for the live preview, so typing `while True:` recovers fast
MAX_TRACE_STEPS = 400
MAX_OUTPUT_CHARS = 20_000
RESULT_MARKER = "__SQL_HELPER_RESULT__"
USER_FILENAME = "<your code>"

# The program the child process runs. Kept as a string so the child needs
# nothing from this package (it runs in isolated mode from an empty folder).
HARNESS = r'''
import io, json, sys, traceback, contextlib

MARK = "__SQL_HELPER_RESULT__"
FILENAME = "<your code>"
MAX_OUT = 20000
MAX_STEPS = 400

def canon(v, depth=0):
    """Order-insensitive, comparable form of a value (sets/dicts sorted, floats rounded)."""
    if depth > 20:
        return "..."
    if isinstance(v, bool) or v is None or isinstance(v, (int, str)):
        return v
    if isinstance(v, float):
        return round(v, 9)
    if isinstance(v, list):
        return [canon(x, depth + 1) for x in v]
    if isinstance(v, tuple):
        return ("tuple",) + tuple(canon(x, depth + 1) for x in v)
    if isinstance(v, (set, frozenset)):
        return ("set",) + tuple(sorted((canon(x, depth + 1) for x in v), key=repr))
    if isinstance(v, dict):
        return ("dict",) + tuple(sorted(((canon(k, depth + 1), canon(x, depth + 1))
                                         for k, x in v.items()), key=repr))
    return ("other", repr(v))

def short(v, n=80):
    try:
        r = repr(v)
    except Exception:
        r = "<unprintable>"
    return r if len(r) <= n else r[: n - 3] + "..."

def snap(v):
    """Describe a value for the visualiser: sequences become boxes."""
    if isinstance(v, (list, tuple)) and len(v) <= 24:
        return {"kind": type(v).__name__, "items": [short(x, 24) for x in v]}
    if isinstance(v, str) and 0 < len(v) <= 24:
        return {"kind": "str", "items": [repr(c)[1:-1] or " " for c in v], "repr": short(v)}
    if isinstance(v, dict) and len(v) <= 16:
        return {"kind": "dict", "items": [[short(k, 20), short(x, 24)] for k, x in v.items()]}
    if isinstance(v, (set, frozenset)) and len(v) <= 16:
        return {"kind": "set", "items": sorted((short(x, 20) for x in v))}
    return {"kind": "value", "repr": short(v), "type": type(v).__name__}

def error_info(exc):
    """Friendly error text plus the line number inside the learner's code."""
    line = None
    if isinstance(exc, SyntaxError) and exc.filename == FILENAME:
        line = exc.lineno
    else:
        for fr in traceback.extract_tb(exc.__traceback__):
            if fr.filename == FILENAME:
                line = fr.lineno
    message = exc.msg if isinstance(exc, SyntaxError) else str(exc)
    text = type(exc).__name__ + ": " + message
    if line:
        text += " (line %d)" % line
    return {"type": type(exc).__name__, "message": message, "line": line, "text": text}

class Tracer:
    def __init__(self, out):
        self.steps, self.out, self.depth, self.stopped = [], out, 0, False

    def record(self, frame, event, arg=None):
        if len(self.steps) >= MAX_STEPS:
            self.stopped = True
            sys.settrace(None)
            return
        local_vars = {}
        for k, v in frame.f_locals.items():
            if k.startswith("__") or callable(v) and not isinstance(v, (list, dict)):
                continue
            if type(v).__name__ == "module":
                continue
            local_vars[k] = snap(v)
        step = {"line": frame.f_lineno, "event": event, "func": frame.f_code.co_name,
                "depth": self.depth, "vars": local_vars, "out": self.out.getvalue()[-2000:]}
        if event == "return":
            step["ret"] = snap(arg)
        self.steps.append(step)

    def __call__(self, frame, event, arg):
        if frame.f_code.co_filename != FILENAME:
            return None
        if event == "call":
            self.depth += 1
            self.record(frame, "call")
        return self.local

    def local(self, frame, event, arg):
        if self.stopped:
            return None
        if event == "line":
            self.record(frame, "line")
        elif event == "return":
            self.record(frame, "return", arg)
            self.depth -= 1
        elif event == "exception":
            self.record(frame, "exception")
        return self.local

def limit_cpu(seconds):
    try:
        import resource
        limit = int(seconds) + 1
        resource.setrlimit(resource.RLIMIT_CPU, (limit, limit))
    except Exception:
        pass   # not available on this OS; the parent's wall-clock timeout still applies

def main():
    payload = json.loads(sys.stdin.read())
    limit_cpu(payload.get("cpu_seconds", 3))
    code, mode = payload["code"], payload["mode"]
    trace_call = payload.get("trace_call")   # index of the test call to trace, or None
    trace_module = payload.get("trace_module", False)
    result = {"ok": True, "error": None, "module_out": "", "calls": [], "steps": [],
              "trace_truncated": False}
    ns = {"__name__": "__main__"}
    module_out = io.StringIO()
    try:
        compiled = compile(code, FILENAME, "exec")
    except SyntaxError as exc:
        result.update(ok=False, error=error_info(exc))
        return result
    tracer = Tracer(module_out) if trace_module else None
    try:
        with contextlib.redirect_stdout(module_out):
            if tracer:
                sys.settrace(tracer)
            try:
                exec(compiled, ns)
            finally:
                sys.settrace(None)
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            raise
        result.update(ok=False, error=error_info(exc))
    result["module_out"] = module_out.getvalue()[:MAX_OUT]
    if tracer:
        result["steps"], result["trace_truncated"] = tracer.steps, tracer.stopped
    if mode != "function" or not result["ok"]:
        return result

    name = payload["function"]
    fn = ns.get(name)
    if not callable(fn):
        result.update(ok=False, error={"type": "NameError", "line": None, "message": "",
                      "text": "Define a function called %s(...)." % name})
        return result
    for i, args in enumerate(payload["calls"]):
        out = io.StringIO()
        call = {"args": ", ".join(short(a, 60) for a in args), "ok": True,
                "value": None, "canon": None, "out": "", "error": None}
        tracer = Tracer(out) if trace_call == i else None
        try:
            with contextlib.redirect_stdout(out):
                if tracer:
                    sys.settrace(tracer)
                try:
                    value = fn(*args)
                finally:
                    sys.settrace(None)
            call["value"] = short(value, 200)
            call["canon"] = repr(canon(value))
        except BaseException as exc:
            if isinstance(exc, KeyboardInterrupt):
                raise
            call.update(ok=False, error=error_info(exc))
        call["out"] = out.getvalue()[:MAX_OUT]
        if tracer:
            result["steps"], result["trace_truncated"] = tracer.steps, tracer.stopped
        result["calls"].append(call)
    return result

try:
    res = main()
except BaseException as exc:   # never let the harness itself die silently
    res = {"ok": False, "error": {"type": type(exc).__name__, "line": None,
           "message": str(exc), "text": "Internal error: %s" % exc},
           "module_out": "", "calls": [], "steps": [], "trace_truncated": False}
sys.__stdout__.write("\n" + MARK + json.dumps(res) + "\n")
'''


@dataclass
class CallResult:
    """One call of the learner's function with one set of test arguments."""

    args: str                    # arguments as they'd appear in the call, e.g. "'abc', 2"
    ok: bool
    value: str | None = None     # repr of the return value, for display
    canon: str | None = None     # order-insensitive form used for grading
    out: str = ""                # anything printed during the call
    error: str | None = None     # friendly error text


@dataclass
class RunResult:
    ok: bool
    error: str | None = None
    error_line: int | None = None
    module_out: str = ""                       # printed while the code itself ran
    calls: list[CallResult] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)   # visualiser trace
    trace_truncated: bool = False
    timed_out: bool = False


def _run(payload: dict, timeout: float) -> RunResult:
    # The child caps its own CPU time (preexec_fn isn't thread-safe, and the UI
    # runs this from a worker thread).
    payload = {**payload, "cpu_seconds": timeout}
    with tempfile.TemporaryDirectory(prefix="sql-helper-py-") as tmp:
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", HARNESS],
                input=json.dumps(payload), capture_output=True, text=True,
                timeout=timeout, cwd=tmp, env={"PATH": os.environ.get("PATH", "")},
            )
        except subprocess.TimeoutExpired:
            return RunResult(ok=False, timed_out=True, error=(
                f"Your code ran longer than {timeout:g}s and was stopped. "
                "Check for a loop that never ends (e.g. a while loop whose condition never "
                "becomes False)."))
    stdout = proc.stdout
    marker_at = stdout.rfind(RESULT_MARKER)
    if marker_at == -1:
        detail = (proc.stderr or "").strip().splitlines()[-1:] or ["no output"]
        return RunResult(ok=False, error=f"Your code stopped unexpectedly ({detail[0]}).")
    data = json.loads(stdout[marker_at + len(RESULT_MARKER):].strip())
    err = data.get("error") or {}
    return RunResult(
        ok=bool(data.get("ok")),
        error=err.get("text"),
        error_line=err.get("line"),
        module_out=data.get("module_out", "")[:MAX_OUTPUT_CHARS],
        calls=[CallResult(args=c["args"], ok=c["ok"], value=c.get("value"),
                          canon=c.get("canon"), out=c.get("out", ""),
                          error=(c.get("error") or {}).get("text"))
               for c in data.get("calls", [])],
        steps=data.get("steps", []),
        trace_truncated=bool(data.get("trace_truncated")),
    )


def run_function(code: str, function: str, calls: list[list], timeout: float = DEFAULT_TIMEOUT_S,
                 trace_call: int | None = None) -> RunResult:
    """Define the learner's code, then call ``function(*args)`` for each args list.

    ``trace_call`` records a step-by-step trace of that one call for the visualiser.
    """
    return _run({"mode": "function", "code": code, "function": function,
                 "calls": calls, "trace_call": trace_call}, timeout)


def run_script(code: str, timeout: float = DEFAULT_TIMEOUT_S, trace: bool = False) -> RunResult:
    """Run code as a script and capture what it prints (optionally with a trace)."""
    return _run({"mode": "script", "code": code, "trace_module": trace}, timeout)
