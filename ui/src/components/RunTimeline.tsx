import { useState } from "react";
import {
  CaretDown,
  CaretRight,
  CheckCircle,
  Spinner,
  XCircle,
} from "@phosphor-icons/react";
import type { NodeTrace } from "../lib/runs";
import { runStatusLabel } from "../lib/runs";

function formatTime(value: string): string {
  if (!value) return "--:--:--";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
}

export function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    running:
      "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
    completed:
      "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
    failed: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
  };
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
        styles[status] ?? "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400"
      }`}
    >
      {runStatusLabel(status)}
    </span>
  );
}

function JsonPanel({ label, value }: { label: string; value: unknown }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="overflow-hidden rounded-lg border border-zinc-200 dark:border-zinc-800">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-zinc-500 transition-colors hover:bg-zinc-50 dark:text-zinc-400 dark:hover:bg-zinc-800"
      >
        {open ? <CaretDown size={12} /> : <CaretRight size={12} />}
        {label}
      </button>
      {open && (
        <pre className="max-h-72 overflow-auto border-t border-zinc-200 bg-zinc-50 p-3 text-xs leading-relaxed text-zinc-700 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300">
          {JSON.stringify(value, null, 2)}
        </pre>
      )}
    </div>
  );
}

function TraceCard({ trace }: { trace: NodeTrace }) {
  const failed = trace.status !== "ok";
  return (
    <li className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex items-center gap-3">
        {failed ? (
          <XCircle size={18} weight="fill" className="text-rose-500" />
        ) : (
          <CheckCircle size={18} weight="fill" className="text-emerald-500" />
        )}
        <span className="text-sm font-semibold">{trace.node}</span>
        <span className="rounded-full bg-zinc-100 px-2 py-0.5 font-mono text-[11px] text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
          step {trace.seq}
        </span>
        <span className="ml-auto font-mono text-xs text-zinc-400">
          {formatTime(trace.started_at)} → {formatTime(trace.ended_at)} ·{" "}
          {trace.duration_s}s
        </span>
      </div>
      {failed && trace.error && (
        <p className="mt-2 text-xs text-rose-600 dark:text-rose-400">
          {trace.error}
        </p>
      )}
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <JsonPanel label="Input" value={trace.input} />
        <JsonPanel label="Output" value={trace.output} />
      </div>
    </li>
  );
}

export default function RunTimeline({
  trace,
  pendingNode,
}: {
  trace: NodeTrace[];
  pendingNode?: string | null;
}) {
  return (
    <ol className="space-y-3">
      {trace.map((item) => (
        <TraceCard key={`${item.seq}-${item.node}`} trace={item} />
      ))}
      {pendingNode && (
        <li className="flex items-center gap-3 rounded-xl border border-dashed border-zinc-300 px-4 py-3 text-sm text-zinc-500 dark:border-zinc-700 dark:text-zinc-400">
          <Spinner size={16} className="animate-spin" />
          <span className="font-medium">{pendingNode}</span> is running
        </li>
      )}
    </ol>
  );
}

export function RunNodeChips({
  trace,
  pendingNode,
}: {
  trace: NodeTrace[];
  pendingNode?: string | null;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {trace.map((item) => (
        <span
          key={`${item.seq}-${item.node}`}
          title={`${item.node} · ${item.duration_s}s · ${item.status}`}
          className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
            item.status === "ok"
              ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
              : "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300"
          }`}
        >
          {item.status === "ok" ? "✓" : "✗"} {item.node}
        </span>
      ))}
      {pendingNode && (
        <span className="flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-700 dark:bg-amber-950 dark:text-amber-300">
          <Spinner size={11} className="animate-spin" />
          {pendingNode}
        </span>
      )}
    </div>
  );
}
