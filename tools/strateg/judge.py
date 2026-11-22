"""Опциональная узкая проверка по рубрике через Jev (TypeSafe AI) — с закрытием при сбое.

Jev не генерирует текст: на вопрос вида «да/нет» или выбор из вариантов возвращает вероятности.
Используется ТОЛЬКО для узких чек-листов (agent/rubrics/judge.json), не для оценки качества стратегии
и не для арифметики. Ключ — только из переменной окружения (TYPESAFE_API_KEY или OPENROUTER_API_KEY).
При отсутствии ключа, ошибке сети или уверенности ниже порога результат = "unchecked" (не «пройдено»):
пункт уходит критику/человеку. Пропуска по умолчанию нет.
Наружу уходят только фрагменты открытых материалов ≤ 8000 символов; интервью — никогда.
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

from . import store

MAX_CHARS = 8000


def _rubric(check_id: str) -> dict:
    r = store.read_json(store.ROOT / "agent" / "rubrics" / "judge.json", {})
    if check_id not in r.get("checks", {}):
        raise store.StError(f"нет проверки {check_id} в agent/rubrics/judge.json; есть: {', '.join(r.get('checks', {}))}")
    return r


def run(check_id: str, file: str, provider: str = "auto") -> dict:
    r = _rubric(check_id)
    q = r["checks"][check_id]
    f = Path(file)
    if "deliverables" not in f.parts or "interviews" in f.parts:
        return {"check": check_id, "result": "unchecked",
                "why": "наружу отправляются только документы из deliverables/ (не материалы, не интервью)"}
    if "interviews" in f.parts:
        return {"check": check_id, "result": "unchecked", "why": "интервью не отправляются во внешние сервисы"}
    text = f.read_text(encoding="utf-8")[:MAX_CHARS]
    tau = r.get("threshold", 0.8)
    key_ts, key_or = os.environ.get("TYPESAFE_API_KEY"), os.environ.get("OPENROUTER_API_KEY")
    if provider == "none" or not (key_ts or key_or):
        return {"check": check_id, "result": "unchecked", "why": "Jev не настроен — работаю без него; "
                "пункт проверяет критик по рубрике (agent/rubrics/review.json)"}
    body = {"model": r.get("model", "typesafe/jev-1.14"), "state": text,
            "questions": {check_id: {"type": q.get("type", "noul"), "instructions": q["instructions"],
                                     "criteria": q.get("criteria", {})}}}
    if key_ts and provider in ("auto", "typesafe"):
        url, key = "https://api.typesafe.ai/v1/systemone", key_ts
    else:
        url, key = "https://openrouter.ai/api/v1/systemone", key_or
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
        ans = (data.get("answers") or data.get("results") or {}).get(check_id) or {}
        prob = ans.get("probability") if isinstance(ans, dict) else None
        if prob is None:
            return {"check": check_id, "result": "unchecked", "why": "ответ без вероятности", "raw": data}
        if max(prob, 1 - prob) < tau:
            return {"check": check_id, "result": "unchecked", "why": f"уверенность ниже порога {tau}", "p_true": prob}
        return {"check": check_id, "result": "pass" if prob >= 0.5 else "fail", "p_true": prob,
                "note": "сигнал судьи, не вердикт; 10% решений выборочно проверяет человек"}
    except Exception as e:
        return {"check": check_id, "result": "unchecked", "why": f"Jev недоступен: {e}"}
