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
from rich.json import JSON as RichJSON  # noqa: N811 — `JSON` is rich's exported name
from rich.table import Table

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Central code knowledge graph CLI.")
repo_app = typer.Typer(no_args_is_help=True, help="Manage repositories.")
token_app = typer.Typer(no_args_is_help=True, help="Manage API tokens (admin scope required).")
graph_app = typer.Typer(no_args_is_help=True, help="Query the graph.")
search_app = typer.Typer(no_args_is_help=True, help="Search the graph.")
source_app = typer.Typer(
    no_args_is_help=True,
    help="Bulk-source ingest — paste a URL, pull every accessible repo.",
)
arch_app = typer.Typer(
    no_args_is_help=True,
    help="Auto-generated architecture map + coupling warnings.",
)

app.add_typer(repo_app, name="repo")
app.add_typer(token_app, name="token")
app.add_typer(graph_app, name="graph")
app.add_typer(search_app, name="search")
app.add_typer(source_app, name="source")
app.add_typer(arch_app, name="arch")

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


@repo_app.command("poll")
def repo_poll(
    repo_id: str,
    every: str = typer.Argument(..., help="Polling interval (e.g. '5m', '1h', '0' to disable)."),
) -> None:
    """Set per-repo polling — scheduler enqueues an incremental ingest each interval."""
    seconds = _parse_duration(every)
    with _client() as c:
        r = c.put(f"/v1/repos/{repo_id}/poll", json={"poll_interval_seconds": seconds})
        r.raise_for_status()
        _print(r.json())


@source_app.command("schedule")
def source_schedule(
    source_id: int,
    every: str = typer.Argument(..., help="Polling interval, e.g. '30m', '1h', '0' to disable."),
) -> None:
    """Set per-source polling. Floor enforced by the scheduler is 60s."""
    seconds = _parse_duration(every)
    with _client() as c:
        r = c.put(f"/v1/sources/{source_id}/schedule", json={"sync_interval_seconds": seconds})
        r.raise_for_status()
        _print(r.json())


@source_app.command("webhook")
def source_webhook(
    source_id: int,
    enable: bool = typer.Option(True, "--enable/--disable"),
    rotate: bool = typer.Option(False, "--rotate", help="Generate a fresh secret."),
) -> None:
    """Enable / disable / rotate the inbound webhook for this source."""
    with _client() as c:
        r = c.put(
            f"/v1/sources/{source_id}/webhook",
            json={"enabled": enable, "rotate_secret": rotate},
        )
        r.raise_for_status()
        data = r.json()
    console.print(
        f"[bold]webhook[/bold] enabled={data['enabled']}\n"
        f"  receiver URL: POST <your-server>/v1/webhooks/{source_id}"
    )
    if data.get("secret"):
        console.print(f"  [yellow]secret[/yellow]: [bold]{data['secret']}[/bold]")
        console.print(
            "  Paste this into:\n"
            "    GitHub    → repo Settings → Webhooks → Secret (content type application/json, just the `push` event)\n"
            "    GitLab    → project Settings → Webhooks → Secret token (Push events)\n"
            "    Bitbucket → workspace Webhooks → URL `?secret=<paste>` (Repository push)"
        )


def _parse_duration(s: str) -> int:
    """Accepts '30s', '5m', '2h', '1d' or a bare integer (seconds)."""
    s = s.strip().lower()
    if not s:
        return 0
    if s[-1].isdigit():
        return int(s)
    n = int(s[:-1])
    return {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(s[-1], 1) * n


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


@graph_app.command("blast")
def graph_blast(repo_id: str, path: str, depth: int = 2) -> None:
    """Files that would break if this file changes (upstream callers)."""
    with _client() as c:
        r = c.get("/v1/graph/blast_radius", params={"repo_id": repo_id, "path": path, "depth": depth})
        r.raise_for_status()
        _print(r.json())


@graph_app.command("downstream")
def graph_downstream(repo_id: str, path: str, depth: int = 2) -> None:
    """Files this file depends on (outgoing callees)."""
    with _client() as c:
        r = c.get("/v1/graph/downstream_dependencies", params={"repo_id": repo_id, "path": path, "depth": depth})
        r.raise_for_status()
        _print(r.json())


@graph_app.command("file")
def graph_file(repo_id: str, path: str) -> None:
    with _client() as c:
        r = c.get("/v1/graph/file", params={"repo_id": repo_id, "path": path})
        r.raise_for_status()
        _print(r.json())


# ── sources ─────────────────────────────────────────────────────────────────


@source_app.command("add")
def source_add(
    url: str = typer.Argument(..., help="GitHub org/user, GitLab group/user, Bitbucket workspace, or manifest URL."),
    token: str = typer.Option("", "--token", "-t", help="PAT for private repos (read from CKG_SOURCE_TOKEN env if omitted)."),
    include_forks: bool = typer.Option(False, "--include-forks"),
    include_archived: bool = typer.Option(False, "--include-archived"),
    no_private: bool = typer.Option(False, "--no-private", help="Skip private repos even when the token allows them."),
    branch: str = typer.Option("", "--branch", help="Override the default branch for every discovered repo."),
    slug_template: str = typer.Option("{owner}-{name}", "--slug-template"),
    sync_now: bool = typer.Option(True, "--sync/--no-sync", help="Run discovery + ingest queueing immediately."),
) -> None:
    tok = token or os.environ.get("CKG_SOURCE_TOKEN") or ""
    body: dict[str, Any] = {
        "url": url,
        "token": tok or None,
        "include_private": not no_private,
        "include_forks": include_forks,
        "include_archived": include_archived,
        "default_branch_override": branch or None,
        "slug_template": slug_template,
        "sync_now": sync_now,
    }
    with _client() as c:
        r = c.post("/v1/sources", json=body)
        r.raise_for_status()
        _print(r.json())


@source_app.command("list")
def source_list() -> None:
    with _client() as c:
        r = c.get("/v1/sources")
        r.raise_for_status()
        rows = r.json()
    if not rows:
        console.print("(no sources)")
        return
    table = Table("id", "kind", "name", "repos", "private", "last synced")
    for row in rows:
        row.get("last_sync_stats") or {}
        table.add_row(
            str(row["id"]), row["kind"], row["name"], str(row.get("repos", "—")),
            "✓" if row.get("has_token") else "—",
            row.get("last_synced_at") or "—",
        )
    console.print(table)


@source_app.command("sync")
def source_sync(source_id: int) -> None:
    """Re-discover and queue ingests for new/changed repos."""
    with _client() as c:
        r = c.post(f"/v1/sources/{source_id}/sync")
        r.raise_for_status()
        _print(r.json())


@source_app.command("repos")
def source_repos(source_id: int) -> None:
    with _client() as c:
        r = c.get(f"/v1/sources/{source_id}/repos")
        r.raise_for_status()
        rows = r.json()
    if not rows:
        console.print("(no repos linked yet — run `ckg source sync`)")
        return
    table = Table("slug", "full name", "branch", "private", "archived", "fork")
    for row in rows:
        table.add_row(
            row["repo_id"], row["full_name"], row["default_branch"],
            "✓" if row["private"] else "—",
            "✓" if row["archived"] else "—",
            "✓" if row["fork"] else "—",
        )
    console.print(table)


@source_app.command("delete")
def source_delete(
    source_id: int,
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Delete a source AND every repo it created (+ their graph data)."""
    if not yes:
        typer.confirm(
            f"delete source {source_id} AND every repo it created (+ Neo4j sub-graphs)?",
            abort=True,
        )
    with _client() as c:
        r = c.delete(f"/v1/sources/{source_id}")
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
        raise typer.Exit(1) from exc


# ── architecture ────────────────────────────────────────────────────────────


@arch_app.command("compute")
def arch_compute(repo_id: str) -> None:
    """Queue a recompute of the architecture map for this repo."""
    with _client() as c:
        r = c.post(f"/v1/repos/{repo_id}/architecture")
        r.raise_for_status()
        _print(r.json())


@arch_app.command("show")
def arch_show(repo_id: str) -> None:
    """List clusters and their cross-cluster dependencies."""
    with _client() as c:
        r = c.get(f"/v1/repos/{repo_id}/architecture")
        r.raise_for_status()
        data = r.json()
    clusters = data.get("clusters") or []
    edges = data.get("edges") or []
    if not clusters:
        console.print(
            "[yellow]No architecture yet.[/yellow] Run "
            f"[bold]ckg arch compute {repo_id}[/bold] and try again in a few seconds."
        )
        return
    table = Table("id", "name", "files", "fan in", "fan out", "instability", "cohesion")
    for c in clusters:
        table.add_row(
            str(c["id"]), c["name"], str(c["file_count"]),
            str(c.get("fan_in", "—")), str(c.get("fan_out", "—")),
            f"{c['instability']:.2f}", f"{c['cohesion']:.2f}",
        )
    console.print("[bold]clusters[/bold]")
    console.print(table)
    if edges:
        edge_table = Table("source", "target", "weight", "files")
        for e in edges:
            edge_table.add_row(str(e["source"]), str(e["target"]), str(e["weight"]), str(e["cross_file_edges"]))
        console.print("[bold]dependencies[/bold]")
        console.print(edge_table)


@arch_app.command("warnings")
def arch_warnings(
    repo_id: str,
    severity: str = typer.Option("", "--severity", "-s", help="Filter by severity (high|medium|low)"),
) -> None:
    """List coupling warnings detected for this repo."""
    params: dict[str, str] = {}
    if severity:
        params["severity"] = severity
    with _client() as c:
        r = c.get(f"/v1/repos/{repo_id}/architecture/warnings", params=params)
        r.raise_for_status()
        rows = r.json().get("warnings") or []
    if not rows:
        console.print("[green]No warnings.[/green]")
        return
    table = Table("severity", "kind", "target", "message")
    for w in rows:
        color = {"high": "red", "medium": "yellow", "low": "cyan"}.get(w["severity"], "white")
        table.add_row(
            f"[{color}]{w['severity']}[/{color}]",
            w["kind"], f"{w['target_kind']}:{w['target_id']}",
            w["message"],
        )
    console.print(table)


if __name__ == "__main__":
    main()
