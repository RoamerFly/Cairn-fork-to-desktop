from __future__ import annotations

import logging
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from cairn.dispatcher.config import DispatchConfig, WorkerConfig
from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.runtime.cancellation import TaskCancellation
from cairn.dispatcher.runtime.containers import ContainerManager
from cairn.dispatcher.runtime.heartbeat import HeartbeatLease
from cairn.dispatcher.runtime.process import ProcessResult

PROCESS_COMMUNICATE_GRACE_SECONDS = 15
LOG_PREVIEW_LIMIT = 1200
GRAPH_SNAPSHOT_ROOT = "/tmp/cairn-prompts"
LOG = logging.getLogger(__name__)


@dataclass(slots=True)
class ConcludeWriteResult:
    status: str
    fact_id: str | None = None


def preview(text: str, limit: int = LOG_PREVIEW_LIMIT) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def did_timeout(result: ProcessResult) -> bool:
    return not result.cancelled and (result.timed_out or result.returncode in (124, 137))


def cancel_reason(result: ProcessResult, cancellation: TaskCancellation | None = None) -> str | None:
    if result.cancelled:
        return result.cancel_reason or "cancelled"
    if cancellation is not None:
        return cancellation.reason
    return None


def communicate_timeout(timeout_seconds: int, grace_seconds: int = PROCESS_COMMUNICATE_GRACE_SECONDS) -> int:
    return timeout_seconds + grace_seconds


def task_healthcheck_enabled(config: DispatchConfig) -> bool:
    if config.runtime.execution == "local":
        return False
    return config.runtime.worker_healthcheck == "startup_and_task"


def write_graph_snapshot_reference(
    container_manager: ContainerManager,
    container_name: str,
    graph_yaml: str,
    *,
    phase: str,
) -> str:
    root = getattr(container_manager, "artifact_root", lambda: None)()
    snapshot_root = f"{root}/prompts" if root else GRAPH_SNAPSHOT_ROOT
    path = f"{snapshot_root}/{phase}-{uuid.uuid4().hex[:12]}/graph.yaml"
    container_manager.write_text_file(container_name, path, graph_yaml)
    return (
        "The graph YAML snapshot is stored in this file inside the current container:\n\n"
        f"{path}\n\n"
        "Before using the graph, read the entire file and treat its contents as the YAML snapshot "
        "for this Graph section."
    )


def run_worker_process(
    container_manager: ContainerManager,
    container_name: str,
    worker: WorkerConfig,
    argv: list[str],
    *,
    phase: str,
    timeout_seconds: int,
    lease: HeartbeatLease | None = None,
    cancellation: TaskCancellation | None = None,
    intent_id: str | None = None,
) -> ProcessResult:
    LOG.info(
        "starting container exec container=%s worker=%s phase=%s timeout=%ss",
        container_name,
        worker.name,
        phase,
        timeout_seconds,
    )
    process = container_manager.build_exec_process(
        container_name,
        dict(worker.env),
        argv,
        timeout_seconds=timeout_seconds,
    )
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    process.start()
    if lease is not None:
        lease.attach_process(process)
    if cancellation is not None:
        cancellation.attach_process(process)
    try:
        result = process.communicate(timeout=communicate_timeout(timeout_seconds))
        archive_worker_result(
            container_manager, container_name, worker, argv, phase, result,
            intent_id=intent_id, started_at=started_at,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return result
    finally:
        if lease is not None:
            lease.attach_process(None)
        if cancellation is not None:
            cancellation.attach_process(None)


def archive_worker_result(
    container_manager: ContainerManager,
    container_name: str,
    worker: WorkerConfig,
    argv: list[str],
    phase: str,
    result: ProcessResult,
    *,
    intent_id: str | None = None,
    started_at: str | None = None,
    duration_ms: int | None = None,
) -> None:
    root = getattr(container_manager, "artifact_root", lambda: None)()
    if not root:
        return
    directory = f"{root}/runs/{phase}-{uuid.uuid4().hex[:12]}"
    secrets = [value for key, value in worker.env.items() if any(token in key.upper() for token in ("KEY", "TOKEN", "PASSWORD")) and value]

    def redact(text: str) -> str:
        for secret in secrets:
            text = text.replace(secret, "[REDACTED]")
        return text

    metadata = {
        "worker": worker.name,
        "phase": phase,
        "argv": argv,
        "returncode": result.returncode,
        "timed_out": result.timed_out,
        "cancelled": result.cancelled,
        "cancel_reason": result.cancel_reason,
        "intent_id": intent_id,
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": duration_ms,
        "token_usage": extract_token_usage(result.stdout, result.stderr),
    }
    try:
        for name, content in (
            ("task.json", json.dumps(metadata, ensure_ascii=False, indent=2)),
            ("stdout.log", result.stdout),
            ("stderr.log", result.stderr),
        ):
            container_manager.write_text_file(container_name, f"{directory}/{name}", redact(content))
    except Exception as exc:
        LOG.warning("could not archive worker process container=%s phase=%s error=%s", container_name, phase, exc)


def extract_token_usage(stdout: str, stderr: str = "") -> dict[str, int] | None:
    """Extract provider-reported token counts from supported CLI JSON output."""

    def normalized(value: object) -> dict[str, int] | None:
        if not isinstance(value, dict):
            return None
        details = value.get("input_tokens_details") or value.get("prompt_tokens_details") or {}
        input_tokens = value.get("input_tokens", value.get("prompt_tokens", value.get("input", value.get("inputTokens"))))
        output_tokens = value.get("output_tokens", value.get("completion_tokens", value.get("output", value.get("outputTokens"))))
        cached = value.get("cached_input_tokens", value.get("cache_read_input_tokens",
                          value.get("cacheRead", value.get("cacheReadInputTokens"))))
        if cached is None and isinstance(details, dict):
            cached = details.get("cached_tokens")
        values = (input_tokens, output_tokens, cached)
        if not any(isinstance(item, (int, float)) and item >= 0 for item in values):
            return None
        usage = {}
        if isinstance(input_tokens, (int, float)) and input_tokens >= 0:
            usage["input_tokens"] = int(input_tokens)
        if isinstance(output_tokens, (int, float)) and output_tokens >= 0:
            usage["output_tokens"] = int(output_tokens)
        if isinstance(cached, (int, float)) and cached >= 0:
            usage["cached_input_tokens"] = int(cached)
        total = value.get("total_tokens", value.get("totalTokens"))
        if isinstance(total, (int, float)) and total >= 0:
            usage["total_tokens"] = int(total)
        elif "input_tokens" in usage and "output_tokens" in usage:
            usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
        return usage

    def sum_usages(usages):
        if not usages:
            return None
        keys = {key for usage in usages for key in usage}
        return {key: sum(usage.get(key, 0) for usage in usages) for key in keys}

    text = stdout.strip()
    candidates = []
    if text:
        try:
            root = json.loads(text)
        except json.JSONDecodeError:
            root = None
        if isinstance(root, dict):
            usage = normalized(root.get("usage"))
            if usage:
                return usage
            model_usage = root.get("modelUsage")
            if isinstance(model_usage, dict):
                return sum_usages([u for item in model_usage.values() if (u := normalized(item))])
        for line in text.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else event
            event_type = payload.get("type") or event.get("type")
            info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
            usage = (normalized(payload.get("usage")) or normalized(payload.get("last_token_usage"))
                     or normalized(info.get("last_token_usage")))
            if usage and event_type in {"turn.completed", "agent_end", "turn_end", "token_count"}:
                candidates.append((event_type, usage))
                continue
            messages = payload.get("messages")
            if event_type == "agent_end" and isinstance(messages, list):
                candidates.append((event_type, sum_usages([
                    u for message in messages if isinstance(message, dict)
                    and message.get("role") == "assistant"
                    and (u := normalized(message.get("usage")))
                ])))
        codex_turns = [usage for kind, usage in candidates if kind == "turn.completed"]
        if codex_turns:
            return sum_usages(codex_turns)
        pi_turns = [usage for kind, usage in candidates if kind == "agent_end" and usage]
        if pi_turns:
            return sum_usages(pi_turns)
        other = [usage for _kind, usage in candidates if usage]
        if other:
            return other[-1]
    return None


def project_allows_conclude_fallback(client: CairnClient, project_id: str, *, worker_name: str, intent_id: str) -> bool:
    project = client.get_project(project_id)
    if project.project.status == "active":
        return True
    LOG.info(
        "skip conclude fallback because project is no longer active project=%s intent=%s worker=%s status=%s",
        project_id,
        intent_id,
        worker_name,
        project.project.status,
    )
    return False


def best_effort_release_reason(client: CairnClient, project_id: str, worker_name: str) -> None:
    response = client.release_reason(project_id, worker_name)
    if not response.ok and response.status_code not in (403, 409):
        LOG.warning(
            "reason release failed project=%s worker=%s status=%s",
            project_id,
            worker_name,
            response.status_code,
        )
    elif response.ok:
        LOG.info("released reason project=%s worker=%s", project_id, worker_name)
    else:
        LOG.info(
            "reason release skipped project=%s worker=%s status=%s",
            project_id,
            worker_name,
            response.status_code,
        )


def write_conclude_result(
    client: CairnClient,
    project_id: str,
    intent_id: str,
    worker_name: str,
    description: str,
    *,
    source: str,
    phase_ms: int,
    total_ms: int | None = None,
) -> str:
    return write_conclude_result_with_fact_id(
        client,
        project_id,
        intent_id,
        worker_name,
        description,
        source=source,
        phase_ms=phase_ms,
        total_ms=total_ms,
    ).status


def write_conclude_result_with_fact_id(
    client: CairnClient,
    project_id: str,
    intent_id: str,
    worker_name: str,
    description: str,
    *,
    source: str,
    phase_ms: int,
    total_ms: int | None = None,
) -> ConcludeWriteResult:
    response = client.conclude(project_id, intent_id, worker_name, description)
    if response.ok:
        fact_id: str | None = None
        if isinstance(response.data, dict):
            fact = response.data.get("fact")
            if isinstance(fact, dict):
                candidate = fact.get("id")
                if isinstance(candidate, str) and candidate:
                    fact_id = candidate
        if total_ms is None:
            LOG.info(
                "intent concluded project=%s intent=%s worker=%s source=%s phase_ms=%s",
                project_id,
                intent_id,
                worker_name,
                source,
                phase_ms,
            )
        else:
            LOG.info(
                "intent concluded project=%s intent=%s worker=%s source=%s phase_ms=%s total_ms=%s",
                project_id,
                intent_id,
                worker_name,
                source,
                phase_ms,
                total_ms,
            )
        return ConcludeWriteResult(status="success", fact_id=fact_id)
    if response.status_code == 403:
        LOG.info(
            "project became inactive during conclude project=%s intent=%s worker=%s",
            project_id,
            intent_id,
            worker_name,
        )
    else:
        LOG.warning(
            "conclude write failed project=%s intent=%s worker=%s status=%s body=%s",
            project_id,
            intent_id,
            worker_name,
            response.status_code,
            response.text,
        )
    best_effort_release(client, project_id, intent_id, worker_name)
    return ConcludeWriteResult(status="failed", fact_id=None)


def best_effort_release(client: CairnClient, project_id: str, intent_id: str, worker_name: str) -> None:
    response = client.release(project_id, intent_id, worker_name)
    if not response.ok and response.status_code not in (403, 409):
        LOG.warning(
            "release failed project=%s intent=%s worker=%s status=%s",
            project_id,
            intent_id,
            worker_name,
            response.status_code,
        )
    elif response.ok:
        LOG.info("released intent project=%s intent=%s worker=%s", project_id, intent_id, worker_name)
    else:
        LOG.info(
            "release skipped project=%s intent=%s worker=%s status=%s",
            project_id,
            intent_id,
            worker_name,
            response.status_code,
        )
