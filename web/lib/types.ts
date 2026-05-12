// Wire types — mirror the FastAPI response shapes for the bits we use.

export type Stats = {
  nodes: number;
  edges: number;
  repos: number;
  files: number;
};

export type Repo = {
  id: string;
  url: string;
  default_branch: string;
  languages: string[];
  last_indexed_at: string | null;
  last_indexed_sha: string | null;
  poll_interval_seconds?: number;
  source_id?: number | null;
  has_token?: boolean;
};

export type IngestRun = {
  id: number;
  repo_id: string;
  status: "queued" | "running" | "success" | "failed" | string;
  mode: "full" | "incremental" | string;
  started_at: string;
  finished_at: string | null;
  stats: Record<string, unknown> | null;
  error: string | null;
};

export type FunctionRef = {
  qn: string;
  path: string;
  line: number | null;
};

export type CallersResp = {
  target?: string;
  source?: string;
  depth: number;
  results: FunctionRef[];
};

export type SearchHit = {
  repo_id: string;
  qualified_name: string;
  path: string;
  line: number | null;
  kind?: string;
  score: number;
};

export type SearchResp = { query: string; results: SearchHit[] };

export type Source = {
  id: number;
  kind: string;
  name: string;
  url: string | null;
  include_private: boolean;
  include_forks: boolean;
  include_archived: boolean;
  slug_template: string;
  default_branch_override: string | null;
  last_synced_at: string | null;
  last_sync_stats: Record<string, unknown> | null;
  has_token: boolean;
  repos: number;
};

export type SourceRepo = {
  repo_id: string;
  full_name: string;
  default_branch: string;
  private: boolean;
  archived: boolean;
  fork: boolean;
};

export type SourceProgress = {
  source_id: number;
  total: number;
  indexed: number;
  queued: number;
  running: number;
  success: number;
  failed: number;
  unstarted: number;
  in_progress: boolean;
  last_run_at: string | null;
  last_synced_at: string | null;
  // Sample of latest-failed runs — newest first, capped at 5. Empty when
  // nothing is currently failed.
  recent_failures?: { repo_id: string; error: string; finished_at: string | null }[];
};

export type Cluster = {
  id: number;
  name: string;
  file_count: number;
  instability: number;
  cohesion: number;
  fan_in: number;
  fan_out: number;
  computed_at: string | null;
  files: string[];
};

export type ClusterEdge = {
  source: number;
  target: number;
  weight: number;
  cross_file_edges: number;
};

export type ArchitectureMap = {
  repo_id: string;
  clusters: Cluster[];
  edges: ClusterEdge[];
  // "calls+imports" (precise), "directory_fallback" (layout-only), or null
  // when the map has never been computed.
  edge_source?: "calls+imports" | "directory_fallback" | "no_files" | string | null;
};

export type Warning = {
  kind: string;
  severity: "high" | "medium" | "low" | string;
  target_kind: string;
  target_id: string;
  message: string;
  detail: Record<string, unknown> | null;
  computed_at: string | null;
};

export type FileOverview = {
  repo_id: string;
  path: string;
  language: string | null;
  size_bytes: number | null;
  classes: { name: string; qualified_name: string; start_line: number | null; end_line: number | null }[];
  functions: { name: string; qualified_name: string; start_line: number | null; end_line: number | null; is_async: boolean | null }[];
};
