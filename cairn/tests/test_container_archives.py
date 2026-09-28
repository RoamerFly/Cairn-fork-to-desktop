from __future__ import annotations

import io
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from cairn.dispatcher.runtime.containers import ContainerManager


def test_text_file_archive_extracts_below_existing_top_level_directory() -> None:
    archive_path, payload = ContainerManager._text_file_archive(
        "/tmp/cairn-prompts/reason_execute-123/graph.yaml",
        "facts:\n- id: f001\n",
    )

    assert archive_path == "/tmp"
    with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        names = archive.getnames()
        assert names == [
            "cairn-prompts",
            "cairn-prompts/reason_execute-123",
            "cairn-prompts/reason_execute-123/graph.yaml",
        ]
        assert "tmp" not in names
        graph = archive.extractfile("cairn-prompts/reason_execute-123/graph.yaml")
        assert graph is not None
        assert graph.read() == b"facts:\n- id: f001\n"


@pytest.mark.parametrize("path", ["relative.txt", "/", "/tmp/../escape.txt"])
def test_text_file_archive_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(ValueError):
        ContainerManager._text_file_archive(path, "content")


def test_persistent_agent_workspace_is_isolated_by_project(tmp_path: Path) -> None:
    manager = object.__new__(ContainerManager)
    manager._persistence_local_root = tmp_path / "dispatcher-output"
    manager._persistence_host_root = tmp_path / "host-output"

    volumes = manager._workspace_volumes("p0001")

    workspace = tmp_path / "dispatcher-output" / "p0001" / "workspace"
    assert (workspace / "AGENTS.md").is_file()
    assert (tmp_path / "dispatcher-output" / "p0001" / "codex").is_dir()
    assert volumes[str(tmp_path / "host-output" / "p0001" / "workspace")]["bind"] == "/home/kali/workspace"
    assert volumes[str(tmp_path / "host-output" / "p0001" / "codex")]["bind"] == "/home/kali/.codex"
    with pytest.raises(ValueError):
        manager._workspace_volumes("../escape")


def test_existing_container_cannot_reuse_another_storage_root(tmp_path: Path) -> None:
    manager = object.__new__(ContainerManager)
    manager._persistence_local_root = tmp_path / "dispatcher-output"
    manager._persistence_host_root = tmp_path / "host-output"
    expected = manager._workspace_volumes("proj_001")
    mounts = [
        {"Type": "bind", "Destination": volume["bind"], "Source": source}
        for source, volume in expected.items()
    ]
    manager._require_container = lambda name: SimpleNamespace(attrs={"Mounts": mounts})
    manager._verify_workspace_mounts("cairn-dispatch-proj_001")
    mounts[0]["Source"] = str(tmp_path / "another-root")
    with pytest.raises(RuntimeError, match="different workspace"):
        manager._verify_workspace_mounts("cairn-dispatch-proj_001")

