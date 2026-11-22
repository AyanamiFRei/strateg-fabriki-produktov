import json
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import FIX, draft, jsonl, make_root, setup_tiny, st

STAGES = ["framing", "collect", "diagnosis", "options", "strategy", "validation", "review"]


class TestFullPath(unittest.TestCase):
    def test_init_to_strategy(self):
        root = make_root()
        p = setup_tiny(root)
        for name in ("situation.md", "options.md", "critique.md", "product_strategy.md", "comms_strategy.md",
                     "validation_plan.md"):
            draft(p, name)
        code, out, err = st(root, "stage", "done", "options")
        self.assertEqual(code, 2, out + err)  # нельзя перепрыгнуть через стадии и ворота человека
        self.assertIn("предыдущие стадии", err)
        self.assertEqual(st(root, "stage", "approve", "options", "--note", "да")[0], 1)  # не ждёт подтверждения
        for s in STAGES:
            code, out, err = st(root, "stage", "done", s)
            if code == 3:
                code, out, err = st(root, "stage", "approve", s, "--note", "ок, продолжаем")
            if s == "review":
                break
            self.assertEqual(code, 0, f"{s}: {out}{err}")
            if s == "validation":
                self.assertEqual(st(root, "report", "strategy")[0], 0)
        strat = (p / "deliverables" / "STRATEGY.md").read_text(encoding="utf-8")
        self.assertIn("Легенда", strat)
        self.assertIn("Откуда эти числа", strat)
        self.assertIn("| K01 |", strat)
        code, out, err = st(root, "check", "all")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(st(root, "report", "run")[0], 0)
        self.assertTrue((p / "deliverables" / "RUN_REPORT.md").exists())
        self.assertIn("Сборка", (p / "PROGRESS.md").read_text(encoding="utf-8"))


class TestResumeMidImport(unittest.TestCase):
    def test_fault_then_resume(self):
        root = make_root()
        p = setup_tiny(root, import_claims=False)
        shutil.copy2(FIX / "inbox.jsonl", p / "inbox" / "a.jsonl")
        code, out, err = st(root, "claim", "import", env_extra={"STRATEG_FAULT": "claim_import:after=3"})
        self.assertEqual(code, 1, out + err)
        self.assertEqual(len(jsonl(p / "evidence" / "claims.jsonl")), 3)
        code, out, err = st(root, "resume")
        self.assertIn("3 из 8", out)
        self.assertIn("claim import", out)
        code, out, err = st(root, "claim", "import")
        self.assertEqual(code, 0, out + err)
        self.assertIn("Пропущено", out)
        rows = jsonl(p / "evidence" / "claims.jsonl")
        self.assertEqual(len(rows), 8)
        self.assertEqual(len({r["text"] for r in rows}), 8)
        self.assertTrue(list((p / "inbox" / "done").glob("*.receipt.json")))


class TestImpact(unittest.TestCase):
    def test_rate_500_to_350(self):
        root = make_root()
        p = setup_tiny(root)
        draft(p, "product_strategy.md")
        self.assertEqual(st(root, "check", "strategy")[0], 0)
        shutil.copy2(FIX / "D.json", p / "decisions" / "D.json")
        self.assertEqual(st(root, "decide", "new", p / "decisions" / "D.json")[0], 0)
        self.assertEqual(st(root, "decide", "accept", "D01")[0], 3)  # без реплики человека
        code, out, err = st(root, "decide", "accept", "D01", "--note", "согласен")
        self.assertEqual(code, 0, out + err)
        lh = json.loads((p / "decisions" / "decisions.jsonl").read_text(encoding="utf-8").splitlines()[-1])["ledger_hash"]
        st(root, "source", "add", "--note", "Финансы: ставка составляет 350 руб. за месяц", "--title", "Финансы")
        (p / "inbox" / "b.jsonl").write_text(json.dumps({"kind": "fact", "supersedes": "F01", "change": "новая ставка",
            "text": "Ставка 350 руб.", "key": "rate", "value": {"num": 350, "unit": "руб."},
            "refs": [{"source": "S02", "quote": "ставка составляет 350 руб"}]}, ensure_ascii=False) + "\n",
            encoding="utf-8")
        self.assertEqual(st(root, "claim", "import")[0], 0)
        code, out, err = st(root, "impact", "--ids", "F01")
        self.assertEqual(code, 3, out + err)
        self.assertIn("12 000", out)
        self.assertIn("17 143", out)
        self.assertIn("D01 (revisiting)", out)
        decs = jsonl(p / "decisions" / "decisions.jsonl")
        self.assertEqual(decs[-1]["status"], "revisiting")
        self.assertEqual(decs[-1]["ledger_hash"], lh)
        self.assertEqual(st(root, "check", "strategy")[0], 2)  # текст устарел
        f = p / "deliverables" / "product_strategy.md"
        f.write_text(f.read_text(encoding="utf-8").replace("12 000", "17 143").replace("500 руб.", "350 руб."),
                     encoding="utf-8")
        code, out, err = st(root, "check", "strategy")
        self.assertEqual(code, 0, out + err)
        shutil.copy2(FIX / "D.json", p / "decisions" / "D2.json")
        code, out, err = st(root, "decide", "supersede", "D01", p / "decisions" / "D2.json")
        self.assertEqual(code, 0, out + err)
        d02 = [d for d in jsonl(p / "decisions" / "decisions.jsonl") if d["id"] == "D02"][-1]
        self.assertEqual(d02["supersedes"], "D01")


class TestInvariants(unittest.TestCase):
    def setUp(self):
        self.root = make_root()
        self.p = setup_tiny(self.root)

    def imp(self, row):
        (self.p / "inbox" / "x.jsonl").write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
        return st(self.root, "claim", "import")

    def test_1_fact_needs_quote(self):
        self.assertEqual(self.imp({"kind": "fact", "text": "x", "refs": [{"source": "S01", "quote": "этого нет в брифе"}]})[0], 2)
        self.assertEqual(self.imp({"kind": "fact", "text": "x", "origin": "agent",
                                   "refs": [{"source": "S01", "quote": "Цель года"}]})[0], 2)
        st(self.root, "source", "retract", "S01", "--reason", "тест")
        self.assertEqual(self.imp({"kind": "fact", "text": "y", "refs": [{"source": "S01", "quote": "Цель года"}]})[0], 2)

    def test_2_synthetic(self):
        self.assertEqual(self.imp({"kind": "synthetic", "text": "73 % клиентов хотят",
                                   "links": [{"rel": "supports", "to": "H01"}]})[0], 2)
        self.assertEqual(self.imp({"kind": "forecast", "text": "p", "links": [{"rel": "depends_on", "to": "Y01"}]})[0], 2)
        d = self.p / "decisions" / "dy.json"
        d.write_text(json.dumps({"question": "q", "basis": ["Y01"]}), encoding="utf-8")
        self.assertEqual(st(self.root, "decide", "new", d)[0], 2)

    def test_3_number_vs_calc(self):
        (self.p / "deliverables" / "product_strategy.md").write_text("# Э\nНужно 13 000 месяцев [K01].\n", encoding="utf-8")
        code, out, err = st(self.root, "check", "strategy")
        self.assertEqual(code, 2)
        self.assertIn("И3", out)

    def test_4_accepted_decision_frozen(self):
        shutil.copy2(FIX / "D.json", self.p / "decisions" / "D.json")
        st(self.root, "decide", "new", self.p / "decisions" / "D.json")
        st(self.root, "decide", "accept", "D01", "--note", "да")
        f = self.p / "decisions" / "decisions.jsonl"
        last = jsonl(f)[-1]
        last.update(chosen="O03", v=last["v"] + 1)
        with open(f, "a", encoding="utf-8") as h:
            h.write(json.dumps(last, ensure_ascii=False) + "\n")
        code, out, err = st(self.root, "check", "after")
        self.assertEqual(code, 2)
        self.assertIn("И4", out)
        self.assertEqual(st(self.root, "decide", "new", self.p / "decisions" / "D.json")[0], 0)  # новое D02 можно


class TestReviewRegressions(unittest.TestCase):
    """Регрессии по находкам ревью кода (docs/design/CODE-REVIEW.md)."""

    def setUp(self):
        self.root = make_root()
        self.p = setup_tiny(self.root)

    def imp(self, rows):
        (self.p / "inbox" / "r.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                                  encoding="utf-8")
        return st(self.root, "claim", "import")

    def test_c1_tampered_snapshot_rejected(self):
        snap = self.p / "evidence" / "raw" / "S01.md"
        snap.write_text(snap.read_text(encoding="utf-8").replace("Компания продаёт", "Отток критичен для бизнеса. Компания продаёт"),
                        encoding="utf-8")
        code, out, err = self.imp([{"kind": "fact", "text": "x", "refs": [{"source": "S01", "quote": "Отток критичен для бизнеса"}]}])
        self.assertEqual(code, 2)
        self.assertIn("изменён после регистрации", err)

    def test_c2_link_to_rejected_row_rejected(self):
        code, out, err = self.imp([
            {"tmp": "bad", "kind": "fact", "text": "выдумка", "refs": [{"source": "S01", "quote": "нет такой цитаты"}]},
            {"tmp": "i", "kind": "agent_inference", "text": "вывод", "links": [{"rel": "derived_from", "to": "bad"}]}])
        self.assertEqual(code, 2)
        self.assertIn("отклонённую строку", err)
        ids = [json.loads(l)["id"] for l in (self.p / "evidence" / "claims.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn("I02", ids)

    def test_h3_synthetic_via_inference_blocked(self):
        code, out, err = self.imp([
            {"tmp": "i", "kind": "agent_inference", "text": "вывод", "links": [{"rel": "derived_from", "to": "Y01"}]}])
        self.assertEqual(code, 2)
        self.assertEqual(self.imp([{"kind": "synthetic", "text": "восемь из десяти просили", "links": [{"rel": "supports", "to": "H01"}]}])[0], 2)

    def test_h7_supersedes_kind_change_rejected(self):
        code, out, err = self.imp([{"kind": "assumption", "supersedes": "F01", "text": "x", "test": "t"}])
        self.assertEqual(code, 2)
        self.assertEqual(self.imp([{"kind": "fact", "supersedes": "F99", "text": "x",
                                    "refs": [{"source": "S01", "quote": "Цель года"}]}])[0], 2)

    def test_h8_corrected_row_not_skipped(self):
        row = {"kind": "hypothesis", "text": "новая гипотеза", "test": "пилот"}
        self.assertEqual(self.imp([row])[0], 0)
        code, out, err = self.imp([dict(row, test="пилот с контролем")])
        self.assertEqual(code, 0)
        self.assertNotIn("Пропущено", out)

    def test_h6_impact_survives_retracted_input(self):
        st(self.root, "claim", "retract", "F01", "--reason", "тест")
        code, out, err = st(self.root, "impact", "--ids", "F01")
        self.assertIn(code, (0, 3), err)
        self.assertIn("нельзя пересчитать", out)

    def test_m14_arithmetic_dos(self):
        import sys
        from helpers import REPO
        sys.path.insert(0, str(REPO / "tools"))
        from strateg import calc
        with self.assertRaises(ValueError):
            calc.arithmetic("9**9**9**9", {})
        with self.assertRaises(ValueError):
            calc.arithmetic("a*2", {"a": [1, 2]})

    def test_m20_interrupted_after_failed_restart(self):
        j = self.p / "state" / "journal.jsonl"
        rows = [
            {"ts": "2026-01-01T00:00:00Z", "op": "calc", "op_id": "calc:test", "phase": "start"},
            {"ts": "2026-01-01T00:01:00Z", "op": "calc", "op_id": "calc:test", "phase": "fail"},
            {"ts": "2026-01-01T00:02:00Z", "op": "calc", "op_id": "calc:test", "phase": "start"},
        ]
        with open(j, "a", encoding="utf-8") as f:
            f.write("".join(json.dumps(r) + "\n" for r in rows))
        code, out, err = st(self.root, "resume")
        self.assertEqual(code, 0, err)
        self.assertIn("ПРЕРВАНО", out)
        self.assertIn("2026-01-01T00:02:00Z", out)
        with open(j, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": "2026-01-01T00:03:00Z", "op": "calc", "op_id": "calc:test",
                                "phase": "done"}) + "\n")
        out = st(self.root, "resume")[1]
        self.assertNotIn("2026-01-01T00:02:00Z", out)

    def test_project_flag_after_command(self):
        code, out, err = st(self.root, "resume", "--project", "tiny")
        self.assertEqual(code, 0, err)
        self.assertEqual(st(self.root, "--project", "../../x", "resume")[0], 1)


class TestInjection(unittest.TestCase):
    def test_injection_is_data(self):
        root = make_root()
        p = setup_tiny(root, import_claims=False)
        before = (root / "config" / "allowlist.json").read_bytes()
        # Файл вне репозитория существует, но читать его нельзя (код 2, не «не найден»).
        outside = Path(tempfile.mkdtemp(prefix="strateg-outside-")) / "hostname.txt"
        outside.write_text("test\n", encoding="utf-8")
        code, out, err = st(root, "source", "add", "--file", outside)
        self.assertEqual(code, 2)  # файлы вне репозитория не читаются
        self.assertIn("вне репозитория", err)
        self.assertEqual(st(root, "source", "add", "--file", outside.parent / "missing.txt")[0], 1)
        secret = p / "materials" / ".env"
        secret.write_text("TOKEN=1\n", encoding="utf-8")
        code, out, err = st(root, "source", "add", "--file", secret)
        self.assertEqual(code, 2)  # похожие на секреты файлы не регистрируются
        self.assertIn("секрет", err)
        shutil.copy2(FIX / "inj.html", p / "materials" / "inj.html")
        code, out, err = st(root, "source", "add", "--file", p / "materials" / "inj.html")
        self.assertEqual(code, 0)
        self.assertIn("ВНИМАНИЕ", out)
        snap = (p / "evidence" / "raw" / "S02.md").read_text(encoding="utf-8")
        self.assertIn("<<<UNTRUSTED", snap)
        self.assertIn("НЕДОВЕРЕННЫЕ ДАННЫЕ", snap)
        self.assertEqual(st(root, "source", "add", "--url", "https://evil.example/x")[0], 2)
        self.assertEqual((root / "config" / "allowlist.json").read_bytes(), before)
        self.assertIn("ВНИМАНИЕ", st(root, "resume")[1])
        code, out, err = st(root, "hook", "pre-tool", input_text=json.dumps(
            {"tool_name": "Edit", "tool_input": {"file_path": str(root / "AGENTS.md")}}))
        self.assertEqual(code, 2)


class TestUnicodePaths(unittest.TestCase):
    def test_cyrillic_root_and_cp1251(self):
        root = make_root("Мои проекты/стратег тест")
        setup_tiny(root)
        code, out, err = st(root, "resume", env_extra={"PYTHONIOENCODING": "cp1251"})
        self.assertEqual(code, 0, err)
        self.assertIn("Постановка", out)
        code, out, err = st(root, "init", "семья")
        self.assertEqual(code, 1)
        for f in (root / "projects" / "tiny").rglob("*"):
            self.assertTrue(f.name.isascii(), f.name)
            if f.suffix in (".md", ".jsonl", ".json") and f.is_file():
                b = f.read_bytes()
                self.assertFalse(b.startswith(b"\xef\xbb\xbf"), f)
                self.assertNotIn(b"\r\n", b, f)


class TestSync(unittest.TestCase):
    def test_sync_check(self):
        root = make_root()
        self.assertEqual(st(root, "sync")[0], 0)
        self.assertEqual(st(root, "sync", "--check")[0], 0)
        self.assertIn("@AGENTS.md", (root / "CLAUDE.md").read_text(encoding="utf-8"))
        f = root / ".claude" / "skills" / "collect" / "SKILL.md"
        f.write_text(f.read_text(encoding="utf-8") + "\nправка\n", encoding="utf-8")
        code, out, err = st(root, "sync", "--check")
        self.assertEqual(code, 2)
        self.assertIn("collect", out)
        for g in [root / "CLAUDE.md", root / ".claude" / "settings.json", root / ".mcp.json"]:
            self.assertNotIn(str(root), g.read_text(encoding="utf-8"))


class TestSurface(unittest.TestCase):
    def test_commands_in_docs_exist(self):
        import re
        import sys
        from helpers import REPO
        sys.path.insert(0, str(REPO / "tools"))
        from strateg.cli import build
        cmds = set(build()._subparsers._group_actions[0].choices)
        docs = [REPO / "AGENTS.md"] + list((REPO / ".agents" / "skills").glob("*/SKILL.md"))
        for d in docs:
            for m in re.finditer(r"st\.py (\w[\w-]*)", d.read_text(encoding="utf-8")):
                self.assertIn(m.group(1), cmds, f"{d.name}: st.py {m.group(1)}")
        self.assertLessEqual(len((REPO / "AGENTS.md").read_text(encoding="utf-8").splitlines()), 150)
        for d in (REPO / ".agents" / "skills").glob("*/SKILL.md"):
            self.assertLessEqual(len(d.read_text(encoding="utf-8").splitlines()), 120, d)


class TestMcp(unittest.TestCase):
    def test_mcp_lists_and_calls(self):
        root = make_root()
        setup_tiny(root)
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "why", "arguments": {"id": "K01"}}}]
        code, out, err = st(root, "mcp", input_text="\n".join(json.dumps(m) for m in msgs) + "\n")
        lines = [json.loads(l) for l in out.splitlines() if l.strip()]
        self.assertEqual(len(lines), 3)
        self.assertIn("why", json.dumps(lines[1], ensure_ascii=False))
        self.assertIn("12000", lines[2]["result"]["content"][0]["text"].replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
