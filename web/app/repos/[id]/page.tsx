"use client";

import { use, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
        <Credentials id={id} />
        <Runs id={id} />
      </main>
    </TokenGate>
  );
}

function Credentials({ id }: { id: string }) {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["repo", id], queryFn: () => api.repo(id) });
  const [token, setToken] = useState("");
  const [status, setStatus] = useState<string | null>(null);

  const setMut = useMutation({
    mutationFn: (t: string | null) => api.setRepoCredentials(id, t),
    onSuccess: (_d, t) => {
      setToken("");
      setStatus(t ? "✓ token saved (encrypted)" : "✓ token cleared");
      qc.invalidateQueries({ queryKey: ["repo", id] });
      setTimeout(() => setStatus(null), 4000);
    },
    onError: (err: Error) => setStatus(`✗ ${err.message}`),
  });

  if (!data) return null;

  return (
    <section className="mb-6 rounded-lg border border-slate-800 bg-slate-900 p-4">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm uppercase tracking-wider text-slate-400">Credentials</h2>
        <span className="text-xs text-slate-400">
          {data.has_token ? (
            <span className="text-emerald-300">✓ PAT stored (encrypted)</span>
          ) : (
            <span>no PAT — anonymous clones only</span>
          )}
        </span>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-[2fr_auto_auto]">
        <input
          type="password"
          placeholder="paste GitHub / GitLab PAT (or username:password for Bitbucket)"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          autoComplete="off"
          className="rounded border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-sm"
        />
        <button
          onClick={() => setMut.mutate(token)}
          disabled={!token || setMut.isPending}
          className="rounded bg-violet-500 px-4 py-2 text-sm font-medium text-violet-50 disabled:opacity-50 hover:bg-violet-400"
        >
          {setMut.isPending ? "Saving…" : "Save"}
        </button>
        {data.has_token && (
          <button
            onClick={() => setMut.mutate(null)}
            disabled={setMut.isPending}
            className="rounded border border-red-800 px-3 py-2 text-sm text-red-300 hover:bg-red-950"
          >
            Clear
          </button>
        )}
      </div>
      {status && <p className="mt-2 text-xs">{status}</p>}
      <p className="mt-2 text-xs text-slate-500">
        Stored encrypted with the server's <code>CKG_SECRET_KEY</code>. Used by the worker
        when cloning private repos. Cleared values are wiped on save.
      </p>
    </section>
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
                    <td className="px-4 py-2 max-w-xl">
                      {r.error ? (
                        <details className="text-red-300">
                          <summary className="cursor-pointer truncate font-mono text-xs">
                            {r.error.slice(0, 120)}
                            {r.error.length > 120 ? "…" : ""}
                          </summary>
                          <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-slate-950 p-2 text-xs">
                            {r.error}
                          </pre>
                        </details>
                      ) : null}
                    </td>
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
