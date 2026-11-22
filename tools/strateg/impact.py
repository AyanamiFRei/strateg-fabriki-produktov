"""Анализ влияния новых данных: какие утверждения, расчёты, разделы и решения затронуты.

Алгоритм: от изменённых записей идём по обратным рёбрам depends_on/derived_from/supports,
по входам расчётов K (в том числе K→K), к разделам документов с якорями и к основаниям решений.
Затронутые расчёты пересчитываются (они детерминированы), отчёт показывает «было → стало».
Принятые решения не переписываются: при пересечении порога нужно новое решение (supersedes).
"""
from __future__ import annotations

import re

from . import analysis, store
from .check import anchors_in
from .store import Project, append_jsonl, now, op_id


def changed_since_last(p: Project) -> list:
    last = ""
    for r in p.journal():
        if r.get("op") == "impact" and r.get("phase") == "done":
            last = r["ts"]
    out = []
    for c in p.claims().values():
        if c.get("ts", "") > last and (c.get("v", 1) > 1 or c["status"] != "active"):
            out.append(c["id"])
    for s in p.sources().values():
        if s.get("status") == "retracted" and s.get("ts", "") > last:
            out.append(s["id"])
    return out


def closure(p: Project, start: list) -> dict:
    claims, calcs, decs = p.claims(), p.calcs(), p.decisions()
    rev: dict = {}
    for c in claims.values():
        for l in c.get("links", []):
            if l.get("rel") in ("depends_on", "derived_from", "supports"):
                rev.setdefault(l["to"], set()).add(c["id"])
        for r in c.get("refs", []):
            rev.setdefault(r.get("source"), set()).add(c["id"])
    for k, v in calcs.items():
        for ref in (v["spec"].get("inputs") or {}).values():
            rev.setdefault(ref, set()).add(k)
    seen, queue = set(start), list(start)
    while queue:
        x = queue.pop()
        for y in rev.get(x, ()):
            if y not in seen:
                seen.add(y)
                queue.append(y)
    affected = seen - set(start)
    sections = []
    ddir = p.p("deliverables")
    if ddir.exists():
        for f in sorted(ddir.glob("*.md")):
            if f.name.startswith(("IMPACT", "RUN_REPORT", "STRATEGY")):
                continue
            head = "(начало)"
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.startswith("#"):
                    head = line.strip("# ").strip()
                hit = set(anchors_in(line)) & seen
                if hit:
                    sections.append((f.name, head, sorted(hit)))
    sec_map: dict = {}
    for name, head, ids in sections:
        sec_map.setdefault((name, head), set()).update(ids)
    dec_hit = {d["id"]: sorted(set(d.get("basis", [])) & seen) for d in decs.values()
               if set(d.get("basis", [])) & seen and d["status"] in ("accepted", "proposed")}
    return {"start": start, "claims": sorted(a for a in affected if a in claims),
            "calcs": sorted(a for a in seen if a in calcs), "sections": sec_map, "decisions": dec_hit}


def run(p: Project, ids: list | None = None, mark: bool = True) -> str:
    start = ids or changed_since_last(p)
    if not start:
        return "Нет изменённых записей с прошлого анализа влияния. Укажите --ids F12,A07."
    cl = closure(p, start)
    before = {k: (v["out"] or {}).get("result", {}).get("value") for k, v in p.calcs().items()}
    recalc = []
    blocked = []
    for k in _order(p, cl["calcs"]):
        try:
            out = analysis.run(p, k, force=True)
        except store.StError as e:
            blocked.append((k, str(e)))
            continue
        recalc.append((k, before.get(k), out["result"]["value"], out["result"].get("unit", ""), out.get("title")))
    claims = p.claims()
    if mark:
        for cid in cl["claims"]:
            c = claims[cid]
            if c["status"] == "active" and c["kind"] in ("agent_inference", "forecast", "hypothesis"):
                append_jsonl(p.claims_path, dict(c, status="under_review", v=c["v"] + 1, ts=now(),
                                                 review_reason=f"затронуто изменением {', '.join(start)}"))
    L = [f"# Анализ влияния новых данных · {store.today()}", "",
         f"Изменились: {', '.join(start)}. Затронуто по графу зависимостей: {len(cl['claims'])} утверждений, "
         f"{len(recalc)} расчётов, {len(cl['sections'])} разделов документов, {len(cl['decisions'])} решений.", ""]
    for sid in start:
        c = claims.get(sid)
        if c:
            L.append(f"- {sid} ({c['kind']}, v{c['v']}, {c['status']}): {c['text']}"
                     + (f" — изменение: {c.get('change')}" if c.get("change") else ""))
    L += ["", "## Расчёты: было → стало", "", "| Расчёт | Было | Стало | Изменилось |", "|---|---:|---:|---|"]
    for k, b, a, unit, title in recalc:
        L.append(f"| {k} {title or ''} | {analysis.fmt_value(b)} | {analysis.fmt_value(a)} {unit} | "
                 f"{'да' if b != a else 'подтвердилось'} |")
    if blocked:
        L += ["", "## Расчёты, которые нельзя пересчитать", ""] + [
            f"- {k}: {msg} — замените вход в analysis/{k}.json или удалите расчёт" for k, msg in blocked]
    L += ["", "## Утверждения, требующие пересмотра", ""]
    L += [f"- {cid} [{claims[cid]['kind']}]: {claims[cid]['text'][:120]}" for cid in cl["claims"]] or ["- нет"]
    L += ["", "## Разделы документов, которые нужно переписать", ""]
    L += [f"- {name} → «{head}» (якоря {', '.join(sorted(ids))})" for (name, head), ids in cl["sections"].items()] or ["- нет"]
    L += ["", "## Решения", ""]
    decs = p.decisions()
    revisiting = []
    if mark:
        for did in cl["decisions"]:
            d = decs[did]
            if d["status"] == "accepted":
                append_jsonl(p.decisions_path, dict(d, status="revisiting", v=d["v"] + 1, ts=now(),
                                                    revisit_reason=f"изменились основания: {', '.join(cl['decisions'][did])}"))
                revisiting.append(did)
        decs = p.decisions()
    for did, hit in cl["decisions"].items():
        d = decs[did]
        L.append(f"- {did} ({d['status']}): «{d['question']}» опирается на {', '.join(hit)}. "
                 + ("Принятое решение не редактируется: если вывод меняется, оформите новое решение "
                    f"(python st.py decide supersede {did} <файл.json>) и подтвердите у человека; если вывод "
                    f"подтвердился — python st.py decide confirm {did} --note \"…\"."
                    if d["status"] in ("accepted", "revisiting") else "Решение ещё не принято — обновите основания."))
    if not cl["decisions"]:
        L.append("- не затронуты")
    L += ["", "Формулировка для пользователя: перечислите, что **изменилось**, а что **подтвердилось** "
          "относительно прежнего суждения; меняется ли рекомендация."]
    md = "\n".join(L) + "\n"
    name = f"IMPACT-{store.today()}.md"
    f = p.p("deliverables", name)
    i = 2
    while f.exists():
        f = p.p("deliverables", f"IMPACT-{store.today()}-{i}.md")
        i += 1
    store.atomic_write(f, md)
    p.log(op="impact", op_id=op_id("impact", [start, now()]), phase="done", note=f.name,
          artifacts=[{"path": f"deliverables/{f.name}", "sha256": store.sha256_file(f)}])
    p._last_revisiting = revisiting
    return md


def _order(p: Project, ks: list) -> list:
    specs = {k: v["spec"] for k, v in p.calcs().items()}
    out, seen = [], set()

    def visit(k):
        if k in seen:
            return
        seen.add(k)
        for ref in (specs.get(k, {}).get("inputs") or {}).values():
            if ref in ks:
                visit(ref)
        out.append(k)

    for k in sorted(ks):
        visit(k)
    return out
