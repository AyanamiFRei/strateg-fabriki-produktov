#!/usr/bin/env python3
"""Сценарий «пришли данные Q1» — кроссплатформенная версия new_data_q1.sh.

Копирует демо-проект, добавляет новую выгрузку аналитика, которая опровергает A04
(0,2 → 0,1), и показывает: регистрацию источника, исправление допущения,
impact «было → стало» и перевод принятого решения D01 в статус revisiting.

Запуск из корня репозитория:
    py eval/scenarios/new_data_q1.py          # Windows
    python3 eval/scenarios/new_data_q1.py     # Linux/macOS

Скрипт ничего не меняет в projects/demo-family: работает с копией demo-q1-data.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = os.environ.get("PY") or sys.executable
TARGET = ROOT / "projects" / "demo-q1-data"
SOURCE = ROOT / "projects" / "demo-family"

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _remove_tree(path: Path) -> None:
    """Удаляет копию проекта, снимая read-only с файлов (Windows копирует атрибуты)."""
    import stat

    def on_error(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    shutil.rmtree(path, onerror=on_error)
    if path.exists():
        raise SystemExit(f"не удалось удалить {path}: закройте файлы проекта и повторите")


def run(*args: str, allow: tuple[int, ...] = (0,), quiet: bool = False) -> subprocess.CompletedProcess:
    cmd = [PY, str(ROOT / "st.py"), "--project", TARGET.name, *args]
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    if not quiet:
        print(out.rstrip())
    if r.returncode not in allow:
        raise SystemExit(f"команда {' '.join(args)} вернула {r.returncode}, ожидалось {allow}")
    return r


def main() -> int:
    if not SOURCE.exists():
        raise SystemExit(f"нет демо-проекта: {SOURCE}")
    if TARGET.exists():
        _remove_tree(TARGET)
    shutil.copytree(SOURCE, TARGET)
    inbox = TARGET / "materials" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    logs = inbox / "q1-logs.txt"
    logs.write_text(
        "Выгрузка аналитика за 3 месяца Q1 (учебные данные сценария).\n"
        "Доля подходящих групп, у которых впервые возник случай низкого остатка участника, "
        "составила 10 % в месяц.\n",
        encoding="utf-8",
    )

    print("\n=== 1. Новые данные видны в resume ===")
    r = run("resume", quiet=True)
    for line in r.stdout.splitlines():
        if "НОВЫЕ ДАННЫЕ" in line or line.startswith("Стадия:"):
            print(line)

    print("\n=== 2. Новый источник зарегистрирован со снимком и цитатой ===")
    run("source", "add", "--file", str(logs), "--title", "Выгрузка аналитика Q1",
        "--reliability", "high", "--why", "журналы оператора")
    moved = TARGET / "materials" / logs.name
    if moved.exists():
        moved.unlink()
    shutil.move(str(logs), str(moved))

    print("\n=== 3. Исправление A04 новой версией (supersedes) ===")
    row = (
        '{"kind":"assumption","supersedes":"A04","change":"данные Q1: фактическая доля первых случаев '
        '10 % в месяц","text":"Вероятность первого случая низкого остатка у подходящей группы в месяц — '
        'по данным Q1","key":"pool.first_case_rate","value":{"num":0.1,"unit":"доля в месяц"},'
        '"test":"подтверждено выгрузкой Q1 (S07)","confidence":"moderate"}\n'
    )
    (TARGET / "inbox" / "q1.jsonl").write_text(row, encoding="utf-8")
    run("claim", "import")

    print("\n=== 4. Impact: что затронуто и «было → стало» ===")
    run("impact", "--ids", "A04", allow=(0, 3))

    print("\n=== 5. Проверка ловит устаревшие числа в документах (ожидаем код 2) ===")
    r = run("check", "all", allow=(0, 2), quiet=True)
    first = [line for line in r.stdout.splitlines() if line.strip().startswith("✗")][:3]
    for line in first:
        print(line)
    print(f"Всего устаревших чисел: {sum(1 for line in r.stdout.splitlines() if line.strip().startswith('✗'))}")
    print("\nГотово. Проект для показа: projects/demo-q1-data; отчёт: "
          "projects/demo-q1-data/deliverables/IMPACT-*.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
