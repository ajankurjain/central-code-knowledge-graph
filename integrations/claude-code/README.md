# Claude Code Integration

Claude Code (CLI + desktop) speaks MCP. Add the central knowledge graph as an
HTTP MCP server.

## 1. Create an API token

```bash
ckg token create claude-code-laptop --scope repo:read
```

## 2. Register the server

Add this to your project's `.mcp.json` (committed) **or** `~/.claude.json`
(personal) under `mcpServers`:

```json
{
  "mcpServers": {
    "ckg": {
      "type": "http",
      "url": "http://localhost:8080/v1/mcp",
      "headers": {
        "Authorization": "Bearer ckg_REPLACE_WITH_REAL_TOKEN"
      }
    }
  }
}
```

Restart Claude Code. The tools will appear as `mcp__ckg__*` in tool listings.

## Verifying

```bash
claude mcp list             # should show ckg as connected
claude mcp call ckg ckg.graph_stats
```

## Project-level CLAUDE.md hint

If you want Claude to prefer graph tools over file scanning, add this to your
project `CLAUDE.md`:

```
## Knowledge graph

This project is indexed in the central ckg server. **Prefer ckg.* tools over
Grep/Glob/Read** for code exploration:

- `ckg.search_keyword` / `ckg.search_semantic` to locate functions
- `ckg.callers_of` / `ckg.callees_of` for relationships
- `ckg.blast_radius` for "what breaks if I change this file?" (upstream callers)
- `ckg.downstream_dependencies` for "what does this file depend on?" (outgoing callees)
- `ckg.file_overview` for a file's symbol table

Default `repo_id` is `<your-repo-slug>`.
```
