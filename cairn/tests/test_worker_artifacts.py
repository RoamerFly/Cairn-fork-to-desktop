from cairn.dispatcher.config import WorkerConfig
from cairn.dispatcher.runtime.process import ProcessResult
from cairn.dispatcher.tasks.common import archive_worker_result


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
    archive_worker_result(Backend(), "container", worker, ["codex", "prompt"], "bootstrap", result)
    assert len(files) == 3
    assert all(path.startswith("/home/kali/workspace/.cairn/runs/bootstrap-") for path in files)
    assert "evidence recorded" in files.values()
    assert "[REDACTED]" in files.values()
    assert all("private-test-key" not in content for content in files.values())
