"""Finding cards use only persisted facts and keep model calls opt-in."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from findings import generate_finding, read_finding
from graph_data import read_runs


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self):
        return json.dumps({"choices": [{"message": {"content": json.dumps({"findings": [
            {"title": "示例漏洞", "category": "访问控制", "location": "/example", "summary": "请求可读取资源",
             "impact": "读取资料", "evidence": ["HTTP 200"],
             "reproduction": [{"action": "请求 /example", "expected": "HTTP 200"}], "limitations": "仅限测试环境"}
        ]}, ensure_ascii=False)}}], "usage": {"prompt_tokens": 31, "completion_tokens": 17, "total_tokens": 48}}).encode()


class FindingTests(unittest.TestCase):
    def test_generate_persists_card_and_usage_and_invalidates_on_fact_change(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"CAIRN_DESKTOP_STORAGE_ROOT": folder}):
            detail = {"facts": [{"id": "f1", "description": "GET /example returned HTTP 200"}],
                      "intents": [{"id": "i1", "to": "f1", "description": "Verify access"}]}
            with patch("findings.urllib.request.urlopen", return_value=_Response()) as request:
                result = generate_finding("p1", "f1", detail, "test-key", "deepseek-flash")
            self.assertEqual(result["findings"][0]["reproduction"][0]["expected"], "HTTP 200")
            self.assertEqual(read_finding("p1", "f1", detail)["findings"], result["findings"])
            self.assertEqual(read_runs(Path(folder) / "output", "p1")[0]["token_usage"]["total_tokens"], 48)
            sent = json.loads(request.call_args.args[0].data)
            self.assertIn("GET /example returned HTTP 200", sent["messages"][1]["content"])
            self.assertNotIn("test-key", (Path(folder) / "output" / "p1" / "workspace" / ".cairn" / "findings" / "f1.json").read_text(encoding="utf-8"))
            detail["facts"][0]["description"] = "changed"
            self.assertTrue(read_finding("p1", "f1", detail)["stale"])

    def test_invalid_ids_and_origin_do_not_call_model(self):
        detail = {"facts": [{"id": "origin", "description": "start"}], "intents": []}
        with self.assertRaises(ValueError):
            generate_finding("p1", "origin", detail, "test-key", "deepseek-flash")
        with self.assertRaises(ValueError):
            read_finding("../escape", "../f1", detail)


if __name__ == "__main__":
    unittest.main()
