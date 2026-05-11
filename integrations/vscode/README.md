# VS Code Integration

VS Code 1.95+ supports MCP servers natively (Settings → Extensions → MCP) and
the GitHub Copilot Chat / Cline / Roo Code extensions also speak MCP.

## 1. Create an API token

```bash
ckg token create vscode-laptop --scope repo:read
```

Copy the returned `token` value.

## 2. Configure VS Code

Open your user settings JSON (`Cmd+Shift+P` → "Preferences: Open User Settings (JSON)")
and add:

```json
{
  "mcp": {
    "servers": {
      "ckg": {
        "type": "http",
        "url": "http://localhost:8080/v1/mcp",
        "headers": {
          "Authorization": "Bearer ckg_REPLACE_WITH_REAL_TOKEN"
        }
      }
    }
  }
}
```

For Copilot Chat specifically, add the same block under
`"github.copilot.chat.mcpServers"`. For Cline / Roo Code, use the extension's
"Add MCP server" UI and paste the same URL + bearer token.

Reload the window. Open Copilot Chat (or your MCP-capable extension) and ask:

> "Using ckg.search_semantic, find functions that handle PV&T BDX ingestion in
> the submission-enterprise repo."

## Workspace-level config (recommended)

If you want per-project rather than user-wide, create `.vscode/mcp.json` in
your repo:

```json
{
  "servers": {
    "ckg": {
      "type": "http",
      "url": "http://localhost:8080/v1/mcp",
      "headers": { "Authorization": "Bearer ckg_REPLACE_WITH_REAL_TOKEN" }
    }
  }
}
```

Add `.vscode/mcp.json` to `.gitignore` so the token is not committed.

## Tools

Same tool set as Cursor — see [../cursor/README.md](../cursor/README.md).
