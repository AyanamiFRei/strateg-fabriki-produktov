"""Один обработчик хуков для Claude Code / Cursor / Codex (усилители; безопасность на них не опирается).

session-start: печатает сводку resume — IDE добавляет её в контекст новой сессии.
stop:          перегенерирует PROGRESS.md и, если есть прерванные шаги или блокировка, напоминает (один раз).
pre-tool:      запрещает запись в защищённые пути и загрузку URL вне allowlist (код 2 = запрет).
"""
from __future__ import annotations

import json
import sys

from . import store

PROTECTED = ("AGENTS.md", "CLAUDE.md", "GIGACODE.md", "agent/", ".agents/", "kb/", "config/", ".claude/",
             ".cursor/", ".gigacode/", "tools/", "st.py")
STATE_ONLY = ("/state/", "/evidence/", "/decisions/", "/analysis/K")


def _stdin_json():
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        data = sys.stdin.buffer.read().decode("utf-8", "replace")
        return json.loads(data) if data.strip() else {}
    except Exception:
        return None  # не разобрали вход


def _rel(path: str) -> str:
    """Нормализованный путь относительно корня (без ./, .., регистр — для сравнения)."""
    import os
    root = os.path.normcase(os.path.normpath(str(store.ROOT)))
    full = os.path.normcase(os.path.normpath(os.path.join(root, path) if not os.path.isabs(path) else path))
    rel = os.path.relpath(full, root) if full.startswith(root) else full
    return rel.replace("\\", "/")


def handle(event: str) -> int:
    payload = _stdin_json()
    if payload is None:
        if event == "pre-tool":
            print("Хук не смог разобрать запрос — действие запрещено (fail-closed).", file=sys.stderr)
            return 2
        payload = {}
    try:
        if event == "session-start":
            from . import state
            try:
                p = store.resolve_project(None)
            except store.StError:
                print("Стратег: активного проекта нет. Новый проект: python st.py init <slug> --from <файл>. "
                      "Демо: python st.py use demo-family && python st.py resume")
                return 0
            print("Сводка проекта (из python st.py resume):\n" + state.resume(p))
            return 0
        if event == "stop":
            if payload.get("stop_hook_active"):
                return 0
            from . import state
            try:
                p = store.resolve_project(None)
            except store.StError:
                return 0
            state.progress(p)
            return 0
        if event == "pre-tool":
            tool = payload.get("tool_name") or payload.get("tool") or ""
            ti = payload.get("tool_input") or {}
            path = ti.get("file_path") or ti.get("path") or ti.get("notebook_path") or ""
            if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit") and path:
                rel = _rel(path)
                prot = tuple(x.lower() for x in PROTECTED)
                if rel.lower().startswith(prot) or rel.startswith(".."):
                    print(f"Запрет: {rel} — постоянные инструкции/знания/инструменты или путь вне репозитория. "
                          "Меняются только по прямой просьбе пользователя (он может отредактировать сам).",
                          file=sys.stderr)
                    return 2
                low = "/" + rel.lower()
                if ("/evidence/" in low or "/state/" in low or low.endswith(".out.json")
                        or (("/decisions/" in low) and low.endswith(".jsonl"))):
                    print(f"Запрет: {rel} пишет только st.py (снимки, реестры, состояние, результаты расчётов). "
                          "Для утверждений — inbox/*.jsonl и python st.py claim import; для расчётов — "
                          "analysis/Kxx.json и python st.py calc run.", file=sys.stderr)
                    return 2
            if tool in ("WebFetch",) and ti.get("url"):
                from .ledger import domain_allowed
                if not domain_allowed(ti["url"]):
                    print("Предупреждение: домен вне allowlist — страница годится только для поиска URL, "
                          "а не как доказательство. Доказательство: python st.py source add --url (allowlist) "
                          "или сохранённый файл.", file=sys.stderr)
                    return 0
            if tool == "Bash":
                import re
                cmd = ti.get("command", "")
                if re.search(r"\b(curl|wget|Invoke-WebRequest|iwr)\b", cmd):
                    print("Запрет: внешние загрузки — только через python st.py source add --url (allowlist).",
                          file=sys.stderr)
                    return 2
                if re.search(r"(>>?|\btee\b|Set-Content|Add-Content|Out-File|\bsed\s+-i|\bmv\b|\bcp\b|\brm\b)"
                             r"[^|;&]*(evidence/|state/|decisions/[^ ]*\.jsonl|\.out\.json|AGENTS\.md|kb/|config/|"
                             r"agent/|\.agents/|tools/)", cmd):
                    print("Запрет: запись в реестры, состояние или инструкции в обход st.py.", file=sys.stderr)
                    return 2
            return 0
    except Exception as e:  # хук никогда не ломает сессию
        print(f"[strateg hook] {e}", file=sys.stderr)
        return 0
    return 0
