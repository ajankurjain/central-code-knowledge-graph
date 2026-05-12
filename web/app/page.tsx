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
        <Repos />
      </main>
    </TokenGate>
  );
}

// Quick-glance integration counts. Mirrors the headline metrics on
// /integrations so the operator gets a status check straight from the
// home page without losing the repos table below.
function IntegrationsRow() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["integrations-summary"],
    queryFn: api.integrationsSummary,
    refetchInterval: 30_000,
  });
  if (isLoading || error || !data) return null;
  const successRate = data.ingests.success_rate_pct;
  const successTone =
    successRate >= 90 ? "text-emerald-300" : successRate >= 60 ? "text-amber-300" : "text-rose-300";
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
          label="Sources"
          value={data.sources.total.toLocaleString()}
          hint={`${data.sources.with_webhook} webhook${data.sources.with_webhook === 1 ? "" : "s"} · ${data.sources.with_schedule} scheduled`}
        />
        <StatsCard
          label="API tokens"
          value={data.tokens.active.toLocaleString()}
          hint={`${data.tokens.used_in_last_24h} used in 24h`}
        />
        <StatsCard
          label="Ingest 24h"
          value={data.ingests.last_24h_total.toLocaleString()}
          hint={
            <span className={successTone}>
              {successRate}% success · {data.ingests.queue_depth} queued
            </span>
          }
        />
        <StatsCard
          label="Languages"
          value={data.repos.by_language.length.toLocaleString()}
          hint={
            data.repos.by_language.length > 0
              ? `top: ${data.repos.by_language.slice(0, 3).map((l) => l.key).join(", ")}`
              : "none yet"
          }
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
