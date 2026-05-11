"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Navbar } from "@/components/Navbar";
import { TokenGate } from "@/components/TokenGate";
import { Spinner } from "@/components/Spinner";
import { api } from "@/lib/api";

export default function SourcesPage() {
  return (
    <TokenGate>
      <Navbar />
      <main className="mx-auto max-w-6xl px-5 py-8">
        <h1 className="mb-1 text-lg font-semibold">Bulk sources</h1>
        <p className="mb-4 text-sm text-slate-400">
          Paste a GitHub org/user, GitLab group/user, Bitbucket workspace, or a JSON/YAML manifest
          URL. We&apos;ll discover every accessible repo and queue full ingests for each.
        </p>
        <AddForm />
        <SourceTable />
      </main>
    </TokenGate>
  );
}

function AddForm() {
  const qc = useQueryClient();
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [includeForks, setIncludeForks] = useState(false);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [includePrivate, setIncludePrivate] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const mut = useMutation({
    mutationFn: () =>
      api.createSource({
        url,
        token: token || undefined,
        include_private: includePrivate,
        include_forks: includeForks,
        include_archived: includeArchived,
        sync_now: true,
      }),
    onSuccess: () => {
      setUrl("");
      setToken("");
      setError(null);
      qc.invalidateQueries({ queryKey: ["sources"] });
      qc.invalidateQueries({ queryKey: ["repos"] });
    },
    onError: (err: Error) => setError(err.message),
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        mut.mutate();
      }}
      className="mb-6 space-y-3 rounded-lg border border-slate-800 bg-slate-900 p-4"
    >
      <div className="grid grid-cols-1 gap-3 md:grid-cols-[2fr_1fr]">
        <input
          required
          placeholder="https://github.com/orgs/anthropics   (or gitlab.com / bitbucket.org)"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          className="rounded border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-sm"
        />
        <input
          type="password"
          placeholder="PAT (optional; required for private repos)"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          className="rounded border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-sm"
        />
      </div>
      <div className="flex flex-wrap items-center gap-4 text-sm">
        <Toggle label="include private" v={includePrivate} on={setIncludePrivate} />
        <Toggle label="include forks" v={includeForks} on={setIncludeForks} />
        <Toggle label="include archived" v={includeArchived} on={setIncludeArchived} />
        <button
          type="submit"
          disabled={mut.isPending}
          className="ml-auto rounded bg-violet-500 px-4 py-2 text-sm font-medium text-violet-50 disabled:opacity-50 hover:bg-violet-400"
        >
          {mut.isPending ? "Discovering…" : "Add & sync"}
        </button>
      </div>
      {error && (
        <div className="rounded border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-300">
          {error}
        </div>
      )}
    </form>
  );
}

function Toggle({ label, v, on }: { label: string; v: boolean; on: (b: boolean) => void }) {
  return (
    <label className="flex select-none items-center gap-2 text-slate-300">
      <input type="checkbox" checked={v} onChange={(e) => on(e.target.checked)} />
      <span>{label}</span>
    </label>
  );
}

function SourceTable() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ["sources"], queryFn: api.sources });

  const sync = useMutation({
    mutationFn: (id: number) => api.syncSource(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }),
  });
  const del = useMutation({
    mutationFn: (id: number) => api.deleteSource(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sources"] });
      qc.invalidateQueries({ queryKey: ["repos"] });
    },
  });

  if (isLoading) return <Spinner />;
  if (error) return <p className="text-red-300">{(error as Error).message}</p>;
  if (!data?.length) return <p className="text-slate-400">No sources yet. Add one above.</p>;

  return (
    <div className="overflow-hidden rounded-lg border border-slate-800">
      <table className="w-full text-sm">
        <thead className="bg-slate-900 text-left text-xs uppercase tracking-wider text-slate-400">
          <tr>
            <th className="px-4 py-2">id</th>
            <th className="px-4 py-2">kind</th>
            <th className="px-4 py-2">name</th>
            <th className="px-4 py-2 text-right">repos</th>
            <th className="px-4 py-2">token</th>
            <th className="px-4 py-2">last synced</th>
            <th className="px-4 py-2">last sync</th>
            <th className="px-4 py-2 text-right">actions</th>
          </tr>
        </thead>
        <tbody>
          {data.map((s) => {
            const stats = (s.last_sync_stats || {}) as Record<string, number | string[]>;
            return (
              <tr key={s.id} className="border-t border-slate-800">
                <td className="px-4 py-2 font-mono">{s.id}</td>
                <td className="px-4 py-2 text-slate-300">{s.kind}</td>
                <td className="px-4 py-2 font-mono">{s.name}</td>
                <td className="px-4 py-2 text-right font-mono">{s.repos}</td>
                <td className="px-4 py-2">{s.has_token ? "✓" : "—"}</td>
                <td className="px-4 py-2 text-slate-400">{s.last_synced_at ?? "—"}</td>
                <td className="px-4 py-2 text-slate-300">
                  {typeof stats.discovered === "number" ? (
                    <>
                      {stats.discovered} discovered, {stats.added as number} added,{" "}
                      {stats.queued as number} queued
                      {Array.isArray(stats.errors) && stats.errors.length > 0 ? (
                        <span className="ml-2 text-red-300">
                          ({stats.errors.length} errors)
                        </span>
                      ) : null}
                    </>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-4 py-2 text-right">
                  <button
                    onClick={() => sync.mutate(s.id)}
                    disabled={sync.isPending}
                    className="mr-2 rounded border border-slate-700 px-2 py-1 text-xs hover:bg-slate-800"
                  >
                    sync
                  </button>
                  <button
                    onClick={() => {
                      if (
                        confirm(
                          `Delete source ${s.id} AND every repo it created (+ graph data)?`,
                        )
                      ) {
                        del.mutate(s.id);
                      }
                    }}
                    disabled={del.isPending}
                    className="rounded border border-red-800 px-2 py-1 text-xs text-red-300 hover:bg-red-950"
                  >
                    delete
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
