"""Хранилище проекта: JSONL с дозаписью и версиями, атомарная запись, op_id, пути.

Все записи реестров (источники, утверждения, расчёты, решения, обязательства) хранятся
строками JSON. Изменение = новая строка с тем же id и v+1. Действует последняя версия.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

ROOT = Path(os.environ.get("STRATEG_ROOT") or Path(__file__).resolve().parents[2])  # корень репозитория
PROJECTS = ROOT / "projects"
CONFIG = ROOT / "config"


class StError(Exception):
    """Ошибка, которую CLI показывает человеку понятным текстом (код выхода 1)."""


class GateError(StError):
    """Нарушение ворот или запрет (код выхода 2)."""


class NeedHuman(StError):
    """Сделано, теперь нужен человек (код выхода 3)."""


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today() -> str:
    return _dt.date.today().isoformat()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(Path(p).read_bytes())


def canon(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def op_id(op: str, inputs) -> str:
    return f"{op}:{sha256_bytes(canon(inputs).encode('utf-8'))[:12]}"


# ------------------------------------------------------------------ файлы

def atomic_write(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        try:
            os.chmod(tmp, 0o644)
        except OSError:
            pass
        safe_replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def safe_replace(src, dst, tries: int = 6) -> None:
    """os.replace с повторами: на Windows файл может быть открыт IDE или антивирусом."""
    import time
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise StError(f"не удалось записать {dst}: файл занят другой программой — закройте его и повторите")
            time.sleep(0.25 * (i + 1))


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


def read_json(path: Path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, obj) -> None:
    atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def append_jsonl(path: Path, rec: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def read_jsonl(path: Path, warn: list | None = None) -> list:
    """Читает JSONL; оборванные строки пропускает и сообщает номер (устойчивость к сбоям)."""
    path = Path(path)
    out = []
    if not path.exists():
        return out
    with open(path, encoding="utf-8-sig") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                if warn is not None:
                    warn.append(f"{path.name}: строка {i} повреждена и пропущена")
    return out


def latest(records: list, key: str = "id") -> dict:
    """Последняя версия каждой записи по id (порядок дозаписи = порядок версий)."""
    cur: dict = {}
    for r in records:
        rid = r.get(key)
        if rid is None:
            continue
        if rid not in cur or r.get("v", 1) >= cur[rid].get("v", 1):
            cur[rid] = r
    return cur


def next_id(existing_ids, prefix: str, width: int = 2) -> str:
    n = 0
    pat = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    for i in existing_ids:
        m = pat.match(i)
        if m:
            n = max(n, int(m.group(1)))
    return f"{prefix}{n + 1:0{width}d}"


# ------------------------------------------------------------------ проект

class Project:
    """Пути и реестры одного проекта: projects/<slug>/"""

    def __init__(self, slug: str):
        if not SLUG_RE.match(slug or ""):
            raise StError(f"недопустимое имя проекта '{slug}': латиница в нижнем регистре, цифры, '-' и '_'")
        self.slug = slug
        self.dir = PROJECTS / slug
        if not self.dir.exists():
            raise StError(f"проект '{slug}' не найден в projects/. Создайте: python st.py init {slug}")

    # пути
    def p(self, *parts) -> Path:
        return self.dir.joinpath(*parts)

    @property
    def task_path(self):
        return self.p("state", "task.json")

    @property
    def journal_path(self):
        return self.p("state", "journal.jsonl")

    @property
    def cost_path(self):
        return self.p("state", "cost.jsonl")

    @property
    def sources_path(self):
        return self.p("evidence", "sources.jsonl")

    @property
    def claims_path(self):
        return self.p("evidence", "claims.jsonl")

    @property
    def decisions_path(self):
        return self.p("decisions", "decisions.jsonl")

    @property
    def commitments_path(self):
        return self.p("decisions", "commitments.jsonl")

    @property
    def observations_path(self):
        return self.p("decisions", "observations.jsonl")

    # состояние
    def task(self) -> dict:
        t = read_json(self.task_path)
        if t is None:
            raise StError(f"нет state/task.json в проекте {self.slug}")
        return t

    def save_task(self, t: dict) -> None:
        t["updated_at"] = now()
        write_json(self.task_path, t)

    # реестры
    def sources(self, warn=None) -> dict:
        return latest(read_jsonl(self.sources_path, warn))

    def claims(self, warn=None) -> dict:
        return latest(read_jsonl(self.claims_path, warn))

    def decisions(self, warn=None) -> dict:
        return latest(read_jsonl(self.decisions_path, warn))

    def commitments(self, warn=None) -> dict:
        return latest(read_jsonl(self.commitments_path, warn))

    def calcs(self) -> dict:
        out = {}
        d = self.p("analysis")
        if d.exists():
            for f in sorted(d.glob("K*.json")):
                if f.name.endswith(".out.json"):
                    continue
                spec = read_json(f)
                res = read_json(f.with_name(f.stem + ".out.json"))
                out[spec.get("id", f.stem)] = {"spec": spec, "out": res, "path": f}
        return out

    def all_ids(self) -> set:
        ids = set(self.sources()) | set(self.claims()) | set(self.decisions()) | set(self.commitments())
        ids |= set(self.calcs())
        return ids

    # журнал
    def log(self, **rec) -> dict:
        rec.setdefault("ts", now())
        rec.setdefault("stage", self.task().get("stage") if self.task_path.exists() else None)
        append_jsonl(self.journal_path, rec)
        return rec

    def journal(self, warn=None) -> list:
        return read_jsonl(self.journal_path, warn)

    def find_done(self, oid: str):
        for r in reversed(self.journal()):
            if r.get("op_id") == oid and r.get("phase") in ("done", "skipped_cached"):
                return r
        return None


def resolve_project(name: str | None) -> Project:
    """Проект из аргумента, переменной STRATEG_PROJECT или .current; иначе единственный проект."""
    if name:
        return Project(name)
    env = os.environ.get("STRATEG_PROJECT")
    if env:
        return Project(env)
    cur = PROJECTS / ".current"
    if cur.exists():
        slug = cur.read_text(encoding="utf-8").strip()
        if slug and (PROJECTS / slug).exists():
            return Project(slug)
    if PROJECTS.exists():
        cands = [d.name for d in PROJECTS.iterdir() if d.is_dir() and (d / "state" / "task.json").exists()]
        if len(cands) == 1:
            return Project(cands[0])
    raise StError("не выбран проект: python st.py use <slug> (список: папки в projects/) или новый: python st.py init <slug> --from <файл>")


def set_current(slug: str) -> None:
    PROJECTS.mkdir(parents=True, exist_ok=True)
    atomic_write(PROJECTS / ".current", slug + "\n")
