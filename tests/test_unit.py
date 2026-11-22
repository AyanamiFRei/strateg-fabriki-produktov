import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from strateg import calc, report, search, store, text  # noqa: E402
from strateg.check import _is_whitelisted, _matches  # noqa: E402


class TestCalc(unittest.TestCase):
    def test_reference_values(self):
        self.assertEqual(calc.break_even_months(6e6)["value"], 12000)
        self.assertEqual(calc.break_even_months(6e6, rate=350)["value"], 17143)
        self.assertEqual(calc.n_two_proportions(.12, .09)["value"], 1638)
        self.assertEqual(calc.n_two_proportions(.12, .08, power=.9)["value"], 1181)
        self.assertEqual(calc.cluster_sample(.12, .09, m=3, icc=.1)["details"]["clusters_per_arm"], 656)
        self.assertAlmostEqual(calc.required_share(8000, 12000)["value"], 0.6667)
        self.assertEqual(calc.recruitment(600, weeks=6)["value"], 100)
        r = calc.pp_vs_relative(.12, .09)
        self.assertEqual(r["value"], -3.0)
        self.assertEqual(r["details"]["relative"], -0.25)
        self.assertEqual(calc.funnel(100, [0.6, 0.5])["value"], 30)
        self.assertEqual(calc.payback([0, 1e6, 2e6, 3e6], [2e6, 1e6, 0, 0])["value"], 3)
        self.assertEqual(calc.stock_flow(6500, 6500, 1000)["value"], 12000)

    def test_arithmetic_is_safe(self):
        self.assertEqual(calc.arithmetic("a*b/2", {"a": 3, "b": 4})["value"], 6)
        with self.assertRaises(ValueError):
            calc.arithmetic("__import__('os')", {})

    def test_ci_and_mde(self):
        ci = calc.ci_diff_proportions(120, 1000, 90, 1000)["details"]
        self.assertLess(ci["ci_low_pp"], -3)
        self.assertGreater(ci["ci_high_pp"], -3)
        self.assertGreater(calc.mde_for_n(.12, 300)["value"], 5)


class TestText(unittest.TestCase):
    def test_quote_normalization(self):
        self.assertTrue(text.quote_in("ещё «важно»", "Это Еще — ВАЖНО, правда"))
        self.assertFalse(text.quote_in("нет такого", "совсем другое"))

    def test_numbers(self):
        n = text.parse_numbers("Итого 17 143 мес. и 66,7 % и 6 млн руб.")
        self.assertEqual([x["value"] for x in n], [17143, 66.7, 6])
        self.assertTrue(n[1]["pct"])
        self.assertEqual(n[2]["scale"], 1e6)

    def test_sentences_keep_abbreviations(self):
        s = text.split_sentences("Вклад 200 000 руб. [K01] при ставке. Второе предложение.")
        self.assertEqual(len(s), 2)

    def test_whitelist_and_match(self):
        for s in ("в Q1 решим", "к 2027 году", "3 варианта", "через 14 дней"):
            nums = text.parse_numbers(s)
            self.assertTrue(all(_is_whitelisted(n, s) for n in nums), s)
        self.assertFalse(_is_whitelisted(text.parse_numbers("42 % клиентов")[0], "42 % клиентов"))
        self.assertTrue(_matches(text.parse_numbers("17 143 мес")[0], [17143.0]))
        self.assertTrue(_matches(text.parse_numbers("66,7 %")[0], [0.6667]))
        self.assertTrue(_matches(text.parse_numbers("6 млн руб")[0], [6000000.0]))
        self.assertFalse(_matches(text.parse_numbers("12 000 мес")[0], [17143.0]))


class TestReaderVersion(unittest.TestCase):
    def test_no_double_period_after_anchor_removal(self):
        md = "# Т\n\nСтоимость 44 тыс. руб. [K25]. Порог 5,5 п.п. [K18].\n"
        out = report.reader_version(md)
        self.assertNotIn("руб..", out)
        self.assertNotIn("п.п..", out)
        self.assertIn("44 тыс. руб.", out)
        self.assertIn("5,5 п.п.", out)
        self.assertNotIn("[K25]", out)


class TestStore(unittest.TestCase):
    def test_torn_line_skipped(self):
        import tempfile
        d = Path(tempfile.mkdtemp())
        f = d / "x.jsonl"
        f.write_text('{"id":"F01","v":1}\n{"id":"F02",\n{"id":"F01","v":2}\n', encoding="utf-8")
        warn = []
        rows = store.read_jsonl(f, warn)
        self.assertEqual(len(rows), 2)
        self.assertIn("строка 2", warn[0])
        self.assertEqual(store.latest(rows)["F01"]["v"], 2)

    def test_bom(self):
        import tempfile
        d = Path(tempfile.mkdtemp())
        f = d / "b.json"
        f.write_bytes("﻿{\"a\": 1}".encode("utf-8"))
        self.assertEqual(store.read_json(f)["a"], 1)


class TestSearch(unittest.TestCase):
    def test_stem_and_yo(self):
        self.assertEqual(search.stem("ещё"), search.stem("еще"))
        self.assertIn("выбыт", search.expand("отток"))


if __name__ == "__main__":
    unittest.main()
