"use client";

// Dedicated /integrations page — one screen showing every external system
// that's wired into this CKG instance, plus the live counts/usage for each.
//
// Four sections:
//   1. Backend services      — Neo4j / Postgres / Redis health, from /readyz
//   2. Service endpoints     — copy-paste-ready connection strings for AI
//                              clients (MCP, GraphQL, REST)
//   3. Connected integrations— bulk sources + API tokens + webhooks
//   4. Analytics             — language histogram, ingest activity, recent
//                              failures

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Navbar } from "@/components/Navbar";
import { TokenGate } from "@/components/TokenGate";
import { Spinner } from "@/components/Spinner";
import { api, API_BASE } from "@/lib/api";
import type { CountByKey, UsageSummary } from "@/lib/types";

export default function IntegrationsPage() {
  return (
    <TokenGate>
      <Navbar />
      <main className="mx-auto max-w-6xl space-y-8 px-5 py-8">
        <header>
          <h1 className="text-lg font-semibold">Integrations</h1>
          <p className="text-sm text-slate-400">
            Everything connected to this CKG instance — backends, code
            sources, AI clients, and live usage. Auto-refreshes every 30 s.
          </p>
        </header>
        <BackendServices />
        <ServiceEndpoints />
        <ConnectedIntegrations />
        <UsageAnalytics />
        <CatalogAnalytics />
      </main>
    </TokenGate>
  );
}

// ── 1. Backend service health ────────────────────────────────────────────

function BackendServices() {
  // /readyz reports per-dependency liveness; we render a card per dep
  // because that's what an operator wants to see on a status page.
  const { data, isLoading, error } = useQuery({
    queryKey: ["readyz"],
    queryFn: api.ready,
    refetchInterval: 30_000,
  });
  return (
    <section>
      <SectionHeader title="Backend services" subtitle="Required dependencies — outage here means CKG can't serve queries." />
      {isLoading && <Spinner />}
      {error && <ErrorBox err={error as Error} />}
      {data && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Object.entries(data.checks).map(([name, ok]) => (
            <ServiceCard
              key={name}
              name={name}
              ok={ok}
              detail={ok ? "responding" : "unreachable"}
            />
          ))}
          <ServiceCard
            name="ckg version"
            ok={true}
            detail={data.version}
            label="metadata"
          />
        </div>
      )}
    </section>
  );
}

function ServiceCard({
  name,
  ok,
  detail,
  label = "service",
}: {
  name: string;
  ok: boolean;
  detail: string;
  label?: string;
}) {
  return (
    <div
      className={
        "rounded-lg border p-4 " +
        (ok
          ? "border-emerald-900/40 bg-emerald-950/20"
          : "border-rose-900/40 bg-rose-950/20")
      }
    >
      <div className="text-[10px] uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <div className="mt-0.5 flex items-center justify-between gap-2">
        <span className="font-mono text-violet-200">{name}</span>
        <span
          className={
            "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wider " +
            (ok
              ? "bg-emerald-900/60 text-emerald-300"
              : "bg-rose-900/60 text-rose-300")
          }
        >
          <span
            className={
              "h-1.5 w-1.5 rounded-full " +
              (ok ? "bg-emerald-400" : "bg-rose-400")
            }
          />
          {ok ? "ok" : "down"}
        </span>
      </div>
      <div className="mt-1 text-xs text-slate-400">{detail}</div>
    </div>
  );
}

// ── 2. Service endpoints ─────────────────────────────────────────────────

function ServiceEndpoints() {
  // The API base the user's browser is hitting. We can show the exact
  // URLs an AI client would use to connect.
  const mcpUrl = `${API_BASE}/v1/mcp`;
  const graphqlUrl = `${API_BASE}/v1/graphql`;
  const restBase = `${API_BASE}/v1`;
  return (
    <section>
      <SectionHeader title="Service endpoints" subtitle="Paste these into your AI client / dashboard / curl. All require a Bearer token (manage tokens below)." />
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <EndpointCard
          name="MCP server"
          purpose="Cursor · VS Code · Claude Code"
          method="POST"
          url={mcpUrl}
          docHref="/integrations#mcp-help"
        />
        <EndpointCard
          name="GraphQL"
          purpose="Browse the schema in GraphiQL"
          method="POST"
          url={graphqlUrl}
          openable
        />
        <EndpointCard
          name="REST API"
          purpose="Programmatic access for agents + scripts"
          method="GET / POST"
          url={restBase}
          docHref="https://github.com/ajankurjain/central-code-knowledge-graph#api"
          openable
        />
      </div>
    </section>
  );
}

function EndpointCard({
  name,
  purpose,
  method,
  url,
  docHref,
  openable,
}: {
  name: string;
  purpose: string;
  method: string;
  url: string;
  docHref?: string;
  openable?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <div className="flex items-center justify-between">
        <span className="font-semibold text-violet-200">{name}</span>
        <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-slate-400">
          {method}
        </span>
      </div>
      <p className="mt-1 text-xs text-slate-400">{purpose}</p>
      <div className="mt-3 flex items-center gap-2 rounded border border-slate-800 bg-slate-950 px-2 py-1.5 font-mono text-xs text-slate-300">
        <span className="truncate flex-1">{url}</span>
        <button
          type="button"
          onClick={() => {
            navigator.clipboard.writeText(url);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }}
          className="rounded border border-slate-700 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-slate-300 hover:bg-slate-800"
        >
          {copied ? "copied" : "copy"}
        </button>
      </div>
      {docHref && (
        <div className="mt-2 text-xs">
          <a
            href={docHref}
            target={docHref.startsWith("http") ? "_blank" : undefined}
            rel="noreferrer"
            className="text-violet-300 hover:underline"
          >
            {docHref.startsWith("http") ? "open docs ↗" : "see usage"}
          </a>
          {openable && (
            <>
              {"  ·  "}
              <a
                href={url}
                target="_blank"
                rel="noreferrer"
                className="text-violet-300 hover:underline"
              >
                open ↗
              </a>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── 3. Connected external systems (sources + tokens + webhooks) ──────────

function ConnectedIntegrations() {
  const summary = useQuery({
    queryKey: ["integrations-summary"],
    queryFn: api.integrationsSummary,
    refetchInterval: 30_000,
  });
  // Tokens endpoint is admin-only — gracefully degrade for read-only viewers.
  const tokens = useQuery({
    queryKey: ["tokens"],
    queryFn: api.tokens,
    retry: false,
  });

  if (summary.isLoading) return <Spinner />;
  if (summary.error) return <ErrorBox err={summary.error as Error} />;
  if (!summary.data) return null;

  const s = summary.data.sources;
  const t = summary.data.tokens;
  return (
    <section>
      <SectionHeader title="Connected integrations" subtitle="What's wired up and how it's being used." />
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <ConnectionCard
          title="Bulk sources"
          value={s.total}
          unit={s.total === 1 ? "source" : "sources"}
          manageHref="/sources"
        >
          <KindList items={s.by_kind} empty="no sources yet" />
          <Bullet ok={s.with_webhook > 0} text={`${s.with_webhook} webhook${s.with_webhook === 1 ? "" : "s"} enabled`} />
          <Bullet ok={s.with_schedule > 0} text={`${s.with_schedule} scheduled poll${s.with_schedule === 1 ? "" : "s"}`} />
          <Bullet ok={!!s.last_synced_at} text={`last synced ${fmtRel(s.last_synced_at)}`} />
        </ConnectionCard>

        <ConnectionCard
          title="AI clients (API tokens)"
          value={t.active}
          unit={t.active === 1 ? "active token" : "active tokens"}
          manageHref="/login"
        >
          <Bullet ok={t.used_in_last_24h > 0} text={`${t.used_in_last_24h} used in last 24h`} />
          <Bullet ok={t.revoked === 0} text={`${t.revoked} revoked`} fade />
          <Bullet ok={!!t.most_recent_use} text={`last call ${fmtRel(t.most_recent_use)}`} />
          {tokens.data && tokens.data.length > 0 && (
            <ul className="mt-2 space-y-0.5 text-[11px]">
              {tokens.data.slice(0, 4).map((tok) => (
                <li key={tok.id} className="flex justify-between gap-2 truncate">
                  <span className="truncate font-mono text-slate-300">{tok.name}</span>
                  <span className="shrink-0 text-slate-500">
                    {tok.scopes.join(" + ")}
                  </span>
                </li>
              ))}
              {tokens.data.length > 4 && (
                <li className="text-slate-500">+ {tokens.data.length - 4} more</li>
              )}
            </ul>
          )}
        </ConnectionCard>

        <ConnectionCard
          title="Inbound webhooks"
          value={s.with_webhook}
          unit={s.with_webhook === 1 ? "endpoint" : "endpoints"}
          manageHref="/sources"
        >
          <p className="text-xs text-slate-400">
            Provider webhooks pointed at <code className="font-mono">/v1/webhooks/&lt;source_id&gt;</code> trigger
            on-commit re-ingest. Enable + rotate secrets on the Sources page.
          </p>
        </ConnectionCard>
      </div>
    </section>
  );
}

function ConnectionCard({
  title,
  value,
  unit,
  manageHref,
  children,
}: {
  title: string;
  value: number;
  unit: string;
  manageHref: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <div className="flex items-baseline justify-between">
        <span className="text-sm font-semibold text-slate-200">{title}</span>
        <Link href={manageHref} className="text-xs text-violet-300 hover:underline">
          manage →
        </Link>
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="text-3xl font-bold tabular-nums text-violet-200">
          {value.toLocaleString()}
        </span>
        <span className="text-xs text-slate-400">{unit}</span>
      </div>
      <div className="mt-3 space-y-1.5 text-xs text-slate-300">{children}</div>
    </div>
  );
}

function KindList({ items, empty }: { items: CountByKey[]; empty: string }) {
  if (items.length === 0) {
    return <p className="text-xs text-slate-500">{empty}</p>;
  }
  return (
    <ul className="flex flex-wrap gap-1">
      {items.map((kv) => (
        <li
          key={kv.key}
          className="rounded bg-slate-800/70 px-1.5 py-0.5 font-mono text-[11px] text-slate-300"
        >
          <span className="text-violet-200">{kv.key}</span>
          <span className="ml-1 text-slate-400">×{kv.value}</span>
        </li>
      ))}
    </ul>
  );
}

function Bullet({ ok, text, fade }: { ok: boolean; text: string; fade?: boolean }) {
  return (
    <div className="flex items-center gap-1.5">
      <span
        className={
          "h-1.5 w-1.5 shrink-0 rounded-full " +
          (fade
            ? "bg-slate-700"
            : ok
            ? "bg-emerald-400"
            : "bg-slate-700")
        }
      />
      <span className={fade ? "text-slate-500" : ""}>{text}</span>
    </div>
  );
}

// ── 4. Usage analytics — how the API is actually being called ────────────

function UsageAnalytics() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["usage-summary"],
    queryFn: api.usageSummary,
    refetchInterval: 15_000,
  });
  if (isLoading) return <Spinner />;
  if (error) return <ErrorBox err={error as Error} />;
  if (!data) return null;
  return (
    <section className="space-y-3">
      <SectionHeader
        title={`API usage · last ${data.window_hours}h`}
        subtitle="What AI clients (and the web UI) are actually calling. Auto-refreshes every 15 s."
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Tile label="total calls" value={data.total_calls} tone="violet" />
        <Tile label="calls / hour" value={data.calls_per_hour} tone="slate" />
        <Tile label="active tokens" value={data.distinct_tokens} tone="emerald" />
        <Tile
          label="error rate"
          value={`${data.error_rate_pct}%`}
          tone={data.error_rate_pct > 20 ? "rose" : data.error_rate_pct > 5 ? "amber" : "emerald"}
        />
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <TopTokensCard rows={data.top_tokens} />
        <TopEndpointsCard rows={data.top_endpoints} />
      </div>

      <RecentCallsCard rows={data.recent} />
    </section>
  );
}

function TopTokensCard({ rows }: { rows: UsageSummary["top_tokens"] }) {
  if (rows.length === 0) {
    return (
      <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
        <SectionHeader title="Top callers" dense />
        <p className="text-xs text-slate-500">No traffic in the last 24 h yet.</p>
      </div>
    );
  }
  const max = rows[0]?.calls_24h ?? 1;
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <SectionHeader title="Top callers" subtitle="by request count" dense />
      <ul className="space-y-1.5">
        {rows.map((t) => (
          <li
            key={`${t.token_id ?? "anon"}-${t.token_name}`}
            className="grid grid-cols-[1fr_6rem_4rem] items-center gap-2"
          >
            <span className="min-w-0">
              <span className="block truncate font-mono text-xs text-violet-200">
                {t.token_name}
              </span>
              <span className="block truncate text-[10px] text-slate-500">
                last {fmtRel(t.last_call_at)}
                {t.last_status !== null && (
                  <>
                    {" · "}
                    <StatusGlyph s={t.last_status} />
                  </>
                )}
              </span>
            </span>
            <span className="h-2 rounded bg-slate-800">
              <span
                className="block h-full rounded bg-violet-500"
                style={{ width: `${(t.calls_24h / max) * 100}%` }}
              />
            </span>
            <span className="text-right font-mono text-xs tabular-nums text-slate-300">
              {t.calls_24h.toLocaleString()}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function TopEndpointsCard({ rows }: { rows: UsageSummary["top_endpoints"] }) {
  if (rows.length === 0) {
    return (
      <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
        <SectionHeader title="Top endpoints" dense />
        <p className="text-xs text-slate-500">No traffic in the last 24 h yet.</p>
      </div>
    );
  }
  const max = rows[0]?.calls_24h ?? 1;
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <SectionHeader title="Top endpoints" subtitle="calls · p95 latency · error rate" dense />
      <ul className="space-y-1.5">
        {rows.map((e) => (
          <li key={`${e.method} ${e.route}`}>
            <div className="grid grid-cols-[3rem_1fr_4rem] items-center gap-2">
              <span className="rounded bg-slate-800 px-1 py-0.5 text-center font-mono text-[10px] text-slate-300">
                {e.method}
              </span>
              <span className="truncate font-mono text-[11px] text-violet-200" title={e.route}>
                {e.route}
              </span>
              <span className="text-right font-mono text-xs tabular-nums text-slate-300">
                {e.calls_24h.toLocaleString()}
              </span>
            </div>
            <div className="ml-[3.5rem] mt-0.5 grid grid-cols-[1fr_auto] items-center gap-2">
              <span className="h-1.5 rounded bg-slate-800">
                <span
                  className="block h-full rounded bg-violet-500/70"
                  style={{ width: `${(e.calls_24h / max) * 100}%` }}
                />
              </span>
              <span className="font-mono text-[10px] text-slate-500">
                p95 {e.p95_duration_ms}ms
                {e.error_rate_pct > 0 && (
                  <span className="ml-1 text-rose-300">· {e.error_rate_pct}% err</span>
                )}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function RecentCallsCard({ rows }: { rows: UsageSummary["recent"] }) {
  if (rows.length === 0) return null;
  return (
    <details className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <summary className="cursor-pointer text-sm uppercase tracking-wider text-slate-400">
        Live tail · last {rows.length} requests
      </summary>
      <ul className="mt-3 space-y-0.5 font-mono text-[11px]">
        {rows.map((r, i) => (
          <li
            key={i}
            className="grid grid-cols-[5rem_2.5rem_8rem_1fr_4rem_3.5rem] items-center gap-2 truncate"
          >
            <span className="text-slate-500" title={r.ts}>
              {fmtClock(r.ts)}
            </span>
            <span className="text-slate-300">{r.method}</span>
            <span className="truncate text-violet-300" title={r.token_name}>
              {r.token_name}
            </span>
            <span className="truncate text-slate-200" title={r.route}>
              {r.route}
            </span>
            <span className="text-right">
              <StatusGlyph s={r.status} />
            </span>
            <span className="text-right text-slate-500">{r.duration_ms}ms</span>
          </li>
        ))}
      </ul>
    </details>
  );
}

function StatusGlyph({ s }: { s: number }) {
  const cls =
    s >= 500
      ? "text-rose-300"
      : s >= 400
      ? "text-amber-300"
      : s >= 300
      ? "text-sky-300"
      : "text-emerald-300";
  return <span className={`font-mono ${cls}`}>{s}</span>;
}

// ── 5. Catalogue analytics — what we know about (smaller, secondary) ─────

function CatalogAnalytics() {
  const summary = useQuery({
    queryKey: ["integrations-summary"],
    queryFn: api.integrationsSummary,
    refetchInterval: 30_000,
  });
  if (summary.isLoading || !summary.data) return null;
  const repos = summary.data.repos;
  const maxLang = repos.by_language[0]?.value ?? 1;
  return (
    <section>
      <SectionHeader
        title="Catalogue"
        subtitle={`${repos.indexed.toLocaleString()} of ${repos.total.toLocaleString()} repos indexed across ${repos.by_language.length} language${repos.by_language.length === 1 ? "" : "s"}`}
      />
      <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
        {repos.by_language.length === 0 ? (
          <p className="text-xs text-slate-500">No indexed languages yet.</p>
        ) : (
          <ul className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
            {repos.by_language.slice(0, 14).map((kv: CountByKey) => (
              <li key={kv.key} className="grid grid-cols-[6rem_1fr_3rem] items-center gap-2">
                <span className="truncate font-mono text-xs text-slate-300">
                  {kv.key}
                </span>
                <span className="h-2 rounded bg-slate-800">
                  <span
                    className="block h-full rounded bg-violet-500"
                    style={{ width: `${(kv.value / maxLang) * 100}%` }}
                  />
                </span>
                <span className="text-right font-mono text-xs tabular-nums text-slate-400">
                  {kv.value.toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        )}
        {repos.by_language.length > 14 && (
          <p className="mt-2 text-[11px] text-slate-500">
            + {repos.by_language.length - 14} more
          </p>
        )}
      </div>
    </section>
  );
}

function Tile({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone: "emerald" | "rose" | "slate" | "amber" | "violet";
}) {
  const cls =
    tone === "emerald"
      ? "border-emerald-900/40 bg-emerald-950/20 text-emerald-300"
      : tone === "rose"
      ? "border-rose-900/40 bg-rose-950/20 text-rose-300"
      : tone === "amber"
      ? "border-amber-900/40 bg-amber-950/20 text-amber-300"
      : tone === "violet"
      ? "border-violet-900/40 bg-violet-950/20 text-violet-200"
      : "border-slate-800 bg-slate-950 text-slate-300";
  return (
    <div className={`rounded border ${cls} px-2 py-2`}>
      <div className="text-2xl font-bold tabular-nums">
        {typeof value === "number" ? value.toLocaleString() : value}
      </div>
      <div className="text-[10px] uppercase tracking-wider opacity-80">{label}</div>
    </div>
  );
}

// "14:32:11" — local time, just the clock for the live tail.
function fmtClock(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(undefined, { hour12: false });
}

// ── Small reusable bits ──────────────────────────────────────────────────

function SectionHeader({
  title,
  subtitle,
  dense,
}: {
  title: string;
  subtitle?: string;
  dense?: boolean;
}) {
  return (
    <div className={dense ? "mb-2" : "mb-3"}>
      <h2 className="text-sm uppercase tracking-wider text-slate-400">{title}</h2>
      {subtitle && <p className="text-xs text-slate-500">{subtitle}</p>}
    </div>
  );
}

function ErrorBox({ err }: { err: Error }) {
  return (
    <div className="rounded border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-300">
      {err.message}
    </div>
  );
}

// "23m ago" / "2d ago" — null → "never".
function fmtRel(iso: string | null | undefined): string {
  if (!iso) return "never";
  const ms = Date.now() - new Date(iso).getTime();
  if (!isFinite(ms) || ms < 0) return "just now";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}
