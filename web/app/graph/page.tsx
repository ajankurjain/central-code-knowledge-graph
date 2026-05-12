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

      {!enabled && (
        <p className="text-slate-400">Pick a repo and enter a qualified function name to render its call graph.</p>
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
