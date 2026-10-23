"""Validate offline graph reading, branching layout and record association."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from graph_data import build_graph, layout_graph, project_folder, read_projects, read_runs, related_intents


class GraphDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "cairn.db"
        with closing(sqlite3.connect(self.db)) as conn:
            conn.executescript("""
                CREATE TABLE projects(id TEXT, title TEXT, status TEXT, created_at TEXT);
                CREATE TABLE facts(id TEXT, project_id TEXT, description TEXT);
                CREATE TABLE intents(id TEXT, project_id TEXT, to_fact_id TEXT, description TEXT,
                    creator TEXT, worker TEXT, created_at TEXT, concluded_at TEXT);
                CREATE TABLE intent_sources(intent_id TEXT, project_id TEXT, fact_id TEXT);
                CREATE TABLE hints(id TEXT, project_id TEXT, content TEXT, created_at TEXT);
                INSERT INTO projects VALUES('p1','分支任务','completed','2026-01-01T00:00:00Z');
            """)
            conn.executemany("INSERT INTO facts VALUES(?, 'p1', ?)",
                             [(key, key) for key in ("origin", "goal", "f1", "f2")])
            for iid, target, sources in (("i1", "f1", ["origin"]), ("i2", "f2", ["origin"]), ("i3", "goal", ["f1", "f2"])):
                conn.execute("INSERT INTO intents VALUES(?, 'p1', ?, 'action', 'test', 'test', 't1', 't2')", (iid, target))
                conn.executemany("INSERT INTO intent_sources VALUES(?, 'p1', ?)", [(iid, source) for source in sources])
            conn.commit()

    def tearDown(self):
        self.temp.cleanup()

    def test_offline_read_keeps_database_unchanged_and_joins_branches(self):
        before = self.db.read_bytes()
        detail = read_projects(self.db, "p1")[0]
        nodes, edges = build_graph(detail)
        positions, cycle = layout_graph(nodes, edges)
        self.assertFalse(cycle)
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(len(nodes), 7)
        self.assertIn(("fact:f1", "intent:i3"), edges)
        self.assertIn(("fact:f2", "intent:i3"), edges)
        self.assertIn(("intent:i3", "fact:goal"), edges)
        self.assertEqual(related_intents(nodes["fact:goal"], detail), {"i3"})
        for source, target in edges:
            self.assertLess(positions[source][1], positions[target][1])

    def test_pending_goal_does_not_invent_completion_edge(self):
        detail = {"facts": [{"id": "origin"}, {"id": "goal"}],
                  "intents": [{"id": "i1", "from": ["origin"], "to": None}]}
        nodes, edges = build_graph(detail)
        positions, _ = layout_graph(nodes, edges)
        self.assertNotIn(("intent:i1", "fact:goal"), edges)
        self.assertGreater(positions["fact:goal"][1], positions["intent:i1"][1])

    def test_cycle_terminates_and_reports_warning(self):
        positions, cycle = layout_graph({"a": {}, "b": {}}, [("a", "b"), ("b", "a")])
        self.assertTrue(cycle)
        self.assertEqual(set(positions), {"a", "b"})

    def test_records_keep_explicit_node_link_and_reject_path_traversal(self):
        folder = project_folder(self.root, "p1") / "workspace" / ".cairn" / "runs"
        run = folder / "explore-1"
        run.mkdir(parents=True)
        (run / "task.json").write_text(json.dumps({"phase": "explore_execute", "intent_id": "i2"}))
        records = read_runs(self.root, "p1")
        self.assertEqual(records[0]["intent_id"], "i2")
        with self.assertRaises(ValueError):
            project_folder(self.root, "../escape")


if __name__ == "__main__":
    unittest.main()
