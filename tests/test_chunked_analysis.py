"""Regression checks for long Codex conversations, without model/API calls."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import context_graph as cg

SID = "01234567-89ab-4def-8234-0123456789ab"


class ChunkTests(unittest.TestCase):
    def test_long_transcript_preserves_all_messages(self):
        original = {"title": "Long session", "messages": [
            {"id": f"m{i}", "role": "user", "content": f"Message {i} " + "x" * 2300}
            for i in range(82)
        ]}
        chunks = cg.split_transcript(original, 60000)
        self.assertGreaterEqual(len(chunks), 4)
        self.assertTrue(all(len(cg.serialize_transcript(chunk)) <= 60000 for chunk in chunks))
        self.assertEqual([m for chunk in chunks for m in chunk["messages"]], original["messages"])

    def test_oversized_single_message_is_lossless(self):
        text = "START " + ("data line with spaces\n" * 15000) + " END"
        original = {"title": "Long message", "messages": [
            {"id": "m1", "role": "user", "content": text},
            {"id": "m2", "role": "assistant", "content": "Finished"}
        ]}
        chunks = cg.split_transcript(original, 60000)
        messages = [m for chunk in chunks for m in chunk["messages"]]
        self.assertTrue(all(len(cg.serialize_transcript(c)) <= 60000 for c in chunks))
        self.assertEqual("".join(m["content"] for m in messages if m["id"] == "m1"), text)
        self.assertEqual(next(m for m in messages if m["id"] == "m2")["content"], "Finished")

    def test_cross_chunk_keys_are_unique_and_links_remapped(self):
        draft = {"nodes": [
            {"key": "topic", "kind": "topic", "parent": None},
            {"key": "one", "kind": "item", "parent": "topic", "supersededBy": "two"},
            {"key": "two", "kind": "item", "parent": "topic"},
        ], "relations": [{"from": "two", "to": "one", "type": "supersedes"}]}
        first = cg.namespace_chunk_draft(draft, 1)
        second = cg.namespace_chunk_draft(draft, 2)
        self.assertTrue(set(n["key"] for n in first["nodes"]).isdisjoint(
            n["key"] for n in second["nodes"]))
        self.assertEqual(first["nodes"][1]["parent"], first["nodes"][0]["key"])
        self.assertEqual(first["nodes"][1]["supersededBy"], first["nodes"][2]["key"])
        self.assertEqual(first["relations"][0]["from"], first["nodes"][2]["key"])
        self.assertEqual(draft["nodes"][0]["key"], "topic")

    def test_end_to_end_chunk_orchestration_and_unchanged_skip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            con = cg.connect(root / "data.db")
            try:
                with con:
                    con.execute("INSERT INTO sessions (id,cwd,project,first_seen,last_seen) VALUES (?,?,'Demo','x','x')", (SID, "Demo"))
                    for i in range(80):
                        con.execute("""INSERT INTO messages(id,session_id,source_path,offset_bytes,role,source_kind,content)
                            VALUES (?,?,?,?,?,?,?)""",
                            (f"row-{i}", SID, "p", i * 3000, "user", "response_item",
                             f"User request {i} " + "z" * 2320))
                skill = root / "conversation-map" / "plugins" / "conversation-map" / "skills" / "conversation-map"
                (skill / "scripts").mkdir(parents=True)
                (skill / "references").mkdir()
                (skill / "scripts" / "conversation-map.mjs").write_text("stub")
                (skill / "references" / "analysis.schema.json").write_text("{}")
                chunks = []
                check_count = []
                def fake_run(cmd, **kwargs):
                    if cmd[0] == "codex":
                        data = json.loads(kwargs["input"].split("TRANSCRIPT PART:\n", 1)[1])
                        chunks.append(data)
                        draft = {"schemaVersion": "1", "title": "Demo", "coverage": {"status": "complete"},
                                 "nodes": [
                                    {"key": "project", "parent": None, "kind": "topic", "title": "Demo", "summary": ""},
                                    {"key": "decision", "parent": "project", "kind": "item", "title": "Use SQLite",
                                     "summary": "Use SQLite", "classification": "decision",
                                     "evidence": [{"message": data["messages"][0]["id"],
                                                   "quote": data["messages"][0]["content"][:20]}]}
                                 ], "relations": [], "notes": []}
                        Path(cmd[cmd.index("-o") + 1]).write_text(json.dumps(draft))
                    elif cmd[0] == "node":
                        if cmd[2] == "check":
                            check_count.extend(p for p in cmd[4:] if p.endswith(".json"))
                            ids = [n["key"] for p in check_count
                                   for n in json.loads(Path(p).read_text())["nodes"]]
                            self.assertEqual(len(ids), len(set(ids)))
                        if cmd[2] == "build":
                            target = Path(cmd[cmd.index("--out-dir") + 1])
                            target.mkdir()
                            (target / "map.json").write_text(json.dumps({"nodes": [
                                {"id": "root", "kind": "root"},
                                {"id": "decision", "kind": "item", "title": "Use SQLite",
                                 "status": "active", "classification": "decision"}], "relations": []}))
                    else:
                        raise AssertionError(str(cmd))
                    return type("Process", (), {"returncode": 0, "stderr": "", "stdout": ""})()

                with patch.object(cg.shutil, "which", return_value="fake"), patch.object(cg.subprocess, "run", side_effect=fake_run):
                    result = cg.auto_analyze(con, SID, skill.parents[3], root)
                    self.assertIn("chunk(s)", result)
                    self.assertGreaterEqual(len(chunks), 4)
                    self.assertEqual(len(chunks), len(check_count))
                    self.assertEqual([m for c in chunks for m in c["messages"]], cg.transcript(con, SID)["messages"])
                    self.assertEqual(cg.auto_analyze(con, SID, skill.parents[3], root), "skipped: unchanged")
                self.assertEqual(con.execute("SELECT count(*) FROM session_maps").fetchone()[0], 1)
            finally:
                con.close()

    def test_failed_chunk_does_not_store_incomplete_map(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            con = cg.connect(root / "data.db")
            try:
                with con:
                    con.execute("INSERT INTO sessions (id,cwd,project,first_seen,last_seen) VALUES (?,?,'Demo','x','x')", (SID, "Demo"))
                    for i in range(80):
                        con.execute("""INSERT INTO messages(id,session_id,source_path,offset_bytes,role,source_kind,content)
                            VALUES (?,?,?,?,?,?,?)""",
                            (f"row-{i}", SID, "p", i * 3000, "user", "response_item", "z" * 2320))
                skill = root / "cm" / "plugins" / "conversation-map" / "skills" / "conversation-map"
                (skill / "scripts").mkdir(parents=True)
                (skill / "references").mkdir()
                (skill / "scripts" / "conversation-map.mjs").write_text("stub")
                (skill / "references" / "analysis.schema.json").write_text("{}")
                calls = [0]
                def fake_run(cmd, **kwargs):
                    if cmd[0] == "codex":
                        calls[0] += 1
                        if calls[0] == 2:
                            return type("Process", (), {"returncode": 1, "stderr": "intentional", "stdout": ""})()
                        Path(cmd[cmd.index("-o") + 1]).write_text("{}")
                    return type("Process", (), {"returncode": 0, "stderr": "", "stdout": ""})()
                with patch.object(cg.shutil, "which", return_value="fake"), patch.object(cg.subprocess, "run", side_effect=fake_run):
                    with self.assertRaisesRegex(RuntimeError, "chunk 2/"):
                        cg.auto_analyze(con, SID, skill.parents[3], root)
                self.assertEqual(con.execute("SELECT count(*) FROM session_maps").fetchone()[0], 0)
            finally:
                con.close()


if __name__ == "__main__":
    unittest.main()
