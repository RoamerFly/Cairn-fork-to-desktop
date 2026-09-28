"""On-demand, source-grounded presentation of facts as finding and replay cards."""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import yaml

from core import data_root, output_root
from graph_data import project_folder


SYSTEM_PROMPT = """你是漏洞结果整理器。只把输入中的已有事实整理成中文 JSON，不进行新测试，不推断未证实的漏洞、影响、请求、结果或复现步骤。一个事实含多个独立发现时，分别列在 findings 中。无法确认漏洞时返回空 findings。每个发现的 evidence 必须忠实引用已有观察；reproduction 只写原文足以支持的可执行步骤及预期结果，信息不足就返回空数组。保留路径、参数、命令、载荷和状态码原样。不要把目标、计划或猜测写成已确认结果。输出 json object，格式：{"findings":[{"title":"","category":"","location":"","summary":"","impact":"","evidence":[""],"reproduction":[{"action":"","expected":""}],"limitations":""}]}。所有字段都必须存在；没有依据的字段填空字符串或空数组。"""


def _fact(detail: dict, fact_id: str) -> tuple[dict, dict | None]:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", fact_id):
        raise ValueError("无效事实 ID")
    fact = next((f for f in detail["facts"] if f["id"] == fact_id), None)
    if fact is None:
        raise KeyError(fact_id)
    intent = next((i for i in detail["intents"] if i.get("to") == fact_id), None)
    return fact, intent


def _source_hash(fact: dict, intent: dict | None) -> str:
    source = {"fact": fact["description"], "intent": intent.get("description", "") if intent else ""}
    return hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _path(project_id: str, fact_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", fact_id):
        raise ValueError("无效事实 ID")
    folder = project_folder(output_root(), project_id)
    path = folder / "workspace" / ".cairn" / "findings" / f"{fact_id}.json"
    if not path.resolve().is_relative_to(folder.resolve()):
        raise ValueError("事实结果路径超出任务目录")
    return path


def read_finding(project_id: str, fact_id: str, detail: dict) -> dict:
    fact, intent = _fact(detail, fact_id)
    path = _path(project_id, fact_id)
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"available": False, "findings": []}
    if not isinstance(report, dict) or not isinstance(report.get("findings"), list):
        return {"available": False, "findings": []}
    if report.get("source_hash") != _source_hash(fact, intent):
        return {"available": False, "findings": [], "stale": True}
    return {"available": True, "findings": report["findings"], "generated_at": report.get("generated_at")}


def _string(value, limit: int = 3000) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _normalize(raw: dict) -> list[dict]:
    if not isinstance(raw, dict):
        raise ValueError("模型未返回有效的漏洞列表，请重试。")
    findings = raw.get("findings")
    if not isinstance(findings, list):
        raise ValueError("模型未返回有效的漏洞列表，请重试。")
    result = []
    for item in findings[:12]:
        if not isinstance(item, dict):
            continue
        evidence = item.get("evidence", [])
        replay = item.get("reproduction", [])
        if not isinstance(evidence, list) or not isinstance(replay, list):
            raise ValueError("模型返回的证据或复现步骤格式不正确。")
        result.append({
            **{name: _string(item.get(name)) for name in ("title", "category", "location", "summary", "impact", "limitations")},
            "evidence": [_string(value) for value in evidence[:20] if _string(value)],
            "reproduction": [{"action": _string(step.get("action")), "expected": _string(step.get("expected"))}
                             for step in replay[:20] if isinstance(step, dict) and _string(step.get("action"))],
        })
    return result


def _api_base() -> str:
    config = data_root() / "dispatch.yaml"
    if not config.is_file():
        return "https://api.deepseek.com"
    saved = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    for worker in saved.get("workers", []):
        url = worker.get("env", {}).get("CODEX_BASE_URL")
        if url:
            if not isinstance(url, str) or not url.startswith("https://"):
                raise ValueError("模型接口地址必须使用 HTTPS。")
            return url.rstrip("/")
    return "https://api.deepseek.com"


def _record_usage(path: Path, fact_id: str, intent: dict | None, usages: list[dict], started: float,
                  outcome: str) -> None:
    if not usages:
        return
    keys = {"input_tokens": "prompt_tokens", "output_tokens": "completion_tokens", "total_tokens": "total_tokens"}
    totals = {target: sum(item.get(source, 0) for item in usages) for target, source in keys.items()}
    if not all(isinstance(value, int) for value in totals.values()):
        return
    run = path.parent.parent / "runs" / f"finding-format-{uuid4().hex[:12]}"
    run.mkdir(parents=True, exist_ok=True)
    metadata = {"phase": "finding_format", "worker": "desktop-deepseek", "intent_id": intent.get("id") if intent else None,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": round((time.monotonic() - started) * 1000),
                "returncode": 0 if outcome == "ok" else 1, "token_usage": totals, "fact_id": fact_id}
    (run / "task.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (run / "stdout.log").write_text("漏洞结果整理已保存到 " + str(path) if outcome == "ok" else "", encoding="utf-8")
    (run / "stderr.log").write_text("" if outcome == "ok" else outcome, encoding="utf-8")


def generate_finding(project_id: str, fact_id: str, detail: dict, key: str, model: str) -> dict:
    fact, intent = _fact(detail, fact_id)
    if fact_id in {"origin", "goal"}:
        raise ValueError("起点和目标不是漏洞发现，无法整理。")
    if not key:
        raise ValueError("请先在设置中保存 DeepSeek API Key。")
    source = {"fact_id": fact_id, "fact": fact["description"],
              "producing_intent": intent.get("description", "") if intent else ""}
    request_body = {"model": model, "messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(source, ensure_ascii=False)},
    ], "thinking": {"type": "disabled"}, "response_format": {"type": "json_object"},
       "stream": False, "max_tokens": 6000}
    started = time.monotonic()
    usages = []
    failure = "模型未返回有效的 JSON 漏洞结果。"
    findings = None
    path = _path(project_id, fact_id)
    for attempt in range(2):
        if attempt:
            request_body["messages"][1]["content"] += "\n请直接返回完整 JSON 对象，不要返回空内容。"
        request = urllib.request.Request(_api_base() + "/chat/completions",
            data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"), method="POST",
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                answer = json.load(response)
        except urllib.error.HTTPError as exc:
            _record_usage(path, fact_id, intent, usages, started, "模型接口请求失败")
            raise ValueError(f"模型整理失败：HTTP {exc.code}。请检查设置中的密钥和模型。") from exc
        except urllib.error.URLError as exc:
            _record_usage(path, fact_id, intent, usages, started, "模型接口连接失败")
            raise ValueError("无法连接模型接口，请检查网络和接口地址。") from exc
        usage = answer.get("usage")
        if isinstance(usage, dict):
            usages.append(usage)
        try:
            choice = answer["choices"][0]
            content = choice["message"]["content"]
            if choice.get("finish_reason") == "length":
                failure = "模型输出被截断；请尝试缩短原始事实后重试。"
                continue
            if not isinstance(content, str) or not content.strip():
                failure = "模型返回了空内容。"
                continue
            findings = _normalize(json.loads(content))
            break
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValueError):
            failure = "模型未返回有效的 JSON 漏洞结果。"
    if findings is None:
        _record_usage(path, fact_id, intent, usages, started, failure)
        raise ValueError(failure + "已自动重试一次，请稍后再试。")

    generated_at = datetime.now(timezone.utc).isoformat()
    report = {"fact_id": fact_id, "source_hash": _source_hash(fact, intent),
              "generated_at": generated_at, "findings": findings}
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_suffix(".json.tmp")
    staged.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    staged.replace(path)

    _record_usage(path, fact_id, intent, usages, started, "ok")
    return {"available": True, "findings": findings, "generated_at": generated_at}
