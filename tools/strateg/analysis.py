"""Запуск расчётов K: спецификация analysis/K*.json → результат K*.out.json.

Спецификация:
{"id":"K03","title":"Размер пилота","fn":"cluster_sample",
 "args":{"p1":0.12,"p2":0.09,"m":3,"icc":0.1},
 "inputs":{"p1":"A07","icc":"A09"},          # аргумент ← значение утверждения (value.num)
 "note":"…"}
Путь аргумента может быть вложенным: "rates.1" — второй элемент списка rates.
Если входное утверждение имеет value.num, оно подставляется вместо args (так работает пересчёт).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from . import calc, store
from .store import Project, StError, now, op_id, read_json, sha256_bytes, write_json


def _set_path(obj: dict, path: str, value):
    parts = path.split(".")
    cur = obj
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        key = int(part) if isinstance(cur, list) else part
        if last:
            cur[key] = value
        else:
            cur = cur[key]


def _claim_num(c: dict):
    v = (c or {}).get("value") or {}
    return v.get("num")


def resolve_args(p: Project, spec: dict) -> tuple[dict, dict]:
    args = copy.deepcopy(spec.get("args") or {})
    used = {}
    claims = p.claims()
    calcs = None
    for path, ref in (spec.get("inputs") or {}).items():
        if ref.startswith("K"):
            calcs = calcs or p.calcs()
            out = (calcs.get(ref) or {}).get("out")
            if not out:
                raise StError(f"{spec['id']}: вход {ref} ещё не рассчитан — сначала calc run {ref}")
            val = out["result"]["value"]
        else:
            c = claims.get(ref)
            if not c:
                raise StError(f"{spec['id']}: вход {path} ссылается на несуществующее {ref}")
            if c.get("status") in ("retracted",):
                raise StError(f"{spec['id']}: вход {ref} отозван")
            val = _claim_num(c)
            if val is None:
                raise StError(f"{spec['id']}: у {ref} нет value.num для подстановки в {path}")
        _set_path(args, path, val)
        used[path] = {"ref": ref, "value": val}
    return args, used


def _kind(p: Project, used: dict) -> str:
    """Расчёт — факт, только если все входы — факты (в том числе через другие расчёты)."""
    if not used:
        return "forecast"
    claims, calcs = p.claims(), None
    for u in used.values():
        ref = u["ref"]
        if ref.startswith("K"):
            calcs = calcs or p.calcs()
            if ((calcs.get(ref) or {}).get("out") or {}).get("kind") != "fact":
                return "forecast"
        elif claims.get(ref, {}).get("kind") != "fact":
            return "forecast"
    return "fact"


def run(p: Project, kid: str, force: bool = False) -> dict:
    f = p.p("analysis", f"{kid}.json")
    spec = read_json(f)
    if not spec:
        raise StError(f"нет спецификации analysis/{kid}.json")
    spec.setdefault("id", kid)
    fn = calc.REGISTRY.get(spec.get("fn"))
    if not fn:
        raise StError(f"{kid}: неизвестная функция '{spec.get('fn')}'. Доступно: {', '.join(calc.REGISTRY)}")
    args, used = resolve_args(p, spec)
    ih = sha256_bytes(store.canon({"fn": spec["fn"], "args": args}).encode())
    outp = f.with_name(f"{kid}.out.json")
    prev = read_json(outp)
    if prev and prev.get("inputs_hash") == ih and not force:
        p.log(op_id=op_id("calc", [kid, ih]), op="calc", phase="skipped_cached", note=kid)
        return dict(prev, _cached=True)
    oid = op_id("calc", [kid, ih])
    p.log(op_id=oid, op="calc", phase="start", note=kid)
    try:
        res = fn(**args)
    except Exception as e:
        p.log(op_id=oid, op="calc", phase="fail", note=kid, error=str(e))
        raise StError(f"{kid}: расчёт не выполнен: {e}") from e
    out = {"id": kid, "title": spec.get("title"), "fn": spec["fn"], "args": args, "inputs": used,
           "result": res, "inputs_hash": ih, "computed_at": now(),
           "kind": _kind(p, used)}
    if prev:
        out["previous"] = {"value": prev.get("result", {}).get("value"), "computed_at": prev.get("computed_at"),
                           "inputs": prev.get("inputs")}
    write_json(outp, out)
    p.log(op_id=oid, op="calc", phase="done", note=kid,
          artifacts=[{"path": str(outp.relative_to(p.dir)).replace("\\", "/")}])
    return out


def run_all(p: Project, force: bool = False) -> list:
    """Запуск всех K в порядке зависимостей (K может ссылаться на K)."""
    specs = {k: v["spec"] for k, v in p.calcs().items()}
    done, order = set(), []

    def visit(k, stack=()):
        if k in done:
            return
        if k in stack:
            raise StError(f"цикл в расчётах: {' → '.join(stack + (k,))}")
        for ref in (specs[k].get("inputs") or {}).values():
            if ref.startswith("K") and ref in specs:
                visit(ref, stack + (k,))
        done.add(k)
        order.append(k)

    for k in sorted(specs):
        visit(k)
    return [run(p, k, force) for k in order]


def fmt_value(v) -> str:
    if isinstance(v, float):
        return f"{v:,.4g}".replace(",", " ")
    if isinstance(v, int):
        return f"{v:,}".replace(",", " ")
    if isinstance(v, list):
        return f"таблица ({len(v)} строк)"
    return json.dumps(v, ensure_ascii=False)
