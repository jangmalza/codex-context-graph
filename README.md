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

## Windows character encoding (CP949)

If a long conversation contains Unicode characters that Windows' legacy CP949 code page cannot encode, older versions may fail with `'cp949' codec can't encode character` during `codex exec`. This version explicitly uses UTF-8 for all Codex and Node.js subprocess pipes (stdin/stdout/stderr). Upgrade to the latest `feat/context-graph-mvp` branch before retrying:

```powershell
git fetch origin
git switch feat/context-graph-mvp
git pull --ff-only origin feat/context-graph-mvp
python -m unittest discover -s tests -v
```

For an **older checkout** that has not yet been updated, `python -X utf8 .\\context_graph.py analyze ...` is a temporary workaround. Changing the terminal code page with `chcp` alone is not a reliable fix for Python subprocess pipes.

## Long-session analysis (automatic chunking)

Sessions longer than 60,000 serialized characters are automatically split into sequential chunks before model analysis. You do **not** have to edit the session file, truncate the conversation, or raise the context limit.

- Each part is sent to Codex separately, so long sessions incur multiple sequential model calls and can take longer.
- Chunks preserve original message IDs. If one individual message exceeds the limit, it is divided into text fragments without losing characters.
- All generated drafts are checked and built against the **full, original** transcript, retaining quote traceability.
- To prevent accidental ID collisions, each chunk's analysis keys are namespaced before merging. Same-title topics can still be deduplicated by Conversation Map.
- If any chunk or evidence validation fails, this run does **not** replace an existing stored graph. The next run retries the whole session.
- Each chunk is interpreted independently; cross-chunk supersessions and semantic relationships may be missed. This is not yet a fully reconciled long-term memory graph.

Example for a long session:

```powershell
python .\context_graph.py analyze `
  --session "YOUR-SESSION-ID" `
  --cm-root "$HOME\src\conversation-map" `
  --allow-model
```

Progress output prints `chunk 1/N`, `chunk 2/N`, and so on. A 184,408-character transcript will generally require at least four chunks depending on message boundaries. The run still requires user opt-in to send the conversation to the configured Codex model.

## Validation recovery and retry cache

The Conversation Map validator checks actual quoted evidence, including the speaker. If the Codex model incorrectly classifies a user quote as `assistant_statement`, the tool now reads the validator's **structured diagnostics**, corrects only reported `attribution-mismatch` classifications (including mixed-speaker `unknown`), and re-runs the full validator. Other errors still stop the import. It does not use `--best-effort` to ignore validation failures.

Each successfully generated **model draft** is also cached locally before validation. On failure or interruption after generating a chunk, unchanged chunks can be reused without additional Codex model calls. Every cached draft is still checked against the full source transcript before being saved as a final map.

- Default cache location: `$HOME\.codex-context-graph\analysis-cache\<hashed-session-id>\`
- With `--db .\local-data\test.db`, the cache is under `.\local-data\analysis-cache\`.
- Cached files contain **raw conversation quotes** and must be treated as sensitive data; they are ignored by Git. Do not share or commit them.
- `--force` bypasses both successful-run and draft cache skipping, requesting fresh model analysis.
- Cache keys account for the transcript chunk and current analysis schema; changed chunks are re-analyzed.
- A previously failed run on an **older version** had no persistent draft cache, so its first retry after upgrading must call Codex for all chunks once more.

```powershell
git fetch origin
git switch feat/context-graph-mvp
git pull --ff-only origin feat/context-graph-mvp
python -m unittest discover -s tests -v

python -X utf8 .\context_graph.py analyze `
  --session "YOUR-SESSION-ID" `
  --cm-root "$HOME\src\conversation-map" `
  --allow-model
```

Note: Repeated validation failure may indicate other issues (unsupported quote, invalid relationship, changed source) that should **not** be auto-suppressed. In that case, report the newly displayed error codes.

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
- Every model request is limited to roughly 60,000 serialized characters; longer sessions are split automatically. Cross-chunk conflict/decision reconciliation is not yet implemented.
- No semantic entity resolution, inference of cross-session contradictions, or branch-specific canonical decisions.
- No MCP server or automatic Windows background service yet.
- Latest import per session replaces the previous map. Node titles must match exactly after normalization to merge.
- Imported maps receive basic structural validation; upstream Conversation Map's `check` and `build` must be used to establish evidence validation.
- Session files and resulting maps can contain sensitive conversation material; no secrets redaction is implemented.

License: MIT. Conversation Map is a separate project and is not redistributed here.
