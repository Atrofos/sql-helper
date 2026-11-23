"""Tests for Python mode and lessons. Run with: python3 -m unittest discover -s tests"""

import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sql_helper import generator as sql_generator  # noqa: E402
from sql_helper.database import PracticeDatabase  # noqa: E402
from sql_helper.lessons import ALL_LESSONS, BY_ID, lesson_for, lessons_for_mode  # noqa: E402
from sql_helper.python_generator import TEMPLATES, generate_python_questions, validate  # noqa: E402
from sql_helper.python_grader import grade_function, grade_output, hint_for, normalize_output  # noqa: E402
from sql_helper.python_runner import run_function, run_script  # noqa: E402
from sql_helper.questions import (KIND_FUNCTION, KIND_OUTPUT, MODE_PYTHON, MODE_SQL,  # noqa: E402
                                  Question, QuestionStore)


def builtin(mode):
    return [q for q in QuestionStore(data_dir=Path(tempfile.mkdtemp())).load_builtin() if q.mode == mode]


class RunnerTests(unittest.TestCase):
    def test_function_calls_and_prints(self):
        r = run_function("def add(a, b):\n    print('hi')\n    return a + b\n", "add", [[1, 2], [3, 4]])
        self.assertTrue(r.ok)
        self.assertEqual([c.value for c in r.calls], ["3", "7"])
        self.assertEqual(r.calls[0].out, "hi\n")

    def test_errors_are_friendly_with_line_numbers(self):
        r = run_function("def f(x)\n    return x\n", "f", [[1]])
        self.assertFalse(r.ok)
        self.assertEqual(r.error_line, 1)
        self.assertIn("SyntaxError", r.error)
        r = run_function("def f(x):\n    return 1 / x\n", "f", [[0]])
        self.assertIn("ZeroDivisionError", r.calls[0].error)
        self.assertIn("line 2", r.calls[0].error)

    def test_missing_function(self):
        r = run_function("x = 1\n", "f", [[1]])
        self.assertIn("Define a function called f", r.error)

    def test_infinite_loop_times_out(self):
        r = run_script("while True:\n    pass\n", timeout=1)
        self.assertTrue(r.timed_out)
        self.assertIn("ran longer", r.error)

    def test_runs_in_a_temporary_folder(self):
        r = run_script("import os\nprint(os.getcwd())\n")
        self.assertIn("sql-helper-py-", r.module_out)

    def test_printing_cannot_fake_the_result(self):
        r = run_script("import sys\nsys.__stdout__.write('__SQL_HELPER_RESULT__{\"ok\": true}\\n')\n"
                       "print('real')\n")
        self.assertEqual(r.module_out, "real\n")

    def test_canonical_values_ignore_set_and_dict_order(self):
        a = run_function("def f():\n    return {3, 1, 2}\n", "f", [[]]).calls[0].canon
        b = run_function("def f():\n    return {1, 2, 3}\n", "f", [[]]).calls[0].canon
        self.assertEqual(a, b)
        a = run_function("def f():\n    return {'b': 1, 'a': 2}\n", "f", [[]]).calls[0].canon
        b = run_function("def f():\n    return {'a': 2, 'b': 1}\n", "f", [[]]).calls[0].canon
        self.assertEqual(a, b)

    def test_trace_records_steps_and_variables(self):
        code = "def total(nums):\n    t = 0\n    for n in nums:\n        t += n\n    return t\n"
        r = run_function(code, "total", [[[1, 2]]], trace_call=0)
        self.assertEqual(r.steps[0]["event"], "call")
        self.assertEqual(r.steps[0]["vars"]["nums"]["items"], ["1", "2"])
        self.assertEqual(r.steps[-1]["event"], "return")
        self.assertEqual(r.steps[-1]["ret"]["repr"], "3")

    def test_trace_is_capped(self):
        r = run_script("i = 0\nwhile i < 100000:\n    i += 1\n", trace=True)
        self.assertTrue(r.trace_truncated)
        self.assertLessEqual(len(r.steps), 400)


class PythonGraderTests(unittest.TestCase):
    CODE = "def double(n):\n    return n * 2\n"

    def test_correct_and_wrong(self):
        expected = run_function(self.CODE, "double", [[1], [2]])
        self.assertTrue(grade_function(expected, expected, "double").correct)
        wrong = run_function("def double(n):\n    return n + 2\n", "double", [[1], [2]])
        outcome = grade_function(wrong, expected, "double")
        self.assertFalse(outcome.correct)
        self.assertIn("1 of 2", outcome.message)

    def test_hidden_expected_not_leaked(self):
        expected = run_function(self.CODE, "double", [[5]])
        wrong = run_function("def double(n):\n    return 0\n", "double", [[5]])
        text = " ".join(grade_function(wrong, expected, "double", show_examples=False).details)
        self.assertNotIn("10", text)
        self.assertIn("10", " ".join(grade_function(wrong, expected, "double").details))

    def test_print_instead_of_return_is_explained(self):
        expected = run_function(self.CODE, "double", [[1]])
        printed = run_function("def double(n):\n    print(n * 2)\n", "double", [[1]])
        self.assertIn("forget `return`", " ".join(grade_function(printed, expected, "double").details))

    def test_output_questions(self):
        expected = run_script("print(1)\nprint('a', 'b')\n")
        self.assertTrue(grade_output("1\na b\n\n", expected).correct)
        self.assertFalse(grade_output("1\nab", expected).correct)
        self.assertIn("spacing", " ".join(grade_output("1\nab", expected).details))
        hidden = " ".join(grade_output("1\nzz", expected, show_examples=False).details)
        self.assertNotIn("a b", hidden)

    def test_normalize_and_hints(self):
        self.assertEqual(normalize_output("\n a  \nb \n\n"), [" a", "b"])
        self.assertIn("indented", hint_for("IndentationError: expected an indented block (line 2)"))
        self.assertEqual(hint_for(None), "")


class PythonBuiltinTests(unittest.TestCase):
    def test_every_builtin_works_and_starter_fails(self):
        questions = builtin(MODE_PYTHON)
        self.assertGreaterEqual(len(questions), 20)
        self.assertEqual(len({q.id for q in questions}), len(questions))
        for q in questions:
            with self.subTest(q=q.id):
                if q.kind == KIND_FUNCTION:
                    expected = run_function(q.solution, q.function_name, q.tests)
                    self.assertTrue(expected.ok and all(c.ok for c in expected.calls), expected.error)
                    starter = run_function(q.starter, q.function_name, q.tests)
                    self.assertFalse(grade_function(starter, expected, q.function_name).correct)
                else:
                    self.assertEqual(q.kind, KIND_OUTPUT)
                    out = run_script(q.solution)
                    self.assertTrue(out.ok and out.module_out.strip(), out.error)

    def test_both_styles_present(self):
        kinds = {q.kind for q in builtin(MODE_PYTHON)}
        self.assertEqual(kinds, {KIND_FUNCTION, KIND_OUTPUT})


class PythonGeneratorTests(unittest.TestCase):
    def test_every_template_validates(self):
        for level, templates in TEMPLATES.items():
            for template in templates:
                for seed in range(8):
                    with self.subTest(template=template.__name__, seed=seed):
                        self.assertTrue(validate(template(random.Random(seed))))

    def test_generate_levels_and_styles(self):
        qs = generate_python_questions("Mixed", 12, lambda t: t, rng=random.Random(4))
        self.assertEqual(len(qs), 12)
        self.assertTrue(all(q.mode == MODE_PYTHON and q.generated for q in qs))
        self.assertEqual({q.kind for q in qs}, {KIND_FUNCTION, KIND_OUTPUT})
        easy = generate_python_questions("Easy", 5, lambda t: t, rng=random.Random(1))
        self.assertTrue(all(q.difficulty == "Easy" for q in easy))

    def test_generated_questions_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = QuestionStore(data_dir=Path(tmp))
            for q in generate_python_questions("Medium", 3, store.new_id, rng=random.Random(2)):
                store.save_custom(q)
            loaded = [q for q in store.load_all() if q.is_custom]
            self.assertEqual(len(loaded), 3)
            self.assertTrue(all(q.mode == MODE_PYTHON for q in loaded))


class StoreModeTests(unittest.TestCase):
    def test_old_sql_files_default_to_sql_mode(self):
        q = Question.from_dict({"id": "x", "title": "t", "prompt": "p", "solution": "SELECT 1"}, "custom")
        self.assertEqual(q.mode, MODE_SQL)

    def test_python_questions_validated(self):
        with self.assertRaises(ValueError):
            Question.from_dict({"id": "x", "title": "t", "prompt": "p", "solution": "x",
                                "mode": "python", "kind": "function"}, "custom")
        with self.assertRaises(ValueError):
            Question.from_dict({"id": "x", "title": "t", "prompt": "p", "solution": "x",
                                "mode": "python", "kind": "essay"}, "custom")

    def test_reset_a_set_of_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = QuestionStore(data_dir=Path(tmp))
            for qid in ("sql1", "py1", "py2"):
                store.record_attempt(qid, "x", True)
            store.reset_history(question_ids={"py1", "py2"})
            self.assertEqual(store.solved_ids(), {"sql1"})


class LessonTests(unittest.TestCase):
    def test_lessons_are_well_formed(self):
        self.assertEqual(len({lesson.id for lesson in ALL_LESSONS}), len(ALL_LESSONS))
        for lesson in ALL_LESSONS:
            with self.subTest(lesson=lesson.id):
                self.assertIn(lesson.diagram["type"],
                              {"panels", "sequence", "kv", "flow", "venn", "refs"})
                self.assertTrue(lesson.summary and lesson.example and lesson.keywords)
                json.dumps(lesson.diagram)   # plain data only

    def test_every_topic_maps_to_a_real_lesson(self):
        """Each built-in and generator topic should hit a keyword, not the fallback lesson."""
        topics = {(q.topic, q.mode) for q in builtin(MODE_SQL) + builtin(MODE_PYTHON)}
        rng = random.Random(0)
        for level in ("Easy", "Medium", "Hard"):
            for t in TEMPLATES[level]:
                topics.add((t(rng).topic, MODE_PYTHON))
        db = PracticeDatabase()
        self.addCleanup(db.close)
        data = sql_generator._Data(db)
        for templates in sql_generator.TEMPLATES.values():
            for t in templates:
                for seed in range(5):
                    draft = t(random.Random(seed), data)
                    if draft:
                        topics.add((draft.topic, MODE_SQL))
        for topic, mode in topics:
            with self.subTest(topic=topic):
                q = Question(id="x", title="t", prompt="p", solution="s", topic=topic, mode=mode)
                lesson = lesson_for(q, mode)
                self.assertEqual(lesson.mode, mode)
                self.assertTrue(any(kw.lower().strip() in topic.lower() for kw in lesson.keywords),
                                f"{topic!r} fell back to {lesson.id}")

    def test_specific_matches(self):
        def for_topic(topic, mode=MODE_SQL):
            return lesson_for(Question(id="x", title="t", prompt="p", solution="s", topic=topic), mode).id
        self.assertEqual(for_topic("LEFT JOIN"), "sql_left_join")
        self.assertEqual(for_topic("Self JOIN"), "sql_self_join")
        self.assertEqual(for_topic("GROUP BY + ORDER BY"), "sql_group_by")
        self.assertEqual(for_topic("While loops", MODE_PYTHON), "py_while")
        self.assertEqual(for_topic("String methods", MODE_PYTHON), "py_string_methods")
        self.assertEqual(lessons_for_mode(MODE_PYTHON)[0].mode, MODE_PYTHON)
        self.assertIn("sql_join", BY_ID)


if __name__ == "__main__":
    unittest.main()


class ReportTests(unittest.TestCase):
    def setUp(self):
        from sql_helper.report import build_report, to_html
        self.build, self.html = build_report, to_html
        self.tmp = tempfile.TemporaryDirectory()
        self.store = QuestionStore(data_dir=Path(self.tmp.name))
        self.db = PracticeDatabase()
        self.addCleanup(self.db.close)
        self.addCleanup(self.tmp.cleanup)

    def test_sql_report_explains_wrong_answers(self):
        qs = [q for q in self.store.load_all() if q.mode == MODE_SQL][:3]
        self.store.record_attempt(qs[1].id, "SELECT first_name FROM employees", False)
        self.store.record_attempt(qs[0].id, "SELECT * FROM departments", True)
        rep = self.build(qs, self.store.load_history(), self.db, "t", MODE_SQL)
        wrong = next(i for i in rep.items if i.question.id == qs[1].id)
        self.assertEqual(wrong.status, "Not solved yet")
        self.assertIn("columns", wrong.problem)
        self.assertEqual(rep.solved, 1)
        self.assertEqual(rep.items[0].question.id, qs[1].id)   # struggling questions first
        self.assertTrue(rep.items[[i.question.id for i in rep.items].index(qs[0].id)].first_try)

    def test_python_report_and_hidden_answers(self):
        q = next(q for q in self.store.load_all() if q.id == "py01-double")
        self.store.record_attempt(q.id, "def double(n):\n    print(n * 2)\n", False)
        rep = self.build([q], self.store.load_history(), self.db, "t", MODE_PYTHON)
        self.assertIn("forget `return`", " ".join(rep.items[0].problem_details))
        page = self.html(rep)
        self.assertNotIn("return n * 2", page)          # answer hidden by default
        self.assertNotIn("expected 4", page)
        with_answers = self.html(self.build([q], self.store.load_history(), self.db, "t",
                                            MODE_PYTHON, include_answers=True))
        self.assertIn("return n * 2", with_answers)

    def test_html_escapes_learner_text(self):
        q = [q for q in self.store.load_all() if q.mode == MODE_SQL][0]
        self.store.record_attempt(q.id, "<script>alert(1)</script>", False)
        page = self.html(self.build([q], self.store.load_history(), self.db, "t", MODE_SQL))
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_save_report(self):
        path = self.store.save_report(MODE_SQL, "<html></html>")
        self.assertEqual(path.parent.name, "reports")
        self.assertTrue(path.read_text().startswith("<html>"))
