"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { Navbar } from "@/components/Navbar";
import { TokenGate } from "@/components/TokenGate";
import { Spinner } from "@/components/Spinner";
import { api } from "@/lib/api";

export default function ReposPage() {
  return (
    <TokenGate>
      <Navbar />
      <main className="mx-auto max-w-6xl px-5 py-8">
        <h1 className="mb-4 text-lg font-semibold">Repositories</h1>
        <RegisterForm />
        <RepoTable />
      </main>
    </TokenGate>
  );
}

function RegisterForm() {
  const qc = useQueryClient();
  const [id, setId] = useState("");
  const [url, setUrl] = useState("");
  const [branch, setBranch] = useState("main");
  const [error, setError] = useState<string | null>(null);

  // The API requires the repo id to be a lowercase slug ([a-z0-9][a-z0-9-_]{0,62}).
  // Slugify what the user typed so "Policy Service" becomes "policy-service" before
  // we send it. Same rules as the server-side render_slug() in ckg/services/sources.py.
  const slug = slugify(id);

  const mut = useMutation({
    mutationFn: () => api.registerRepo(slug, url, branch),
    onSuccess: () => {
      setId("");
      setUrl("");
      setBranch("main");
      setError(null);
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
      className="mb-6 rounded-lg border border-slate-800 bg-slate-900 p-4"
    >
      <div className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_2fr_1fr_auto]">
        <input
          placeholder="name (e.g. Policy Service)"
          value={id}
          onChange={(e) => setId(e.target.value)}
          className="rounded border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-sm"
          required
        />
        <input
          placeholder="git URL or file:///abs/path"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          className="rounded border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-sm"
          required
        />
        <input
          placeholder="branch"
          value={branch}
          onChange={(e) => setBranch(e.target.value)}
          className="rounded border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-sm"
        />
        <button
          type="submit"
          disabled={mut.isPending || !slug || !url}
          className="rounded bg-violet-500 px-4 py-2 text-sm font-medium text-violet-50 disabled:opacity-50 hover:bg-violet-400"
        >
          {mut.isPending ? "Registering…" : "Register"}
        </button>
      </div>
      {id && (
        <p className="mt-2 text-xs text-slate-400">
          will be registered as{" "}
          <code className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-violet-300">
            {slug || "(invalid — start with a letter or digit)"}
          </code>
        </p>
      )}
      {error && (
        <div className="mt-3 rounded border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-300">
          {error}
        </div>
      )}
    </form>
  );
}

// Mirror of the server-side slugifier in ckg/services/sources.py::render_slug.
// Lowercase, replace non [a-z0-9-_] with `-`, collapse runs, trim leading
// non-alphanumerics, cap at 63 chars (matches the API's regex).
function slugify(raw: string): string {
  if (!raw) return "";
  let s = raw.toLowerCase().replace(/[^a-z0-9\-_]+/g, "-");
  s = s.replace(/-+/g, "-").replace(/^[-_]+|[-_]+$/g, "");
  // The API requires the FIRST char to be [a-z0-9]; strip leading non-alnum just in case.
  s = s.replace(/^[^a-z0-9]+/, "");
  return s.slice(0, 63);
}

type IngestStatus =
  | { kind: "idle" }
  | { kind: "queueing"; mode: "full" | "incremental" }
  | { kind: "queued"; runId: number; mode: "full" | "incremental" }
  | { kind: "error"; message: string };

function RepoTable() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ["repos"], queryFn: api.repos });

  // Per-row ingest status — `useMutation` is shared across the table, but we
  // want each row to show its OWN spinner / queued / error state.
  const [statuses, setStatuses] = useState<Record<string, IngestStatus>>({});

  function setStatus(id: string, s: IngestStatus) {
    setStatuses((m) => ({ ...m, [id]: s }));
  }

  async function fireIngest(id: string, mode: "full" | "incremental") {
    setStatus(id, { kind: "queueing", mode });
    try {
      const run = await api.ingest(id, mode);
      setStatus(id, { kind: "queued", runId: run.id, mode });
      qc.invalidateQueries({ queryKey: ["repos"] });
      qc.invalidateQueries({ queryKey: ["runs", id] });
      // Clear the "queued" badge after 5s — the user can hop to the repo
      // detail page to watch progress live.
      setTimeout(() => {
        setStatuses((m) => {
          const cur = m[id];
          if (cur?.kind === "queued" && cur.runId === run.id) {
            return { ...m, [id]: { kind: "idle" } };
          }
          return m;
        });
      }, 5000);
    } catch (err) {
      setStatus(id, { kind: "error", message: (err as Error).message });
    }
  }

  if (isLoading) return <Spinner />;
  if (error) return <p className="text-red-300">{(error as Error).message}</p>;
  if (!data?.length) return <p className="text-slate-400">No repositories yet.</p>;

  return (
    <div className="overflow-hidden rounded-lg border border-slate-800">
      <table className="w-full text-sm">
        <thead className="bg-slate-900 text-left text-xs uppercase tracking-wider text-slate-400">
          <tr>
            <th className="px-4 py-2">id</th>
            <th className="px-4 py-2">url</th>
            <th className="px-4 py-2">last indexed</th>
            <th className="px-4 py-2 text-right">actions</th>
          </tr>
        </thead>
        <tbody>
          {data.map((r) => {
            const s = statuses[r.id] ?? { kind: "idle" };
            const busy = s.kind === "queueing";
            return (
              <tr key={r.id} className="border-t border-slate-800">
                <td className="px-4 py-2 font-mono align-top">
                  <Link
                    href={`/repos/${encodeURIComponent(r.id)}`}
                    className="text-violet-300 hover:underline"
                  >
                    {r.id}
                  </Link>
                </td>
                <td className="px-4 py-2 text-slate-400 align-top">{r.url}</td>
                <td className="px-4 py-2 text-slate-400 align-top">
                  {r.last_indexed_at ?? "—"}
                </td>
                <td className="px-4 py-2 text-right align-top">
                  <button
                    onClick={() => fireIngest(r.id, "incremental")}
                    disabled={busy}
                    className="mr-2 rounded border border-slate-700 px-2 py-1 text-xs disabled:opacity-50 hover:bg-slate-800"
                  >
                    {busy && s.mode === "incremental" ? "queuing…" : "ingest Δ"}
                  </button>
                  <button
                    onClick={() => fireIngest(r.id, "full")}
                    disabled={busy}
                    className="rounded border border-slate-700 px-2 py-1 text-xs disabled:opacity-50 hover:bg-slate-800"
                  >
                    {busy && s.mode === "full" ? "queuing…" : "full reparse"}
                  </button>
                  {s.kind === "queued" && (
                    <div className="mt-1 text-xs text-emerald-300">
                      ✓ queued ({s.mode}, run #{s.runId}) —{" "}
                      <Link
                        href={`/repos/${encodeURIComponent(r.id)}`}
                        className="underline hover:text-emerald-200"
                      >
                        watch progress
                      </Link>
                    </div>
                  )}
                  {s.kind === "error" && (
                    <div className="mt-1 text-xs text-red-300" title={s.message}>
                      ✗ {s.message.slice(0, 80)}
                    </div>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
