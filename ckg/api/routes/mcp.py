"""MCP HTTP transport.

A minimal JSON-RPC endpoint that maps Model Context Protocol method calls
onto the underlying graph + search services. This lets Cursor / VS Code /
Claude Code reach the central server over HTTP.

Spec: https://modelcontextprotocol.io/specification

We implement a small surface (initialize, tools/list, tools/call) so the
common AI clients can discover and invoke our tools.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ckg.api.routes.graph import (
    blast_radius,
    callees_of,
    callers_of,
    downstream_dependencies,
    file_overview,
    graph_stats,
    imports_of,
)
from ckg.api.routes.search import keyword_search, semantic_search
from ckg.auth import Principal, require_repo_read
from ckg.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/mcp", tags=["mcp"])


class JsonRpc(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str | None = None
    method: str
    params: dict[str, Any] | None = None


TOOL_DEFS = [
    {
        "name": "ckg.graph_stats",
        "description": "Overall counts: nodes, edges, repos, files.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "ckg.callers_of",
        "description": "Functions that (transitively) call the given function.",
        "inputSchema": {
            "type": "object",
            "required": ["repo_id", "qualified_name"],
            "properties": {
                "repo_id": {"type": "string"},
                "qualified_name": {"type": "string"},
                "depth": {"type": "integer", "minimum": 1, "maximum": 4, "default": 1},
                "limit": {"type": "integer", "default": 100},
            },
        },
    },
    {
        "name": "ckg.callees_of",
        "description": "Functions (transitively) called by the given function.",
        "inputSchema": {
            "type": "object",
            "required": ["repo_id", "qualified_name"],
            "properties": {
                "repo_id": {"type": "string"},
                "qualified_name": {"type": "string"},
                "depth": {"type": "integer", "minimum": 1, "maximum": 4, "default": 1},
                "limit": {"type": "integer", "default": 100},
            },
        },
    },
    {
        "name": "ckg.imports_of",
        "description": "Modules/files imported by a file.",
        "inputSchema": {
            "type": "object",
            "required": ["repo_id", "path"],
            "properties": {
                "repo_id": {"type": "string"},
                "path": {"type": "string"},
                "limit": {"type": "integer", "default": 200},
            },
        },
    },
    {
        "name": "ckg.blast_radius",
        "description": "Files that would be affected if this file changes — upstream callers of its functions, transitively.",
        "inputSchema": {
            "type": "object",
            "required": ["repo_id", "path"],
            "properties": {
                "repo_id": {"type": "string"},
                "path": {"type": "string"},
                "depth": {"type": "integer", "minimum": 1, "maximum": 4, "default": 2},
                "limit": {"type": "integer", "default": 500},
            },
        },
    },
    {
        "name": "ckg.downstream_dependencies",
        "description": "Files this file depends on — outgoing callees from its functions, transitively.",
        "inputSchema": {
            "type": "object",
            "required": ["repo_id", "path"],
            "properties": {
                "repo_id": {"type": "string"},
                "path": {"type": "string"},
                "depth": {"type": "integer", "minimum": 1, "maximum": 4, "default": 2},
                "limit": {"type": "integer", "default": 500},
            },
        },
    },
    {
        "name": "ckg.file_overview",
        "description": "Classes + functions defined in a file.",
        "inputSchema": {
            "type": "object",
            "required": ["repo_id", "path"],
            "properties": {
                "repo_id": {"type": "string"},
                "path": {"type": "string"},
            },
        },
    },
    {
        "name": "ckg.search_keyword",
        "description": "Lucene full-text search over function/class names + docs.",
        "inputSchema": {
            "type": "object",
            "required": ["q"],
            "properties": {
                "q": {"type": "string"},
                "repo_id": {"type": "string"},
                "limit": {"type": "integer", "default": 25},
            },
        },
    },
    {
        "name": "ckg.search_semantic",
        "description": "Vector search over function embeddings.",
        "inputSchema": {
            "type": "object",
            "required": ["q"],
            "properties": {
                "q": {"type": "string"},
                "repo_id": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
        },
    },
]


def _ok(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _dispatch_tool(name: str, args: dict[str, Any], principal: Principal) -> dict:
    """Route an MCP tool call to the matching FastAPI handler."""
    if name == "ckg.graph_stats":
        return graph_stats(_=principal)  # type: ignore[arg-type]
    if name == "ckg.callers_of":
        return callers_of(
            repo_id=args["repo_id"],
            qualified_name=args["qualified_name"],
            depth=int(args.get("depth", 1)),
            limit=int(args.get("limit", 100)),
            _=principal,  # type: ignore[arg-type]
        )
    if name == "ckg.callees_of":
        return callees_of(
            repo_id=args["repo_id"],
            qualified_name=args["qualified_name"],
            depth=int(args.get("depth", 1)),
            limit=int(args.get("limit", 100)),
            _=principal,  # type: ignore[arg-type]
        )
    if name == "ckg.imports_of":
        return imports_of(
            repo_id=args["repo_id"],
            path=args["path"],
            limit=int(args.get("limit", 200)),
            _=principal,  # type: ignore[arg-type]
        )
    if name == "ckg.blast_radius":
        return blast_radius(
            repo_id=args["repo_id"],
            path=args["path"],
            depth=int(args.get("depth", 2)),
            limit=int(args.get("limit", 500)),
            _=principal,  # type: ignore[arg-type]
        )
    if name == "ckg.downstream_dependencies":
        return downstream_dependencies(
            repo_id=args["repo_id"],
            path=args["path"],
            depth=int(args.get("depth", 2)),
            limit=int(args.get("limit", 500)),
            _=principal,  # type: ignore[arg-type]
        )
    if name == "ckg.file_overview":
        return file_overview(
            repo_id=args["repo_id"],
            path=args["path"],
            _=principal,  # type: ignore[arg-type]
        )
    if name == "ckg.search_keyword":
        return keyword_search(
            q=args["q"],
            repo_id=args.get("repo_id"),
            limit=int(args.get("limit", 25)),
            _=principal,  # type: ignore[arg-type]
        )
    if name == "ckg.search_semantic":
        return semantic_search(
            q=args["q"],
            repo_id=args.get("repo_id"),
            limit=int(args.get("limit", 10)),
            _=principal,  # type: ignore[arg-type]
        )
    raise ValueError(f"unknown tool: {name}")


@router.post("")
async def jsonrpc(request: Request, principal: Principal = Depends(require_repo_read)) -> dict:
    """JSON-RPC 2.0 endpoint. Methods: initialize, tools/list, tools/call."""
    body = await request.json()
    req = JsonRpc.model_validate(body)
    if req.method == "initialize":
        return _ok(req.id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ckg", "version": "0.1.0"},
        })
    if req.method == "tools/list":
        return _ok(req.id, {"tools": TOOL_DEFS})
    if req.method == "tools/call":
        params = req.params or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if not name:
            return _err(req.id, -32602, "missing 'name'")
        try:
            result = _dispatch_tool(name, args, principal)
            return _ok(req.id, {"content": [{"type": "json", "json": result}]})
        except KeyError as e:
            # Surface only the missing argument name (part of the public
            # tool input-schema contract). Avoid str(e) which CodeQL flags
            # as potential information disclosure.
            missing = e.args[0] if e.args else "<unknown>"
            return _err(req.id, -32602, f"missing required argument: {missing!r}")
        except Exception:
            # Do NOT leak the internal exception message back to the caller;
            # an MCP client doesn't need it and surfacing internals can
            # disclose implementation details. Log server-side instead so
            # operators can still debug.
            log.exception("mcp_tool_failed", tool=name)
            return _err(req.id, -32603, "internal error executing tool")
    return _err(req.id, -32601, "method not found")
