"""Token + cost savings model for ckg.

Premise: an AI assistant answering a structural code question without ckg
has to ingest a lot of source text — grep for symbols, read every
matching file, follow imports. With ckg it asks one focused endpoint and
gets back a small, structured JSON payload. The delta is the saving.

We don't store per-call token counts (we'd need an LLM tokenizer in the
middleware), so this module supplies heuristic **per-endpoint** values:

  baseline_tokens — what an agent would have spent without ckg
                    (reading N files of avg M tokens each, plus a grep
                    over a substantial subset of the repo)
  response_tokens — what ckg actually returns instead (small structured
                    JSON; roughly response_bytes / 4 if we cared to log
                    it, but the per-endpoint upper-bound used here is
                    within ~30 % of measured values)

`saving_per_call = baseline_tokens - response_tokens` is then multiplied
by a model price (USD per 1M tokens) to surface a dollar figure on the
dashboard. We blend input/output at 80/20 because the baseline use of
LLM tokens is overwhelmingly input (reading source); only the small
final synthesis is output. Operators can switch the model in the UI.

The numbers below are conservative; users can tune via env if needed:
the goal isn't bookkeeping accuracy, it's communicating order-of-
magnitude impact to teams deciding whether ckg is worth wiring into
their agent stacks.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass

# ─── Heuristics ──────────────────────────────────────────────────────────────
# Per-route baseline (tokens an agent would have read WITHOUT ckg) and
# response (tokens ckg actually returns). Routes not listed default to
# (0, 0) and therefore contribute nothing to the savings total.
#
# Inclusion criteria (deliberate, not a placeholder):
#   1. A reasonable AI agent answering the user's question WITHOUT ckg
#      would have had to ingest source text to answer it (grep + read
#      files, walk imports, scan the tree).
#   2. ckg replaces that with a small structured JSON answer.
#
# Endpoints used by the web UI itself (CRUD: /v1/repos, /v1/sources,
# /v1/graph/stats, /v1/analytics/*, /v1/tokens, ingest mgmt, run
# polling, webhook config, etc.) DO NOT meet (1) — they're API
# bookkeeping, not work an AI agent would otherwise do — so they're
# omitted on purpose. With only dashboard polling running, savings
# should read $0 / 0 tokens; numbers only appear when real AI traffic
# (MCP / graph traversal / search / architecture) hits the API.

PER_ENDPOINT_TOKENS: dict[str, tuple[int, int]] = {
    # ── Graph traversal — the highest-leverage endpoints ─────────────
    # callers/callees of a function: agents would typically grep + read
    # ~20 files at ~800 tokens to chase references.
    "/v1/graph/callers_of":            (16_000,   400),
    "/v1/graph/callees_of":            (16_000,   400),
    # blast_radius / downstream_dependencies hit further — ~30 files.
    "/v1/graph/blast_radius":          (24_000,   600),
    "/v1/graph/downstream_dependencies": (24_000, 600),
    "/v1/graph/imports_of":            ( 1_500,   200),
    "/v1/graph/file":                  ( 2_000,   300),
    "/v1/graph/entry_points":          (15_000,   600),

    # ── Search ────────────────────────────────────────────────────────
    # Baseline: agent does grep + reads top-N hits (~10 files x 800).
    "/v1/search/keyword":              ( 8_000,   500),
    "/v1/search/semantic":             ( 8_000,   500),

    # ── Architecture / overview ──────────────────────────────────────
    # Without ckg, getting a structural overview means scanning the
    # whole codebase — capped here so a single call doesn't dominate.
    "/v1/repos/{repo_id}/architecture":          (30_000, 1_500),
    "/v1/repos/{repo_id}/architecture/warnings": ( 5_000,   400),

    # ── MCP — the umbrella endpoint for IDE agents ───────────────────
    # MCP wraps the per-tool calls above; we attribute an averaged
    # saving because we don't introspect the JSON-RPC body here.
    "/v1/mcp":                         (12_000,   800),

    # ── GraphQL — composed traversals ────────────────────────────────
    "/v1/graphql":                     ( 6_000,   800),
}


# ─── Model price cards ───────────────────────────────────────────────────────
# USD per 1M tokens. The dashboard exposes these so a team can see what
# the savings translate to in THEIR provider's billing.
# Numbers here reflect public list prices at time of writing — operators
# should treat them as a starting point and PR a fresh card when needed.

@dataclass(frozen=True)
class ModelPrice:
    id: str
    label: str
    input_per_million_usd: float
    output_per_million_usd: float
    # Reasonable mix for "agent reading code" workloads — heavy on input
    # (the baseline is mostly source text fed to the model) with a small
    # response synthesis on top.
    input_share: float = 0.85

    def blended_per_million_usd(self) -> float:
        return (
            self.input_per_million_usd * self.input_share
            + self.output_per_million_usd * (1 - self.input_share)
        )

    def dollars_per_token(self) -> float:
        return self.blended_per_million_usd() / 1_000_000.0


MODELS: dict[str, ModelPrice] = {
    m.id: m
    for m in (
        ModelPrice(id="claude-sonnet-4",  label="Claude Sonnet 4",  input_per_million_usd=3.00,  output_per_million_usd=15.00),
        ModelPrice(id="claude-opus-4",    label="Claude Opus 4",    input_per_million_usd=15.00, output_per_million_usd=75.00),
        ModelPrice(id="claude-haiku-4",   label="Claude Haiku 4",   input_per_million_usd=0.80,  output_per_million_usd=4.00),
        ModelPrice(id="gpt-4o",           label="GPT-4o",           input_per_million_usd=2.50,  output_per_million_usd=10.00),
        ModelPrice(id="gpt-4o-mini",      label="GPT-4o mini",      input_per_million_usd=0.15,  output_per_million_usd=0.60),
        ModelPrice(id="gemini-2.5-pro",   label="Gemini 2.5 Pro",   input_per_million_usd=1.25,  output_per_million_usd=10.00),
    )
}

DEFAULT_MODEL_ID = os.environ.get("CKG_DEFAULT_PRICE_MODEL", "claude-sonnet-4")


def get_model(model_id: str | None) -> ModelPrice:
    if model_id and model_id in MODELS:
        return MODELS[model_id]
    return MODELS[DEFAULT_MODEL_ID]


def list_models() -> list[ModelPrice]:
    return list(MODELS.values())


# ─── Per-call savings ────────────────────────────────────────────────────────


def tokens_saved_for_route(route: str) -> int:
    """Heuristic per-call saving for a given route template.

    Returns 0 for routes not mapped — admin/CRUD endpoints don't save
    AI agents any tokens. Negative results are clamped at zero (a
    route's response tokens could in principle exceed its baseline,
    e.g. paginated dumps; we don't penalise users for those).
    """
    baseline, response = PER_ENDPOINT_TOKENS.get(route, (0, 0))
    saving = baseline - response
    return saving if saving > 0 else 0


def integration_for_route(route: str) -> str:
    """Coarse bucket name used in the per-integration breakdown chart.

    Maps a route template to one of: `mcp`, `graphql`, `rest`, `other`.
    """
    if route.startswith("/v1/mcp"):
        return "mcp"
    if route.startswith("/v1/graphql"):
        return "graphql"
    if route.startswith("/v1/"):
        return "rest"
    return "other"


# ─── Aggregation helpers ─────────────────────────────────────────────────────


@dataclass
class RouteSaving:
    route: str
    calls: int
    tokens_saved: int


def aggregate_savings(
    rows: Iterable[tuple[str, int]],
) -> tuple[int, list[RouteSaving]]:
    """Take an iterable of (route, call_count) tuples and return:
       (total_tokens_saved, [RouteSaving sorted by saving desc])
    """
    out: list[RouteSaving] = []
    total = 0
    for route, calls in rows:
        per_call = tokens_saved_for_route(route)
        if per_call == 0 or calls == 0:
            continue
        saving = per_call * calls
        total += saving
        out.append(RouteSaving(route=route, calls=calls, tokens_saved=saving))
    out.sort(key=lambda r: r.tokens_saved, reverse=True)
    return total, out


# Routes carry templated path parameters like `/v1/repos/{repo_id}`. The
# `api_calls.route` column already stores the templated form (we set it
# from `request.scope["route"].path` in the middleware). The fallback
# here only collapses NUMERIC segments — pure ints are unambiguously
# IDs, while alphanumeric segments (like `callers_of`, `entry_points`,
# or even repo slugs like `policy-service`) could just as easily be
# route names so we leave them alone. If the result still doesn't match
# the heuristic table, that route doesn't contribute savings — which is
# the right answer for unrecognised paths.
_NUMERIC_SEGMENT = re.compile(r"/\d+(?=/|$)")


def normalise_route(raw: str) -> str:
    """Best-effort: collapse purely-numeric path segments back to
    `{id}` so a concrete `/v1/sources/1/progress` matches the templated
    form. Anything non-numeric passes through verbatim.
    """
    if "{" in raw:
        return raw
    return _NUMERIC_SEGMENT.sub("/{id}", raw)
