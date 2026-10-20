# Codex Context Graph (MVP)

Local-first collector and cross-session knowledge graph for Codex CLI/Desktop session records. Python 3.10+; Windows 11 supported.

> Experimental MVP. The automatic Codex analyzer has **not** been verified end-to-end on an authenticated installation. This is a reconstruction of conversation knowledge, not access to the model's actual internal context.

## Capabilities

- Read-only incremental collection from `CODEX_HOME/sessions/**/rollout-*.jsonl` and `archived_sessions`
- SQLite checkpointing, session deduplication, user/assistant text-only normalization
- Export a session transcript for [Conversation Map](https://github.com/tonitalej/conversation-map)
- Import analyzed `map.json` and merge evidence across sessions by project + classification + exactly normalized title
- Export searchable offline HTML and graph JSON
- Opt-in automated analysis using `codex exec` and a separate Conversation Map checkout
- Poll for newly appended session messages

## Quick start (Windows PowerShell)

```powershell
git clone https://github.com/jangmalza/codex-context-graph.git
cd codex-context-graph
python --version
python .\context_graph.py scan
python .\context_graph.py status
python .\context_graph.py graph --html .\output\graph.html --json .\output\graph.json
Start-Process .\output\graph.html
```

By default, Codex sessions are read from `$env:CODEX_HOME` or `$HOME\.codex`. The SQLite database is written outside the repository to `$HOME\.codex-context-graph\knowledge.db`.

The graph remains empty until you import semantic analyses or run the opt-in analyzer.

## Automatic semantic analysis (opt-in)

Requires Node.js 18+, installed/authenticated Codex CLI, and a local checkout of Conversation Map:

```powershell
git clone https://github.com/tonitalej/conversation-map.git "$HOME\src\conversation-map"
python .\context_graph.py scan
python .\context_graph.py analyze --cm-root "$HOME\src\conversation-map" --allow-model
python .\context_graph.py graph --html .\output\graph.html
```

**Privacy:** `--allow-model` sends the exported conversation text to the configured Codex model. The local collector alone does not make model calls. Avoid placing passwords, production credentials, or other secrets in exports. Never commit local databases, transcripts, or generated maps.

Manual import of an upstream-validated map:

```powershell
python .\context_graph.py status
python .\context_graph.py export-transcript --session <SESSION_ID> --output .\local-data\transcript.json
# Analyze with Conversation Map and obtain its validated map.json
python .\context_graph.py import-map --session <SESSION_ID> --file .\local-data\map.json
python .\context_graph.py graph --html .\output\graph.html
```

## Continuous collection

```powershell
python .\context_graph.py watch --interval 10
# Optional continuous model analysis:
python .\context_graph.py watch --interval 30 --analyze --allow-model --cm-root "$HOME\src\conversation-map"
```

The watcher runs only while the command remains active; no Windows service is installed.

## Multiple Git worktrees

Supply `--project-map path-to-projects.json` **before** the subcommand. Example mapping:

```json
{
  "C:\\projects\\OmniRoute": "OmniRoute",
  "C:\\worktrees\\OmniRoute": "OmniRoute"
}
```

```powershell
python .\context_graph.py --project-map .\projects.json scan
```

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Architecture

```text
Codex rollout JSONL -> read-only scanner -> SQLite
                                         -> session transcript
                                         -> Codex analyzer (explicit opt-in)
                                         -> Conversation Map validation/build
                                         -> map.json imports
                                         -> conservative cross-session merge
                                         -> offline HTML / JSON graph
```

## Limitations

- Experimental local JSONL parsing; Codex may change its event schema.
- Analysis is limited to 60,000 characters per session for now; longer sessions must be split manually.
- No semantic entity resolution, inference of cross-session contradictions, or branch-specific canonical decisions.
- No MCP server or automatic Windows background service yet.
- Latest import per session replaces the previous map. Node titles must match exactly after normalization to merge.
- Imported maps receive basic structural validation; upstream Conversation Map's `check` and `build` must be used to establish evidence validation.
- Session files and resulting maps can contain sensitive conversation material; no secrets redaction is implemented.

License: MIT. Conversation Map is a separate project and is not redistributed here.
