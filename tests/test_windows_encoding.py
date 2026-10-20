"""Regression tests for Windows cp949 subprocess encoding (no Codex model calls)."""
from pathlib import Path
from unittest.mock import patch
import json
import locale
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import context_graph as cg

SID = '01234567-89ab-4def-8234-0123456789ab'


class WindowsEncodingTests(unittest.TestCase):
    def test_cp949_rejects_character_but_utf8_pipe_handles_it(self):
        # This text is valid UTF-8, but CP949 cannot encode U+0080.
        sample = 'Codex conversation example \u0080 漢字 😀'
        with self.assertRaises(UnicodeEncodeError):
            sample.encode('cp949')
        code = 'import sys;sys.stdout.buffer.write(sys.stdin.buffer.read())'
        with patch.object(locale, 'getencoding', return_value='cp949'):
            got = subprocess.run(
                [sys.executable, '-c', code], input=sample, text=True,
                encoding='utf-8', errors='replace', capture_output=True, check=True)
        self.assertEqual(got.stdout, sample)

    def test_pipeline_passes_utf8_to_codex_and_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            con = cg.connect(home / 'knowledge.db')
            try:
                with con:
                    con.execute('INSERT INTO sessions(id,cwd,project,first_seen,last_seen) VALUES(?, ?, ?, ?, ?)',
                                (SID, 'C:/project', 'project', 'x', 'x'))
                    con.execute('INSERT INTO messages(id,session_id,source_path,offset_bytes,role,source_kind,content) VALUES(?,?,?,?,?,?,?)',
                                ('msg1', SID, 'source.jsonl', 100, 'user', 'response_item', 'Check Unicode \u0080 確認'))

                cm = home / 'conversation-map'
                skill = cm / 'plugins/conversation-map/skills/conversation-map'
                (skill / 'scripts').mkdir(parents=True)
                (skill / 'references').mkdir()
                (skill / 'scripts/conversation-map.mjs').write_text('// mock')
                (skill / 'references/analysis.schema.json').write_text('{}')
                actions = []

                def fake_run(cmd, **kw):
                    self.assertEqual(kw.get('encoding'), 'utf-8', f'No explicit UTF-8 for: {cmd}')
                    self.assertEqual(kw.get('errors'), 'replace')
                    actions.append(cmd[0:3])
                    if cmd[0] == 'codex':
                        self.assertIn('\u0080', kw['input'])
                        chunk = json.loads(kw['input'].split('TRANSCRIPT PART:\n', 1)[1])
                        m = chunk['messages'][0]
                        draft = {'schemaVersion': '1', 'title': 'Project',
                                 'coverage': {'status': 'complete'}, 'nodes': [
                                    {'key': 'project', 'parent': None, 'kind': 'topic', 'title': 'Project', 'summary': ''},
                                    {'key': 'unicode-decision', 'parent': 'project', 'kind': 'item',
                                     'classification': 'decision', 'title': 'Handle Unicode', 'summary': 'UTF-8',
                                     'evidence': [{'message': m['id'], 'quote': m['content']}]}
                                 ], 'relations': [], 'notes': []}
                        Path(cmd[cmd.index('-o') + 1]).write_text(json.dumps(draft), encoding='utf-8')
                    elif cmd[0] == 'node' and cmd[2] == 'build':
                        folder = Path(cmd[cmd.index('--out-dir') + 1])
                        folder.mkdir()
                        (folder / 'map.json').write_text(json.dumps({'nodes': [
                            {'id': 'root', 'kind': 'root'},
                            {'id': 'unicode-decision', 'kind': 'item', 'title': 'Handle Unicode',
                             'summary': 'UTF-8', 'classification': 'decision', 'status': 'active'}
                        ], 'relations': []}), encoding='utf-8')
                    return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')

                with patch.object(cg.shutil, 'which', return_value='binary'), \
                     patch.object(cg.subprocess, 'run', side_effect=fake_run):
                    result = cg.auto_analyze(con, SID, cm, home)
                self.assertIn('analyzed & imported', result)
                self.assertEqual([x[0] for x in actions], ['codex', 'node', 'node'])
                self.assertEqual(con.execute('select count(*) from session_maps').fetchone()[0], 1)
            finally:
                con.close()


if __name__ == '__main__':
    unittest.main()
