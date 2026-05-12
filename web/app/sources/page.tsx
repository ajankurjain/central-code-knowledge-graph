"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Navbar } from "@/components/Navbar";
import { TokenGate } from "@/components/TokenGate";
import { Spinner } from "@/components/Spinner";
import { api } from "@/lib/api";
import type { SourceProgress } from "@/lib/types";

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
  const [branch, setBranch] = useState("");
  const [includeForks, setIncludeForks] = useState(false);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [includePrivate, setIncludePrivate] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const mut = useMutation({
    mutationFn: () =>
      api.createSource({
        url,
        token: token || undefined,
        // Operator-chosen branch wins over the per-repo default reported
        // by the provider. Pass it as default_branch_override so every
        // discovered repo gets cloned on this branch. Leave empty to use
        // whatever the provider says.
        default_branch_override: branch.trim() || undefined,
        include_private: includePrivate,
        include_forks: includeForks,
        include_archived: includeArchived,
        sync_now: true,
      }),
    onSuccess: () => {
      setUrl("");
      setToken("");
      setBranch("");
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
      <div className="grid grid-cols-1 gap-1">
        <label className="text-xs uppercase tracking-wider text-slate-400">
          branch to ingest{" "}
          <span className="ml-1 text-slate-500 normal-case tracking-normal">
            applied to every discovered repo · leave empty to use each
            repo's reported default
          </span>
        </label>
        <input
          placeholder="develop / main / master / …"
          value={branch}
          onChange={(e) => setBranch(e.target.value)}
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
  const setBranch = useMutation({
    mutationFn: ({ id, branch }: { id: number; branch: string }) =>
      api.setSourceBranch(id, branch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }),
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
            <th className="px-4 py-2">token</th>
            <th className="px-4 py-2">branch</th>
            <th className="px-4 py-2 w-[28%]">progress</th>
            <th className="px-4 py-2 text-right">actions</th>
          </tr>
        </thead>
        <tbody>
          {data.map((s) => (
            <tr key={s.id} className="border-t border-slate-800 align-top">
              <td className="px-4 py-3 font-mono">{s.id}</td>
              <td className="px-4 py-3 text-slate-300">{s.kind}</td>
              <td className="px-4 py-3 font-mono">{s.name}</td>
              <td className="px-4 py-3">{s.has_token ? "✓" : "—"}</td>
              <td className="px-4 py-3">
                <BranchEditor
                  current={s.default_branch_override}
                  onSave={(b) => setBranch.mutateAsync({ id: s.id, branch: b })}
                />
              </td>
              <td className="px-4 py-3">
                <ProgressCell sourceId={s.id} fallbackTotal={s.repos} />
              </td>
              <td className="px-4 py-3 text-right whitespace-nowrap">
                <button
                  onClick={() => sync.mutate(s.id)}
                  disabled={sync.isPending}
                  className="mr-2 rounded border border-slate-700 px-2 py-1 text-xs hover:bg-slate-800"
                >
                  {sync.isPending && sync.variables === s.id ? "syncing…" : "sync"}
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
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Inline branch-override editor for a source row. Empty value means "use
// each repo's reported default", a non-empty value applies to every NEW
// repo on the next sync.
function BranchEditor({
  current,
  onSave,
}: {
  current: string | null | undefined;
  onSave: (branch: string) => Promise<unknown>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(current ?? "");
  const [pending, setPending] = useState(false);

  // Reset draft when the source data refreshes underneath us.
  useEffect(() => {
    if (!editing) setDraft(current ?? "");
  }, [current, editing]);

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => setEditing(true)}
        className="rounded border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-xs hover:border-slate-600"
        title="Click to set / clear the branch override"
      >
        {current ? (
          <span className="text-violet-200">{current}</span>
        ) : (
          <span className="text-slate-500">(per-repo)</span>
        )}
      </button>
    );
  }
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        setPending(true);
        try {
          await onSave(draft.trim());
          setEditing(false);
        } finally {
          setPending(false);
        }
      }}
      className="flex items-center gap-1"
    >
      <input
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        placeholder="(empty = per-repo)"
        className="w-32 rounded border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-xs"
      />
      <button
        type="submit"
        disabled={pending}
        className="rounded bg-violet-500 px-2 py-1 text-xs text-violet-50 disabled:opacity-50 hover:bg-violet-400"
      >
        {pending ? "…" : "save"}
      </button>
      <button
        type="button"
        onClick={() => {
          setDraft(current ?? "");
          setEditing(false);
        }}
        className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800"
      >
        cancel
      </button>
    </form>
  );
}

// Live progress bar per source. Polls /progress every 5s while there's any
// queued or running run, slows to 30s once everything is settled so we
// aren't hammering the API on idle pages.
function ProgressCell({ sourceId, fallbackTotal }: { sourceId: number; fallbackTotal: number }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["source-progress", sourceId],
    queryFn: () => api.sourceProgress(sourceId),
    refetchInterval: (q) => {
      const p = q.state.data as SourceProgress | undefined;
      return p?.in_progress ? 5000 : 30000;
    },
    refetchOnWindowFocus: true,
  });

  if (isLoading) {
    return <div className="text-xs text-slate-500">loading…</div>;
  }
  if (error || !data) {
    return (
      <div className="text-xs text-slate-500">
        {fallbackTotal} repos · progress unavailable
      </div>
    );
  }

  const { total, indexed, queued, running, success, failed, in_progress, last_run_at, last_synced_at, recent_failures } = data;
  const denom = total || 1;
  const pctIndexed = Math.round((indexed / denom) * 100);
  const pctFailed = Math.round((failed / denom) * 100);
  const pctRunning = Math.round((running / denom) * 100);

  return (
    <div className="space-y-1.5">
      {/* Segmented bar. Order matters — indexed (green) | running (blue,
          pulsing) | failed (red) | remainder (slate). */}
      <div className="flex h-2 w-full overflow-hidden rounded bg-slate-800" title={`${indexed}/${total} indexed`}>
        {indexed > 0 && (
          <div className="h-full bg-emerald-500" style={{ width: `${pctIndexed}%` }} />
        )}
        {running > 0 && (
          <div
            className="h-full animate-pulse bg-sky-500"
            style={{ width: `${Math.max(2, pctRunning)}%` }}
          />
        )}
        {failed > 0 && (
          <div className="h-full bg-rose-500" style={{ width: `${pctFailed}%` }} />
        )}
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
        <span className="font-mono text-emerald-300">
          {indexed.toLocaleString()} / {total.toLocaleString()} indexed
        </span>
        {running > 0 && (
          <span className="font-mono text-sky-300">⟳ {running} running</span>
        )}
        {queued > 0 && (
          <span className="font-mono text-slate-300">{queued} queued</span>
        )}
        {success > 0 && success !== indexed && (
          <span className="font-mono text-slate-400">{success} succeeded</span>
        )}
        {failed > 0 && (
          <span className="font-mono text-rose-300">{failed} failed</span>
        )}
      </div>
      <div className="text-[11px] text-slate-500">
        {in_progress ? (
          <span className="text-sky-300">sync in progress —</span>
        ) : (
          <span>idle —</span>
        )}{" "}
        last sync {fmtTs(last_synced_at)}
        {last_run_at && last_run_at !== last_synced_at && (
          <>
            {" · "}last ingest {fmtTs(last_run_at)}
          </>
        )}
      </div>
      {recent_failures && recent_failures.length > 0 && (
        <details className="mt-1 rounded border border-rose-900/50 bg-rose-950/20 px-2 py-1 text-[11px] text-rose-200">
          <summary className="cursor-pointer text-rose-300">
            {failed} failed — see {recent_failures.length === 1 ? "the reason" : "sample reasons"}
          </summary>
          <ul className="mt-1 space-y-1">
            {recent_failures.map((f) => (
              <li key={f.repo_id} className="break-words">
                <span className="font-mono text-rose-300">{f.repo_id}</span>
                <span className="ml-1 text-rose-200/80">— {f.error || "(no error message recorded)"}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

// Render a timestamp as "2 min ago · 14:32:11" so the user has both relative
// (at-a-glance) and absolute (for cross-referencing logs) context. Re-renders
// every 30 s so the "ago" stays fresh without an extra query.
function fmtTs(iso: string | null | undefined): string {
  if (!iso) return "never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const diff = Date.now() - d.getTime();
  const ago = relative(diff);
  // Local time, second precision.
  const hh = d.getHours().toString().padStart(2, "0");
  const mm = d.getMinutes().toString().padStart(2, "0");
  const ss = d.getSeconds().toString().padStart(2, "0");
  return `${ago} · ${hh}:${mm}:${ss}`;
}

function relative(ms: number): string {
  if (ms < 0) return "just now";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

