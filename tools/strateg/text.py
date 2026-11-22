"""Текст: нормализация для поиска цитат, извлечение текста из файлов, разбор чисел."""
from __future__ import annotations

import csv
import html
import io
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path

_PUNCT = re.compile(r"[\s   «»\"'“”„‘’`.,;:!?()\[\]{}–—\-…/\\|*_#>]+")


def norm(s: str) -> str:
    """Нормализация для сравнения цитат: регистр, ё→е, пунктуация и пробелы схлопнуты."""
    s = s.lower().replace("ё", "е")
    return _PUNCT.sub(" ", s).strip()


def quote_in(quote: str, text: str) -> bool:
    q = norm(quote)
    return bool(q) and q in norm(text)


# ------------------------------------------------------------------ извлечение текста

class _HTML2Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(raw: str) -> str:
    p = _HTML2Text()
    p.feed(raw)
    t = "".join(p.out)
    t = re.sub(r"[ \t ]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def _docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    return html.unescape(re.sub(r"<[^>]+>", "", xml)).strip()


def _xlsx_text(path: Path) -> str:
    """Минимальный читатель xlsx на stdlib: общие строки + значения ячеек по листам."""
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            sx = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
            for si in re.findall(r"<si>(.*?)</si>", sx, flags=re.S):
                shared.append(html.unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", si, flags=re.S))))
        lines = []
        sheets = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml", n))
        for sh in sheets:
            lines.append(f"## {Path(sh).stem}")
            sx = z.read(sh).decode("utf-8", "replace")
            for row in re.findall(r"<row[^>]*>(.*?)</row>", sx, flags=re.S):
                cells = []
                for attrs, body in re.findall(r"<c([^>]*)>(.*?)</c>", row, flags=re.S):
                    v = re.search(r"<v>(.*?)</v>", body, flags=re.S)
                    t = re.search(r"<t[^>]*>(.*?)</t>", body, flags=re.S)
                    if 't="s"' in attrs and v:
                        cells.append(shared[int(v.group(1))])
                    elif v:
                        cells.append(html.unescape(v.group(1)))
                    elif t:
                        cells.append(html.unescape(t.group(1)))
                    else:
                        cells.append("")
                lines.append("\t".join(cells))
        return "\n".join(lines)


def _pdf_text(path: Path) -> str:
    try:
        import pypdf  # опционально
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("для PDF установите pypdf (pip install pypdf) или сохраните текст в .txt") from e
    r = pypdf.PdfReader(str(path))
    return "\n\n".join(f"[стр. {i}]\n" + (p.extract_text() or "") for i, p in enumerate(r.pages, start=1))


TEXT_EXT = {".md", ".txt", ".json", ".jsonl", ".yaml", ".yml"}
MEDIA_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp3", ".wav", ".m4a", ".ogg", ".mp4", ".mov", ".webm"}


def extract_text(path: Path) -> tuple[str, str]:
    """Возвращает (тип, текст). Для медиа — описание-заглушка: смысл извлекает модель IDE
    (изображения) или пользователь даёт расшифровку (аудио/видео)."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext in TEXT_EXT:
        return "doc", path.read_text(encoding="utf-8", errors="replace")
    if ext in {".html", ".htm"}:
        return "web", html_to_text(path.read_text(encoding="utf-8", errors="replace"))
    if ext in {".csv", ".tsv"}:
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
        dialect = "excel-tab" if ext == ".tsv" else "excel"
        rows = list(csv.reader(io.StringIO(raw), dialect=dialect))
        return "table", "\n".join("\t".join(r) for r in rows)
    if ext == ".docx":
        return "doc", _docx_text(path)
    if ext == ".xlsx":
        return "table", _xlsx_text(path)
    if ext == ".pdf":
        return "doc", _pdf_text(path)
    if ext in MEDIA_EXT:
        kind = "image" if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif"} else "media"
        return kind, (f"[{kind}-файл {path.name}: текст не извлекается скриптом. "
                      "Изображение агент читает средствами IDE; для аудио/видео нужна расшифровка (.txt).]")
    return "doc", path.read_text(encoding="utf-8", errors="replace")


# ------------------------------------------------------------------ числа

_NUM = re.compile(r"(?<![\w.,])[-−]?\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|(?<![\w.,])[-−]?\d+(?:[.,]\d+)?")
_SCALE = {"тыс": 1e3, "тыс.": 1e3, "млн": 1e6, "млн.": 1e6, "млрд": 1e9}


def parse_numbers(sentence: str) -> list[dict]:
    """Числа в предложении: значение, исходный текст, признак процента и множитель."""
    out = []
    for m in _NUM.finditer(sentence):
        raw = m.group(0)
        s = raw.replace("−", "-").replace(" ", "").replace(" ", "").replace(" ", "").replace(",", ".")
        try:
            v = float(s)
        except ValueError:
            continue
        tail = sentence[m.end():m.end() + 8].lstrip().lower()
        pct = tail.startswith("%") or tail.startswith("п.п") or tail.startswith("процент")
        scale = 1.0
        for k, mult in _SCALE.items():
            if tail.startswith(k):
                scale = mult
                break
        out.append({"raw": raw, "value": v, "pct": pct, "scale": scale, "start": m.start(), "end": m.end()})
    return out


_ABBR = ("руб.", "тыс.", "млн.", "млрд.", "п.п.", "т.е.", "т.д.", "т.п.", "г.", "гг.", "мес.", "чел.", "стр.",
         "др.", "им.", "напр.", "ок.", "прим.", "св.", "шт.", "кв.", "мин.", "ч.", "см.", "e.g.", "i.e.")


def split_sentences(text: str) -> list[str]:
    out = []
    for line in re.split(r"\n+", text):
        start = 0
        for m in re.finditer(r"[.!?]\s+(?=[А-ЯЁA-Z«])", line):
            before = line[start:m.start() + 1]
            last = before.split()[-1].lower() if before.split() else ""
            if last.endswith(_ABBR) or re.search(r"\d[.,]?$", last[:-1] if last.endswith(".") else last) and last.endswith("п.п."):
                continue
            out.append(line[start:m.end()].strip())
            start = m.end()
        out.append(line[start:].strip())
    return [p for p in out if p]
