"""Generate random Python practice questions from templates.

Mirrors generator.py (SQL): each template picks random parameters (a number,
a word, a letter...) and returns a Draft with a prompt, a reference solution,
and test inputs. ``generate_python_questions`` runs every reference solution
and keeps only those that run cleanly, so generated questions are always
answerable. Both question styles are covered: "write a function" and
"predict the output".
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Callable

from .generator import GENERATOR_DIFFICULTIES, MAX_COUNT, MIXED
from .python_runner import run_function, run_script
from .questions import KIND_FUNCTION, KIND_OUTPUT, MODE_PYTHON, Question

ATTEMPTS_PER_QUESTION = 30
WORDS = ["python", "interview", "banana", "keyboard", "galaxy", "planet", "coffee",
         "dragon", "window", "summer", "rocket", "puzzle", "garden", "silver"]
SENTENCES = ["the quick brown fox", "practice makes perfect", "code every single day",
             "hello world from python", "keep it simple", "learning never stops"]


@dataclass
class PyDraft:
    title: str
    prompt: str
    solution: str
    topic: str
    hint: str
    kind: str = KIND_FUNCTION
    function_name: str = ""
    tests: list = field(default_factory=list)


def _starter(name: str, params: str) -> str:
    return f"def {name}({params}):\n    pass\n"


def _nums(rng: random.Random, n: int = 6, lo: int = -5, hi: int = 20) -> list[int]:
    return [rng.randint(lo, hi) for _ in range(n)]


# ---------------------------------------------------------------------------
# "Write a function" templates
# ---------------------------------------------------------------------------
def easy_multiply(rng: random.Random) -> PyDraft:
    k = rng.randint(3, 9)
    name = f"times_{k}"
    return PyDraft(f"Multiply by {k}", f"Write {name}(n) that returns n multiplied by {k}.",
                   f"def {name}(n):\n    return n * {k}\n", "Functions",
                   "Use return, not print.", function_name=name,
                   tests=[[x] for x in (0, 1, rng.randint(2, 12), -rng.randint(1, 9))])


def easy_add_suffix(rng: random.Random) -> PyDraft:
    suffix = rng.choice(["ing", "!", "_v2", "ly", "?!", "s"])
    return PyDraft(f"Add '{suffix}' to a word", f"Write add_suffix(word) that returns word with "
                   f"\"{suffix}\" added to the end.",
                   f"def add_suffix(word):\n    return word + {suffix!r}\n", "Strings",
                   "Strings join with +.", function_name="add_suffix",
                   tests=[[w] for w in rng.sample(WORDS, 3)] + [[""]])


def easy_first_n(rng: random.Random) -> PyDraft:
    n = rng.randint(2, 5)
    end = rng.random() < 0.5
    part, slc = ("last", f"s[-{n}:]") if end else ("first", f"s[:{n}]")
    return PyDraft(f"The {part} {n} characters", f"Write {part}_{n}(s) that returns the {part} "
                   f"{n} characters of s (or the whole string if it's shorter).",
                   f"def {part}_{n}(s):\n    return {slc}\n", "Slicing",
                   f"Slicing: {slc}. Slices never raise errors for short strings.",
                   function_name=f"{part}_{n}",
                   tests=[[w] for w in rng.sample(WORDS, 3)] + [["ab"]])


def easy_compare(rng: random.Random) -> PyDraft:
    t = rng.randint(5, 50)
    op, words = rng.choice([(">", "greater than"), ("<", "less than"), (">=", "at least")])
    return PyDraft(f"Is it {words} {t}?", f"Write check(n) that returns True if n is {words} {t}, "
                   "otherwise False.",
                   f"def check(n):\n    return n {op} {t}\n", "Conditionals",
                   f"A comparison like n {op} {t} is already True or False, so you can return it.",
                   function_name="check", tests=[[t - 1], [t], [t + 1], [0]])


def easy_nth_item(rng: random.Random) -> PyDraft:
    i = rng.choice([0, 1, 2, -1, -2])
    where = {0: "first", 1: "second", 2: "third", -1: "last", -2: "second-to-last"}[i]
    return PyDraft(f"The {where} item", f"Write pick(items) that returns the {where} item of a "
                   "list (the list always has at least 3 items).",
                   f"def pick(items):\n    return items[{i}]\n", "Lists",
                   "Indexes start at 0; negative indexes count from the end.",
                   function_name="pick",
                   tests=[[_nums(rng, 5)], [rng.sample(WORDS, 4)], [_nums(rng, 3)]])


def medium_count_greater(rng: random.Random) -> PyDraft:
    t = rng.randint(0, 10)
    return PyDraft(f"Count numbers above {t}", f"Write count_above(nums) that returns how many "
                   f"numbers in the list are greater than {t}.",
                   f"def count_above(nums):\n    return sum(1 for n in nums if n > {t})\n",
                   "Loops", "Loop over nums and add 1 to a counter when n is big enough.",
                   function_name="count_above",
                   tests=[[_nums(rng)], [_nums(rng)], [[]], [[t, t, t + 1]]])


def medium_filter_words(rng: random.Random) -> PyDraft:
    n = rng.randint(3, 6)
    return PyDraft(f"Words longer than {n} letters", f"Write long_words(words) that returns a list "
                   f"of the words with more than {n} letters, in their original order.",
                   f"def long_words(words):\n    return [w for w in words if len(w) > {n}]\n",
                   "Comprehensions", "A list comprehension with an if: [w for w in words if ...]",
                   function_name="long_words",
                   tests=[[rng.sample(WORDS, 5)], [rng.sample(WORDS, 4)], [[]], [["a", "bb"]]])


def medium_sum_multiples(rng: random.Random) -> PyDraft:
    d = rng.randint(2, 7)
    return PyDraft(f"Add up multiples of {d}", f"Write sum_multiples(n) that returns the total of "
                   f"all numbers from 1 to n (inclusive) that are divisible by {d}.",
                   f"def sum_multiples(n):\n    return sum(i for i in range(1, n + 1) if i % {d} == 0)\n",
                   "Range", "range(1, n + 1) includes n. Use % to test divisibility.",
                   function_name="sum_multiples",
                   tests=[[x] for x in (d, rng.randint(10, 30), 1, rng.randint(31, 60))])


def medium_count_letter(rng: random.Random) -> PyDraft:
    letter = rng.choice("aeinorst")
    return PyDraft(f"Count the letter '{letter}'", f"Write count_{letter}(s) that returns how many "
                   f"times the letter '{letter}' appears in s, upper or lower case.",
                   f"def count_{letter}(s):\n    return s.lower().count({letter!r})\n",
                   "String methods", "s.lower() then .count(...), or loop and compare each character.",
                   function_name=f"count_{letter}",
                   tests=[[rng.choice(SENTENCES)], [rng.choice(SENTENCES).upper()], [""],
                          [rng.choice(WORDS)]])


def medium_fizzbuzz_variant(rng: random.Random) -> PyDraft:
    a, b = rng.choice([(2, 3), (3, 7), (4, 5), (3, 4), (2, 5)])
    w1, w2 = rng.choice([("Fizz", "Buzz"), ("Ping", "Pong"), ("Tick", "Tock"), ("Foo", "Bar")])
    sol = (f"def label(n):\n    if n % {a} == 0 and n % {b} == 0:\n        return {w1 + w2!r}\n"
           f"    if n % {a} == 0:\n        return {w1!r}\n    if n % {b} == 0:\n"
           f"        return {w2!r}\n    return str(n)\n")
    return PyDraft(f"{w1}{w2} with {a} and {b}", f"Write label(n) that returns \"{w1}{w2}\" if n is "
                   f"divisible by both {a} and {b}, \"{w1}\" if only by {a}, \"{w2}\" if only by "
                   f"{b}, and otherwise n as a string.",
                   sol, "Conditionals", "Check the 'both' case first.", function_name="label",
                   tests=[[a], [b], [a * b], [1], [a * b * 2], [rng.choice([7, 11, 13])]])


def medium_lookup(rng: random.Random) -> PyDraft:
    items = rng.sample(["apple", "bread", "milk", "eggs", "tea", "rice", "jam"], 3)
    prices = {item: rng.randint(1, 9) for item in items}
    missing = rng.choice(["cake", "soap", "salt"])
    return PyDraft(f"Look up a price ({', '.join(items)})", f"PRICES is a dictionary of item prices (it's already in the "
                   f"editor). Write price_of(item) that returns the price of item, or 0 if the "
                   f"item isn't in PRICES.",
                   f"PRICES = {prices!r}\n\ndef price_of(item):\n    return PRICES.get(item, 0)\n",
                   "Dictionaries", "d.get(key, default) returns default when the key is missing.",
                   function_name="price_of", tests=[[items[0]], [items[2]], [missing]])


def hard_running_totals(rng: random.Random) -> PyDraft:
    return PyDraft("Running totals", "Write running_totals(nums) that returns a list where each "
                   "item is the sum of all numbers up to and including that position, e.g. "
                   "[1, 2, 3] gives [1, 3, 6].",
                   "def running_totals(nums):\n    out, total = [], 0\n    for n in nums:\n"
                   "        total += n\n        out.append(total)\n    return out\n",
                   "Loops", "Keep a running total, and append it to a result list on each loop.",
                   function_name="running_totals",
                   tests=[[_nums(rng, 5, 0, 9)], [_nums(rng, 4, -5, 5)], [[]], [[rng.randint(1, 9)]]])


def hard_longest_word(rng: random.Random) -> PyDraft:
    return PyDraft("Longest word", "Write longest_word(sentence) that returns the longest word in "
                   "the sentence. If several words tie, return the first one.",
                   "def longest_word(sentence):\n    best = ''\n    for w in sentence.split():\n"
                   "        if len(w) > len(best):\n            best = w\n    return best\n",
                   "Strings", "Track the best word so far; only replace it when a word is strictly longer.",
                   function_name="longest_word",
                   tests=[[s] for s in rng.sample(SENTENCES, 3)] + [["a bb cc"]])


def hard_invert_dict(rng: random.Random) -> PyDraft:
    keys = rng.sample(["a", "b", "c", "d", "e"], 3)
    d = {k: rng.randint(1, 99) + i * 100 for i, k in enumerate(keys)}
    return PyDraft("Swap keys and values", "Write invert(d) that returns a new dictionary with "
                   "each value of d as a key and its key as the value. All values are unique.",
                   "def invert(d):\n    return {v: k for k, v in d.items()}\n",
                   "Dictionaries", "Loop over d.items() to get (key, value) pairs.",
                   function_name="invert", tests=[[d], [{}], [{"x": 1}]])


def hard_chunks(rng: random.Random) -> PyDraft:
    k = rng.randint(2, 4)
    return PyDraft(f"Split a list into groups of {k}", f"Write chunks(items) that splits the list "
                   f"into smaller lists of {k} items each (the last one may be shorter), e.g. for "
                   f"{k}: {list(range(1, k + 2))} gives {[list(range(1, k + 1)), [k + 1]]}.",
                   f"def chunks(items):\n    return [items[i:i + {k}] for i in range(0, len(items), {k})]\n",
                   "Slicing", f"range(0, len(items), {k}) gives the start of each chunk; slice from there.",
                   function_name="chunks",
                   tests=[[_nums(rng, 7, 0, 9)], [_nums(rng, k, 0, 9)], [[]], [_nums(rng, 1, 0, 9)]])


def hard_digit_sum(rng: random.Random) -> PyDraft:
    return PyDraft("Add up the digits", "Write digit_sum(n) that returns the sum of the digits of "
                   "the non-negative whole number n, using a while loop and % 10 (not str()).",
                   "def digit_sum(n):\n    total = 0\n    while n > 0:\n        total += n % 10\n"
                   "        n //= 10\n    return total\n",
                   "While loops", "n % 10 is the last digit; n // 10 removes it. Repeat until n is 0.",
                   function_name="digit_sum",
                   tests=[[0], [rng.randint(1, 9)], [rng.randint(100, 9999)], [rng.randint(10000, 99999)]])


# ---------------------------------------------------------------------------
# "Predict the output" templates
# ---------------------------------------------------------------------------
def easy_out_division(rng: random.Random) -> PyDraft:
    a, b = rng.randint(10, 40), rng.randint(3, 7)
    return PyDraft(f"// and % with {a} and {b}", "What does this code print?",
                   f"a = {a}\nb = {b}\nprint(a // b, a % b)\n", "Variables",
                   "// is whole-number division; % is the remainder.", kind=KIND_OUTPUT)


def easy_out_slice(rng: random.Random) -> PyDraft:
    w = rng.choice(WORDS)
    i = rng.randint(0, 2)
    j = rng.randint(i + 2, len(w))
    return PyDraft(f"Slicing '{w}'", "What does this code print?",
                   f"s = {w!r}\nprint(s[{i}:{j}])\nprint(s[-1])\n", "Slicing",
                   "s[i:j] starts at index i and stops just before j.", kind=KIND_OUTPUT)


def medium_out_accumulate(rng: random.Random) -> PyDraft:
    n, k = rng.randint(3, 5), rng.randint(2, 4)
    return PyDraft("A loop with a running total", "What does this code print?",
                   f"total = 0\nfor i in range({n}):\n    total += i * {k}\nprint(total)\n", "Loops",
                   f"range({n}) is 0 to {n - 1}. Work out total after each pass.", kind=KIND_OUTPUT)


def medium_out_list_ops(rng: random.Random) -> PyDraft:
    nums = _nums(rng, 4, 1, 9)
    x = rng.randint(10, 20)
    return PyDraft("append and pop", "What does this code print?",
                   f"nums = {nums}\nnums.append({x})\nfirst = nums.pop(0)\nprint(first)\nprint(nums)\n",
                   "Lists", "append adds to the end; pop(0) removes and returns the first item.",
                   kind=KIND_OUTPUT)


def hard_out_while(rng: random.Random) -> PyDraft:
    n = rng.choice([16, 20, 33, 50, 64, 100])
    return PyDraft(f"Halving {n}", "What does this code print?",
                   f"n = {n}\nsteps = 0\nwhile n > 1:\n    n //= 2\n    steps += 1\nprint(n, steps)\n",
                   "While loops", "Write down n after each pass until the condition n > 1 is False.",
                   kind=KIND_OUTPUT)


def hard_out_join(rng: random.Random) -> PyDraft:
    sentence = rng.choice(SENTENCES)
    sep = rng.choice(["-", "+", ", "])
    return PyDraft("split, reverse, join", "What does this code print?",
                   f"words = {sentence!r}.split()\nprint({sep!r}.join(reversed(words)))\n"
                   "print(len(words))\n",
                   "String methods", "split() makes a list of words; join puts them back with the separator.",
                   kind=KIND_OUTPUT)


TEMPLATES: dict[str, list[Callable[[random.Random], PyDraft]]] = {
    "Easy": [easy_multiply, easy_add_suffix, easy_first_n, easy_compare, easy_nth_item,
             easy_out_division, easy_out_slice],
    "Medium": [medium_count_greater, medium_filter_words, medium_sum_multiples, medium_count_letter,
               medium_fizzbuzz_variant, medium_lookup, medium_out_accumulate, medium_out_list_ops],
    "Hard": [hard_running_totals, hard_longest_word, hard_invert_dict, hard_chunks,
             hard_digit_sum, hard_out_while, hard_out_join],
}


def normalize_code(code: str) -> str:
    return re.sub(r"\s+", " ", code.strip())


def starter_for(draft: PyDraft) -> str:
    """Editor starting code: the function outline, keeping any setup lines (like PRICES)."""
    if draft.kind != KIND_FUNCTION:
        return ""
    head, _, _ = draft.solution.partition(f"def {draft.function_name}(")
    params = draft.solution.split(f"def {draft.function_name}(", 1)[1].split(")", 1)[0]
    return head + _starter(draft.function_name, params)


def validate(draft: PyDraft) -> bool:
    if draft.kind == KIND_FUNCTION:
        result = run_function(draft.solution, draft.function_name, draft.tests)
        return result.ok and len(result.calls) == len(draft.tests) and all(c.ok for c in result.calls)
    result = run_script(draft.solution)
    return result.ok and bool(result.module_out.strip())


def generate_python_questions(difficulty: str, count: int, id_factory: Callable[[str], str],
                              existing_solutions: set[str] | None = None,
                              rng: random.Random | None = None) -> list[Question]:
    """Return up to ``count`` new, validated Python questions (Easy/Medium/Hard/Mixed)."""
    if difficulty not in GENERATOR_DIFFICULTIES:
        raise ValueError(f"unknown difficulty: {difficulty}")
    count = max(1, min(int(count), MAX_COUNT))
    rng = rng or random.Random()
    seen = {normalize_code(s) for s in (existing_solutions or set())}
    questions: list[Question] = []
    attempts = 0
    while len(questions) < count and attempts < count * ATTEMPTS_PER_QUESTION:
        attempts += 1
        level = rng.choice(("Easy", "Medium", "Hard")) if difficulty == MIXED else difficulty
        draft = rng.choice(TEMPLATES[level])(rng)
        key = normalize_code(draft.solution)
        if key in seen or not validate(draft):
            continue
        seen.add(key)
        questions.append(Question(
            id=id_factory(draft.title), title=draft.title, prompt=draft.prompt,
            solution=draft.solution, difficulty=level, topic=draft.topic, hint=draft.hint,
            generated=True, mode=MODE_PYTHON, kind=draft.kind,
            function_name=draft.function_name, starter=starter_for(draft), tests=draft.tests,
        ))
    return questions
