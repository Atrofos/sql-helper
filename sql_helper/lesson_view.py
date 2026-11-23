"""Tk widgets that draw lesson diagrams and Python variable values.

``LessonView`` shows one Lesson: title, explanation, example code and a
diagram drawn on a canvas. The drawing helpers here are also used by the
Python visualiser to draw variables (lists as numbered boxes, dicts as
key -> value pairs).

Colours come from ``palette()``, which checks whether macOS is in light or
dark mode so the diagrams stay readable in both.
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from .lessons import Lesson

IS_MAC = sys.platform == "darwin"
PAD = 16
CELL_PAD = 8
ROW_H = 24
BOX = 34          # minimum width of a sequence box


def mono(size: int = 12, weight: str = "normal") -> tuple:
    return ("Menlo", size, weight) if IS_MAC else ("Courier", size - 1, weight)


def is_dark(widget: tk.Misc) -> bool:
    """True when the window background is dark (macOS dark mode)."""
    try:
        bg = ttk.Style(widget).lookup("TFrame", "background") or widget.cget("background")
        r, g, b = widget.winfo_rgb(bg)
    except tk.TclError:
        return False
    return (0.299 * r + 0.587 * g + 0.114 * b) / 65535 < 0.5


def palette(widget: tk.Misc) -> dict:
    if is_dark(widget):
        return {"bg": "#1e1e1e", "fg": "#e6e6e6", "muted": "#7a7a7a", "line": "#5a5a5a",
                "box": "#2b2b2b", "head": "#3a3a3a", "keep": "#1f4d2c", "drop_fg": "#6b6b6b",
                "new": "#1d3b66", "accent": "#5b4a12", "accent_line": "#e3b341",
                "link": "#58a6ff", "changed": "#e3b341",
                "groups": ["#1d3b66", "#4a2a5e", "#1f4d2c", "#5b3a12", "#2f4f4f"]}
    return {"bg": "#ffffff", "fg": "#1f2328", "muted": "#8c959f", "line": "#afb8c1",
            "box": "#f6f8fa", "head": "#eaeef2", "keep": "#dafbe1", "drop_fg": "#a0a7af",
            "new": "#ddf4ff", "accent": "#fff1b8", "accent_line": "#bf8700",
            "link": "#0969da", "changed": "#bf8700",
            "groups": ["#ddf4ff", "#fbefff", "#dafbe1", "#fff1e5", "#e6f4f1"]}


def fmt(v) -> str:
    return "NULL" if v is None else str(v)


class Painter:
    """Draws diagram specs (see lessons.py) onto a canvas."""

    def __init__(self, canvas: tk.Canvas) -> None:
        self.c = canvas
        self.p = palette(canvas)
        self.font = mono(12)
        self.bold = mono(12, "bold")
        self.small = mono(10)
        self.measure = tkfont.Font(font=self.font).measure

    # ---- primitives ------------------------------------------------------
    def text(self, x, y, s, anchor="nw", font=None, fill=None):
        return self.c.create_text(x, y, text=s, anchor=anchor, font=font or self.font,
                                  fill=fill or self.p["fg"])

    def rect(self, x1, y1, x2, y2, fill=None, outline=None, width=1):
        return self.c.create_rectangle(x1, y1, x2, y2, fill=fill or self.p["box"],
                                       outline=outline or self.p["line"], width=width)

    def arrow(self, x1, y1, x2, y2, fill=None, width=2, smooth=False, points=None):
        coords = points or (x1, y1, x2, y2)
        return self.c.create_line(*coords, arrow="last", fill=fill or self.p["muted"],
                                  width=width, smooth=smooth)

    # ---- tables ----------------------------------------------------------
    def table(self, x, y, spec) -> tuple[float, float, list[float]]:
        """Draw one table. Returns (width, height, y-centre of each row)."""
        cols, rows = spec["columns"], spec["rows"]
        states = spec.get("states") or [None] * len(rows)
        groups = spec.get("groups")
        hcols = set(spec.get("highlight_cols") or [])
        widths = [max([self.measure(c)] + [self.measure(fmt(r[i])) for r in rows]) + 2 * CELL_PAD
                  for i, c in enumerate(cols)]
        total = sum(widths)
        self.text(x, y, spec.get("name", ""), font=self.bold)
        y += 20
        cx = x
        for i, (c, w) in enumerate(zip(cols, widths)):
            self.rect(cx, y, cx + w, y + ROW_H,
                      fill=self.p["accent"] if i in hcols else self.p["head"])
            self.text(cx + CELL_PAD, y + ROW_H / 2, c, anchor="w", font=self.bold)
            cx += w
        centres = []
        for r_i, row in enumerate(rows):
            ry = y + ROW_H * (r_i + 1)
            state = states[r_i]
            fill = self.p["box"]
            if groups is not None:
                fill = self.p["groups"][groups[r_i] % len(self.p["groups"])]
            if state == "keep":
                fill = self.p["keep"] if groups is None else fill
            elif state == "new":
                fill = self.p["new"]
            cx = x
            for i, (v, w) in enumerate(zip(row, widths)):
                cell_fill = fill
                if i in hcols and state != "drop" and groups is None and state is None:
                    cell_fill = self.p["accent"]
                self.rect(cx, ry, cx + w, ry + ROW_H, fill=cell_fill)
                colour = self.p["drop_fg"] if state == "drop" else (
                    self.p["muted"] if v is None else self.p["fg"])
                self.text(cx + CELL_PAD, ry + ROW_H / 2, fmt(v), anchor="w", fill=colour)
                cx += w
            if state == "drop":
                self.c.create_line(x + 4, ry + ROW_H / 2, x + total - 4, ry + ROW_H / 2,
                                   fill=self.p["drop_fg"], width=1)
            centres.append(ry + ROW_H / 2)
        height = 20 + ROW_H * (len(rows) + 1)
        return total, height, centres

    def panels(self, x, y, spec) -> float:
        gap = 64
        boxes, cx, tallest = [], x, 0
        for i, panel in enumerate(spec["panels"]):
            w, h, centres = self.table(cx, y, panel)
            boxes.append((cx, w, centres))
            tallest = max(tallest, h)
            if i < len(spec["panels"]) - 1:
                ay = y + 20 + ROW_H * 1.5
                if not (spec.get("links") and i == 0):
                    self.arrow(cx + w + 12, ay, cx + w + gap - 12, ay)
            cx += w + gap
        for li, ri in spec.get("links") or []:
            (lx, lw, lc), (rx, _rw, rc) = boxes[0], boxes[1]
            if li < len(lc) and ri < len(rc):
                self.c.create_line(lx + lw, lc[li], rx, rc[ri], fill=self.p["link"], width=2)
                self.c.create_oval(lx + lw - 3, lc[li] - 3, lx + lw + 3, lc[li] + 3,
                                   fill=self.p["link"], outline="")
                self.c.create_oval(rx - 3, rc[ri] - 3, rx + 3, rc[ri] + 3,
                                   fill=self.p["link"], outline="")
        return tallest

    # ---- sequences ---------------------------------------------------------
    def boxes(self, x, y, items, highlight=None, picks=None, index=True, negative=False,
              changed=False) -> tuple[float, float]:
        """A row of boxes, optionally with index numbers above (and negative ones below)."""
        top = y + (14 if index else 0)
        cx = x
        n = len(items)
        for i, item in enumerate(items):
            w = max(BOX, self.measure(item) + 14)
            lit = (highlight and highlight[0] <= i < highlight[1]) or (picks and i in picks)
            dim = picks is not None and i not in picks
            self.rect(cx, top, cx + w, top + 30, fill=self.p["accent"] if lit else self.p["box"],
                      outline=self.p["accent_line"] if lit or changed else self.p["line"],
                      width=2 if lit or changed else 1)
            self.text(cx + w / 2, top + 15, item, anchor="center",
                      fill=self.p["drop_fg"] if dim else self.p["fg"])
            if index:
                self.text(cx + w / 2, y, str(i), anchor="n", font=self.small, fill=self.p["muted"])
            if negative:
                self.text(cx + w / 2, top + 33, str(i - n), anchor="n", font=self.small,
                          fill=self.p["muted"])
            cx += w
        height = (14 if index else 0) + 30 + (16 if negative else 0)
        return cx - x, height

    def sequence(self, x, y, spec) -> float:
        label_w = max(self.measure(r.get("label", "")) for r in spec["rows"]) + 20
        cy = y
        for row in spec["rows"]:
            index = not row.get("no_index")
            self.text(x, cy + (14 if index else 0) + 15, row.get("label", ""), anchor="w",
                      font=self.bold)
            _w, h = self.boxes(x + label_w, cy, row["items"], row.get("highlight"),
                               row.get("picks"), index, row.get("negative", False))
            cy += h + 14
        return cy - y

    # ---- other diagrams -----------------------------------------------------
    def kv(self, x, y, spec) -> float:
        self.text(x, y, spec.get("label", "dict"), font=self.bold)
        cy = y + 24
        kw = max(self.measure(k) for k, _ in spec["pairs"]) + 20
        for k, v in spec["pairs"]:
            self.rect(x, cy, x + kw, cy + 30, fill=self.p["head"])
            self.text(x + kw / 2, cy + 15, k, anchor="center")
            self.arrow(x + kw + 6, cy + 15, x + kw + 46, cy + 15)
            vw = max(BOX, self.measure(v) + 16)
            self.rect(x + kw + 52, cy, x + kw + 52 + vw, cy + 30)
            self.text(x + kw + 52 + vw / 2, cy + 15, v, anchor="center")
            cy += 38
        return cy - y

    def flow(self, x, y, spec) -> float:
        steps = spec["steps"]
        width = max(self.measure(s["text"]) for s in steps) + 40
        cx = x + 60
        tops = []
        cy = y
        for i, step in enumerate(steps):
            tops.append(cy)
            decision = step.get("kind") == "decision"
            self.rect(cx, cy, cx + width, cy + 36,
                      fill=self.p["accent"] if decision else self.p["box"],
                      outline=self.p["accent_line"] if decision else self.p["line"],
                      width=2 if decision else 1)
            self.text(cx + width / 2, cy + 18, step["text"], anchor="center")
            if decision and step.get("yes"):
                label = step.get("question") and "yes" or "True"
                self.arrow(cx + width, cy + 18, cx + width + 50, cy + 18, fill=self.p["link"])
                self.text(cx + width + 8, cy + 2, label, font=self.small, fill=self.p["link"])
                yw = self.measure(step["yes"]) + 20
                self.rect(cx + width + 54, cy + 4, cx + width + 54 + yw, cy + 32, fill=self.p["keep"])
                self.text(cx + width + 54 + yw / 2, cy + 18, step["yes"], anchor="center")
            if decision and step.get("no"):
                self.arrow(cx + width, cy + 18, cx + width + 50, cy + 18, fill=self.p["muted"])
                self.text(cx + width + 8, cy + 2, "False", font=self.small, fill=self.p["muted"])
                self.text(cx + width + 56, cy + 18, step["no"], anchor="w")
            if i < len(steps) - 1:
                label = ""
                if decision:
                    label = "error" if step.get("question") else ("True" if step.get("no") else "False")
                self.arrow(cx + width / 2, cy + 36, cx + width / 2, cy + 58)
                if label:
                    self.text(cx + width / 2 + 6, cy + 40, label, font=self.small, fill=self.p["muted"])
            cy += 58
        if spec.get("loop_to") is not None:
            target = tops[spec["loop_to"]] + 18
            bottom = tops[-1] + 18
            self.arrow(0, 0, 0, 0, fill=self.p["link"], points=(
                cx, bottom, cx - 34, bottom, cx - 34, target, cx, target))
            self.text(cx - 58, (target + bottom) / 2, "repeat", anchor="center", font=self.small,
                      fill=self.p["link"])
        return cy - y

    def venn(self, x, y, spec) -> float:
        r = 70
        lx, rx, cy = x + 90, x + 190, y + 90
        for cx_, tag in ((lx, 0), (rx, 1)):
            self.c.create_oval(cx_ - r * 1.15, cy - r, cx_ + r * 1.15, cy + r,
                               outline=self.p["link"], width=2)
            self.text(cx_, cy - r - 8, spec["labels"][tag], anchor="s", font=self.bold)
        for items, px in ((spec["left"], lx - 40), (spec["both"], (lx + rx) / 2), (spec["right"], rx + 40)):
            for j, item in enumerate(items):
                self.text(px, cy - 10 * (len(items) - 1) + 20 * j, item, anchor="center")
        return 2 * r + 30

    def refs(self, x, y, spec) -> float:
        values = spec["values"]
        pointed = {target for _n, target in spec["names"]}
        vy = {}
        for j, v in enumerate(values):
            top = y + j * 44
            vy[j] = top + 15
            dim = j not in pointed
            self.rect(x + 200, top, x + 200 + max(BOX, self.measure(v) + 16), top + 30,
                      fill=self.p["box"], outline=self.p["drop_fg"] if dim else self.p["line"])
            self.text(x + 216, top + 15, v, anchor="w",
                      fill=self.p["drop_fg"] if dim else self.p["fg"])
        for i, (name, target) in enumerate(spec["names"]):
            top = y + i * 44
            self.rect(x, top, x + 60, top + 30, fill=self.p["head"])
            self.text(x + 30, top + 15, name, anchor="center", font=self.bold)
            self.arrow(x + 62, top + 15, x + 196, vy[target], fill=self.p["link"])
        return max(len(values), len(spec["names"])) * 44

    def draw(self, spec: dict, x: float = PAD, y: float = PAD) -> float:
        kind = spec.get("type")
        drawer = {"panels": self.panels, "sequence": self.sequence, "kv": self.kv,
                  "flow": self.flow, "venn": self.venn, "refs": self.refs}.get(kind)
        if drawer is None:
            return 0
        h = drawer(x, y, spec)
        if spec.get("caption"):
            self.text(x, y + h + 10, spec["caption"], font=mono(11), fill=self.p["muted"])
            h += 30
        return h

    # ---- visualiser values -----------------------------------------------------
    def value(self, x, y, name: str, snap: dict, changed: bool) -> float:
        """Draw one variable for the visualiser. Returns the height used."""
        self.text(x, y + 22, name, anchor="w", font=self.bold,
                  fill=self.p["changed"] if changed else self.p["fg"])
        vx = x + max(70, self.measure(name) + 16)
        kind = snap.get("kind")
        if kind in ("list", "tuple", "str") and snap.get("items") is not None:
            items = snap["items"]
            if not items:
                self.text(vx, y + 22, "[]" if kind == "list" else ("()" if kind == "tuple" else "''"),
                          anchor="w")
                return 40
            _w, h = self.boxes(vx, y, items, index=True, changed=changed)
            self.text(vx, y + h + 2, kind, font=self.small, fill=self.p["muted"])
            return h + 18
        if kind == "dict":
            cy = y
            if not snap["items"]:
                self.text(vx, y + 22, "{}", anchor="w")
                return 40
            for k, v in snap["items"]:
                kw = max(BOX, self.measure(k) + 14)
                self.rect(vx, cy + 8, vx + kw, cy + 34, fill=self.p["head"],
                          outline=self.p["accent_line"] if changed else self.p["line"])
                self.text(vx + kw / 2, cy + 21, k, anchor="center")
                self.arrow(vx + kw + 4, cy + 21, vx + kw + 28, cy + 21)
                vw = max(BOX, self.measure(v) + 14)
                self.rect(vx + kw + 32, cy + 8, vx + kw + 32 + vw, cy + 34)
                self.text(vx + kw + 32 + vw / 2, cy + 21, v, anchor="center")
                cy += 30
            return cy - y + 12
        if kind == "set":
            _w, h = self.boxes(vx, y, snap["items"] or ["(empty)"], index=False, changed=changed)
            self.text(vx, y + h + 2, "set (no order)", font=self.small, fill=self.p["muted"])
            return h + 22
        text = snap.get("repr", "?")
        w = max(BOX, self.measure(text) + 16)
        self.rect(vx, y + 8, vx + w, y + 36,
                  outline=self.p["accent_line"] if changed else self.p["line"],
                  width=2 if changed else 1)
        self.text(vx + w / 2, y + 22, text, anchor="center")
        if snap.get("type"):
            self.text(vx + w + 8, y + 22, snap["type"], anchor="w", font=self.small,
                      fill=self.p["muted"])
        return 44


class ScrollCanvas(ttk.Frame):
    """A canvas with scrollbars whose scroll region follows what's drawn."""

    def __init__(self, master, height: int = 260) -> None:
        super().__init__(master)
        self.canvas = tk.Canvas(self, highlightthickness=0, height=height)
        ys = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        xs = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

    def start(self) -> Painter:
        self.canvas.delete("all")
        painter = Painter(self.canvas)
        self.canvas.configure(background=painter.p["bg"])
        return painter

    def finish(self) -> None:
        box = self.canvas.bbox("all")
        if box:
            self.canvas.configure(scrollregion=(0, 0, box[2] + PAD, box[3] + PAD))


class LessonView(ttk.Frame):
    """Shows a lesson card: a picker, title, explanation, example and diagram."""

    def __init__(self, master) -> None:
        super().__init__(master, padding=(8, 8))
        self.lessons: list[Lesson] = []
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Lesson:").pack(side="left")
        self.picker = ttk.Combobox(top, state="readonly", width=40)
        self.picker.pack(side="left", padx=6)
        self.picker.bind("<<ComboboxSelected>>", lambda _e: self._picked())

        title_font = tkfont.nametofont("TkDefaultFont").copy()
        title_font.configure(size=15, weight="bold")
        self.title = ttk.Label(self, font=title_font)
        self.title.pack(anchor="w", pady=(10, 2))
        self.summary = ttk.Label(self, justify="left", wraplength=520)
        self.summary.pack(anchor="w", fill="x")
        ttk.Label(self, text="Example", font=tkfont.nametofont("TkDefaultFont")).pack(
            anchor="w", pady=(8, 0))
        self.example = tk.Text(self, height=4, font=mono(12), wrap="none", borderwidth=1,
                               relief="solid", padx=8, pady=6)
        self.example.pack(fill="x")
        self.diagram = ScrollCanvas(self)
        self.diagram.pack(fill="both", expand=True, pady=(10, 0))
        self.bind("<Configure>", lambda e: self.summary.configure(wraplength=max(e.width - 30, 240)))

    def set_lessons(self, lessons: list[Lesson]) -> None:
        self.lessons = lessons
        self.picker["values"] = [lesson.title for lesson in lessons]

    def show(self, lesson: Lesson) -> None:
        if lesson in self.lessons:
            self.picker.current(self.lessons.index(lesson))
        self.title.configure(text=lesson.title)
        self.summary.configure(text=lesson.summary)
        self.example.configure(state="normal")
        self.example.delete("1.0", "end")
        self.example.insert("1.0", lesson.example)
        self.example.configure(height=min(lesson.example.count("\n") + 1, 8), state="disabled")
        painter = self.diagram.start()
        painter.draw(lesson.diagram)
        self.diagram.finish()

    def _picked(self) -> None:
        idx = self.picker.current()
        if 0 <= idx < len(self.lessons):
            self.show(self.lessons[idx])
