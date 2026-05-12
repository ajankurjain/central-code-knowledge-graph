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

export type CountByKey = { key: string; value: number };

export type IntegrationsSummary = {
  sources: {
    total: number;
    by_kind: CountByKey[];
    with_webhook: number;
    with_schedule: number;
    last_synced_at: string | null;
  };
  tokens: {
    total: number;
    active: number;
    revoked: number;
    used_in_last_24h: number;
    most_recent_use: string | null;
  };
  repos: {
    total: number;
    indexed: number;
    by_language: CountByKey[];
    most_recent_index: string | null;
  };
  ingests: {
    last_24h_total: number;
    last_24h_success: number;
    last_24h_failed: number;
    success_rate_pct: number;
    queue_depth: number;
    recent_failures: { repo_id: string; error: string; finished_at: string | null }[];
  };
};

export type TokenUsageRow = {
  token_id: number | null;
  token_name: string;
  calls_24h: number;
  last_call_at: string | null;
  last_status: number | null;
};

export type EndpointUsageRow = {
  route: string;
  method: string;
  calls_24h: number;
  p95_duration_ms: number;
  error_rate_pct: number;
};

export type ApiCallRow = {
  ts: string;
  token_name: string;
  method: string;
  route: string;
  status: number;
  duration_ms: number;
};

export type UsageSummary = {
  window_hours: number;
  total_calls: number;
  calls_per_hour: number;
  distinct_tokens: number;
  error_rate_pct: number;
  top_tokens: TokenUsageRow[];
  top_endpoints: EndpointUsageRow[];
  recent: ApiCallRow[];
};

export type SavingsModelOption = {
  id: string;
  label: string;
  input_per_million_usd: number;
  output_per_million_usd: number;
  blended_per_million_usd: number;
};

export type SavingsRouteRow = {
  route: string;
  integration: "mcp" | "graphql" | "rest" | "other" | string;
  calls: number;
  tokens_saved: number;
  dollars_saved: number;
};

export type SavingsTokenRow = {
  token_id: number | null;
  token_name: string;
  calls: number;
  tokens_saved: number;
  dollars_saved: number;
};

export type SavingsBucketRow = {
  integration: string;
  calls: number;
  tokens_saved: number;
  dollars_saved: number;
};

export type SavingsDayPoint = {
  day: string; // YYYY-MM-DD
  tokens_saved: number;
  dollars_saved: number;
};

export type SavingsSummary = {
  model: SavingsModelOption;
  window_hours: number;
  total_calls: number;
  total_calls_saving: number;
  tokens_saved: number;
  dollars_saved: number;
  lifetime_tokens_saved: number;
  lifetime_dollars_saved: number;
  by_route: SavingsRouteRow[];
  by_token: SavingsTokenRow[];
  by_integration: SavingsBucketRow[];
  daily: SavingsDayPoint[];
  available_models: SavingsModelOption[];
};

export type ReadyzResp = {
  ready: boolean;
  checks: Record<string, boolean>;
  version: string;
};

export type TokenInfo = {
  id: number;
  name: string;
  scopes: string[];
  created_at: string;
  last_used_at: string | null;
  revoked: boolean;
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
