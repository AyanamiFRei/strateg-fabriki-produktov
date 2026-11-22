"""Минимальный MCP-сервер (stdio, JSON-RPC 2.0, только чтение) поверх тех же функций st.py.

Нужен для IDE, где терминал ограничен (режимы Ask, плагины): resume, status, search, why, check, due.
Записи по-прежнему делает только CLI — так сохраняется единственный путь к побочным эффектам.
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout

from . import store

TOOLS = {
    "resume": {"description": "Сводка проекта для продолжения работы", "props": {}},
    "status": {"description": "PROGRESS.md: стадии, ожидания от человека, стоимость", "props": {}},
    "search": {"description": "Поиск по реестру, источникам, документам и базе знаний",
               "props": {"query": {"type": "string"}, "kind": {"type": "string"}}},
    "why": {"description": "Происхождение записи (F/A/H/P/I/K/S/D)", "props": {"id": {"type": "string"}}},
    "check": {"description": "Проверка стадии (framing…after) или all", "props": {"stage": {"type": "string"}}},
    "due": {"description": "Сопровождение решений: триггеры, просрочки, что решать сейчас", "props": {}},
}


def _call(name: str, args: dict) -> str:
    from . import cli
    argv = []
    if args.get("project"):
        argv += ["--project", args["project"]]
    if name == "search":
        argv += ["search", args.get("query", "")] + (["--kind", args["kind"]] if args.get("kind") else [])
    elif name == "why":
        argv += ["why", args.get("id", "")]
    elif name == "check":
        argv += ["check", args.get("stage", "all")]
    elif name == "due":
        argv += ["decide", "due"]
    else:
        argv += [name]
    buf = io.StringIO()
    with redirect_stdout(buf):
        try:
            cli.main(argv)
        except SystemExit:
            pass
    return buf.getvalue()


def serve() -> int:
    stream = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    for line in stream:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        mid, method = msg.get("id"), msg.get("method")
        if mid is None:
            continue  # уведомления
        if method == "initialize":
            res = {"protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
                   "capabilities": {"tools": {}}, "serverInfo": {"name": "strateg", "version": "1.0"}}
        elif method == "tools/list":
            res = {"tools": [{"name": n, "description": t["description"],
                              "inputSchema": {"type": "object", "properties": dict(t["props"], project={"type": "string"})}}
                             for n, t in TOOLS.items()]}
        elif method == "tools/call":
            p = msg.get("params", {})
            if p.get("name") not in TOOLS:
                res = {"content": [{"type": "text", "text": "нет такого инструмента"}], "isError": True}
            else:
                res = {"content": [{"type": "text", "text": _call(p["name"], p.get("arguments") or {})}]}
        elif method == "ping":
            res = {}
        else:
            print(json.dumps({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}),
                  flush=True)
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": mid, "result": res}, ensure_ascii=False), flush=True)
    return 0
