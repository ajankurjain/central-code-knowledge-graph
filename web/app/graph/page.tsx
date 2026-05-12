"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams, useRouter } from "next/navigation";
import { Navbar } from "@/components/Navbar";
import { TokenGate } from "@/components/TokenGate";
import { Spinner } from "@/components/Spinner";
import { FunctionGraph, type GraphLink, type GraphNode } from "@/components/ForceGraph";
import { RepoPicker, RefreshButton } from "@/components/RepoPicker";
import { api } from "@/lib/api";

export default function GraphPage() {
  return (
    <TokenGate>
      <Navbar />
      <main className="mx-auto max-w-6xl px-5 py-8">
        <h1 className="mb-4 text-lg font-semibold">Function call graph</h1>
        <Inner />
      </main>
    </TokenGate>
  );
}

function Inner() {
  const router = useRouter();
  const params = useSearchParams();
  const repo = params.get("repo") || "";
  const qname = params.get("qname") || "";
  const [depth, setDepth] = useState(2);

  const repos = useQuery({ queryKey: ["repos"], queryFn: api.repos });
  const selectedRepo = repos.data?.find((r) => r.id === repo);

  const enabled = !!repo && !!qname;
  const callers = useQuery({
    queryKey: ["callers", repo, qname, depth],
    queryFn: () => api.callersOf(repo, qname, depth, 200),
    enabled,
  });
  const callees = useQuery({
    queryKey: ["callees", repo, qname, depth],
    queryFn: () => api.calleesOf(repo, qname, depth, 200),
    enabled,
  });

  // When the user picks a repo but hasn't typed a qname yet, offer the
  // most-connected functions in that repo as click-to-fill suggestions —
  // otherwise the page just sits empty with a "enter a function name"
  // prompt and the user has nowhere to start. Only fires once the repo
  // has been indexed (no graph data otherwise).
  const entries = useQuery({
    queryKey: ["entry-points", repo],
    queryFn: () => api.entryPoints(repo, 20),
    enabled: !!repo && !qname && !!selectedRepo?.last_indexed_at,
  });

  const data = useMemo(() => {
    const nodes: Record<string, GraphNode> = {};
    const links: GraphLink[] = [];
    if (qname) nodes[qname] = { id: qname, kind: "self", label: shortName(qname) };
    for (const r of callers.data?.results || []) {
      nodes[r.qn] = nodes[r.qn] ?? { id: r.qn, kind: "fn", label: shortName(r.qn) };
      links.push({ source: r.qn, target: qname });
    }
    for (const r of callees.data?.results || []) {
      nodes[r.qn] = nodes[r.qn] ?? { id: r.qn, kind: "fn", label: shortName(r.qn) };
      links.push({ source: qname, target: r.qn });
    }
    return { nodes: Object.values(nodes), links };
  }, [callers.data, callees.data, qname]);

  function update(next: Partial<{ repo: string; qname: string }>) {
    const usp = new URLSearchParams(params.toString());
    if (next.repo !== undefined) {
      if (next.repo) usp.set("repo", next.repo);
      else usp.delete("repo");
    }
    if (next.qname !== undefined) usp.set("qname", next.qname);
    router.replace(`/graph?${usp.toString()}`);
  }

  return (
    <>
      <form
        onSubmit={(e) => e.preventDefault()}
        className="mb-4 grid grid-cols-1 gap-3 rounded-lg border border-slate-800 bg-slate-900 p-4 md:grid-cols-[1fr_auto_2fr_auto]"
      >
        <RepoPicker
          repos={repos.data ?? []}
          value={repo}
          onChange={(id) => update({ repo: id })}
        />
        <RefreshButton
          onClick={() => repos.refetch()}
          isFetching={repos.isFetching}
          dataUpdatedAt={repos.dataUpdatedAt}
        />
        <input
          placeholder="qualified function name, e.g. my.module.foo"
          value={qname}
          onChange={(e) => update({ qname: e.target.value })}
          className="rounded border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-sm"
        />
        <label className="flex items-center gap-2 text-sm text-slate-300">
          depth
          <input
            type="number"
            min={1}
            max={4}
            value={depth}
            onChange={(e) => setDepth(Math.max(1, Math.min(4, Number(e.target.value))))}
            className="w-16 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-sm"
          />
        </label>
      </form>

      {!repo && (
        <p className="text-slate-400">Pick a repo to start.</p>
      )}
      {repo && selectedRepo && !selectedRepo.last_indexed_at && (
        <div className="rounded border border-amber-700/60 bg-amber-950/30 px-3 py-2 text-sm text-amber-200">
          <b>{selectedRepo.id}</b> hasn't been indexed yet — no call edges to traverse.
          Trigger an ingest from the{" "}
          <a
            href={`/repos/${encodeURIComponent(selectedRepo.id)}`}
            className="underline"
          >
            repo page
          </a>{" "}
          first.
        </div>
      )}
      {repo && !qname && selectedRepo?.last_indexed_at && (
        <EntryPointSuggestions
          entries={entries.data?.results}
          isLoading={entries.isLoading}
          error={entries.error as Error | null}
          onPick={(qn) => update({ qname: qn })}
        />
      )}
      {enabled && (callers.isLoading || callees.isLoading) && <Spinner />}
      {(callers.error || callees.error) && (
        <p className="text-red-300">
          {(callers.error as Error)?.message ?? (callees.error as Error)?.message}
        </p>
      )}
      {enabled && data.nodes.length > 0 && (
        <>
          <div className="mb-2 flex items-center gap-4 text-xs text-slate-400">
            <Legend color="bg-violet-400" label="target" />
            <Legend color="bg-emerald-400" label="caller / callee" />
            <span>{data.nodes.length} nodes · {data.links.length} edges</span>
          </div>
          <FunctionGraph data={data} />
        </>
      )}
    </>
  );
}

// Click-to-fill list of the most-connected functions in the selected repo,
// rendered when the user picked a repo but hasn't typed a qname yet. Saves
// them from having to know any qualified names ahead of time.
function EntryPointSuggestions({
  entries,
  isLoading,
  error,
  onPick,
}: {
  entries: { qn: string; path: string; line: number | null; callers: number; callees: number; total: number }[] | undefined;
  isLoading: boolean;
  error: Error | null;
  onPick: (qn: string) => void;
}) {
  if (isLoading) return <Spinner />;
  if (error)
    return (
      <p className="text-red-300">Couldn't load entry points: {error.message}</p>
    );
  if (!entries || entries.length === 0) {
    return (
      <p className="text-slate-400">
        No call edges discovered in this repo yet — try ingesting it first, or
        enter a qualified function name manually above.
      </p>
    );
  }
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
      <h2 className="mb-3 text-sm uppercase tracking-wider text-slate-400">
        Most-connected functions · click to render
      </h2>
      <ul className="grid grid-cols-1 gap-1 sm:grid-cols-2">
        {entries.map((e) => (
          <li key={e.qn}>
            <button
              type="button"
              onClick={() => onPick(e.qn)}
              className="flex w-full items-center justify-between gap-3 rounded px-3 py-2 text-left hover:bg-slate-900"
            >
              <span className="min-w-0 flex-1">
                <span className="block truncate font-mono text-sm text-violet-200">
                  {shortName(e.qn)}
                </span>
                <span className="block truncate text-xs text-slate-500">
                  {e.path}
                  {e.line ? `:${e.line}` : ""}
                </span>
              </span>
              <span className="shrink-0 text-xs text-slate-400">
                <span className="text-emerald-300">{e.callers}</span>↓ ·{" "}
                <span className="text-sky-300">{e.callees}</span>↑
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
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

function shortName(qn: string): string {
  const sep = qn.includes("::") ? "::" : ".";
  const parts = qn.split(sep);
  return parts[parts.length - 1] ?? qn;
}
