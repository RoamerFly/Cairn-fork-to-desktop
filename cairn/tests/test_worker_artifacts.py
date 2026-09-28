import json

from cairn.dispatcher.config import WorkerConfig
from cairn.dispatcher.runtime.process import ProcessResult
from cairn.dispatcher.tasks.common import archive_worker_result, extract_token_usage


def test_worker_archive_redacts_credentials_and_preserves_evidence() -> None:
    files = {}

    class Backend:
        def artifact_root(self):
            return "/home/kali/workspace/.cairn"

        def write_text_file(self, container, path, content):
            files[path] = content

    worker = WorkerConfig(
        name="test", type="codex", task_types=["bootstrap"], max_running=1, priority=0,
        env={"OPENAI_API_KEY": "private-test-key"},
    )
    result = ProcessResult(0, "evidence recorded", "private-test-key")
    archive_worker_result(Backend(), "container", worker, ["codex", "prompt"], "bootstrap", result,
                          intent_id="i003", started_at="2026-01-01T00:00:00Z", duration_ms=1250)
    assert len(files) == 3
    assert all(path.startswith("/home/kali/workspace/.cairn/runs/bootstrap-") for path in files)
    assert "evidence recorded" in files.values()
    assert "[REDACTED]" in files.values()
    assert all("private-test-key" not in content for content in files.values())
    metadata = json.loads(next(content for path, content in files.items() if path.endswith("task.json")))
    assert metadata["intent_id"] == "i003"
    assert metadata["duration_ms"] == 1250
    assert metadata["started_at"] == "2026-01-01T00:00:00Z"
    assert metadata["finished_at"]
    assert metadata["token_usage"] is None


def test_extracts_reported_token_usage_from_codex_pi_and_claude_output() -> None:
    codex = '{"type":"turn.completed","usage":{"input_tokens":21,"output_tokens":7,"total_tokens":28}}'
    assert extract_token_usage(codex) == {
        "input_tokens": 21, "output_tokens": 7, "total_tokens": 28,
    }

    pi = '{"type":"agent_end","messages":[{"role":"assistant","usage":{"input":11,"output":4,"cacheRead":3}}]}'
    assert extract_token_usage(pi) == {
        "input_tokens": 11, "output_tokens": 4, "cached_input_tokens": 3, "total_tokens": 15,
    }

    claude = '{"result":"ok","usage":{"input_tokens":13,"output_tokens":5,"cache_read_input_tokens":2}}'
    assert extract_token_usage(claude) == {
        "input_tokens": 13, "output_tokens": 5, "cached_input_tokens": 2, "total_tokens": 18,
    }
    assert extract_token_usage("plain text without provider usage") is None
