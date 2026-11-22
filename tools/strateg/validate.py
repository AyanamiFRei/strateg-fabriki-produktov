"""Проверка репозитория перед запуском/сдачей: навыки, роли, размер AGENTS.md, секреты, адаптеры."""
from __future__ import annotations

import re

from . import store, sync

SECRET = re.compile(r"(sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|xox[bp]-[A-Za-z0-9-]{20,}|"
                    r"-----BEGIN (RSA |EC )?PRIVATE KEY-----|Bearer [A-Za-z0-9._-]{30,})")
SKIP_DIRS = {".git", ".cache", "__pycache__", "node_modules"}


def run() -> int:
    R = store.ROOT
    errs, warns = [], []
    a = R / "AGENTS.md"
    if not a.exists():
        errs.append("нет AGENTS.md")
    else:
        n = len(a.read_text(encoding="utf-8").splitlines())
        size = a.stat().st_size
        if n > 160:
            warns.append(f"AGENTS.md {n} строк (цель ≤150)")
        if size > 32 * 1024:
            errs.append("AGENTS.md больше 32 KiB (Codex обрежет)")
    for f in sorted((R / ".agents" / "skills").glob("*/SKILL.md")):
        meta, body = sync._frontmatter(f.read_text(encoding="utf-8"))
        if meta.get("name") != f.parent.name:
            errs.append(f"{f.parent.name}: name во frontmatter должен совпадать с папкой")
        d = meta.get("description", "")
        if not d or len(d) > 1024:
            errs.append(f"{f.parent.name}: description пуст или длиннее 1024 символов")
        if "$ARGUMENTS" in body:
            warns.append(f"{f.parent.name}: $ARGUMENTS непереносим между IDE")
        if len(body.splitlines()) > 300:
            warns.append(f"{f.parent.name}: тело навыка длиннее 300 строк")
    for f in sorted((R / "agent" / "roles").glob("*.md")):
        meta, _ = sync._frontmatter(f.read_text(encoding="utf-8"))
        for k in ("name", "description", "tier"):
            if not meta.get(k):
                errs.append(f"роль {f.name}: нет поля {k}")
    for f in R.rglob("*"):
        if f.is_file() and not (set(f.relative_to(R).parts) & SKIP_DIRS) and f.suffix in (
                ".md", ".json", ".jsonl", ".py", ".toml", ".txt", ".env", ".yaml", ".yml", ".mdc"):
            try:
                if SECRET.search(f.read_text(encoding="utf-8", errors="ignore")):
                    errs.append(f"похоже на секрет: {f.relative_to(R)}")
            except Exception:
                pass
    if (R / ".env").exists():
        gi = (R / ".gitignore").read_text(encoding="utf-8") if (R / ".gitignore").exists() else ""
        if ".env" not in gi:
            errs.append(".env есть, но не в .gitignore")
    rc = sync.run(check=True)
    if rc:
        errs.append("адаптеры не синхронизированы")
    print(f"validate: ошибок {len(errs)}, предупреждений {len(warns)}")
    for e in errs:
        print("  ✗", e)
    for w in warns:
        print("  !", w)
    return 2 if errs else 0
