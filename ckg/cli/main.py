"""`ckg` — command-line client for the central knowledge graph server.

Authentication
--------------
The CLI reads the API token from one of (in order):
  1. --token flag
  2. CKG_TOKEN env var
  3. ~/.ckg/token  (plain text, single line)

Server URL: CKG_SERVER env var (default http://localhost:8080).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import httpx
import typer
from rich.console import Console
from rich.json import JSON as RichJSON
from rich.table import Table

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Central code knowledge graph CLI.")
repo_app = typer.Typer(no_args_is_help=True, help="Manage repositories.")
token_app = typer.Typer(no_args_is_help=True, help="Manage API tokens (admin scope required).")
graph_app = typer.Typer(no_args_is_help=True, help="Query the graph.")
search_app = typer.Typer(no_args_is_help=True, help="Search the graph.")

app.add_typer(repo_app, name="repo")
app.add_typer(token_app, name="token")
app.add_typer(graph_app, name="graph")
app.add_typer(search_app, name="search")

console = Console()


def _server() -> str:
    return os.environ.get("CKG_SERVER", "http://localhost:8080").rstrip("/")


def _token(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    env = os.environ.get("CKG_TOKEN")
    if env:
        return env
    cfg = Path.home() / ".ckg" / "token"
    if cfg.exists():
        return cfg.read_text().strip()
    console.print("[red]No API token. Provide --token, CKG_TOKEN, or ~/.ckg/token.[/red]")
    raise typer.Exit(2)


def _client(token: str | None = None) -> httpx.Client:
    return httpx.Client(
        base_url=_server(),
        headers={"Authorization": f"Bearer {_token(token)}"},
        timeout=30.0,
    )


def _print(data: Any) -> None:
    if isinstance(data, (dict, list)):
        console.print(RichJSON.from_data(data))
    else:
        console.print(data)


# ── auth ────────────────────────────────────────────────────────────────────


@app.command()
def login(
    token: str = typer.Option(..., "--token", "-t", prompt=True, hide_input=True,
                              help="API token (will be saved to ~/.ckg/token)"),
) -> None:
    """Save a token locally so you don't have to pass --token every time."""
    cfg = Path.home() / ".ckg"
    cfg.mkdir(parents=True, exist_ok=True)
    out = cfg / "token"
    out.write_text(token.strip() + "\n")
    out.chmod(0o600)
    console.print(f"[green]Saved token to {out}[/green]")


@app.command()
def status() -> None:
    """Check server health and your auth."""
    r = httpx.get(f"{_server()}/readyz", timeout=10)
    console.print(f"[bold]server[/bold]: {_server()}  →  {r.status_code}")
    _print(r.json())
    try:
        with _client() as c:
            who = c.get("/v1/graph/stats")
        console.print("[bold]graph[/bold]:")
        _print(who.json())
    except typer.Exit:
        raise
    except Exception as exc:
        console.print(f"[yellow]graph stats unavailable: {exc}[/yellow]")


# ── tokens ──────────────────────────────────────────────────────────────────


@token_app.command("create")
def token_create(
    name: str = typer.Argument(..., help="Human-readable name"),
    scopes: list[str] = typer.Option(["repo:read"], "--scope", "-s", help="Repeatable scope flag"),
) -> None:
    with _client() as c:
        r = c.post("/v1/tokens", json={"name": name, "scopes": scopes})
        r.raise_for_status()
        console.print("[green]New token created — copy it now, it won't be shown again:[/green]")
        _print(r.json())


@token_app.command("list")
def token_list() -> None:
    with _client() as c:
        r = c.get("/v1/tokens")
        r.raise_for_status()
        rows = r.json()
    table = Table("id", "name", "scopes", "created", "revoked")
    for row in rows:
        table.add_row(
            str(row["id"]), row["name"], ",".join(row["scopes"]),
            row["created_at"], "yes" if row["revoked"] else "no",
        )
    console.print(table)


@token_app.command("revoke")
def token_revoke(token_id: int) -> None:
    with _client() as c:
        r = c.delete(f"/v1/tokens/{token_id}")
        r.raise_for_status()
    console.print(f"[green]revoked token {token_id}[/green]")


# ── repos ───────────────────────────────────────────────────────────────────


@repo_app.command("register")
def repo_register(
    repo_id: str = typer.Argument(..., help="Stable slug"),
    url: str = typer.Argument(..., help="git URL (https/ssh) or file:///abs/path for a local clone"),
    branch: str = typer.Option("main", "--branch", "-b"),
) -> None:
    with _client() as c:
        r = c.post("/v1/repos", json={"id": repo_id, "url": url, "default_branch": branch})
        r.raise_for_status()
        _print(r.json())


@repo_app.command("list")
def repo_list() -> None:
    with _client() as c:
        r = c.get("/v1/repos")
        r.raise_for_status()
        rows = r.json()
    if not rows:
        console.print("(no repos registered)")
        return
    table = Table("id", "url", "branch", "languages", "last indexed")
    for row in rows:
        table.add_row(
            row["id"], row["url"], row["default_branch"],
            ",".join(row.get("languages", []) or []),
            row.get("last_indexed_at") or "—",
        )
    console.print(table)


@repo_app.command("ingest")
def repo_ingest(
    repo_id: str,
    full: bool = typer.Option(False, "--full", help="Wipe and re-parse from scratch."),
    incremental: bool = typer.Option(False, "--incremental", help="(default) only re-parse files whose sha changed."),
) -> None:
    """Queue an ingest. Returns the run id."""
    if full and incremental:
        raise typer.BadParameter("pass at most one of --full / --incremental")
    mode = "full" if full else "incremental"
    with _client() as c:
        r = c.post(f"/v1/repos/{repo_id}/ingest", params={"mode": mode})
        r.raise_for_status()
        _print(r.json())


@repo_app.command("runs")
def repo_runs(repo_id: str) -> None:
    with _client() as c:
        r = c.get(f"/v1/repos/{repo_id}/runs")
        r.raise_for_status()
        rows = r.json()
    if not rows:
        console.print("(no runs)")
        return
    table = Table("id", "mode", "status", "started", "finished", "files", "Δadd", "Δchg", "Δrm", "fns", "error")
    for row in rows:
        stats = row.get("stats") or {}
        table.add_row(
            str(row["id"]), row.get("mode", "—"), row["status"],
            row["started_at"] or "—",
            row.get("finished_at") or "—",
            str(stats.get("files_parsed", "—")),
            str(stats.get("files_added", "—")),
            str(stats.get("files_changed", "—")),
            str(stats.get("files_removed", "—")),
            str(stats.get("functions", "—")),
            (row.get("error") or "")[:60],
        )
    console.print(table)


@repo_app.command("delete")
def repo_delete(repo_id: str, yes: bool = typer.Option(False, "--yes", "-y")) -> None:
    if not yes:
        typer.confirm(f"delete repo {repo_id} (DB row + Neo4j sub-graph)?", abort=True)
    with _client() as c:
        r = c.delete(f"/v1/repos/{repo_id}")
        r.raise_for_status()
    console.print(f"[green]deleted {repo_id}[/green]")


# ── graph ───────────────────────────────────────────────────────────────────


@graph_app.command("stats")
def graph_stats() -> None:
    with _client() as c:
        r = c.get("/v1/graph/stats")
        r.raise_for_status()
        _print(r.json())


@graph_app.command("callers")
def graph_callers(repo_id: str, qualified_name: str, depth: int = 1, limit: int = 100) -> None:
    with _client() as c:
        r = c.get("/v1/graph/callers_of", params={
            "repo_id": repo_id, "qualified_name": qualified_name, "depth": depth, "limit": limit,
        })
        r.raise_for_status()
        _print(r.json())


@graph_app.command("callees")
def graph_callees(repo_id: str, qualified_name: str, depth: int = 1, limit: int = 100) -> None:
    with _client() as c:
        r = c.get("/v1/graph/callees_of", params={
            "repo_id": repo_id, "qualified_name": qualified_name, "depth": depth, "limit": limit,
        })
        r.raise_for_status()
        _print(r.json())


@graph_app.command("impact")
def graph_impact(repo_id: str, path: str, depth: int = 2) -> None:
    with _client() as c:
        r = c.get("/v1/graph/impact_radius", params={"repo_id": repo_id, "path": path, "depth": depth})
        r.raise_for_status()
        _print(r.json())


@graph_app.command("file")
def graph_file(repo_id: str, path: str) -> None:
    with _client() as c:
        r = c.get("/v1/graph/file", params={"repo_id": repo_id, "path": path})
        r.raise_for_status()
        _print(r.json())


# ── search ──────────────────────────────────────────────────────────────────


@search_app.command("keyword")
def search_keyword(q: str, repo: str | None = typer.Option(None, "--repo"), limit: int = 25) -> None:
    with _client() as c:
        params: dict[str, Any] = {"q": q, "limit": limit}
        if repo:
            params["repo_id"] = repo
        r = c.get("/v1/search/keyword", params=params)
        r.raise_for_status()
        _print(r.json())


@search_app.command("semantic")
def search_semantic(q: str, repo: str | None = typer.Option(None, "--repo"), limit: int = 10) -> None:
    with _client() as c:
        params: dict[str, Any] = {"q": q, "limit": limit}
        if repo:
            params["repo_id"] = repo
        r = c.get("/v1/search/semantic", params=params)
        r.raise_for_status()
        _print(r.json())


def main() -> None:
    try:
        app()
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]HTTP {exc.response.status_code}[/red]: {exc.response.text}", file=sys.stderr)
        raise typer.Exit(1)


if __name__ == "__main__":
    main()
