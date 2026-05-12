"use client";

// Cost-saving dashboard.
//
// Every authenticated API call is logged into `api_calls`. We map each
// route to a heuristic "tokens an AI agent would have spent without ckg"
// (read N files of source) minus "tokens ckg actually returns" (a small
// structured JSON). The difference is the saving. Pricing it at a chosen
// model's per-token rate gives the dollar figure.
//
// The heuristics live in ckg/services/savings.py — operators can tune
// them there without touching the UI.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Navbar } from "@/components/Navbar";
import { TokenGate } from "@/components/TokenGate";
import { Spinner } from "@/components/Spinner";
import { StatsCard } from "@/components/StatsCard";
import { api } from "@/lib/api";
import type { SavingsSummary } from "@/lib/types";

// Windows the operator can toggle between for "X-hour roll-up".
const WINDOWS: { label: string; hours: number }[] = [
  { label: "24h", hours: 24 },
  { label: "7d", hours: 24 * 7 },
  { label: "30d", hours: 24 * 30 },
];

export default function SavingsPage() {
  return (
    <TokenGate>
      <Navbar />
      <main className="mx-auto max-w-6xl space-y-6 px-5 py-8">
        <header>
          <h1 className="text-lg font-semibold">Cost saving</h1>
          <p className="text-sm text-slate-400">
            Tokens (and dollars) AI agents would have spent reading source
            files but didn&apos;t, because they asked ckg instead. Numbers
            are heuristic — derived from the request log + a per-route
            baseline that lives in <code className="font-mono">ckg/services/savings.py</code>.
          </p>
        </header>
        <Inner />
      </main>
    </TokenGate>
  );
}

function Inner() {
  const [windowHours, setWindowHours] = useState<number>(24);
  const [model, setModel] = useState<string | undefined>(undefined);

  const { data, isLoading, error } = useQuery({
    queryKey: ["savings-summary", windowHours, model],
    queryFn: () => api.savingsSummary({ windowHours, model }),
    refetchInterval: 60_000,
  });

  if (isLoading) return <Spinner />;
  if (error) {
    return (
      <p className="rounded border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-300">
        {(error as Error).message}
      </p>
    );
  }
  if (!data) return null;

  const blendedMTok = data.model.blended_per_million_usd;

  return (
    <div className="space-y-6">
      {/* Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-xs uppercase tracking-wider text-slate-400">
            window
          </label>
          <div className="flex overflow-hidden rounded border border-slate-700 bg-slate-950 text-xs">
            {WINDOWS.map((w) => (
              <button
                key={w.hours}
                type="button"
                onClick={() => setWindowHours(w.hours)}
                className={
                  "px-3 py-1.5 " +
                  (windowHours === w.hours
                    ? "bg-violet-600 text-violet-50"
                    : "text-slate-300 hover:bg-slate-900")
                }
              >
                {w.label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs uppercase tracking-wider text-slate-400">
            price model
          </label>
          <select
            value={data.model.id}
            onChange={(e) => setModel(e.target.value)}
            className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-200"
          >
            {data.available_models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label} · ${m.blended_per_million_usd}/M
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Headline tiles */}
      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatsCard
          label={`Saved · ${WINDOWS.find((w) => w.hours === windowHours)?.label ?? `${windowHours}h`}`}
          value={fmtUsd(data.dollars_saved)}
          hint={`${fmtTokens(data.tokens_saved)} tokens`}
        />
        <StatsCard
          label="Lifetime saved"
          value={fmtUsd(data.lifetime_dollars_saved)}
          hint={`${fmtTokens(data.lifetime_tokens_saved)} tokens`}
        />
        <StatsCard
          label="Calls in window"
          value={data.total_calls.toLocaleString()}
          hint={`${data.total_calls_saving.toLocaleString()} saved tokens · ${data.total_calls > 0
              ? Math.round((100 * data.total_calls_saving) / data.total_calls)
              : 0}% leverage`}
        />
        <StatsCard
          label="Effective rate"
          value={`$${blendedMTok}/M`}
          hint={`${data.model.label} blended (85/15 in/out)`}
        />
      </section>

      <DailyTrend data={data} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ByIntegration data={data} />
        <ByToken data={data} />
      </div>

      <ByRoute data={data} />

      <Methodology />
    </div>
  );
}

// ── Daily trend bar chart ───────────────────────────────────────────────

function DailyTrend({ data }: { data: SavingsSummary }) {
  if (data.daily.length === 0) return null;
  const max = Math.max(...data.daily.map((d) => d.tokens_saved));
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <SectionHeader
        title="Daily savings"
        subtitle={`${data.daily.length} day${data.daily.length === 1 ? "" : "s"} of data in window`}
      />
      <div className="flex h-32 items-end gap-1">
        {data.daily.map((d) => {
          const heightPct = max > 0 ? (d.tokens_saved / max) * 100 : 0;
          return (
            <div
              key={d.day}
              className="group relative flex-1"
              style={{ height: "100%" }}
            >
              <div className="absolute inset-x-0 bottom-0 rounded-t bg-violet-500/80 transition group-hover:bg-violet-400"
                style={{ height: `${heightPct}%` }}
              />
              <div className="absolute inset-x-0 -top-12 hidden flex-col items-center text-center text-[10px] text-slate-200 group-hover:flex">
                <span className="rounded bg-slate-950 px-1.5 py-0.5 font-mono">
                  {fmtUsd(d.dollars_saved)}
                </span>
                <span className="text-slate-400">{d.day}</span>
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex items-baseline justify-between text-[10px] text-slate-500">
        <span>{data.daily[0].day}</span>
        <span>{data.daily[data.daily.length - 1].day}</span>
      </div>
    </section>
  );
}

// ── Per-integration breakdown (mcp / graphql / rest) ────────────────────

function ByIntegration({ data }: { data: SavingsSummary }) {
  const total = data.by_integration.reduce((acc, x) => acc + x.tokens_saved, 0) || 1;
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <SectionHeader
        title="By integration"
        subtitle="MCP vs GraphQL vs REST — which channel saves the most"
      />
      {data.by_integration.length === 0 ? (
        <p className="text-xs text-slate-500">No traffic yet.</p>
      ) : (
        <ul className="space-y-2">
          {data.by_integration.map((b) => {
            const pct = (b.tokens_saved / total) * 100;
            return (
              <li key={b.integration} className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-mono uppercase text-violet-200">{b.integration}</span>
                  <span className="font-mono text-slate-300">
                    {fmtUsd(b.dollars_saved)} · {b.calls.toLocaleString()} calls
                  </span>
                </div>
                <div className="h-2 rounded bg-slate-800">
                  <div
                    className="h-full rounded bg-violet-500"
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// ── Per-token breakdown (team / agent attribution) ──────────────────────

function ByToken({ data }: { data: SavingsSummary }) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <SectionHeader
        title="By token / team"
        subtitle="Which API tokens — i.e. which agents or IDEs — drive the savings"
      />
      {data.by_token.length === 0 ? (
        <p className="text-xs text-slate-500">No qualifying calls in window.</p>
      ) : (
        <table className="w-full text-xs">
          <thead className="text-left text-[10px] uppercase tracking-wider text-slate-500">
            <tr>
              <th className="py-1">token</th>
              <th className="py-1 text-right">calls</th>
              <th className="py-1 text-right">tokens</th>
              <th className="py-1 text-right">saved</th>
            </tr>
          </thead>
          <tbody>
            {data.by_token.map((t) => (
              <tr key={`${t.token_id ?? "anon"}-${t.token_name}`} className="border-t border-slate-800">
                <td className="py-1.5 font-mono text-violet-200">{t.token_name}</td>
                <td className="py-1.5 text-right font-mono text-slate-300">{t.calls.toLocaleString()}</td>
                <td className="py-1.5 text-right font-mono text-slate-400">{fmtTokens(t.tokens_saved)}</td>
                <td className="py-1.5 text-right font-mono text-emerald-300">{fmtUsd(t.dollars_saved)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

// ── Per-route breakdown (which endpoints carry the leverage) ────────────

function ByRoute({ data }: { data: SavingsSummary }) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <SectionHeader
        title="By endpoint"
        subtitle="Which ckg routes are pulling the weight"
      />
      {data.by_route.length === 0 ? (
        <p className="text-xs text-slate-500">No qualifying calls in window.</p>
      ) : (
        <table className="w-full text-xs">
          <thead className="text-left text-[10px] uppercase tracking-wider text-slate-500">
            <tr>
              <th className="py-1">route</th>
              <th className="py-1">integration</th>
              <th className="py-1 text-right">calls</th>
              <th className="py-1 text-right">tokens</th>
              <th className="py-1 text-right">saved</th>
            </tr>
          </thead>
          <tbody>
            {data.by_route.map((r) => (
              <tr key={r.route} className="border-t border-slate-800">
                <td className="py-1.5 font-mono text-violet-200">{r.route}</td>
                <td className="py-1.5">
                  <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono uppercase text-[10px] text-slate-400">
                    {r.integration}
                  </span>
                </td>
                <td className="py-1.5 text-right font-mono text-slate-300">{r.calls.toLocaleString()}</td>
                <td className="py-1.5 text-right font-mono text-slate-400">{fmtTokens(r.tokens_saved)}</td>
                <td className="py-1.5 text-right font-mono text-emerald-300">{fmtUsd(r.dollars_saved)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

// ── Methodology footer ──────────────────────────────────────────────────

function Methodology() {
  return (
    <details className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 text-xs text-slate-400">
      <summary className="cursor-pointer text-slate-300">How is this computed?</summary>
      <div className="mt-2 space-y-2 leading-relaxed">
        <p>
          For every logged API call we look up a per-endpoint{" "}
          <code className="font-mono">(baseline_tokens, response_tokens)</code>{" "}
          pair. <b>baseline</b> is what an agent without ckg would have
          spent reading source files to answer the same question (e.g.
          ~20 files × 800 tokens for <code className="font-mono">callers_of</code>),{" "}
          <b>response</b> is what ckg actually returns. The difference,
          summed over all calls, is the token saving.
        </p>
        <p>
          The price model card (USD per 1M tokens) is then applied with
          an 85/15 input/output blend — agent-reads-code workloads are
          overwhelmingly input. Switch the model in the selector above to
          see what the savings translate to for your provider.
        </p>
        <p>
          Heuristics + price cards live in{" "}
          <code className="font-mono">ckg/services/savings.py</code>. Treat
          numbers as order-of-magnitude — useful for "is ckg worth wiring
          into our agents", not for SOX-grade cost attribution.
        </p>
      </div>
    </details>
  );
}

// ── Bits ─────────────────────────────────────────────────────────────────

function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-3">
      <h2 className="text-sm uppercase tracking-wider text-slate-400">{title}</h2>
      {subtitle && <p className="text-[11px] text-slate-500">{subtitle}</p>}
    </div>
  );
}

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
