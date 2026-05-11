"""LSP-backed precision pass.

After the tree-sitter ingest writes CallSites and the name-based resolver
materializes coarse `(:Function)-[:CALLS]->(:Function)` edges, this pass
walks the CallSites that the LSP can resolve and **upgrades** the edges
with `precise: true` plus the precise target qname. Edges the LSP can't
resolve keep the name-match fallback.

Off by default — gated by `CKG_LSP_ENABLED=true`.

Performance note: LSPs are slow on cold start (pyright takes 30-90s to
index a medium repo). For large repos this pass can easily 10x the ingest
time. Run it asynchronously or skip it for size-sensitive workloads.
"""

from __future__ import annotations

from pathlib import Path

from ckg.config import get_settings
from ckg.db.neo4j import session as neo_session
from ckg.logging import get_logger
from ckg.lsp.client import LspClient
from ckg.lsp.registry import available_adapters

log = get_logger(__name__)


def run_lsp_pass(repo_id: str, repo_root: Path) -> dict:
    """Run all enabled LSP adapters against the repo and upgrade CALLS edges."""
    settings = get_settings()
    if not settings.lsp_enabled:
        return {"skipped": True, "reason": "CKG_LSP_ENABLED=false"}

    enabled = _enabled_lsp_languages()
    adapters = [a for a in available_adapters() if (not enabled) or a.language in enabled]
    if not adapters:
        return {"skipped": True, "reason": "no LSP adapters available on PATH"}

    stats = {"upgraded": 0, "skipped": 0, "errors": 0, "languages": {}}
    for adapter in adapters:
        log.info("lsp_pass_start", repo_id=repo_id, language=adapter.language)
        try:
            per_lang = _run_for_language(repo_id=repo_id, repo_root=repo_root, adapter=adapter)
        except Exception as exc:
            log.warning("lsp_pass_failed", language=adapter.language, error=str(exc))
            stats["errors"] += 1
            continue
        stats["upgraded"] += per_lang["upgraded"]
        stats["skipped"] += per_lang["skipped"]
        stats["languages"][adapter.language] = per_lang
        log.info("lsp_pass_done", repo_id=repo_id, language=adapter.language, **per_lang)
    return stats


def _enabled_lsp_languages() -> set[str]:
    raw = (get_settings().lsp_adapters or "").strip()
    if not raw:
        return set()
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def _run_for_language(*, repo_id: str, repo_root: Path, adapter) -> dict:
    # Pull every CallSite belonging to functions defined in files of this
    # adapter's language. We carry file_path, the (1-based) line, and column
    # (0 when the parser hasn't recorded it).
    cy = """
        MATCH (f:File {repo_id: $rid, language: $lang})
              -[:DEFINES]->(caller:Function)
              -[:HAS_CALL]->(cs:CallSite)
        WHERE cs.file_path = f.path
        RETURN cs.caller_qname AS caller_qname,
               cs.callee_name AS callee_name,
               cs.file_path AS file_path,
               cs.line AS line,
               coalesce(cs.character, 0) AS character
    """
    with neo_session() as s:
        sites = s.run(cy, rid=repo_id, lang=adapter.language).data()

    if not sites:
        return {"upgraded": 0, "skipped": 0}

    sites_by_file: dict[str, list[dict]] = {}
    for site in sites:
        sites_by_file.setdefault(site["file_path"], []).append(site)

    client = LspClient(
        cmd=adapter.server_command(repo_root),
        repo_root=repo_root,
        language_id=adapter.language_id(),
        init_options=adapter.initialization_options(),
    )
    upgraded, skipped = 0, 0
    try:
        for rel_path, file_sites in sites_by_file.items():
            abs_path = (repo_root / rel_path).resolve()
            if not abs_path.exists():
                skipped += len(file_sites)
                continue
            try:
                text = abs_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                skipped += len(file_sites)
                continue
            client.did_open(abs_path, text)
            try:
                for site in file_sites:
                    locations = client.definition(abs_path, site["line"], site["character"])
                    if not locations:
                        skipped += 1
                        continue
                    loc = locations[0]  # take the first definition
                    if _upgrade_edge(repo_id, site, loc):
                        upgraded += 1
                    else:
                        skipped += 1
            finally:
                client.did_close(abs_path)
    finally:
        client.close()

    return {"upgraded": upgraded, "skipped": skipped}


def _upgrade_edge(repo_id: str, site: dict, loc) -> bool:
    """Promote the matching (caller)-[:CALLS]->(callee) edge to precise=true,
    creating one if the name-match didn't already.

    Returns True iff a CALLS edge was created or modified.
    """
    cy = """
        MATCH (caller:Function {repo_id: $rid, qualified_name: $caller_qname})
        MATCH (callee:Function {repo_id: $rid, file_path: $target_path})
        WHERE callee.start_line <= $target_line AND callee.end_line >= $target_line
        WITH caller, callee
        ORDER BY (callee.end_line - callee.start_line) ASC
        LIMIT 1
        MERGE (caller)-[r:CALLS]->(callee)
          SET r.precise = true,
              r.line = $line
        RETURN id(r) AS edge_id
    """
    with neo_session() as s:
        row = s.run(cy,
            rid=repo_id,
            caller_qname=site["caller_qname"],
            target_path=loc.file_path,
            target_line=loc.line,
            line=site["line"],
        ).single()
    return row is not None
