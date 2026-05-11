"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams, useRouter } from "next/navigation";
import { Navbar } from "@/components/Navbar";
import { TokenGate } from "@/components/TokenGate";
import { Spinner } from "@/components/Spinner";
import { FunctionGraph, type GraphLink, type GraphNode } from "@/components/ForceGraph";
import { api } from "@/lib/api";
import type { Cluster, Warning } from "@/lib/types";

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
    usp.set("repo", id);
    router.replace(`/arch?${usp.toString()}`);
  }

  return (
    <>
      <div className="mb-4 grid grid-cols-1 gap-3 rounded-lg border border-slate-800 bg-slate-900 p-4 md:grid-cols-[1fr_auto]">
        <select
          value={repo}
          onChange={(e) => pickRepo(e.target.value)}
          className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
        >
          <option value="">— select repo —</option>
          {repos.data?.map((r) => (
            <option key={r.id} value={r.id}>{r.id}</option>
          ))}
        </select>
        {repo && <ComputeButton repoId={repo} />}
      </div>

      {!repo && <p className="text-slate-400">Pick a repo to load its architecture map.</p>}
      {repo && <Content repoId={repo} />}
    </>
  );
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
