import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import context_graph as cg

SID = "01234567-89ab-4def-8234-0123456789ab"

class ContextGraphTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "codex"
        self.path = self.home / "sessions" / "2026" / "10" / "20" / f"rollout-2026-10-20-{SID}.jsonl"
        self.path.parent.mkdir(parents=True)
        self.db = cg.connect(self.base / "knowledge.db")
        self.addCleanup(self.db.close)
        self.events = [
            {"type":"session_meta","payload":{"id":SID,"cwd":r"C:\\dev\\Project"}},
            {"type":"event_msg","payload":{"type":"user_message","message":"Use SQLite"}},
            {"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"Use SQLite"}]}},
            {"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Agreed."}]}},
            {"type":"response_item","payload":{"type":"message","role":"developer","content":[{"type":"input_text","text":"secret system instruction"}]}},
        ]
        self.path.write_text("".join(json.dumps(x)+"\n" for x in self.events),encoding="utf-8")

    def test_incremental_scan_and_deduplication(self):
        cg.scan(self.db,self.home)
        self.assertEqual([(m["role"],m["content"]) for m in cg.transcript(self.db,SID)["messages"]],[("user","Use SQLite"),("assistant","Agreed.")])
        self.assertEqual(cg.scan(self.db,self.home)[0]["added_messages"],0)
        self.assertEqual(self.db.execute("select count(*) from messages").fetchone()[0],3)

    def test_partial_line_waits_for_completion(self):
        cg.scan(self.db,self.home)
        with self.path.open("ab") as f:
            f.write(b'{"type":"event_msg","payload":{"type":"user_message","message":"Next"')
        self.assertEqual(cg.scan(self.db,self.home)[0]["added_messages"],0)
        with self.path.open("ab") as f:
            f.write(b'}}\n')
        self.assertEqual(cg.scan(self.db,self.home)[0]["added_messages"],1)

    def test_archive_copy_deduplication(self):
        cg.scan(self.db,self.home)
        archive = self.home / "archived_sessions" / self.path.name
        archive.parent.mkdir(parents=True)
        archive.write_bytes(self.path.read_bytes())
        cg.scan(self.db,self.home)
        self.assertEqual(len(cg.transcript(self.db,SID)["messages"]),2)

    def test_cross_session_graph(self):
        cg.scan(self.db,self.home)
        obj={"nodes":[{"id":"root","kind":"root"},{"id":"decision","kind":"item","title":"Use SQLite","classification":"decision","status":"active","summary":"Storage decision","evidence":[{"messageId":"m1","quote":"Use SQLite","verified":True}]}],"relations":[]}
        file=self.base/"map.json"
        file.write_text(json.dumps(obj),encoding="utf-8")
        cg.import_map(self.db,SID,file)
        graph=cg.build_graph(self.db)
        self.assertEqual(graph["sessionCount"],1)
        self.assertEqual(graph["nodes"][0]["provenance"][0]["session_id"],SID)

    def test_reject_duplicate_node_id(self):
        cg.scan(self.db,self.home)
        file=self.base/"bad.json"
        file.write_text(json.dumps({"nodes":[{"id":"same"},{"id":"same"}],"relations":[]}),encoding="utf-8")
        with self.assertRaises(ValueError):
            cg.import_map(self.db,SID,file)

    def test_html_script_breakout(self):
        graph={"projects":[],"nodes":[{"id":"1","title":"</script><img src=x onerror=alert(1)>","project":"x","classification":"decision","status":"active","summary":"","provenance":[]}],"edges":[],"sessionCount":1}
        dest=self.base/"map.html"
        cg.render_html(graph,dest)
        self.assertNotIn("</script><img",dest.read_text(encoding="utf-8"))

    def test_project_mapping(self):
        cg.scan(self.db,self.home,{r"C:\\dev":"group"})
        self.assertEqual(self.db.execute("select project from sessions").fetchone()[0],"group")

    def test_no_model_without_opt_in(self):
        rc=cg.main(["--db",str(self.base/"other.db"),"analyze","--cm-root",str(self.base)])
        self.assertEqual(rc,2)

if __name__=="__main__":
    unittest.main()
