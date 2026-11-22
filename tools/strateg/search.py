"""Поиск по формулировке, смыслу и связям без платной инфраструктуры.

- формулировка: BM25 по основам слов (облегчённый русский стеммер, ё→е);
- смысл: глоссарий синонимов (kb/glossary.md: строки «a = b = c») + перефразировки запроса от модели IDE
  (несколько --q), результаты сливаются через Reciprocal Rank Fusion;
- связи: у каждого найденного утверждения показываются соседи (подтверждает/опровергает/зависит).
Отозванные и заменённые записи скрыты (--all показывает); выводы агента помечены как «не доказательство».
"""
from __future__ import annotations

import math
import re
from collections import Counter

from . import store
from .store import Project

_ENDINGS = sorted("""ами ями ого его ому ему ыми ими ией ией ой ей ий ый ая яя ое ее ые ие ую юю ом ем ах ях
ам ям ов ев ия ья ие ье ию ью ть ти ет ют ут ит ат ят ешь ишь ем им ете ите ло ла ли ость ости ение ения ений
ание ания аний ов а я о е ы и у ю ь""".split(), key=len, reverse=True)
_WORD = re.compile(r"[a-zа-яё0-9]+", re.I)


def stem(w: str) -> str:
    w = w.lower().replace("ё", "е")
    if len(w) <= 4 or w.isdigit():
        return w
    for e in _ENDINGS:
        if w.endswith(e) and len(w) - len(e) >= 3:
            return w[: -len(e)]
    return w


def tokens(text: str) -> list[str]:
    return [stem(w) for w in _WORD.findall(text or "")]


def _glossary(p: Project | None = None) -> list[set]:
    groups = []
    for f in [store.ROOT / "kb" / "glossary.md"] + ([p.p("glossary.md")] if p else []):
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith("- ") and " = " in line and "≠" not in line:
                groups.append({stem(x.strip()) for x in re.split(r"\s=\s", line[2:].split("—")[0]) if x.strip()})
    return groups


def expand(q: str, p: Project | None = None) -> list[str]:
    toks = tokens(q)
    extra = []
    for g in _glossary(p):
        if any(t in g for t in toks):
            extra += list(g)
    return toks + extra


def _docs(p: Project | None, scopes: set, include_all: bool):
    docs = []
    if p and "claims" in scopes:
        for c in p.claims().values():
            if not include_all and c["status"] in ("retracted", "superseded"):
                continue
            docs.append({"id": c["id"], "scope": "claims", "text": c["text"] + " " + (c.get("key") or ""),
                         "meta": c})
    if p and "sources" in scopes:
        from .ledger import snapshot_text
        for s in p.sources().values():
            if s["status"] != "active" and not include_all:
                continue
            txt = snapshot_text(p, s["id"])
            for i, chunk in enumerate(_chunks(txt)):
                docs.append({"id": f"{s['id']}#{i + 1}", "scope": "sources", "text": chunk, "meta": s})
    if p and "deliverables" in scopes and p.p("deliverables").exists():
        for f in sorted(p.p("deliverables").glob("*.md")):
            for i, chunk in enumerate(_chunks(f.read_text(encoding="utf-8"))):
                docs.append({"id": f"{f.name}#{i + 1}", "scope": "deliverables", "text": chunk, "meta": {}})
    if p and "decisions" in scopes:
        for d in p.decisions().values():
            docs.append({"id": d["id"], "scope": "decisions", "text": d["question"] + " " + str(d.get("chosen")),
                         "meta": d})
    if "kb" in scopes:
        for f in sorted((store.ROOT / "kb").rglob("*.md")):
            for i, chunk in enumerate(_chunks(f.read_text(encoding="utf-8"))):
                docs.append({"id": f"kb/{f.relative_to(store.ROOT / 'kb').as_posix()}#{i + 1}", "scope": "kb",
                             "text": chunk, "meta": {}})
    return docs


def _chunks(text: str, size: int = 900) -> list[str]:
    paras, out, cur = re.split(r"\n\s*\n", text), [], ""
    for para in paras:
        if len(cur) + len(para) > size and cur:
            out.append(cur)
            cur = ""
        cur += para + "\n\n"
    if cur.strip():
        out.append(cur)
    return out


def bm25(docs: list, q_toks: list, k1=1.5, b=0.75) -> list:
    N = len(docs) or 1
    toks = [tokens(d["text"]) for d in docs]
    avg = sum(len(t) for t in toks) / N if toks else 1
    df = Counter()
    for t in toks:
        df.update(set(t))
    scores = []
    for i, t in enumerate(toks):
        tf = Counter(t)
        s = 0.0
        for q in set(q_toks):
            if q in tf:
                idf = math.log(1 + (N - df[q] + 0.5) / (df[q] + 0.5))
                s += idf * tf[q] * (k1 + 1) / (tf[q] + k1 * (1 - b + b * len(t) / avg))
        if s > 0:
            scores.append((s, i))
    scores.sort(reverse=True)
    return [i for _, i in scores]


def search(p: Project | None, queries: list[str], scopes=("claims", "sources", "deliverables", "decisions", "kb"),
           kinds: list | None = None, top: int = 8, include_all: bool = False) -> list[dict]:
    docs = _docs(p, set(scopes), include_all)
    if kinds:
        docs = [d for d in docs if d["scope"] != "claims" or d["meta"].get("kind") in kinds]
    rrf: Counter = Counter()
    for q in queries:
        for rank, i in enumerate(bm25(docs, expand(q, p))[:50]):
            rrf[i] += 1 / (60 + rank)
    res = []
    claims = p.claims() if p else {}
    for i, sc in rrf.most_common(top):
        d = docs[i]
        item = {"id": d["id"], "scope": d["scope"], "score": round(sc, 4), "text": d["text"].strip()[:300]}
        m = d["meta"]
        if d["scope"] == "claims":
            item["kind"] = m["kind"]
            item["status"] = m["status"]
            item["links"] = [f"{l['rel']}→{l['to']}" for l in m.get("links", [])]
            item["linked_from"] = [f"{c['id']}:{l['rel']}" for c in claims.values() for l in c.get("links", [])
                                   if l.get("to") == m["id"]][:6]
            if m["kind"] == "agent_inference":
                item["note"] = "прежний вывод агента — не доказательство; ссылайтесь на его источники"
        if d["scope"] == "deliverables":
            item["note"] = "текст прежнего документа — не доказательство"
        res.append(item)
    return res
