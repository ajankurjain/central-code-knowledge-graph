"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useSearchParams, useRouter } from "next/navigation";
import { Navbar } from "@/components/Navbar";
import { TokenGate } from "@/components/TokenGate";
import { Spinner } from "@/components/Spinner";
import { FunctionGraph, type GraphLink, type GraphNode } from "@/components/ForceGraph";
import { RepoPicker, RefreshButton } from "@/components/RepoPicker";
import { api } from "@/lib/api";
import type { Cluster, Warning } from "@/lib/types";

// How long to keep polling the GET after a Recompute click before we conclude
// the worker either succeeded-with-zero-clusters or silently died. The Louvain
// + Cypher writes for a ~600-file repo finish in well under this.
const ARCH_POLL_BUDGET_MS = 90_000;
const ARCH_POLL_INTERVAL_MS = 2_500;

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

// Compute-state machine driven by Inner. ComputeButton triggers it; Content
// reads it to decide whether to poll, show a banner, or render the map.
type ComputeState =
  | { kind: "idle" }
  | { kind: "queueing" }                   // POST in flight
  | { kind: "computing"; startedAt: number } // POST accepted, polling for clusters
  | { kind: "timed_out"; startedAt: number } // polled past budget, never saw clusters
  | { kind: "error"; message: string };

function Inner() {
  const router = useRouter();
  const params = useSearchParams();
  const repo = params.get("repo") || "";

  const repos = useQuery({ queryKey: ["repos"], queryFn: api.repos });

  // Compute state, owned here so the button and the content panel share it.
  // Keyed on repoId so picking a different repo resets the machine.
  const [computeState, setComputeState] = useState<ComputeState>({ kind: "idle" });
  const lastRepoRef = useRef(repo);
  useEffect(() => {
    if (lastRepoRef.current !== repo) {
      setComputeState({ kind: "idle" });
      lastRepoRef.current = repo;
    }
  }, [repo]);

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
        {repo && (
          <ComputeButton
            repoId={repo}
            state={computeState}
            onState={setComputeState}
          />
        )}
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
      {repo && (
        <Content
          repoId={repo}
          computeState={computeState}
          onComputeState={setComputeState}
        />
      )}
    </>
  );
}

function ComputeButton({
  repoId,
  state,
  onState,
}: {
  repoId: string;
  state: ComputeState;
  onState: (s: ComputeState) => void;
}) {
  const mut = useMutation({
    mutationFn: () => api.computeArchitecture(repoId),
    onMutate: () => onState({ kind: "queueing" }),
    onSuccess: () => onState({ kind: "computing", startedAt: Date.now() }),
    onError: (err: Error) =>
      onState({
        kind: "error",
        // Truncate so a 2 KB stack trace doesn't blow up the layout.
        message: err.message.slice(0, 400),
      }),
  });
  const busy = state.kind === "queueing" || state.kind === "computing";
  return (
    <button
      onClick={() => mut.mutate()}
      disabled={busy}
      className="rounded bg-violet-500 px-4 py-2 text-sm font-medium text-violet-50 disabled:opacity-50 hover:bg-violet-400"
    >
      {state.kind === "queueing" && "Queueing…"}
      {state.kind === "computing" && "Computing…"}
      {(state.kind === "idle" || state.kind === "timed_out" || state.kind === "error") &&
        "Recompute"}
    </button>
  );
}

function Content({
  repoId,
  computeState,
  onComputeState,
}: {
  repoId: string;
  computeState: ComputeState;
  onComputeState: (s: ComputeState) => void;
}) {
  // Poll aggressively while we're waiting for the worker; the first non-empty
  // response flips us out of `computing`. If nothing shows up within the
  // budget we surface "timed out / produced no clusters" so the user isn't
  // stranded on a screen that looks identical to "never ran".
  const polling = computeState.kind === "computing";
  const arch = useQuery({
    queryKey: ["arch", repoId],
    queryFn: () => api.architecture(repoId),
    refetchInterval: polling ? ARCH_POLL_INTERVAL_MS : false,
  });
  const warnings = useQuery({
    queryKey: ["arch-warnings", repoId],
    queryFn: () => api.architectureWarnings(repoId),
    // Only refresh warnings after we have a map; otherwise we just hammer
    // an endpoint that returns nothing.
    enabled: (arch.data?.clusters.length ?? 0) > 0,
  });

  useEffect(() => {
    if (computeState.kind !== "computing") return;
    // Saw clusters land — done.
    if ((arch.data?.clusters.length ?? 0) > 0) {
      onComputeState({ kind: "idle" });
      return;
    }
    // Past the budget without seeing anything — flip to timed_out so the UI
    // explains what happened.
    if (Date.now() - computeState.startedAt > ARCH_POLL_BUDGET_MS) {
      onComputeState({ kind: "timed_out", startedAt: computeState.startedAt });
    }
  }, [arch.data, computeState, onComputeState]);

  if (arch.isLoading && !arch.data) return <Spinner />;

  const banner = (() => {
    if (computeState.kind === "queueing") {
      return (
        <div className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-300">
          Sending recompute request…
        </div>
      );
    }
    if (computeState.kind === "computing") {
      const secs = Math.round((Date.now() - computeState.startedAt) / 1000);
      return (
        <div className="flex items-center gap-2 rounded border border-sky-800/60 bg-sky-950/30 px-3 py-2 text-sm text-sky-200">
          <Spinner />
          <span>
            Computing architecture map — this can take ~30 s on big repos.{" "}
            <span className="text-sky-400/80">({secs}s elapsed)</span>
          </span>
        </div>
      );
    }
    if (computeState.kind === "error") {
      return (
        <div className="rounded border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-300">
          Recompute failed: {computeState.message}
        </div>
      );
    }
    if (computeState.kind === "timed_out") {
      return (
        <div className="rounded border border-amber-700/60 bg-amber-950/30 px-3 py-2 text-sm text-amber-200">
          Recompute finished but no clusters reached the UI — this usually means
          the repo has no <code>File</code> nodes in the graph yet. Trigger a
          full ingest from the{" "}
          <a
            href={`/repos/${encodeURIComponent(repoId)}`}
            className="underline"
          >
            repo page
          </a>{" "}
          and retry, or check the worker logs.
        </div>
      );
    }
    return null;
  })();

  const hasMap = arch.data && arch.data.clusters.length > 0;

  return (
    <div className="space-y-6">
      {banner}
      {arch.error && (
        <p className="text-red-300">{(arch.error as Error).message}</p>
      )}
      {!hasMap && computeState.kind === "idle" && (
        <p className="text-slate-400">
          No architecture map yet. Click <b>Recompute</b> above — it'll run in
          the worker and progress will show here while it's working.
        </p>
      )}
      {hasMap && arch.data && (
        <>
          {arch.data.edge_source === "directory_fallback" && (
            <div className="rounded border border-slate-700 bg-slate-900/70 px-3 py-2 text-xs text-slate-300">
              Built from the repo's directory layout — the call / import
              graph was too thin for this repo's language(s) to cluster on
              precisely. Fan-in / fan-out / instability numbers below are
              structural proxies, not behavioural.
            </div>
          )}
          <ClusterMap data={arch.data.clusters} edges={arch.data.edges} />
          <ClusterTable clusters={arch.data.clusters} />
          <WarningsPanel
            warnings={warnings.data?.warnings ?? []}
            loading={warnings.isLoading}
          />
        </>
      )}
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
