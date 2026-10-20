"""Regression tests for evidence-grounded speaker correction and draft retry caching.

No external model/network calls are made by these tests.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import context_graph as cg

SID = "01234567-89ab-4def-8234-0123456789ab"


def completed(cmd, code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(cmd, code, stdout, stderr)


class AttributionRecoveryTests(unittest.TestCase):
    def test_repair_only_upstream_approved_speaker_mismatches(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "draft.json"
            original = {"nodes": [
                {"key": "c1-a", "kind": "item", "classification": "assistant_statement"},
                {"key": "c1-b", "kind": "item", "classification": "decision"},
                {"key": "c1-c", "kind": "item", "classification": "user_statement"},
            ]}
            file.write_text(json.dumps(original), encoding="utf-8")
            diagnostic = {"errors": [
                {"code": "attribution-mismatch", "node": "c1-a", "repaired": True,
                 "message": '"c1-a" is classified assistant_statement, but its verified evidence comes from the user; reclassified as user_statement.'},
                {"code": "relation-unknown-node", "node": "c1-b",
                 "message": "Invalid relation"},
            ]}
            self.assertEqual(cg.repair_attribution_errors([file], diagnostic), 1)
            fixed = json.loads(file.read_text(encoding="utf-8"))
            self.assertEqual([n["classification"] for n in fixed["nodes"]],
                             ["user_statement", "decision", "user_statement"])

    def test_check_retries_after_verified_attribution_repair(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            transcript = temp / "transcript.json"
            transcript.write_text("{}", encoding="utf-8")
            draft = temp / "draft.json"
            draft.write_text(json.dumps({"nodes": [
                {"key": "a", "kind": "item", "classification": "assistant_statement"}
            ]}), encoding="utf-8")
            attempts = []

            def fake_run(cmd, **kwargs):
                attempts.append(cmd)
                self.assertEqual(cmd[-1], "--json")
                self.assertEqual(kwargs.get("encoding"), "utf-8")
                current = json.loads(draft.read_text(encoding="utf-8"))
                if current["nodes"][0]["classification"] == "assistant_statement":
                    return completed(cmd, 2, json.dumps({"errors": [{
                        "code": "attribution-mismatch", "node": "a",
                        "message": '"a" is classified assistant_statement, but its verified evidence comes from the user; reclassified as user_statement.'
                    }], "warnings": []}))
                return completed(cmd, 0, json.dumps({"ok": True, "errors": [], "warnings": []}))

            with patch.object(cg.subprocess, "run", side_effect=fake_run):
                self.assertEqual(cg.check_with_attribution_repair(temp / "script.mjs", transcript, [draft]), 1)
            self.assertEqual(len(attempts), 2)
            self.assertEqual(json.loads(draft.read_text(encoding="utf-8"))["nodes"][0]["classification"], "user_statement")

    def test_unrelated_validation_errors_still_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            draft = temp / "draft.json"
            draft.write_text(json.dumps({"nodes": [{"key": "a", "kind": "item", "classification": "decision"}]}), encoding="utf-8")
            def fake_run(cmd, **kwargs):
                return completed(cmd, 2, json.dumps({"errors": [{"code": "relation-unknown-node",
                            "message": "not found"}], "warnings": []}))
            with patch.object(cg.subprocess, "run", side_effect=fake_run):
                with self.assertRaisesRegex(RuntimeError, "relation-unknown-node"):
                    cg.check_with_attribution_repair(temp / "script.mjs", temp / "transcript.json", [draft])

    def test_cache_drafts_even_when_upstream_check_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            con = cg.connect(root / "knowledge.db")
            try:
                with con:
                    con.execute("INSERT INTO sessions (id,cwd,project,first_seen,last_seen) VALUES (?,?,'Demo','x','x')",
                                (SID, "C:/Demo"))
                    for i in range(90):
                        con.execute("""INSERT INTO messages (id,session_id,source_path,offset_bytes,role,source_kind,content)
                                    VALUES (?,?,?,?,?,?,?)""",
                                    (f"row-{i}", SID, "p", i * 3000, "user", "response_item",
                                     f"Need a project decision {i} " + "a" * 2100))
                cm = root / "conversation-map"
                skill = cm / "plugins" / "conversation-map" / "skills" / "conversation-map"
                (skill / "scripts").mkdir(parents=True)
                (skill / "references").mkdir(parents=True)
                (skill / "scripts" / "conversation-map.mjs").write_text("// stub", encoding="utf-8")
                (skill / "references" / "analysis.schema.json").write_text("{}", encoding="utf-8")
                model_calls = [0]
                check_should_fail = [True]
                def fake_run(cmd, **kwargs):
                    if cmd[0] == "codex":
                        model_calls[0] += 1
                        part = json.loads(kwargs["input"].split("TRANSCRIPT PART:\n", 1)[1])
                        message = part["messages"][0]
                        draft = {"schemaVersion": "1", "title": "Demo", "coverage": {"status": "complete"},
                                 "nodes": [
                                     {"key": "project", "parent": None, "kind": "topic", "title": "Demo", "summary": ""},
                                     {"key": "choice", "parent": "project", "kind": "item",
                                      "classification": "assistant_statement", "title": "Choice",
                                      "summary": "Chosen", "evidence": [{"message": message["id"], "quote": message["content"][:30]}]},
                                 ], "relations": [], "notes": []}
                        Path(cmd[cmd.index("-o") + 1]).write_text(json.dumps(draft), encoding="utf-8")
                        return completed(cmd)
                    if cmd[0] == "node" and cmd[2] == "check":
                        if check_should_fail[0]:
                            return completed(cmd, 2, json.dumps({"errors": [{"code": "relation-unknown-node",
                                                    "message": "test failure"}]}))
                        issues = []
                        for filepath in cmd[4:]:
                            if not filepath.endswith(".json"):
                                continue
                            draft = json.loads(Path(filepath).read_text(encoding="utf-8"))
                            for node in draft["nodes"]:
                                if node.get("classification") == "assistant_statement":
                                    issues.append({"code": "attribution-mismatch", "node": node["key"],
                                                   "message": f'"{node["key"]}" is classified assistant_statement, but its verified evidence comes from the user; reclassified as user_statement.'})
                        return completed(cmd, 2 if issues else 0,
                                         json.dumps({"ok": not issues, "errors": issues, "warnings": []}))
                    if cmd[0] == "node" and cmd[2] == "build":
                        dest = Path(cmd[cmd.index("--out-dir") + 1])
                        dest.mkdir(parents=True, exist_ok=True)
                        (dest / "map.json").write_text(json.dumps({"nodes": [
                            {"id": "root", "kind": "root"},
                            {"id": "one", "kind": "item", "title": "Choice",
                             "status": "active", "classification": "user_statement"}], "relations": []}), encoding="utf-8")
                        return completed(cmd)
                    raise AssertionError(f"unexpected command: {cmd}")

                with patch.object(cg.shutil, "which", return_value="fake"), patch.object(cg.subprocess, "run", side_effect=fake_run):
                    with self.assertRaisesRegex(RuntimeError, "relation-unknown-node"):
                        cg.auto_analyze(con, SID, cm, root)
                    previous_count = model_calls[0]
                    self.assertGreaterEqual(previous_count, 3)
                    self.assertEqual(con.execute("SELECT COUNT(*) FROM session_maps").fetchone()[0], 0)
                    check_should_fail[0] = False
                    result = cg.auto_analyze(con, SID, cm, root)
                    self.assertIn("analyzed & imported", result)
                    self.assertEqual(model_calls[0], previous_count, "retry should not repeat model calls")
                    self.assertGreaterEqual(len(list((root / "analysis-cache").rglob("*.json"))), 3)
                    self.assertEqual(con.execute("SELECT COUNT(*) FROM session_maps").fetchone()[0], 1)
            finally:
                con.close()


if __name__ == "__main__":
    unittest.main()
