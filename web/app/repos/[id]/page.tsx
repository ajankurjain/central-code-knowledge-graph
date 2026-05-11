"use client";

import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Navbar } from "@/components/Navbar";
import { TokenGate } from "@/components/TokenGate";
import { Spinner } from "@/components/Spinner";
import { api } from "@/lib/api";

export default function RepoDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <TokenGate>
      <Navbar />
      <main className="mx-auto max-w-6xl px-5 py-8">
        <Header id={id} />
        <Runs id={id} />
      </main>
    </TokenGate>
  );
}

function Header({ id }: { id: string }) {
  const { data, isLoading } = useQuery({ queryKey: ["repo", id], queryFn: () => api.repo(id) });
  return (
    <div className="mb-6">
      <Link href="/repos" className="text-xs text-slate-400 hover:underline">
        ← repos
      </Link>
      <h1 className="mt-1 font-mono text-xl">{id}</h1>
      {isLoading && <Spinner />}
      {data && (
        <div className="mt-2 text-sm text-slate-400">
          <div>
            url: <span className="font-mono">{data.url}</span>
          </div>
          <div>
            branch: <span className="font-mono">{data.default_branch}</span>
          </div>
          <div>
            languages: <span className="font-mono">{(data.languages || []).join(", ") || "—"}</span>
          </div>
          <div>last indexed: {data.last_indexed_at ?? "—"}</div>
        </div>
      )}
    </div>
  );
}

function Runs({ id }: { id: string }) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["runs", id],
    queryFn: () => api.runs(id),
    refetchInterval: (q) =>
      Array.isArray(q.state.data) && q.state.data.some((r) => r.status === "queued" || r.status === "running")
        ? 3_000
        : false,
  });

  return (
    <section>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm uppercase tracking-wider text-slate-400">Ingest runs</h2>
        <button onClick={() => refetch()} className="text-xs text-violet-300 hover:underline">
          refresh
        </button>
      </div>
      {isLoading && <Spinner />}
      {error && <p className="text-red-300">{(error as Error).message}</p>}
      {data && data.length === 0 && <p className="text-slate-400">No runs yet.</p>}
      {data && data.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-900 text-left text-xs uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-4 py-2">id</th>
                <th className="px-4 py-2">mode</th>
                <th className="px-4 py-2">status</th>
                <th className="px-4 py-2">started</th>
                <th className="px-4 py-2">finished</th>
                <th className="px-4 py-2 text-right">files Δ</th>
                <th className="px-4 py-2 text-right">fns</th>
                <th className="px-4 py-2">error</th>
              </tr>
            </thead>
            <tbody>
              {data.map((r) => {
                const stats = (r.stats || {}) as Record<string, number>;
                const delta = `${stats.files_added ?? 0}+ ${stats.files_changed ?? 0}↻ ${stats.files_removed ?? 0}−`;
                const status =
                  r.status === "success"
                    ? "text-emerald-300"
                    : r.status === "failed"
                      ? "text-red-300"
                      : "text-amber-300";
                return (
                  <tr key={r.id} className="border-t border-slate-800">
                    <td className="px-4 py-2 font-mono">{r.id}</td>
                    <td className="px-4 py-2 text-slate-300">{r.mode}</td>
                    <td className={`px-4 py-2 ${status}`}>{r.status}</td>
                    <td className="px-4 py-2 text-slate-400">{r.started_at}</td>
                    <td className="px-4 py-2 text-slate-400">{r.finished_at ?? "—"}</td>
                    <td className="px-4 py-2 text-right font-mono">{delta}</td>
                    <td className="px-4 py-2 text-right font-mono">{stats.functions ?? "—"}</td>
                    <td className="px-4 py-2 text-red-300">{r.error?.slice(0, 80) || ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
