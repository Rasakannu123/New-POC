export type Bucket = "input" | "output" | "skip" | "review";

export interface InputFile {
  name: string;
  size: number;
}

export interface PageEntry {
  kind: "page";
  name: string;
  image: string;
  record: PageRecord;
}

export interface DocumentRecord extends PageRecord {
  file?: string;
  pages?: number[];
  page_count?: number;
  models_used?: string[];
  cost?: {
    totals: ModelCostBucket;
    by_model: Record<string, ModelCostBucket>;
  };
}

export interface DocumentEntry {
  kind: "document";
  name: string;
  pdf: string;
  record: DocumentRecord;
}

export type BucketItem = PageEntry | DocumentEntry;

export interface PageRecord {
  document?: string;
  page?: number;
  image_file?: string;
  quality_score?: number;
  quality_tier?: string;
  model_used?: string;
  extracted_fields?: Record<string, unknown>;
  field_confidence_scores?: Record<string, number>;
  confidence_score?: number;
  extraction_success?: boolean;
  processing_time_seconds?: number;
  page_skipped?: boolean;
  skip_reason?: string;
  split_reply?: string;
  manual_review?: boolean;
  split_reason?: string;
  error?: string;
}

export interface Template {
  extracted_fields: Record<string, string>;
  no_need_page: Record<string, string>;
  "multiple-docs"?: {
    "same-words-every-pages": Record<string, string>;
  };
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export async function listBucket(
  bucket: Bucket,
): Promise<{ items: InputFile[] | BucketItem[] }> {
  return request(`/api/buckets/${bucket}`);
}

export function imageUrl(bucket: Bucket, image: string): string {
  return `/api/image/${bucket}/${encodeURIComponent(image)}`;
}

export function pdfUrl(bucket: Bucket, pdf: string): string {
  return `/api/pdf/${bucket}/${pdf.split("/").map(encodeURIComponent).join("/")}`;
}

export async function uploadFiles(files: File[]): Promise<{ saved: string[] }> {
  const form = new FormData();
  for (const file of files) {
    form.append("files", file);
  }
  return request("/api/upload", { method: "POST", body: form });
}

export async function getTemplate(): Promise<Template> {
  return request("/api/template");
}

export async function saveTemplate(template: Template): Promise<Template> {
  return request("/api/template", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(template),
  });
}

export interface ProcessStatus {
  running: boolean;
  last_exit_code: number | null;
  error: string | null;
  finished_at: number | null;
  runs?: {
    run_id: string;
    document: string;
    status: string;
    started_at: string;
  }[];
}

export async function startProcess(): Promise<{ started: boolean }> {
  return request("/api/process", { method: "POST" });
}

export async function getProcessStatus(): Promise<ProcessStatus> {
  return request("/api/process/status");
}

export interface ModelCostBucket {
  input_tokens: number;
  output_tokens: number;
  input_cost: number;
  output_cost: number;
  total_cost: number;
  input_rate?: number;
  output_rate?: number;
}

export interface CostSummary {
  totals: ModelCostBucket;
  by_model: Record<string, ModelCostBucket>;
  cost_blocks_scanned: number;
}

export async function deleteInputFile(name: string): Promise<void> {
  await request(`/api/input/${encodeURIComponent(name)}`, { method: "DELETE" });
}

export async function deleteDocument(bucket: Bucket, stem: string): Promise<void> {
  await request(`/api/document/${bucket}/${encodeURIComponent(stem)}`, {
    method: "DELETE",
  });
}

export async function deletePage(bucket: Bucket, name: string): Promise<void> {
  await request(`/api/page/${bucket}/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
}

export async function clearBucket(bucket: Bucket): Promise<{ removed: number }> {
  return request(`/api/clear/${bucket}`, { method: "DELETE" });
}

export async function getCosts(): Promise<CostSummary> {
  return request("/api/costs");
}

export function formatUsd(value: number): string {
  if (value === 0) return "$0";
  if (value < 0.01) return `$${value.toFixed(6)}`;
  if (value < 1) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

export function formatTokens(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

export async function checkHealth(): Promise<boolean> {
  try {
    await request<{ status: string }>("/api/health");
    return true;
  } catch {
    return false;
  }
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function tierLabel(tier: string | undefined): string {
  switch (tier) {
    case "clear":
      return "Clear";
    case "blurry":
      return "Blurry";
    case "very_blurry":
      return "Very blurry";
    default:
      return "Unknown";
  }
}
