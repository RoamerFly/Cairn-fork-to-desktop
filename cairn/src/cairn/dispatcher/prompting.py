from __future__ import annotations

import json
from importlib import resources
from typing import Any


def load_prompt(group: str, name: str, output_language: str = "auto") -> str:
    text = resources.files("cairn.dispatcher.prompts").joinpath(group).joinpath(name).read_text(encoding="utf-8")
    languages = {"zh-CN": "Simplified Chinese (简体中文)", "en": "English"}
    if output_language in languages:
        text += (
            "\n\n## User-facing output language\n"
            f"Write all user-facing fact descriptions, intent descriptions, summaries and report files in {languages[output_language]}. "
            "Keep JSON field names, identifiers, commands, paths and verbatim evidence unchanged. "
            "This language requirement applies even when task context or previous records use a different language.\n"
        )
    return text


def render_prompt(template: str, replacements: dict[str, str]) -> str:
    text = template
    for key, value in replacements.items():
        text = text.replace("{" + key + "}", value)
    return text


def format_fact_ids(fact_ids: list[str]) -> str:
    return format_json_block(fact_ids)


def format_open_intents(intents: list[dict[str, Any]]) -> str:
    return format_json_block(intents)


def format_hints(hints: list[dict[str, Any]]) -> str:
    return format_json_block(hints)


def format_json_block(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)
