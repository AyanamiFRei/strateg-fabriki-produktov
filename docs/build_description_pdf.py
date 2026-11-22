#!/usr/bin/env python3
"""Собирает PDF-описание для жюри из docs/DESCRIPTION.md и docs/screenshots/*.png.

Запуск: py docs/build_description_pdf.py
Результат: docs/STRATEGY-DESCRIPTION.pdf (A4, Chrome headless).
Скриншоты должны быть собраны заранее: py docs/build_screenshots.py
"""
from __future__ import annotations

import html
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SRC = DOCS / "DESCRIPTION.md"
SHOTS = DOCS / "screenshots"
OUT_HTML = DOCS / "_description.html"
OUT_PDF = DOCS / "STRATEGY-DESCRIPTION.pdf"

CHROME = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
]

# Плейсхолдер в тексте → файл и подпись.
FIGURES = [
    ("PROGRESS.md", "progress.png", "PROGRESS.md: полоса стадий, предупреждения, реестр и стоимость"),
    ("why K45", "why.png", "st.py why K45: цепочка числа до формулы, допущений и проверок"),
    ("архитектура", "architecture.png", "Архитектура: модель рассуждает, код проверяет"),
    ("impact", "impact.png", "Новые данные: «было → стало», пересчёт 16 расчётов, решение D01 на пересмотре"),
    ("resume", "resume.png", "st.py resume: стадия, ворота, следующий шаг, стоимость"),
    ("тесты", "tests.png", "32 теста OK, validate — 0 ошибок, check all — 0 нарушений"),
    ("check", "check.png", "check ловит подменённое число: жёсткое нарушение, код возврата 2"),
]


def inline(text: str) -> str:
    """Экранирование + инлайн-разметка Markdown."""
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", text)
    text = re.sub(r"(?<![\w_])_([^_\n]+)_(?![\w_])", r"<em>\1</em>", text)
    return text


def figure(caption_text: str) -> str:
    for key, name, cap in FIGURES:
        if key in caption_text:
            src = SHOTS / name
            if not src.exists():
                raise SystemExit(f"Нет файла {src}. Сначала: py docs/build_screenshots.py")
            return (f'<figure><img src="screenshots/{name}" alt="{html.escape(cap)}">'
                    f"<figcaption>{html.escape(cap)}</figcaption></figure>")
    raise SystemExit(f"Не найден скриншот для плейсхолдера: {caption_text}")


def table(rows: list[str]) -> str:
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    head, body = cells[0], cells[2:]
    cls = f"c{len(head)}" if len(head) in (2, 3, 4) else ""
    out = [f'<table class="{cls}"><thead><tr>']
    out += [f"<th>{inline(c)}</th>" for c in head]
    out.append("</tr></thead><tbody>")
    for row in body:
        out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def render(md: str) -> str:
    lines = md.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()

        if not s:
            i += 1
            continue

        if s.startswith("```"):
            i += 1
            buf = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            if "┌" in "\n".join(buf) and "st.py" in "\n".join(buf):
                # ASCII-схема остаётся в Markdown; в PDF её заменяет architecture.png
                continue
            out.append("<pre>" + html.escape("\n".join(buf)) + "</pre>")
            continue

        if s.startswith("#"):
            level = len(s) - len(s.lstrip("#"))
            out.append(f"<h{level}>{inline(s[level:].strip())}</h{level}>")
            i += 1
            continue

        if s.startswith("|") and i + 1 < len(lines) and set(lines[i + 1].strip()) <= set("|-: "):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(table(rows))
            continue

        if s.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            out.append("<blockquote>" + inline(" ".join(buf)) + "</blockquote>")
            continue

        if s.startswith("[скриншот:"):
            out.append(figure(s))
            i += 1
            continue

        if re.match(r"^([-*]|\d+\.)\s+", s):
            items: list[tuple[int, str, str]] = []
            while i < len(lines):
                raw = lines[i]
                m = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", raw)
                if not m:
                    if raw.strip() and items and raw.startswith("  "):
                        # продолжение пункта
                        ind, mark, txt = items[-1]
                        items[-1] = (ind, mark, txt + " " + raw.strip())
                        i += 1
                        continue
                    break
                indent = len(m.group(1))
                items.append((indent, m.group(2), m.group(3)))
                i += 1
            html_items: list[str] = []
            stack: list[str] = []
            for indent, mark, txt in items:
                level = 1 if indent >= 2 else 0
                while len(stack) > level + 1:
                    html_items.append(f"</{stack.pop()}>")
                while len(stack) < level + 1:
                    tag = "ol" if mark.endswith(".") else "ul"
                    stack.append(tag)
                    html_items.append(f"<{tag}>")
                html_items.append(f"<li>{inline(txt)}</li>")
            while stack:
                html_items.append(f"</{stack.pop()}>")
            out.append("".join(html_items))
            continue

        # абзац: склеиваем строки до пустой
        buf = [s]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
                r"^\s*(#|\||>|```|[-*]\s|\d+\.\s|\[скриншот:)", lines[i]):
            buf.append(lines[i].strip())
            i += 1
        out.append("<p>" + inline(" ".join(buf)) + "</p>")

    return "\n".join(out)


CSS = """
@page { size: A4; margin: 18mm 16mm 16mm 16mm; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", "PT Sans", Arial, sans-serif; font-size: 10.2pt; line-height: 1.5;
       color: #111827; margin: 0; }
h1 { font-size: 22pt; line-height: 1.2; margin: 0 0 4mm; color: #0f172a; }
h2 { font-size: 14pt; margin: 9mm 0 3mm; padding-bottom: 1.5mm; border-bottom: 1.5px solid #2563eb;
     color: #1e3a8a; page-break-after: avoid; }
h3 { font-size: 11.5pt; margin: 6mm 0 2mm; color: #1e40af; page-break-after: avoid; }
p { margin: 0 0 2.6mm; text-align: left; }
ul, ol { margin: 0 0 3mm; padding-left: 6mm; }
li { margin: 0 0 1.2mm; }
ul:not(:has(> li:nth-child(5))), ol:not(:has(> li:nth-child(5))) { break-inside: avoid; }
ul ul { margin-top: 1.2mm; }
code { font-family: "Cascadia Mono", Consolas, monospace; font-size: 8.8pt; background: #f1f5f9;
       padding: 0.3mm 1.2mm; border-radius: 1.5mm; }
pre { font-family: "Cascadia Mono", Consolas, monospace; font-size: 7.4pt; line-height: 1.28;
      background: #0f172a; color: #e2e8f0; padding: 3mm 3.5mm; border-radius: 2mm;
      overflow: hidden; white-space: pre; page-break-inside: avoid; }
pre code { background: none; padding: 0; color: inherit; }
table { width: 100%; border-collapse: collapse; margin: 2mm 0 4mm; font-size: 8.9pt; table-layout: fixed; }
table.c2 th:nth-child(1) { width: 26%; }
table.c3 th:nth-child(1) { width: 25%; }
table.c3 th:nth-child(2) { width: 45%; }
table.c4 th:nth-child(1) { width: 15%; }
table.c4 th:nth-child(2) { width: 17%; }
table.c4 th:nth-child(3) { width: 48%; }
th { background: #e8eefc; text-align: left; padding: 1.6mm 2mm; border: 0.4px solid #b9c6e4; }
thead { display: table-header-group; }
td { padding: 1.4mm 2mm; border: 0.4px solid #cfd8e8; vertical-align: top; }
td code { overflow-wrap: anywhere; }
tr { page-break-inside: avoid; }
blockquote { margin: 3mm 0; padding: 2mm 4mm; border-left: 3px solid #94a3b8; color: #334155;
             background: #f8fafc; }
figure { margin: 4mm 0 5mm; page-break-inside: avoid; }
figure img { width: 100%; border: 0.5px solid #cbd5e1; border-radius: 1.5mm; }
figcaption { font-size: 8.6pt; color: #475569; margin-top: 1.5mm; font-style: italic; }
strong { color: #0f172a; }
a { color: #1d4ed8; text-decoration: none; }
.cover { border-left: 5px solid #2563eb; padding: 0 0 0 5mm; margin-bottom: 6mm; }
.cover .sub { color: #475569; font-size: 10pt; }
.cover .meta { color: #64748b; font-size: 9pt; margin-top: 2mm; }
"""


def build_html(md: str) -> str:
    body = render(md)
    body = body.replace(
        "<h1>Стратег Фабрики продуктов — описание работы</h1>",
        '<div class="cover"><h1>Стратег Фабрики продуктов — описание работы</h1>'
        '<div class="sub">ИИ-агент для руководителя цифрового продукта: от размытого запроса '
        "до проверяемой стратегии и сопровождения решения</div>"
        '<div class="meta">Репозиторий с демо-проектом · описание, архитектура, проверки · '
        "22 ноября 2026</div></div>", 1)
    return ("<!DOCTYPE html><html lang=\"ru\"><head><meta charset=\"utf-8\">"
            f"<title>Стратег Фабрики продуктов</title><style>{CSS}</style></head>"
            f"<body>{body}</body></html>")


def number_pages(path: Path) -> int:
    """Номера страниц «N / всего» внизу. PyMuPDF нужен только для сборки PDF."""
    try:
        import fitz
    except ImportError:
        print("PyMuPDF нет — PDF без номеров страниц")
        return 0
    doc = fitz.open(path)
    total = doc.page_count
    for i, page in enumerate(doc, 1):
        r = page.rect
        label = f"{i} / {total}"
        w = fitz.get_text_length(label, fontname="helv", fontsize=8)
        page.insert_text((r.width / 2 - w / 2, r.height - 20), label,
                         fontname="helv", fontsize=8, color=(0.45, 0.5, 0.58))
    tmp = path.with_suffix(".tmp.pdf")
    doc.save(tmp, garbage=3, deflate=True)
    doc.close()
    tmp.replace(path)
    return total


def find_chrome() -> Path:
    for p in CHROME:
        if p.exists():
            return p
    raise SystemExit("Chrome/Edge не найден — PDF не собрать.")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    if not SRC.exists():
        raise SystemExit(f"Нет {SRC}")
    md = SRC.read_text(encoding="utf-8")
    page = build_html(md)
    OUT_HTML.write_text(page, encoding="utf-8")
    chrome = find_chrome()
    if OUT_PDF.exists():
        OUT_PDF.unlink()
    cmd = [str(chrome), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
           "--virtual-time-budget=8000", f"--print-to-pdf={OUT_PDF}", OUT_HTML.as_uri()]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if not OUT_PDF.exists():
        print(r.stdout, r.stderr)
        raise SystemExit("PDF не создан")
    size = OUT_PDF.stat().st_size
    print(f"{OUT_PDF.name}: {size // 1024} КБ, {size} байт")
    print("HTML:", OUT_HTML.name)
    pages = number_pages(OUT_PDF)
    if pages:
        print(f"Страниц: {pages}, номера проставлены")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
