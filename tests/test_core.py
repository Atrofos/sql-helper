"""Tests for the non-UI modules. Run with: python3 -m unittest discover -s tests"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import random  # noqa: E402

from sql_helper.database import PracticeDatabase, QueryResult  # noqa: E402
from sql_helper.generator import TEMPLATES, _Data, generate_questions, normalize_sql  # noqa: E402
from sql_helper.grader import grade  # noqa: E402
from sql_helper.questions import Question, QuestionStore  # noqa: E402


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = PracticeDatabase(timeout_s=0.3)

    def tearDown(self):
        self.db.close()

    def test_select_returns_rows_and_columns(self):
        result = self.db.run("SELECT first_name, salary FROM employees WHERE emp_id = 1")
        self.assertTrue(result.ok)
        self.assertEqual(result.columns, ["first_name", "salary"])
        self.assertEqual(result.rows, [("Alice", 145000)])

    def test_writes_are_blocked_and_data_unchanged(self):
        for sql in ("DELETE FROM employees", "DROP TABLE orders",
                    "UPDATE products SET price = 0", "CREATE TABLE t (x)",
                    "INSERT INTO departments VALUES (9, 'X', 'Y')"):
            with self.subTest(sql=sql):
                self.assertFalse(self.db.run(sql).ok)
        self.assertEqual(self.db.run("SELECT COUNT(*) FROM employees").rows, [(12,)])

    def test_attach_and_pragma_are_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "x.db"
            self.assertFalse(self.db.run(f"ATTACH '{target}' AS x").ok)
            self.assertFalse(target.exists())
        self.assertFalse(self.db.run("PRAGMA table_info(employees)").ok)

    def test_runaway_query_is_stopped(self):
        result = self.db.run("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) "
                             "SELECT COUNT(*) FROM c")
        self.assertFalse(result.ok)
        self.assertIn("stopped", result.error)

    def test_recursive_cte_with_limit_works(self):
        result = self.db.run("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c "
                             "WHERE x < 3) SELECT x FROM c")
        self.assertEqual(result.rows, [(1,), (2,), (3,)])

    def test_multiple_statements_rejected(self):
        self.assertIn("one statement", self.db.run("SELECT 1; SELECT 2").error)

    def test_empty_and_syntax_error(self):
        self.assertFalse(self.db.run("   ").ok)
        self.assertIn("syntax error", self.db.run("SELEC 1").error)

    def test_row_cap(self):
        db = PracticeDatabase(max_rows=5)
        result = db.run("SELECT * FROM employees")
        self.assertEqual(len(result.rows), 5)
        self.assertTrue(result.truncated)

    def test_schema_listing(self):
        self.assertEqual(self.db.table_names(),
                         ["departments", "employees", "customers", "products", "orders"])
        self.assertIn(("salary", "INTEGER"), self.db.table_columns("employees"))


class GraderTests(unittest.TestCase):
    def r(self, columns, rows):
        return QueryResult(columns=columns, rows=rows)

    def test_same_rows_any_order_is_correct(self):
        self.assertTrue(grade(self.r(["a"], [(2,), (1,)]), self.r(["a"], [(1,), (2,)])).correct)

    def test_order_enforced_when_required(self):
        outcome = grade(self.r(["a"], [(2,), (1,)]), self.r(["a"], [(1,), (2,)]), order_matters=True)
        self.assertFalse(outcome.correct)
        self.assertIn("order", outcome.message)

    def test_column_names_do_not_matter(self):
        outcome = grade(self.r(["total"], [(5,)]), self.r(["COUNT(*)"], [(5,)]))
        self.assertTrue(outcome.correct)
        self.assertTrue(outcome.details)  # a tip about names

    def test_float_rounding_tolerance(self):
        self.assertTrue(grade(self.r(["x"], [(98333.3333,)]), self.r(["x"], [(98333.33,)])).correct)
        self.assertTrue(grade(self.r(["x"], [(5,)]), self.r(["x"], [(5.0,)])).correct)

    def test_duplicates_count(self):
        self.assertFalse(grade(self.r(["a"], [(1,)]), self.r(["a"], [(1,), (1,)])).correct)

    def test_wrong_column_count(self):
        outcome = grade(self.r(["a", "b"], [(1, 2)]), self.r(["a"], [(1,)]))
        self.assertFalse(outcome.correct)
        self.assertIn("columns", outcome.message)

    def test_missing_and_extra_rows_reported(self):
        outcome = grade(self.r(["a"], [(1,), (3,)]), self.r(["a"], [(1,), (2,)]))
        self.assertFalse(outcome.correct)
        text = " ".join(outcome.details)
        self.assertIn("Missing", text)
        self.assertIn("unexpected", text)

    def test_hidden_expected_gives_no_examples(self):
        expected = self.r(["first_name"], [("Alice",), ("Bob",)])
        outcome = grade(self.r(["x"], [("Zed",)]), expected, show_examples=False)
        text = " ".join(outcome.details)
        self.assertNotIn("Alice", text)
        self.assertIn("Zed", text)  # the user's own extra rows are fine to show
        wrong_cols = grade(self.r(["a", "b"], [(1, 2)]), expected, show_examples=False)
        self.assertNotIn("first_name", " ".join(wrong_cols.details))

    def test_user_error(self):
        outcome = grade(QueryResult(error="boom"), self.r(["a"], [(1,)]))
        self.assertFalse(outcome.correct)


class BuiltinQuestionTests(unittest.TestCase):
    """Every built-in question must have a working, non-empty, self-consistent solution."""

    def test_builtin_solutions(self):
        db = PracticeDatabase()
        questions = QuestionStore(data_dir=Path(tempfile.mkdtemp())).load_builtin()
        self.assertEqual(len({q.id for q in questions}), len(questions), "duplicate ids")
        for q in questions:
            with self.subTest(question=q.id):
                result = db.run(q.solution)
                self.assertTrue(result.ok, result.error)
                self.assertTrue(result.rows, "solution returns no rows")
                self.assertTrue(grade(result, result, q.order_matters).correct)
                if q.order_matters:
                    self.assertIn("ORDER BY", q.solution.upper())


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = QuestionStore(data_dir=Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, title="My question"):
        return Question(id=self.store.new_id(title), title=title,
                        prompt="Do a thing", solution="SELECT 1")

    def test_save_load_delete_roundtrip(self):
        q = self.make()
        path = self.store.save_custom(q)
        self.assertTrue(path.exists())
        loaded = [x for x in self.store.load_all() if x.is_custom]
        self.assertEqual([x.id for x in loaded], [q.id])
        self.store.delete_custom(loaded[0])
        self.assertFalse(path.exists())

    def test_builtin_is_read_only(self):
        builtin = self.store.load_builtin()[0]
        with self.assertRaises(ValueError):
            self.store.save_custom(builtin)
        with self.assertRaises(ValueError):
            self.store.delete_custom(builtin)

    def test_bad_files_are_skipped_with_warning(self):
        self.store.questions_dir.mkdir(parents=True)
        (self.store.questions_dir / "broken.json").write_text("{not json")
        (self.store.questions_dir / "partial.json").write_text(json.dumps({"id": "x"}))
        (self.store.questions_dir / "list.json").write_text("[]")
        self.store.save_custom(self.make())
        customs = [q for q in self.store.load_all() if q.is_custom]
        self.assertEqual(len(customs), 1)
        self.assertEqual(len(self.store.warnings), 3)

    def test_unknown_fields_ignored(self):
        self.store.questions_dir.mkdir(parents=True)
        data = self.make().to_dict() | {"future_field": 1}
        (self.store.questions_dir / "q.json").write_text(json.dumps(data))
        self.assertEqual(len([q for q in self.store.load_all() if q.is_custom]), 1)

    def test_history_and_solved(self):
        self.store.record_attempt("q1", "SELECT 1", False)
        self.store.record_attempt("q1", "SELECT 2", True)
        self.store.record_attempt("q2", "SELECT 3", False)
        with open(self.store.history_file, "a") as fh:
            fh.write("garbage line\n")
        self.assertEqual(len(self.store.load_history()), 3)
        self.assertEqual(self.store.solved_ids(), {"q1"})

    def test_id_cannot_escape_folder(self):
        q = self.make()
        q.id = "../../evil"
        path = self.store.save_custom(q)
        self.assertEqual(path.parent, self.store.questions_dir)


class ResetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = QuestionStore(data_dir=Path(self.tmp.name))
        for qid, ok in (("q1", True), ("q2", True), ("q1", False)):
            self.store.record_attempt(qid, "SELECT 1", ok)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reset_one_question_keeps_others_and_backs_up(self):
        backup = self.store.reset_history("q1")
        self.assertEqual(self.store.solved_ids(), {"q2"})
        self.assertEqual(len(self.store.load_history()), 1)
        self.assertEqual(len(backup.read_text().splitlines()), 3)

    def test_reset_all(self):
        backup = self.store.reset_history()
        self.assertEqual(self.store.load_history(), [])
        self.assertTrue(backup.exists())

    def test_reset_with_no_history(self):
        self.store.reset_history()
        self.assertIsNone(self.store.reset_history())


class GeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = PracticeDatabase()

    def test_every_template_produces_valid_sql(self):
        data = _Data(self.db)
        for level, templates in TEMPLATES.items():
            for template in templates:
                for seed in range(40):
                    draft = template(random.Random(seed), data)
                    if draft is None:
                        continue  # template declined (e.g. ties); generator retries
                    with self.subTest(template=template.__name__, seed=seed):
                        result = self.db.run(draft.solution)
                        self.assertTrue(result.ok, result.error)
                        self.assertTrue(result.rows, draft.solution)

    def test_generate_count_difficulty_and_uniqueness(self):
        for difficulty in ("Easy", "Medium", "Hard"):
            qs = generate_questions(self.db, difficulty, 8, lambda t: t, rng=random.Random(3))
            self.assertEqual(len(qs), 8)
            self.assertTrue(all(q.difficulty == difficulty and q.generated for q in qs))
            self.assertEqual(len({normalize_sql(q.solution) for q in qs}), 8)

    def test_mixed_and_skips_existing(self):
        first = generate_questions(self.db, "Mixed", 10, lambda t: t, rng=random.Random(5))
        again = generate_questions(self.db, "Mixed", 10, lambda t: t,
                                   existing_solutions={q.solution for q in first},
                                   rng=random.Random(5))
        overlap = {normalize_sql(q.solution) for q in first} & {normalize_sql(q.solution) for q in again}
        self.assertFalse(overlap)

    def test_order_matters_questions_are_tie_free(self):
        qs = generate_questions(self.db, "Easy", 20, lambda t: t, rng=random.Random(11))
        for q in qs:
            if q.order_matters:
                self.assertIn("ORDER BY", q.solution)

    def test_generated_question_roundtrips_through_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = QuestionStore(data_dir=Path(tmp))
            q = generate_questions(self.db, "Easy", 1, store.new_id, rng=random.Random(1))[0]
            store.save_custom(q)
            loaded = [x for x in store.load_all() if x.is_custom]
            self.assertTrue(loaded[0].generated)

    def test_bad_difficulty(self):
        with self.assertRaises(ValueError):
            generate_questions(self.db, "Impossible", 1, lambda t: t)


if __name__ == "__main__":
    unittest.main()
