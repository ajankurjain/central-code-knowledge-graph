// Typed API client. Reads the API base URL at build time (NEXT_PUBLIC_CKG_API)
// and the token at runtime from localStorage.

import { getToken } from "./auth";
import type {
  ArchitectureMap,
  CallersResp,
  FileOverview,
  IngestRun,
  Repo,
  SearchResp,
  Source,
  SourceRepo,
  Stats,
  Warning,
} from "./types";

const BASE = (process.env.NEXT_PUBLIC_CKG_API || "http://localhost:8080").replace(/\/+$/, "");

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  headers.set("accept", "application/json");
  if (token) headers.set("authorization", `Bearer ${token}`);
  if (init.body && !headers.has("content-type")) headers.set("content-type", "application/json");

  const r = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!r.ok) {
    const body = await r.text();
    throw new ApiError(r.status, body || r.statusText);
  }
  if (r.status === 204) return undefined as unknown as T;
  return (await r.json()) as T;
}

function qs(params: Record<string, string | number | undefined | null>): string {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    usp.append(k, String(v));
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}

export const api = {
  ready: () => req<{ ready: boolean; checks: Record<string, boolean>; version: string }>("/readyz"),

  stats: () => req<Stats>("/v1/graph/stats"),

  repos: () => req<Repo[]>("/v1/repos"),
  repo: (id: string) => req<Repo>(`/v1/repos/${encodeURIComponent(id)}`),
  ingest: (id: string, mode: "full" | "incremental" = "incremental") =>
    req<IngestRun>(`/v1/repos/${encodeURIComponent(id)}/ingest${qs({ mode })}`, { method: "POST" }),
  runs: (id: string) => req<IngestRun[]>(`/v1/repos/${encodeURIComponent(id)}/runs`),
  registerRepo: (id: string, url: string, branch = "main") =>
    req<Repo>("/v1/repos", {
      method: "POST",
      body: JSON.stringify({ id, url, default_branch: branch }),
    }),

  callersOf: (repoId: string, qn: string, depth = 1, limit = 100) =>
    req<CallersResp>(
      `/v1/graph/callers_of${qs({ repo_id: repoId, qualified_name: qn, depth, limit })}`,
    ),
  calleesOf: (repoId: string, qn: string, depth = 1, limit = 100) =>
    req<CallersResp>(
      `/v1/graph/callees_of${qs({ repo_id: repoId, qualified_name: qn, depth, limit })}`,
    ),
  blastRadius: (repoId: string, path: string, depth = 2, limit = 500) =>
    req<{ source: string; depth: number; affected_files: { path: string; language: string }[] }>(
      `/v1/graph/blast_radius${qs({ repo_id: repoId, path, depth, limit })}`,
    ),
  downstreamDependencies: (repoId: string, path: string, depth = 2, limit = 500) =>
    req<{ source: string; depth: number; dependency_files: { path: string; language: string }[] }>(
      `/v1/graph/downstream_dependencies${qs({ repo_id: repoId, path, depth, limit })}`,
    ),
  fileOverview: (repoId: string, path: string) =>
    req<FileOverview>(`/v1/graph/file${qs({ repo_id: repoId, path })}`),

  keyword: (q: string, repoId?: string, limit = 25) =>
    req<SearchResp>(`/v1/search/keyword${qs({ q, repo_id: repoId, limit })}`),
  semantic: (q: string, repoId?: string, limit = 10) =>
    req<SearchResp>(`/v1/search/semantic${qs({ q, repo_id: repoId, limit })}`),

  sources: () => req<Source[]>("/v1/sources"),
  source: (id: number) => req<Source>(`/v1/sources/${id}`),
  sourceRepos: (id: number) => req<SourceRepo[]>(`/v1/sources/${id}/repos`),
  createSource: (body: {
    url: string;
    token?: string;
    include_private?: boolean;
    include_forks?: boolean;
    include_archived?: boolean;
    default_branch_override?: string;
    slug_template?: string;
    sync_now?: boolean;
  }) =>
    req<Source>("/v1/sources", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  syncSource: (id: number) =>
    req<{ discovered: number; added: number; already: number; skipped: number; queued: number; errors: string[] }>(
      `/v1/sources/${id}/sync`,
      { method: "POST" },
    ),
  deleteSource: (id: number) =>
    req<{ deleted_source_id: number; repos_dropped: string[] }>(`/v1/sources/${id}`, { method: "DELETE" }),

  computeArchitecture: (repoId: string) =>
    req<{ status: string; repo_id: string }>(
      `/v1/repos/${encodeURIComponent(repoId)}/architecture`,
      { method: "POST" },
    ),
  architecture: (repoId: string) =>
    req<ArchitectureMap>(`/v1/repos/${encodeURIComponent(repoId)}/architecture`),
  architectureWarnings: (repoId: string, severity?: "high" | "medium" | "low") =>
    req<{ repo_id: string; warnings: Warning[] }>(
      `/v1/repos/${encodeURIComponent(repoId)}/architecture/warnings${qs({ severity })}`,
    ),
};

export { ApiError, BASE as API_BASE };
