"""Стоимость, отчёт о прогоне (RUN_REPORT.md) и сборка итогового документа (STRATEGY.md)."""
from __future__ import annotations

import math
import re

from . import store
from .check import STAGE_RU, anchors_in
from .store import Project, append_jsonl, now, read_json

# ------------------------------------------------------------------ стоимость


def _cost_cfg() -> dict:
    return read_json(store.CONFIG / "cost.json", {})


def estimate_tokens(chars: int, lang: str = "ru") -> int:
    k = _cost_cfg().get("chars_per_token", {}).get(lang, 3.0)
    return math.ceil(chars / k)


def log_cost(p: Project, *, stage=None, in_tok=0, out_tok=0, tier="strong", basis="estimate", usd=None,
             cat="model", note=None, chars_in=None, chars_out=None) -> dict:
    cfg = _cost_cfg()
    if chars_in:
        in_tok = estimate_tokens(chars_in)
    if chars_out:
        out_tok = estimate_tokens(chars_out)
    if usd is None:
        price = cfg.get("price_usd_per_mtok", {}).get(tier, {"in": 3.0, "out": 15.0})
        usd = in_tok / 1e6 * price["in"] + out_tok / 1e6 * price["out"]
    rec = {"ts": now(), "stage": stage or p.task()["stage"], "cat": cat, "tier": tier, "in_tok": in_tok,
           "out_tok": out_tok, "basis": basis, "usd": round(usd, 4), "note": note}
    append_jsonl(p.cost_path, rec)
    return rec


def log_human(p: Project, minutes: float, what: str) -> dict:
    rec = {"ts": now(), "stage": p.task()["stage"], "cat": "human", "human_min": minutes, "note": what,
           "basis": "reported", "usd": 0}
    append_jsonl(p.cost_path, rec)
    return rec


def cost_summary(p: Project) -> dict:
    recs = store.read_jsonl(p.cost_path)
    usd = sum(r.get("usd") or 0 for r in recs)
    tok = sum((r.get("in_tok") or 0) + (r.get("out_tok") or 0) for r in recs)
    hm = sum(r.get("human_min") or 0 for r in recs)
    bases = {r.get("basis") for r in recs if r.get("cat") != "human"}
    basis = "оценка" if bases <= {"estimate", None} else "частично по данным IDE" if "estimate" in bases else "по данным IDE"
    return {"usd": usd, "tokens": tok, "human_min": hm, "basis": basis, "records": recs}


# ------------------------------------------------------------------ RUN_REPORT


def run_report(p: Project) -> str:
    t = p.task()
    j = p.journal()
    cs = cost_summary(p)
    by_stage: dict = {}
    for r in cs["records"]:
        s = r.get("stage") or "—"
        d = by_stage.setdefault(s, {"usd": 0.0, "tok": 0, "human": 0.0})
        d["usd"] += r.get("usd") or 0
        d["tok"] += (r.get("in_tok") or 0) + (r.get("out_tok") or 0)
        d["human"] += r.get("human_min") or 0
    ops = {}
    for r in j:
        if r.get("phase") in ("done", "skipped_cached", "fail"):
            key = (r.get("op"), r.get("phase"))
            ops[key] = ops.get(key, 0) + 1
    fails = [r for r in j if r.get("phase") == "fail"]
    routes = [r for r in j if r.get("phase") in ("route", "route_corrected")]
    gates = [r for r in j if r.get("op") in ("gate", "human_gate")]
    human = [r for r in cs["records"] if r.get("cat") == "human"]
    t0 = j[0]["ts"] if j else now()
    t1 = j[-1]["ts"] if j else now()
    L = [f"# Отчёт о прогоне: {t.get('title', p.slug)}", "",
         f"Период: {t0} — {t1}. Итог стадии: {STAGE_RU[t['stage']]} ({t['status']}).", "",
         "## Время и стоимость по стадиям", "",
         "| Стадия | Токены (≈) | $ (≈) | Минуты человека |", "|---|---:|---:|---:|"]
    for s, d in by_stage.items():
        L.append(f"| {STAGE_RU.get(s, s)} | {d['tok']:,} | {d['usd']:.2f} | {d['human']:.0f} |".replace(",", " "))
    L.append(f"| **Итого** | **{cs['tokens']:,}** | **{cs['usd']:.2f}** | **{cs['human_min']:.0f}** |".replace(",", " "))
    L += ["", f"Основание оценки: {cs['basis']}. Токены оцениваются по числу символов "
          "(коэффициент в config/cost.json), если IDE не показывает точный расход; точные цифры из IDE "
          "вносятся командой `cost log --basis reported`.", "",
          "## Операции", ""]
    for (op, ph), n in sorted(ops.items(), key=lambda x: (str(x[0][0]), str(x[0][1]))):
        L.append(f"- {op} · {ph}: {n}")
    L += ["", f"Повторы, пропущенные как уже выполненные (без тихого повторного выполнения): "
          f"{sum(n for (op, ph), n in ops.items() if ph == 'skipped_cached')}"]
    L += ["", "## Ошибки и сбои", ""] + ([f"- {r['ts']} {r.get('op')}: {r.get('error') or r.get('errors')}"
                                          for r in fails] or ["- нет"])
    L += ["", "## Маршрутизация", ""] + ([f"- {r.get('phase')}: {r.get('route') or r.get('note')}" for r in routes]
                                        or ["- исправлений маршрута не было"])
    L += ["", "## Участие человека", ""] + ([f"- {r['ts'][:16]} {r.get('human_min')} мин: {r.get('note')}"
                                             for r in human] or ["- не зафиксировано"])
    L += [f"- ворота: " + "; ".join(f"{r.get('stage')}:{r.get('phase')} {r.get('note') or ''}".strip()
                                    for r in gates[-10:])]
    if t.get("warnings"):
        L += ["", "## Невыполненные мягкие проверки (на момент последних ворот)", ""] + \
             [f"- {w}" for w in t["warnings"]]
    md = "\n".join(L) + "\n"
    store.atomic_write(p.p("deliverables", "RUN_REPORT.md"), md)
    return md


# ------------------------------------------------------------------ STRATEGY.md

ORDER = ["situation.md", "product_strategy.md", "comms_strategy.md", "validation_plan.md", "options.md"]
LEGEND = ("Легенда: [F] факт из источника · [A] допущение · [H] гипотеза · [P] прогноз · [I] вывод агента · "
          "[Y] синтетика (не доказательство) · [K] расчёт · [S] источник · [D] решение · [O] вариант. "
          "Происхождение любого якоря: `python st.py why <ID>`.")


def sources_table(p: Project, text: str) -> list[str]:
    """Таблица происхождения: все якоря документа и, транзитивно, все входы расчётов —
    чтобы любой расчёт можно было повторить по одной таблице."""
    ids = []
    claims, sources, calcs = p.claims(), p.sources(), p.calcs()

    def add(i):
        if i in ids:
            return
        ids.append(i)
        if i in calcs:
            for ref in (calcs[i]["spec"].get("inputs") or {}).values():
                add(ref)

    for i in anchors_in(text):
        add(i)
    ids.sort(key=lambda x: (x[0], int(x[1:]) if x[1:].isdigit() else 0))
    rows = ["| ID | Что это | Значение | Откуда |", "|---|---|---|---|"]
    for i in ids:
        if i in claims:
            c = claims[i]
            v = (c.get("value") or {})
            val = f"{v.get('num')} {v.get('unit') or ''}".strip() if v.get("num") is not None else ""
            frm = ", ".join(f"{r.get('source')} ({r.get('loc') or '—'})" for r in c.get("refs", [])) or \
                  ", ".join(l["to"] for l in c.get("links", []) if l.get("rel") in ("depends_on", "derived_from")) or \
                  (c.get("test") and f"проверить: {c['test']}") or "—"
            rows.append(f"| {i} | {_kind_ru(c['kind'])}: {c['text'][:90]} | {val} | {frm[:120]} |")
        elif i in calcs:
            out = calcs[i]["out"] or {}
            res = out.get("result", {})
            ins = ", ".join(f"{k}←{u['ref']}" for k, u in (out.get("inputs") or {}).items()) or "параметры в K-файле"
            rows.append(f"| {i} | расчёт {out.get('fn')}: {out.get('title') or ''} | {res.get('value')} {res.get('unit', '')} | {ins} |")
        elif i in sources:
            s = sources[i]
            rows.append(f"| {i} | источник: {s.get('title')} | — | {s.get('url') or s.get('file') or ''} |")
    return rows


def _kind_ru(k):
    from .ledger import KIND_RU
    return KIND_RU.get(k, k)


def assemble_strategy(p: Project, summary_file: str = "summary.md") -> str:
    """STRATEGY.md = резюме + разделы в порядке ORDER + таблица «откуда эти числа»."""
    t = p.task()
    parts = [f"# Стратегия: {t.get('title', p.slug)}", "", f"_{LEGEND}_", ""]
    sm = p.p("deliverables", summary_file)
    if sm.exists():
        parts += [sm.read_text(encoding="utf-8").strip(), ""]
    body = []
    for name in ORDER:
        f = p.p("deliverables", name)
        if f.exists():
            txt = f.read_text(encoding="utf-8").strip()
            txt = re.sub(r"^(#+) ", r"#\1 ", txt, flags=re.M) if txt.startswith("# ") else txt
            body.append(txt)
    parts += ["\n\n---\n\n".join(body)]
    if p.p("deliverables", "critique.md").exists():
        parts += ["", "---", "", "_Независимая критика и что по ней сделано: `deliverables/critique.md`. "
                  "Отчёт о времени и стоимости: `deliverables/RUN_REPORT.md`._"]
    all_text = "\n".join(parts)
    parts += ["", "---", "", "## Откуда эти числа", ""] + sources_table(p, all_text)
    md = "\n".join(parts) + "\n"
    store.atomic_write(p.p("deliverables", "STRATEGY.md"), md)
    store.atomic_write(p.p("deliverables", "STRATEGY-reader.md"), reader_version(md))
    return md


def reader_version(md: str) -> str:
    """Версия для руководителя: без служебных якорей, легенды и таблицы происхождения.
    Проверяемая версия с якорями — STRATEGY.md; числа в обеих одинаковые."""
    cut = md.find("## Откуда эти числа")
    body = md[:cut] if cut > 0 else md
    body = re.sub(r"^_Легенда:.*?_\s*$", "", body, flags=re.M)
    body = re.sub(r"\s?\[(?:[FAHPIYSKDTOQ]\d{2,}(?:[,;]\s*)?)+\]", "", body)
    body = re.sub(r"_Независимая критика.*?_", "", body, flags=re.S)
    body = re.sub(r"`[^`]*st\.py[^`]*`", "", body)
    # После удаления якорей остаются двойные точки: «руб. [K25].» → «руб..».
    body = re.sub(r"(?<!\.)\.\.(?!\.)", ".", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    head = ("> Версия для чтения. Источник и расчёт каждого числа — в проверяемой версии STRATEGY.md "
            "(якоря вида [K23] и таблица «Откуда эти числа»).\n\n")
    first_nl = body.find("\n")
    return body[:first_nl + 1] + "\n" + head + body[first_nl + 1:].lstrip()
