"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams, useRouter } from "next/navigation";
import { Navbar } from "@/components/Navbar";
import { TokenGate } from "@/components/TokenGate";
import { Spinner } from "@/components/Spinner";
import { FunctionGraph, type GraphLink, type GraphNode } from "@/components/ForceGraph";
import { api } from "@/lib/api";
import type { Cluster, Repo, Warning } from "@/lib/types";

export default function ArchitecturePage() {
  return (
    <TokenGate>
      <Navbar />
      <main className="mx-auto max-w-6xl px-5 py-8">
        <h1 className="mb-1 text-lg font-semibold">Architecture map</h1>
        <p className="mb-4 text-sm text-slate-400">
          Auto-generated module map — files clustered by call / import affinity,
          plus design-smell warnings. Recompute after any meaningful ingest.
        </p>
        <Inner />
      </main>
    </TokenGate>
  );
}

function Inner() {
  const router = useRouter();
  const params = useSearchParams();
  const repo = params.get("repo") || "";

  const repos = useQuery({ queryKey: ["repos"], queryFn: api.repos });

  function pickRepo(id: string) {
    const usp = new URLSearchParams(params.toString());
    if (id) usp.set("repo", id);
    else usp.delete("repo");
    router.replace(`/arch?${usp.toString()}`);
  }

  const selectedRepo = repos.data?.find((r) => r.id === repo);

  return (
    <>
      <div className="mb-4 grid grid-cols-1 gap-3 rounded-lg border border-slate-800 bg-slate-900 p-4 md:grid-cols-[1fr_auto_auto]">
        <RepoPicker repos={repos.data ?? []} value={repo} onChange={pickRepo} />
        <RefreshButton
          onClick={() => repos.refetch()}
          isFetching={repos.isFetching}
          dataUpdatedAt={repos.dataUpdatedAt}
        />
        {repo && <ComputeButton repoId={repo} />}
      </div>

      {!repo && <p className="text-slate-400">Pick a repo to load its architecture map.</p>}
      {repo && selectedRepo && !selectedRepo.last_indexed_at && (
        <div className="mb-4 rounded border border-amber-700/60 bg-amber-950/30 px-3 py-2 text-sm text-amber-200">
          <b>{selectedRepo.id}</b> hasn't been indexed yet — there's no graph data to cluster.
          Trigger an ingest from the{" "}
          <a href={`/repos/${encodeURIComponent(selectedRepo.id)}`} className="underline">
            repo page
          </a>{" "}
          first, then come back and click <b>Recompute</b>.
        </div>
      )}
      {repo && <Content repoId={repo} />}
    </>
  );
}

// Searchable repo picker. The native <select> works but at 500+ entries it's
// unusable, and there's no visual cue for which repos are actually indexed
// (and therefore have anything to cluster). This combobox filters as you type
// and labels each row with its index state.
function RepoPicker({
  repos,
  value,
  onChange,
}: {
  repos: Repo[];
  value: string;
  onChange: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const wrapRef = useRef<HTMLDivElement | null>(null);

  // Close on outside click.
  useEffect(() => {
    function onDown(e: MouseEvent) {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  const indexed = repos.filter((r) => r.last_indexed_at);
  const sorted = useMemo(() => {
    // Indexed repos first (they're the useful ones for arch), then alpha.
    return [...repos].sort((a, b) => {
      const ai = a.last_indexed_at ? 0 : 1;
      const bi = b.last_indexed_at ? 0 : 1;
      if (ai !== bi) return ai - bi;
      return a.id.localeCompare(b.id);
    });
  }, [repos]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return sorted;
    return sorted.filter(
      (r) => r.id.toLowerCase().includes(q) || (r.url ?? "").toLowerCase().includes(q),
    );
  }, [sorted, query]);

  const current = repos.find((r) => r.id === value);

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between rounded border border-slate-700 bg-slate-950 px-3 py-2 text-left text-sm hover:border-slate-600"
      >
        <span className={current ? "font-mono text-violet-200" : "text-slate-500"}>
          {current ? current.id : "— select repo —"}
        </span>
        <span className="ml-3 text-xs text-slate-500">
          {repos.length.toLocaleString()} total · {indexed.length.toLocaleString()} indexed
        </span>
      </button>
      {open && (
        <div className="absolute left-0 right-0 z-20 mt-1 max-h-80 overflow-hidden rounded border border-slate-700 bg-slate-950 shadow-xl">
          <input
            autoFocus
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="filter…"
            className="w-full border-b border-slate-800 bg-slate-950 px-3 py-2 text-sm placeholder:text-slate-500 focus:outline-none"
          />
          <ul className="max-h-64 overflow-y-auto py-1 text-sm">
            {value && (
              <li>
                <button
                  type="button"
                  onClick={() => {
                    onChange("");
                    setOpen(false);
                    setQuery("");
                  }}
                  className="w-full px-3 py-1.5 text-left text-slate-400 hover:bg-slate-900"
                >
                  — clear —
                </button>
              </li>
            )}
            {filtered.length === 0 && (
              <li className="px-3 py-2 text-slate-500">no matches</li>
            )}
            {filtered.slice(0, 200).map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  onClick={() => {
                    onChange(r.id);
                    setOpen(false);
                    setQuery("");
                  }}
                  className={`flex w-full items-center justify-between gap-3 px-3 py-1.5 text-left hover:bg-slate-900 ${
                    r.id === value ? "bg-slate-900" : ""
                  }`}
                >
                  <span className="truncate font-mono text-violet-200">{r.id}</span>
                  <span
                    className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wider ${
                      r.last_indexed_at
                        ? "bg-emerald-900/60 text-emerald-300"
                        : "bg-slate-800 text-slate-400"
                    }`}
                  >
                    {r.last_indexed_at ? "indexed" : "not indexed"}
                  </span>
                </button>
              </li>
            ))}
            {filtered.length > 200 && (
              <li className="px-3 py-1.5 text-xs text-slate-500">
                showing first 200 of {filtered.length.toLocaleString()} — refine the filter
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}

// Re-fetches the repo list so newly-indexed repos move from "not indexed"
// to "indexed" in the picker without a full page reload.
function RefreshButton({
  onClick,
  isFetching,
  dataUpdatedAt,
}: {
  onClick: () => void;
  isFetching: boolean;
  dataUpdatedAt: number;
}) {
  const since = useRelativeTime(dataUpdatedAt);
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={isFetching}
      title={`Refresh repos${dataUpdatedAt ? ` · last loaded ${since}` : ""}`}
      aria-label="Refresh repos"
      className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 hover:border-slate-600 hover:bg-slate-900 disabled:opacity-50"
    >
      <svg
        viewBox="0 0 24 24"
        width="16"
        height="16"
        aria-hidden="true"
        className={`inline-block ${isFetching ? "animate-spin" : ""}`}
      >
        <path
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M21 12a9 9 0 1 1-3.2-6.9M21 4v5h-5"
        />
      </svg>
    </button>
  );
}

// Lightweight "x s/m/h ago" formatter so the tooltip stays current without
// pulling in date-fns just for one label.
function useRelativeTime(ts: number): string {
  const [, tick] = useState(0);
  useEffect(() => {
    const i = setInterval(() => tick((n) => n + 1), 15_000);
    return () => clearInterval(i);
  }, []);
  if (!ts) return "";
  const diff = Math.max(0, Date.now() - ts);
  if (diff < 60_000) return `${Math.round(diff / 1000)}s ago`;
  if (diff < 3_600_000) return `${Math.round(diff / 60_000)}m ago`;
  return `${Math.round(diff / 3_600_000)}h ago`;
}

function ComputeButton({ repoId }: { repoId: string }) {
  const qc = useQueryClient();
  const mut = useMutation({
    mutationFn: () => api.computeArchitecture(repoId),
    onSuccess: () => {
      // Allow worker a moment, then refetch.
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ["arch", repoId] });
        qc.invalidateQueries({ queryKey: ["arch-warnings", repoId] });
      }, 1500);
    },
  });
  return (
    <button
      onClick={() => mut.mutate()}
      disabled={mut.isPending}
      className="rounded bg-violet-500 px-4 py-2 text-sm font-medium text-violet-50 disabled:opacity-50 hover:bg-violet-400"
    >
      {mut.isPending ? "Queueing…" : "Recompute"}
    </button>
  );
}

function Content({ repoId }: { repoId: string }) {
  const arch = useQuery({
    queryKey: ["arch", repoId],
    queryFn: () => api.architecture(repoId),
  });
  const warnings = useQuery({
    queryKey: ["arch-warnings", repoId],
    queryFn: () => api.architectureWarnings(repoId),
  });

  if (arch.isLoading) return <Spinner />;
  if (arch.error) return <p className="text-red-300">{(arch.error as Error).message}</p>;
  if (!arch.data || arch.data.clusters.length === 0) {
    return (
      <p className="text-slate-400">
        No architecture map yet. Click <b>Recompute</b> above — it'll run in the worker and the
        page will refresh in a few seconds.
      </p>
    );
  }

  return (
    <div className="space-y-8">
      <ClusterMap data={arch.data.clusters} edges={arch.data.edges} />
      <ClusterTable clusters={arch.data.clusters} />
      <WarningsPanel warnings={warnings.data?.warnings ?? []} loading={warnings.isLoading} />
    </div>
  );
}

function ClusterMap({
  data,
  edges,
}: {
  data: Cluster[];
  edges: { source: number; target: number; weight: number }[];
}) {
  const graphData = useMemo(() => {
    const nodes: GraphNode[] = data.map((c) => ({
      id: String(c.id),
      kind: c.instability > 0.6 ? "fn" : c.instability > 0.3 ? "file" : "cls",
      label: `${c.name} (${c.file_count})`,
    }));
    const links: GraphLink[] = edges.map((e) => ({
      source: String(e.source),
      target: String(e.target),
    }));
    return { nodes, links };
  }, [data, edges]);

  return (
    <section>
      <h2 className="mb-2 text-sm uppercase tracking-wider text-slate-400">Cluster map</h2>
      <div className="mb-2 flex flex-wrap items-center gap-4 text-xs text-slate-400">
        <Legend color="bg-emerald-400" label="stable (I ≤ 0.3)" />
        <Legend color="bg-blue-400" label="medium (0.3–0.6)" />
        <Legend color="bg-amber-400" label="unstable (> 0.6)" />
        <span>{data.length} clusters · {edges.length} dependencies</span>
      </div>
      <FunctionGraph data={graphData} />
    </section>
  );
}

function ClusterTable({ clusters }: { clusters: Cluster[] }) {
  return (
    <section>
      <h2 className="mb-3 text-sm uppercase tracking-wider text-slate-400">Clusters</h2>
      <div className="overflow-hidden rounded-lg border border-slate-800">
        <table className="w-full text-sm">
          <thead className="bg-slate-900 text-left text-xs uppercase tracking-wider text-slate-400">
            <tr>
              <th className="px-4 py-2">id</th>
              <th className="px-4 py-2">name</th>
              <th className="px-4 py-2 text-right">files</th>
              <th className="px-4 py-2 text-right">fan in</th>
              <th className="px-4 py-2 text-right">fan out</th>
              <th className="px-4 py-2 text-right">instability</th>
              <th className="px-4 py-2 text-right">cohesion</th>
            </tr>
          </thead>
          <tbody>
            {clusters.map((c) => (
              <tr key={c.id} className="border-t border-slate-800">
                <td className="px-4 py-2 font-mono">{c.id}</td>
                <td className="px-4 py-2 font-mono text-violet-300">{c.name}</td>
                <td className="px-4 py-2 text-right">{c.file_count}</td>
                <td className="px-4 py-2 text-right font-mono">{c.fan_in}</td>
                <td className="px-4 py-2 text-right font-mono">{c.fan_out}</td>
                <td className="px-4 py-2 text-right font-mono">{c.instability.toFixed(2)}</td>
                <td className="px-4 py-2 text-right font-mono">{c.cohesion.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function WarningsPanel({ warnings, loading }: { warnings: Warning[]; loading: boolean }) {
  const [filter, setFilter] = useState<"" | "high" | "medium" | "low">("");
  const filtered = filter ? warnings.filter((w) => w.severity === filter) : warnings;

  return (
    <section>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm uppercase tracking-wider text-slate-400">
          Coupling warnings {warnings.length > 0 ? `· ${warnings.length}` : ""}
        </h2>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value as "" | "high" | "medium" | "low")}
          className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-300"
        >
          <option value="">all severities</option>
          <option value="high">high</option>
          <option value="medium">medium</option>
          <option value="low">low</option>
        </select>
      </div>
      {loading && <Spinner />}
      {!loading && filtered.length === 0 && (
        <p className="text-emerald-300">No warnings 🎉</p>
      )}
      {!loading && filtered.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-900 text-left text-xs uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-4 py-2">severity</th>
                <th className="px-4 py-2">kind</th>
                <th className="px-4 py-2">target</th>
                <th className="px-4 py-2">message</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((w, i) => (
                <tr key={`${w.kind}-${w.target_id}-${i}`} className="border-t border-slate-800">
                  <td className={`px-4 py-2 ${sevColor(w.severity)}`}>{w.severity}</td>
                  <td className="px-4 py-2 font-mono text-slate-300">{w.kind}</td>
                  <td className="px-4 py-2 font-mono text-slate-400">{w.target_kind}:{w.target_id}</td>
                  <td className="px-4 py-2">{w.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`inline-block h-2 w-2 rounded-full ${color}`} />
      {label}
    </span>
  );
}

function sevColor(s: string): string {
  return s === "high"
    ? "text-red-300"
    : s === "medium"
      ? "text-amber-300"
      : s === "low"
        ? "text-cyan-300"
        : "text-slate-300";
}
