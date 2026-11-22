"""Сопровождение решений: решения D, обязательства T, наблюдения, триггеры пересмотра, «что решать сейчас».

И4: принятое решение не редактируется. Изменение = новое решение с supersedes.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from . import ledger, store
from .store import GateError, Project, StError, append_jsonl, now, op_id, read_json


def _load(path_or_json: str) -> dict:
    s = path_or_json.strip()
    if s.startswith("{"):
        return json.loads(s)
    f = Path(path_or_json)
    if not f.exists():
        raise StError(f"нет файла {path_or_json}")
    return json.loads(f.read_text(encoding="utf-8"))


def new(p: Project, spec: str) -> dict:
    d = _load(spec)
    decs = p.decisions()
    did = d.get("id") or store.next_id(decs.keys(), "D")
    if did in decs and decs[did].get("status") in ("accepted", "revisiting", "superseded"):
        raise GateError(f"И4: {did} уже принято — изменить нельзя. Создайте новое решение с \"supersedes\": \"{did}\"")
    claims = p.claims()
    for b in d.get("basis", []):
        if b.startswith("Y") or ledger.synthetic_in_closure(b, claims):
            raise GateError(f"И2: основание {b} — синтетика или опирается на неё; решение на синтетике не принимается")
        if b not in p.all_ids():
            raise StError(f"основание {b} не найдено в реестре")
    rec = {"id": did, "question": d["question"], "status": "proposed", "date": store.today(),
           "approver": d.get("approver", "руководитель направления"), "driver": d.get("driver"),
           "options": d.get("options", []), "chosen": d.get("chosen"), "rejected": d.get("rejected", {}),
           "basis": d.get("basis", []), "key_assumptions": d.get("key_assumptions", []),
           "expect": d.get("expect"), "kill": d.get("kill", []), "revisit": d.get("revisit", []),
           "due": d.get("due"), "supersedes": d.get("supersedes"), "ledger_hash": None,
           "v": decs[did]["v"] + 1 if did in decs else 1, "ts": now()}
    append_jsonl(p.decisions_path, rec)
    p.log(op="decide_new", op_id=op_id("decide", rec), phase="done", note=did)
    return rec


def accept(p: Project, did: str, note: str) -> dict:
    if not (note or "").strip():
        from .store import NeedHuman
        raise NeedHuman(f"решение принимает человек: python st.py decide accept {did} --note \"<его реплика>\"")
    d = p.decisions().get(did)
    if not d:
        raise StError(f"нет решения {did}")
    if d["status"] == "accepted":
        return dict(d, _cached=True)
    rec = dict(d, status="accepted", accepted_at=now(), accept_note=note, ledger_hash=ledger.ledger_hash(p),
               v=d["v"] + 1, ts=now())
    append_jsonl(p.decisions_path, rec)
    if d.get("supersedes"):
        old = p.decisions().get(d["supersedes"])
        if old:
            append_jsonl(p.decisions_path, dict(old, status="superseded", superseded_by=did, v=old["v"] + 1, ts=now()))
    p.log(op="decide_accept", op_id=op_id("accept", [did]), phase="done", note=did, origin="human")
    return rec


def supersede(p: Project, old_id: str, spec: str) -> dict:
    old = p.decisions().get(old_id)
    if not old:
        raise StError(f"нет решения {old_id}")
    d = _load(spec)
    d["supersedes"] = old_id
    d.pop("id", None)
    return new(p, json.dumps(d, ensure_ascii=False))


def confirm(p: Project, did: str, note: str) -> dict:
    """Пересмотр показал, что решение в силе: статус accepted, новый снимок реестра пишется в журнал."""
    d = p.decisions().get(did)
    if not d or d["status"] != "revisiting":
        raise StError(f"{did} не в статусе revisiting")
    rec = dict(d, status="accepted", reconfirmed_at=now(), reconfirm_note=note,
               reconfirm_ledger_hash=ledger.ledger_hash(p), v=d["v"] + 1, ts=now())
    append_jsonl(p.decisions_path, rec)
    p.log(op="decide_confirm", op_id=op_id("confirm", [did, note]), phase="done", note=did, origin="human")
    return rec


def commit_add(p: Project, what: str, owner: str, due: str, decision: str | None = None,
               blocks: str | None = None) -> dict:
    cm = p.commitments()
    tid = store.next_id(cm.keys(), "T")
    _parse_date(due)
    rec = {"id": tid, "what": what, "owner": owner, "due": due, "decision": decision,
           "blocks": blocks.split(",") if blocks else [], "status": "open", "done_evidence": None, "v": 1, "ts": now()}
    append_jsonl(p.commitments_path, rec)
    return rec


def commit_done(p: Project, tid: str, evidence: str) -> dict:
    c = p.commitments().get(tid)
    if not c:
        raise StError(f"нет обязательства {tid}")
    rec = dict(c, status="done", done_evidence=evidence, v=c["v"] + 1, ts=now())
    append_jsonl(p.commitments_path, rec)
    return rec


def observe(p: Project, key: str, value: float, date: str | None = None, source: str | None = None) -> dict:
    if value is None or not key:
        raise StError("нужны ключ и --value <число>")
    rec = {"ts": now(), "key": key, "value": value, "date": date or store.today(), "source": source}
    append_jsonl(p.observations_path, rec)
    return rec


def _parse_date(s: str) -> _dt.date:
    try:
        return _dt.date.fromisoformat(s[:10])
    except Exception as e:
        raise StError(f"дата в формате ГГГГ-ММ-ДД: {s}") from e


def due(p: Project, today: str | None = None) -> list[str]:
    """Сработавшие триггеры, просроченные обязательства, устаревшие основания, «решить сейчас»."""
    td = _parse_date(today) if today else _dt.date.today()
    out = []
    obs: dict = {}
    for o in store.read_jsonl(p.observations_path):
        obs[o["key"]] = o
    claims, sources = p.claims(), p.sources()
    for d in p.decisions().values():
        if d["status"] not in ("accepted", "proposed", "revisiting"):
            continue
        if d["status"] == "proposed" and d.get("due"):
            dd = _parse_date(d["due"])
            if (dd - td).days <= 14:
                missing = [a for a in d.get("key_assumptions", []) if claims.get(a, {}).get("kind") != "fact"]
                out.append(f"РЕШИТЬ СЕЙЧАС {d['id']} до {d['due']}: {d['question']}"
                           + (f" · не подтверждены допущения: {', '.join(missing)}" if missing else ""))
        for tr in d.get("revisit", []):
            typ = tr.get("type")
            if typ == "date" and _parse_date(tr["at"]) <= td:
                out.append(f"{d['id']}: дата пересмотра {tr['at']} наступила")
            elif typ == "metric" and tr.get("key") in obs and isinstance(obs[tr["key"]].get("value"), (int, float)) \
                    and isinstance(tr.get("value"), (int, float)):
                v = obs[tr["key"]]["value"]
                op, thr = tr.get("op", "<"), tr.get("value")
                hit = (v < thr) if op == "<" else (v > thr) if op == ">" else (v <= thr) if op == "<=" else (v >= thr)
                if hit:
                    out.append(f"{d['id']}: метрика {tr['key']}={v} {op} {thr} — сработал триггер пересмотра")
            elif typ == "claim":
                for cid in tr.get("ids", []):
                    c = claims.get(cid)
                    if c and (c["status"] != "active" or c.get("v", 1) > 1 and c.get("ts", "") > d.get("accepted_at", d["ts"])):
                        out.append(f"{d['id']}: основание {cid} изменилось ({c['status']}, v{c['v']}) — пересмотреть")
            elif typ == "ttl":
                s = sources.get(tr.get("source"))
                if s and s.get("ttl_days"):
                    age = (td - _parse_date(s["retrieved_at"])).days
                    if age > s["ttl_days"]:
                        out.append(f"{d['id']}: источник {s['id']} устарел ({age} дн > {s['ttl_days']})")
        for b in d.get("basis", []):
            c = claims.get(b)
            if c and c["status"] in ("retracted", "superseded", "under_review"):
                out.append(f"{d['id']}: основание {b} теперь {c['status']}")
    for c in p.commitments().values():
        if c["status"] == "open" and _parse_date(c["due"]) < td:
            out.append(f"ПРОСРОЧЕНО {c['id']} ({c['owner']}, срок {c['due']}): {c['what']}")
        elif c["status"] == "open" and (_parse_date(c["due"]) - td).days <= 14:
            out.append(f"скоро срок {c['id']} ({c['owner']}, {c['due']}): {c['what']}")
    return out


def decisions_md(p: Project) -> str:
    L = ["# Решения и обязательства", "", "_Генерируется `python st.py decide list`._", ""]
    for d in p.decisions().values():
        L += [f"## {d['id']} · {d['status']} · {d['question']}",
              f"- Выбрано: {d.get('chosen')}; отклонено: " + "; ".join(f"{k} — {v}" for k, v in (d.get('rejected') or {}).items()),
              f"- Основания: {', '.join(d.get('basis', []))}; ключевые допущения: {', '.join(d.get('key_assumptions', []))}",
              f"- Ожидаем: {json.dumps(d.get('expect'), ensure_ascii=False)}",
              "- Условия остановки: " + "; ".join(f"{k.get('signal')} {k.get('threshold', '')} → {k.get('action')} ({k.get('owner')})" for k in d.get("kill", [])),
              "- Пересмотр: " + "; ".join(json.dumps(r, ensure_ascii=False) for r in d.get("revisit", [])),
              f"- Утверждает: {d.get('approver')}; снимок реестра: {str(d.get('ledger_hash'))[:12]}", ""]
    L += ["## Обязательства", "", "| ID | Что | Владелец (роль) | Срок | Решение | Статус |", "|---|---|---|---|---|---|"]
    for c in p.commitments().values():
        L.append(f"| {c['id']} | {c['what']} | {c['owner']} | {c['due']} | {c.get('decision') or ''} | {c['status']} |")
    md = "\n".join(L) + "\n"
    store.atomic_write(p.p("decisions", "DECISIONS.md"), md)
    return md
