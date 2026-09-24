import type { ModelCostBucket } from "./api";

export interface NodeTrace {
  node: string;
  seq: number;
  started_at: string;
  ended_at: string;
  duration_s: number;
  status: "ok" | "error";
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  error: string | null;
}

export interface RunTotals {
  pages: number;
  extracted: number;
  skipped: number;
  manual_review: number;
  documents: number;
}

export interface RunRecord {
  run_id: string;
  document: string;
  pdf_path: string;
  status: "running" | "completed" | "failed";
  started_at: string;
  started_ts?: number;
  finished_at: string | null;
  error: string | null;
  trace: NodeTrace[];
  page_count?: number;
  document_count?: number;
  skipped_count?: number;
  review_count?: number;
  files?: string[];
  totals?: RunTotals;
  cost?: {
    totals: ModelCostBucket;
    by_model: Record<string, ModelCostBucket>;
  };
}

export interface RunSummary {
  run_id: string;
  document: string;
  status: string;
  started_at: string;
}

export interface CheckpointStep {
  step: number;
  checkpoint_id?: string | null;
  node: string;
  next: string[];
  writes: Record<string, string[]>;
  values: Record<string, unknown>;
}

export interface RunEvent {
  type: "run_start" | "node_start" | "node" | "run_end";
  run_id: string;
  node?: string;
  trace?: NodeTrace;
  document?: string;
  started_at?: string;
  status?: string;
  error?: string | null;
  finished_at?: string | null;
}

async function requestJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export async function listRuns(): Promise<{ runs: RunRecord[] }> {
  return requestJson("/api/runs");
}

export async function getRun(runId: string): Promise<RunRecord> {
  return requestJson(`/api/runs/${encodeURIComponent(runId)}`);
}

export async function getRunCheckpoints(
  runId: string,
): Promise<{ checkpoints: CheckpointStep[] }> {
  return requestJson(`/api/runs/${encodeURIComponent(runId)}/checkpoints`);
}

export function runStreamUrl(runId: string): string {
  return `/api/runs/${encodeURIComponent(runId)}/stream`;
}

export function runStatusLabel(status: string | undefined): string {
  switch (status) {
    case "running":
      return "Running";
    case "completed":
      return "Completed";
    case "failed":
      return "Failed";
    default:
      return "Unknown";
  }
}
