from importlib import resources

import pytest

from cairn.dispatcher.prompting import load_prompt
from cairn.dispatcher.config import RuntimeConfig


@pytest.mark.parametrize("name", ["bootstrap.md", "bootstrap_conclude.md", "reason.md", "explore.md", "explore_conclude.md"])
def test_language_requirement_covers_every_agent_phase(name):
    original = resources.files("cairn.dispatcher.prompts").joinpath("default", name).read_text(encoding="utf-8")
    assert load_prompt("default", name) == original
    chinese = load_prompt("default", name, "zh-CN")
    assert chinese.startswith(original)
    assert "Simplified Chinese (简体中文)" in chinese
    assert "Keep JSON field names, identifiers, commands, paths and verbatim evidence unchanged" in chinese
    assert "English" in load_prompt("default", name, "en")


def test_invalid_language_is_rejected_by_config():
    values = dict(max_workers=1, max_running_projects=1, max_project_workers=1,
                  interval=1, healthcheck_timeout=60, prompt_group="default")
    assert RuntimeConfig(**values).output_language == "auto"
    assert RuntimeConfig(**values, output_language="zh-CN").output_language == "zh-CN"
    with pytest.raises(ValueError):
        RuntimeConfig(**values, output_language="invalid")
