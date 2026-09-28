"""Read-only project graph and persisted Worker records; works without Docker."""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict, deque
from contextlib import closing
from pathlib import Path


def read_projects(database: Path, project_id: str | None = None) -> list[dict]:
    if not database.is_file():
        return []
    uri = database.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN")
        rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
        projects = []
        for row in rows:
            if project_id is not None and row["id"] != project_id:
                continue
            project = dict(row)
            pid = project["id"]
            facts = [dict(item) for item in conn.execute(
                "SELECT id, description FROM facts WHERE project_id = ? ORDER BY rowid", (pid,)
            )]
            intents = []
            for item in conn.execute("SELECT * FROM intents WHERE project_id = ? ORDER BY created_at, id", (pid,)):
                intent = dict(item)
                intent["to"] = intent.pop("to_fact_id")
                intent["from"] = [source[0] for source in conn.execute(
                    "SELECT fact_id FROM intent_sources WHERE project_id = ? AND intent_id = ? ORDER BY rowid",
                    (pid, intent["id"]),
                )]
                intents.append(intent)
            hints = [dict(item) for item in conn.execute(
                "SELECT * FROM hints WHERE project_id = ? ORDER BY created_at", (pid,)
            )]
            projects.append({"project": project, "facts": facts, "intents": intents, "hints": hints})
        return projects


def build_graph(detail: dict) -> tuple[dict[str, dict], list[tuple[str, str]]]:
    nodes = {}
    edges = []
    for fact in detail.get("facts", []):
        nodes[f"fact:{fact['id']}"] = {**fact, "kind": "fact"}
    for intent in detail.get("intents", []):
        key = f"intent:{intent['id']}"
        nodes[key] = {**intent, "kind": "intent"}
        for source in intent.get("from", []):
            if f"fact:{source}" in nodes:
                edges.append((f"fact:{source}", key))
        target = f"fact:{intent.get('to')}"
        if target in nodes:
            edges.append((key, target))
    return nodes, edges


def layout_graph(nodes: dict, edges: list[tuple[str, str]]) -> tuple[dict[str, tuple[int, int]], bool]:
    """Lay out actual dependencies from top to bottom, preserving parallel branches."""
    indegree = {key: 0 for key in nodes}
    successors = defaultdict(list)
    levels = {key: 0 for key in nodes}
    for source, target in edges:
        successors[source].append(target)
        indegree[target] += 1
    ready = deque(key for key in nodes if indegree[key] == 0)
    seen = set()
    while ready:
        key = ready.popleft()
        seen.add(key)
        for target in successors[key]:
            levels[target] = max(levels[target], levels[key] + 1)
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    cycle = len(seen) != len(nodes)
    for key in (key for key in nodes if key not in seen):
        levels[key] = max(levels.values(), default=0) + 1
    # A goal exists from project creation; place it last without inventing an edge.
    if "fact:goal" in nodes:
        levels["fact:goal"] = max(levels.values(), default=0)
        if not any(target == "fact:goal" for _, target in edges):
            levels["fact:goal"] += 1
    rows = defaultdict(int)
    positions = {}
    for key in nodes:
        level = levels[key]
        positions[key] = (40 + rows[level] * 300, 45 + level * 170)
        rows[level] += 1
    return positions, cycle


def project_folder(output: Path, project_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", project_id):
        raise ValueError("Invalid project ID")
    folder = (output / project_id).resolve()
    if not folder.is_relative_to(output.resolve()):
        raise ValueError("Project folder escapes output directory")
    return folder


def read_runs(output: Path, project_id: str) -> list[dict]:
    folder = project_folder(output, project_id)
    records = []
    for path in sorted((folder / "workspace" / ".cairn" / "runs").glob("*/task.json")):
        if not path.resolve().is_relative_to(folder):
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(record, dict):
                record["directory"] = str(path.parent)
                records.append(record)
        except (OSError, ValueError):
            continue  # A phase may be writing its metadata during a refresh.
    return sorted(records, key=lambda item: item.get("started_at") or Path(item["directory"]).name)


def read_record_text(record: dict, name: str, limit: int = 200_000) -> str:
    if name not in {"stdout.log", "stderr.log"}:
        raise ValueError("Unsupported log file")
    path = Path(record["directory"]) / name
    try:
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            content = stream.read(limit + 1)
        return content[:limit] + ("\n\n[显示已截断，请打开记录目录查看完整文件]" if len(content) > limit else "")
    except OSError:
        return "记录尚未写入。"


def related_intents(node: dict, detail: dict) -> set[str]:
    if node["kind"] == "intent":
        return {node["id"]}
    return {intent["id"] for intent in detail.get("intents", []) if intent.get("to") == node["id"]}
