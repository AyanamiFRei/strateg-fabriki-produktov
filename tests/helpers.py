"""Общие функции тестов: временный корень репозитория и запуск CLI в отдельном процессе."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "tests" / "fixtures" / "tiny"
COPY = ["AGENTS.md", "agent", "kb", "config", ".agents"]


def make_root(name: str = "root") -> Path:
    base = Path(tempfile.mkdtemp(prefix="strateg-"))
    root = base / name
    root.mkdir(parents=True)
    for item in COPY:
        src = REPO / item
        if src.is_dir():
            shutil.copytree(src, root / item)
        elif src.exists():
            shutil.copy2(src, root / item)
    (root / "projects").mkdir()
    return root


def st(root: Path, *args, env_extra=None, input_text=None):
    env = dict(os.environ, STRATEG_ROOT=str(root), PYTHONIOENCODING="utf-8")
    env.pop("STRATEG_PROJECT", None)
    if env_extra:
        env.update(env_extra)
    r = subprocess.run([sys.executable, str(REPO / "st.py"), *map(str, args)], cwd=str(root), env=env,
                       capture_output=True, input=(input_text or "").encode("utf-8"))
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def setup_tiny(root: Path, slug: str = "tiny", import_claims: bool = True):
    code, out, err = st(root, "init", slug, "--from", FIX / "brief.md", "--title", "Подписка на обеды")
    assert code == 0, err
    p = root / "projects" / slug
    if import_claims:
        shutil.copy2(FIX / "inbox.jsonl", p / "inbox" / "a.jsonl")
        code, out, err = st(root, "claim", "import")
        assert code == 0, out + err
        for k in ("K01", "K02", "K03"):
            shutil.copy2(FIX / f"{k}.json", p / "analysis" / f"{k}.json")
        code, out, err = st(root, "calc", "run")
        assert code == 0, out + err
    return p


def draft(p: Path, name: str):
    shutil.copy2(FIX / "drafts" / name, p / "deliverables" / name)


def jsonl(path: Path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
