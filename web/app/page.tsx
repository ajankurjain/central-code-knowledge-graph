"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Navbar } from "@/components/Navbar";
import { TokenGate } from "@/components/TokenGate";
import { StatsCard } from "@/components/StatsCard";
import { Spinner } from "@/components/Spinner";
import { PaginationBar, SearchBox, usePaginatedList } from "@/components/Pagination";
import { api } from "@/lib/api";
import type { Repo } from "@/lib/types";

export default function Dashboard() {
  return (
    <TokenGate>
      <Navbar />
      <main className="mx-auto max-w-6xl px-5 py-8">
        <Stats />
        <IntegrationsRow />
        <CostSavingRow />
        <Repos />
      </main>
    </TokenGate>
  );
}

// Quick-glance savings tiles. Renders the headline numbers from the
// dedicated /savings page so the operator sees the dollar impact without
// clicking through. Returns null while data is loading or empty so it
// doesn't push the repos table down on a fresh install.
function CostSavingRow() {
  const { data } = useQuery({
    queryKey: ["savings-summary", 24, "default"],
    queryFn: () => api.savingsSummary({ windowHours: 24 }),
    refetchInterval: 60_000,
  });
  if (!data) return null;
  const topIntegration = data.by_integration[0];
  const topToken = data.by_token[0];
  return (
    <section className="mb-8">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm uppercase tracking-wider text-slate-400">
          Cost saving
        </h2>
        <Link href="/savings" className="text-xs text-violet-300 hover:underline">
          Details →
        </Link>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatsCard
          label="Saved · 24h"
          value={fmtUsd(data.dollars_saved)}
          hint={
            <span className="text-emerald-300">
              {fmtTokens(data.tokens_saved)} tokens
            </span>
          }
        />
        <StatsCard
          label="Lifetime saved"
          value={fmtUsd(data.lifetime_dollars_saved)}
          hint={`${fmtTokens(data.lifetime_tokens_saved)} tokens`}
        />
        <StatsCard
          label="Top integration"
          value={topIntegration ? topIntegration.integration.toUpperCase() : "—"}
          hint={
            topIntegration
              ? `${fmtUsd(topIntegration.dollars_saved)} · ${topIntegration.calls.toLocaleString()} calls`
              : "no traffic yet"
          }
        />
        <StatsCard
          label="Top team"
          value={topToken ? topToken.token_name : "—"}
          hint={
            topToken
              ? `${fmtUsd(topToken.dollars_saved)} saved`
              : `priced at ${data.model.label}`
          }
        />
      </div>
    </section>
  );
}

// Local formatters mirrored from /savings/page.tsx — keeping them inline
// avoids pulling the whole page into the dashboard bundle just for two
// helpers.
function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}
function fmtUsd(n: number): string {
  if (n >= 100) return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  if (n >= 1) return `$${n.toFixed(2)}`;
  if (n >= 0.01) return `$${n.toFixed(3)}`;
  return `$${n.toFixed(4)}`;
}

// Quick-glance integration counts. Mirrors the headline metrics on
// /integrations so the operator gets a status check straight from the
// home page. Now centred on USAGE (API call volume, top caller, error
// rate) — operational health (ingest queue, etc.) is one click away on
// /integrations.
function IntegrationsRow() {
  const summary = useQuery({
    queryKey: ["integrations-summary"],
    queryFn: api.integrationsSummary,
    refetchInterval: 30_000,
  });
  const usage = useQuery({
    queryKey: ["usage-summary"],
    queryFn: api.usageSummary,
    refetchInterval: 30_000,
  });
  if (summary.isLoading || summary.error || !summary.data) return null;
  const s = summary.data;
  const u = usage.data;
  const errTone =
    !u
      ? "text-slate-400"
      : u.error_rate_pct > 20
      ? "text-rose-300"
      : u.error_rate_pct > 5
      ? "text-amber-300"
      : "text-emerald-300";
  const topCaller = u?.top_tokens[0];
  return (
    <section className="mb-8">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm uppercase tracking-wider text-slate-400">Integrations</h2>
        <Link href="/integrations" className="text-xs text-violet-300 hover:underline">
          Details →
        </Link>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatsCard
          label="API calls 24h"
          value={u ? u.total_calls.toLocaleString() : "—"}
          hint={
            u ? (
              <span className={errTone}>
                {u.calls_per_hour}/hr · {u.error_rate_pct}% errors
              </span>
            ) : (
              "warming up"
            )
          }
        />
        <StatsCard
          label="Top caller"
          value={topCaller ? topCaller.calls_24h.toLocaleString() : "—"}
          hint={
            topCaller
              ? `${topCaller.token_name} (${u?.distinct_tokens ?? 0} active)`
              : "no traffic yet"
          }
        />
        <StatsCard
          label="Sources"
          value={s.sources.total.toLocaleString()}
          hint={`${s.sources.with_webhook} webhook${s.sources.with_webhook === 1 ? "" : "s"} · ${s.sources.with_schedule} scheduled`}
        />
        <StatsCard
          label="API tokens"
          value={s.tokens.active.toLocaleString()}
          hint={`${s.tokens.used_in_last_24h} used in 24h`}
        />
      </div>
    </section>
  );
}

function Stats() {
  const { data, isLoading, error } = useQuery({ queryKey: ["stats"], queryFn: api.stats });
  return (
    <section className="mb-8">
      <h2 className="mb-3 text-sm uppercase tracking-wider text-slate-400">Graph</h2>
      {isLoading && <Spinner />}
      {error && <ErrorBox err={error as Error} />}
      {data && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatsCard label="Repos" value={data.repos.toLocaleString()} />
          <StatsCard label="Files" value={data.files.toLocaleString()} />
          <StatsCard label="Nodes" value={data.nodes.toLocaleString()} />
          <StatsCard label="Edges" value={data.edges.toLocaleString()} />
        </div>
      )}
    </section>
  );
}

function Repos() {
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ["repos"], queryFn: api.repos });
  const paged = usePaginatedList<Repo>(
    data,
    (r, q) =>
      r.id.toLowerCase().includes(q) ||
      (r.url ?? "").toLowerCase().includes(q) ||
      (r.languages ?? []).some((l) => l.toLowerCase().includes(q)),
    10,
  );
  return (
    <section>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm uppercase tracking-wider text-slate-400">Repositories</h2>
        <Link
          href="/repos"
          className="text-xs text-violet-300 hover:underline"
        >
          Manage →
        </Link>
      </div>
      {isLoading && <Spinner />}
      {error && <ErrorBox err={error as Error} onRetry={() => refetch()} />}
      {data && data.length === 0 && (
        <div className="rounded-lg border border-dashed border-slate-700 bg-slate-900/50 p-6 text-center">
          <p className="text-slate-300">No repositories yet.</p>
          <p className="mt-1 text-sm text-slate-500">
            Register one with{" "}
            <code className="font-mono text-violet-300">ckg repo register …</code>{" "}
            or POST to <code className="font-mono">/v1/repos</code>.
          </p>
        </div>
      )}
      {data && data.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-slate-800">
          <div className="flex items-center justify-between gap-3 border-b border-slate-800 bg-slate-900/40 px-3 py-2">
            <SearchBox
              value={paged.query}
              onChange={paged.setQuery}
              placeholder="filter by id, url, or language…"
            />
            <span className="text-xs text-slate-500">
              {paged.rawTotal.toLocaleString()} repositor{paged.rawTotal === 1 ? "y" : "ies"}
            </span>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-slate-900 text-left text-xs uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-4 py-2">id</th>
                <th className="px-4 py-2">url</th>
                <th className="px-4 py-2">languages</th>
                <th className="px-4 py-2">last indexed</th>
              </tr>
            </thead>
            <tbody>
              {paged.slice.map((r) => (
                <tr key={r.id} className="border-t border-slate-800 hover:bg-slate-900/60">
                  <td className="px-4 py-2 font-mono">
                    <Link href={`/repos/${encodeURIComponent(r.id)}`} className="text-violet-300 hover:underline">
                      {r.id}
                    </Link>
                  </td>
                  <td className="px-4 py-2 text-slate-400">{r.url}</td>
                  <td className="px-4 py-2 text-slate-300">
                    {(r.languages || []).join(", ") || "—"}
                  </td>
                  <td className="px-4 py-2 text-slate-400">{r.last_indexed_at ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <PaginationBar
            page={paged.page}
            pageCount={paged.pageCount}
            total={paged.total}
            rawTotal={paged.rawTotal}
            rangeStart={paged.rangeStart}
            rangeEnd={paged.rangeEnd}
            onPage={paged.setPage}
          />
        </div>
      )}
    </section>
  );
}

function ErrorBox({ err, onRetry }: { err: Error; onRetry?: () => void }) {
  return (
    <div className="rounded border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-300">
      {err.message}
      {onRetry && (
        <button onClick={onRetry} className="ml-3 underline">
          retry
        </button>
      )}
    </div>
  );
}
