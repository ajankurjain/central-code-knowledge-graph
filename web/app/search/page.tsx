"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Navbar } from "@/components/Navbar";
import { TokenGate } from "@/components/TokenGate";
import { Spinner } from "@/components/Spinner";
import { api } from "@/lib/api";
import type { SearchResp } from "@/lib/types";

type Mode = "keyword" | "semantic";

export default function SearchPage() {
  return (
    <TokenGate>
      <Navbar />
      <main className="mx-auto max-w-6xl px-5 py-8">
        <h1 className="mb-4 text-lg font-semibold">Search</h1>
        <SearchUI />
      </main>
    </TokenGate>
  );
}

function SearchUI() {
  const [q, setQ] = useState("");
  const [submitted, setSubmitted] = useState<{ q: string; mode: Mode; repo: string } | null>(null);
  const [mode, setMode] = useState<Mode>("keyword");
  const [repo, setRepo] = useState("");

  const repos = useQuery({ queryKey: ["repos"], queryFn: api.repos });

  const results = useQuery<SearchResp>({
    queryKey: ["search", submitted],
    enabled: !!submitted,
    queryFn: () =>
      submitted!.mode === "keyword"
        ? api.keyword(submitted!.q, submitted!.repo || undefined)
        : api.semantic(submitted!.q, submitted!.repo || undefined),
  });

  return (
    <>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setSubmitted({ q: q.trim(), mode, repo });
        }}
        className="mb-6 grid grid-cols-1 gap-3 rounded-lg border border-slate-800 bg-slate-900 p-4 md:grid-cols-[2fr_1fr_1fr_auto]"
      >
        <input
          placeholder="search functions, classes, docs…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          required
        />
        <select
          value={mode}
          onChange={(e) => setMode(e.target.value as Mode)}
          className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
        >
          <option value="keyword">keyword (FTS)</option>
          <option value="semantic">semantic (vector)</option>
        </select>
        <select
          value={repo}
          onChange={(e) => setRepo(e.target.value)}
          className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
        >
          <option value="">all repos</option>
          {repos.data?.map((r) => (
            <option key={r.id} value={r.id}>
              {r.id}
            </option>
          ))}
        </select>
        <button className="rounded bg-violet-500 px-4 py-2 text-sm font-medium text-violet-50 hover:bg-violet-400">
          Search
        </button>
      </form>

      {results.isLoading && <Spinner />}
      {results.error && <p className="text-red-300">{(results.error as Error).message}</p>}
      {results.data && results.data.results.length === 0 && (
        <p className="text-slate-400">No results.</p>
      )}
      {results.data && results.data.results.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-900 text-left text-xs uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-4 py-2">score</th>
                <th className="px-4 py-2">repo</th>
                <th className="px-4 py-2">qualified name</th>
                <th className="px-4 py-2">file</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {results.data.results.map((r, i) => (
                <tr key={`${r.qualified_name}-${i}`} className="border-t border-slate-800">
                  <td className="px-4 py-2 font-mono text-slate-300">{r.score.toFixed(3)}</td>
                  <td className="px-4 py-2 font-mono text-violet-300">{r.repo_id}</td>
                  <td className="px-4 py-2 font-mono">{r.qualified_name}</td>
                  <td className="px-4 py-2 text-slate-400">
                    {r.path}
                    {r.line ? <span className="text-slate-500">:{r.line}</span> : null}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <Link
                      href={`/graph?repo=${encodeURIComponent(r.repo_id)}&qname=${encodeURIComponent(r.qualified_name)}`}
                      className="text-xs text-violet-300 hover:underline"
                    >
                      graph →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
