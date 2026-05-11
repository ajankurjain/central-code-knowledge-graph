# Cursor Integration

Cursor speaks the Model Context Protocol (MCP). Point it at the central
knowledge graph server and it'll get tools for callers/callees, impact radius,
keyword search, and semantic search.

## 1. Create an API token

From a machine with the CLI:

```bash
export CKG_TOKEN=$CKG_BOOTSTRAP_TOKEN   # the .env bootstrap token, admin-scoped
ckg token create cursor-laptop --scope repo:read
# → copy the printed `token` value (shown once)
```

## 2. Add the server to Cursor

Open Cursor → Settings → MCP → **Add new MCP server**. Paste this JSON (edit
`url` and `token`):

```json
{
  "mcpServers": {
    "ckg": {
      "transport": "http",
      "url": "http://localhost:8080/v1/mcp",
      "headers": {
        "Authorization": "Bearer ckg_REPLACE_WITH_REAL_TOKEN"
      }
    }
  }
}
```

If your Cursor build uses the file format directly, drop the same block into
`~/.cursor/mcp.json` (macOS / Linux) or `%APPDATA%\Cursor\mcp.json` (Windows)
under the `mcpServers` key.

Restart Cursor. In a chat, ask:

> "Use ckg.graph_stats to show the graph summary."

You should see Cursor invoke the tool and return live numbers from your server.

## Tools you get

| Tool | What it does |
|------|--------------|
| `ckg.graph_stats` | Total nodes / edges / repos / files. |
| `ckg.callers_of` | Functions that (transitively) call a given function. |
| `ckg.callees_of` | Functions called by a given function. |
| `ckg.imports_of` | Modules / files imported by a file. |
| `ckg.impact_radius` | Files transitively affected by a change. |
| `ckg.file_overview` | Classes + functions defined in a file. |
| `ckg.search_keyword` | Lucene FTS on names + docs. |
| `ckg.search_semantic` | Vector search over function embeddings. |

## Scoping a single repo

All tools take an optional `repo_id`. Tell Cursor in its rules:

```
When using ckg.* tools, default repo_id to "submission-enterprise".
```
