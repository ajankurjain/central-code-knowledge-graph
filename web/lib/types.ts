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

export type FileOverview = {
  repo_id: string;
  path: string;
  language: string | null;
  size_bytes: number | null;
  classes: { name: string; qualified_name: string; start_line: number | null; end_line: number | null }[];
  functions: { name: string; qualified_name: string; start_line: number | null; end_line: number | null; is_async: boolean | null }[];
};
