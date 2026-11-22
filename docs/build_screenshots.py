#!/usr/bin/env python3
"""Собирает изображения для PDF-описания: реальные выводы команд и схему архитектуры.

Запуск: py docs/build_screenshots.py
Результат: docs/screenshots/*.png
Требуется Pillow (только для сборки PDF, не для работы агента).
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
PY = sys.executable
MONO = Path(r"C:\Windows\Fonts\CascadiaMono.ttf")
MONO_B = Path(r"C:\Windows\Fonts\CascadiaMono.ttf")
UI = Path(r"C:\Windows\Fonts\segoeui.ttf")
UI_B = Path(r"C:\Windows\Fonts\segoeuib.ttf")

BG = (15, 23, 32)
BAR = (30, 41, 59)
FG = (229, 231, 235)
DIM = (148, 163, 184)
ACCENT = (56, 189, 248)
GREEN = (52, 211, 153)
RED = (248, 113, 113)


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


SYMBOLS = set("✓✔✗✘⚠★☆⏱→←")
SYM = Path(r"C:\Windows\Fonts\seguisym.ttf")


def draw_mixed(d: ImageDraw.ImageDraw, xy, text: str, f, size: int, fill, extra=None):
    """Рисует строку, подставляя символьный шрифт для глифов, которых нет в основном."""
    extra = SYMBOLS if extra is None else extra
    x, y = xy
    buf = ""
    cur_sym = None

    def flush():
        nonlocal x, buf, cur_sym
        if not buf:
            return
        ft = font(SYM, size) if cur_sym else f
        d.text((x, y), buf, font=ft, fill=fill)
        x += d.textlength(buf, font=ft)
        buf = ""

    for ch in text:
        s = ch in extra
        if s != cur_sym:
            flush()
            cur_sym = s
        buf += ch
    flush()


def run(args: list[str], cwd: Path | None = None, env: dict | None = None) -> str:
    e = dict(os.environ, PYTHONIOENCODING="utf-8")
    if env:
        e.update(env)
    r = subprocess.run(args, cwd=str(cwd or ROOT), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=e)
    return ((r.stdout or "") + (r.stderr or "")).replace("\r\n", "\n").strip("\n")


def wrap_lines(text: str, max_chars: int) -> list[str]:
    out: list[str] = []
    for raw in text.splitlines():
        if not raw:
            out.append("")
            continue
        if len(raw) <= max_chars:
            out.append(raw)
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        cont = " " * min(indent + 2, 8)
        out.extend(textwrap.wrap(raw, width=max_chars, subsequent_indent=cont,
                                 replace_whitespace=False, drop_whitespace=False) or [""])
    return out


def terminal(text: str, title: str, name: str, width: int = 2300, size: int = 30) -> Path:
    f = font(MONO, size)
    char_w = f.getlength("M")
    pad = 34
    max_chars = max(40, int((width - 2 * pad) / char_w))
    lines = wrap_lines(text, max_chars)
    line_h = int(size * 1.42)
    head_h = 62
    height = head_h + pad * 2 + line_h * max(1, len(lines))
    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, width, head_h], fill=BAR)
    for i, c in enumerate([(248, 113, 113), (251, 191, 36), (52, 211, 153)]):
        d.ellipse([20 + i * 26, 22, 36 + i * 26, 38], fill=c)
    d.text((110, 17), title, font=font(UI, 24), fill=DIM)
    y = head_h + pad
    for line in lines:
        color = FG
        if line.strip().startswith(("✗", "Ошибка", "Запрет", "FAILED")):
            color = RED
        elif line.strip().startswith(("✓", "OK", "Импортировано", "S07", "Жёстких нарушений: 0")):
            color = GREEN
        elif line.strip().startswith(("===", "#", "##")):
            color = ACCENT
        draw_mixed(d, (pad, y), line, f, size, color, extra=SYMBOLS - {"✓"})
        y += line_h
    path = OUT / name
    img.save(path, "PNG", optimize=True)
    print(f"{name}: {width}×{height}")
    return path


def card(markdown: str, title: str, name: str, width: int = 1700) -> Path:
    """Рендерит Markdown-файл как страницу документа (для PROGRESS.md)."""
    lines = markdown.splitlines()
    pad = 70
    body: list[tuple[str, int, tuple]] = []
    for raw in lines:
        s = raw.strip()
        if not s:
            body.append(("", 14, FG))
            continue
        text = re.sub(r"[*`]", "", s)
        if len(text) > 2 and text.startswith("_") and text.endswith("_"):
            text = text[1:-1]
        if s.startswith("# "):
            body.append((text[2:], 40, (15, 23, 42)))
        elif s.startswith("## "):
            body.append((text[3:], 30, (15, 23, 42)))
        elif s.startswith("**") and s.endswith("**"):
            body.append((text.strip("*"), 24, (30, 64, 175)))
        elif s.startswith("- "):
            body.append(("• " + text[2:], 22, (51, 65, 85)))
        elif s.startswith("> "):
            body.append((text[2:], 24, (185, 28, 28)))
        else:
            body.append((text, 22, (51, 65, 85)))
    heights = [int(sz * 1.45) for _, sz, _ in body]
    height = pad * 2 + sum(heights) + 70
    img = Image.new("RGB", (width, height), (248, 250, 252))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, width, 8], fill=(37, 99, 235))
    y = pad
    d.text((pad, y), title, font=font(UI_B, 26), fill=(100, 116, 139))
    y += 54
    for (text, size, color), h in zip(body, heights):
        if text:
            draw_mixed(d, (pad, y), text, font(UI_B if size >= 30 else UI, size), size, color)
        y += h
    path = OUT / name
    img.save(path, "PNG", optimize=True)
    print(f"{name}: {width}×{height}")
    return path


def box(d: ImageDraw.ImageDraw, xy, text: str, fill, outline, size=26, bold=False):
    x0, y0, x1, y1 = xy
    d.rounded_rectangle(xy, radius=14, fill=fill, outline=outline, width=3)
    f = font(UI_B if bold else UI, size)
    lines = wrap_lines(text, max(16, int((x1 - x0 - 24) / (size * 0.52))))
    total = len(lines) * int(size * 1.35)
    ty = y0 + (y1 - y0 - total) // 2
    for line in lines:
        w = d.textlength(line, font=f)
        d.text((x0 + (x1 - x0 - w) / 2, ty), line, font=f, fill=(15, 23, 42))
        ty += int(size * 1.35)


def arrow(d: ImageDraw.ImageDraw, p1, p2, color=(100, 116, 139)):
    d.line([p1, p2], fill=color, width=4)
    x, y = p2
    d.polygon([(x, y), (x - 12, y - 7), (x - 12, y + 7)], fill=color)


def architecture(name: str = "architecture.png") -> Path:
    W, H = 2000, 1180
    img = Image.new("RGB", (W, H), (248, 250, 252))
    d = ImageDraw.Draw(img)
    d.text((70, 45), "Архитектура: модель рассуждает, код проверяет", font=font(UI_B, 42), fill=(15, 23, 42))
    d.text((70, 105), "Один регламент и один CLI для Cursor, Claude Code, Codex, GigaCode и OpenCode",
           font=font(UI, 24), fill=(71, 85, 105))

    box(d, (70, 180, 420, 330), "Пользователь\n(чат, файлы, решения)", (219, 234, 254), (37, 99, 235), 28, True)
    box(d, (520, 160, 1180, 360),
        "Модель IDE\nчитает AGENTS.md → навык стадии → kb/\nпишет черновики и тексты",
        (224, 231, 255), (79, 70, 229), 28, True)
    box(d, (520, 430, 1180, 600),
        "Черновики\ninbox/*.jsonl · deliverables/*.md\n(не попадают в реестр без проверки)",
        (254, 249, 195), (202, 138, 4), 26)
    box(d, (520, 670, 1180, 900),
        "st.py — детерминированное ядро\nреестры · расчёты · проверки · ворота\nсостояние · журнал · стоимость",
        (220, 252, 231), (5, 150, 105), 28, True)
    box(d, (1320, 160, 1900, 300), "evidence/\nснимки источников, F/A/H/P/I/Y", (255, 237, 213), (194, 65, 12), 24)
    box(d, (1320, 330, 1900, 470), "analysis/\nK*.json → K*.out.json", (255, 237, 213), (194, 65, 12), 24)
    box(d, (1320, 500, 1900, 640), "state/\ntask.json · журнал · стоимость", (255, 237, 213), (194, 65, 12), 24)
    box(d, (1320, 670, 1900, 810), "decisions/\nD · T · триггеры", (255, 237, 213), (194, 65, 12), 24)
    box(d, (520, 960, 1180, 1090), "Субагенты: critic · source-reader · respondent",
        (243, 232, 255), (126, 34, 206), 24)

    arrow(d, (420, 255), (520, 255))
    arrow(d, (850, 360), (850, 430))
    arrow(d, (850, 600), (850, 670))
    arrow(d, (1180, 700), (1320, 230))
    arrow(d, (1180, 730), (1320, 400))
    arrow(d, (1180, 790), (1320, 570))
    arrow(d, (1180, 830), (1320, 740))
    arrow(d, (850, 900), (850, 960))
    d.text((70, 1130), "Правила и знания — только человек; состояние и реестры — только st.py.",
           font=font(UI, 22), fill=(100, 116, 139))
    path = OUT / name
    img.save(path, "PNG", optimize=True)
    print(f"{name}: {W}×{H}")
    return path


def force_rm(path: Path):
    def onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    if path.exists():
        shutil.rmtree(path, onerror=onerror)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    OUT.mkdir(parents=True, exist_ok=True)

    architecture()

    progress = (ROOT / "projects" / "demo-family" / "PROGRESS.md").read_text(encoding="utf-8")
    card(progress, "projects/demo-family/PROGRESS.md", "progress.png")

    resume = run([PY, "st.py", "--project", "demo-family", "resume"])
    terminal(resume, "py st.py --project demo-family resume", "resume.png")

    why = run([PY, "st.py", "--project", "demo-family", "why", "K45"])
    terminal("\n".join(why.splitlines()[:55]), "py st.py --project demo-family why K45", "why.png")

    tests = run([PY, "-m", "unittest", "discover", "-s", "tests"])
    tail = "\n".join([l for l in tests.splitlines() if l.strip()][-4:])
    validate = run([PY, "st.py", "validate"])
    check = run([PY, "st.py", "--project", "demo-family", "check", "all"])
    terminal(f"$ py -m unittest discover -s tests\n{tail}\n\n$ py st.py validate\n{validate}\n\n"
             f"$ py st.py --project demo-family check all\n{check}",
             "Проверки перед сдачей", "tests.png", size=28)

    # Ловим неверное число: копия демо, одна цифра заменена.
    tmp = ROOT / "projects" / "checkdemo"
    force_rm(tmp)
    shutil.copytree(ROOT / "projects" / "demo-family", tmp)
    f = tmp / "deliverables" / "product_strategy.md"
    txt = f.read_text(encoding="utf-8")
    txt = txt.replace("около −48 тыс. руб. [K25]", "около −49 тыс. руб. [K25]", 1)
    f.write_text(txt, encoding="utf-8")
    bad = run([PY, "st.py", "--project", "checkdemo", "check", "strategy"])
    terminal("\n".join(bad.splitlines()[:18]), "py st.py --project checkdemo check strategy  → код 2",
             "check.png", size=28)
    force_rm(tmp)

    # Impact: запускаем сценарий новых данных и берём раздел 4.
    scen = run([PY, "eval/scenarios/new_data_q1.py"])
    start = scen.find("=== 4.")
    end = scen.find("=== 5.")
    impact = scen[start:end].strip() if start >= 0 else scen[:4000]
    terminal("\n".join(impact.splitlines()[:46]), "py eval/scenarios/new_data_q1.py  → impact",
             "impact.png", size=28)
    force_rm(ROOT / "projects" / "demo-q1-data")

    print("Готово:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
