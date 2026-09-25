import { useCallback, useEffect, useState, Fragment } from "react";
import {
  ArrowsClockwise,
  FlowArrow,
  ListNumbers,
  WarningCircle,
} from "@phosphor-icons/react";
import RunTimeline, { StatusBadge } from "../components/RunTimeline";
import ConfirmDialog from "../components/ConfirmDialog";
import { useRunStream } from "../lib/useRunStream";
import { formatUsd } from "../lib/api";
import type { CheckpointStep, RunRecord } from "../lib/runs";
import { clearRuns, getRun, getRunCheckpoints, listRuns } from "../lib/runs";

function formatTime(value: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
}

function CheckpointTable({ steps }: { steps: CheckpointStep[] }) {
  const [openStep, setOpenStep] = useState<number | null>(null);
  return (
    <div className="overflow-hidden rounded-xl border border-zinc-200 dark:border-zinc-800">
      <table className="w-full text-left text-sm">
        <thead className="bg-zinc-50 text-xs uppercase tracking-wide text-zinc-400 dark:bg-zinc-900 dark:text-zinc-500">
          <tr>
            <th className="px-4 py-2.5">Step</th>
            <th className="px-4 py-2.5">Checkpoint</th>
            <th className="px-4 py-2.5">Node</th>
            <th className="px-4 py-2.5">Next</th>
            <th className="px-4 py-2.5">Wrote</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {steps.map((step) => (
            <Fragment key={step.step}>
              <tr
                onClick={() =>
                  setOpenStep((prev) => (prev === step.step ? null : step.step))
                }
                className="cursor-pointer bg-white hover:bg-zinc-50 dark:bg-zinc-900 dark:hover:bg-zinc-800"
              >
                <td className="px-4 py-2.5 font-mono text-xs">{step.step}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-zinc-400">
                  {(step.checkpoint_id ?? "").slice(0, 8) || "-"}
                </td>
                <td className="px-4 py-2.5 font-medium">{step.node || "-"}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-zinc-400">
                  {step.next.length ? step.next.join(", ") : "END"}
                </td>
                <td className="px-4 py-2.5 font-mono text-xs text-zinc-400">
                  {Object.values(step.writes)
                    .flat()
                    .join(", ")}
                </td>
              </tr>
              {openStep === step.step && (
                <tr key={`${step.step}-values`}>
                  <td colSpan={5} className="bg-zinc-50 px-4 py-3 dark:bg-zinc-950">
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-400">
                      State at this checkpoint
                    </p>
                    <pre className="max-h-80 overflow-auto rounded-lg border border-zinc-200 bg-white p-3 text-xs leading-relaxed text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
                      {JSON.stringify(step.values, null, 2)}
                    </pre>
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function PipelinePage() {
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [record, setRecord] = useState<RunRecord | null>(null);
  const [checkpoints, setCheckpoints] = useState<CheckpointStep[] | null>(null);
  const [tab, setTab] = useState<"nodes" | "checkpoints">("nodes");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [clearOpen, setClearOpen] = useState(false);
  const [clearBusy, setClearBusy] = useState(false);

  const loadRuns = useCallback(() => {
    listRuns()
      .then((data) => {
        setRuns(data.runs);
        setSelectedId((prev) => prev ?? data.runs[0]?.run_id ?? null);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(loadRuns, [loadRuns]);

  useEffect(() => {
    setRecord(null);
    setCheckpoints(null);
    setTab("nodes");
    if (!selectedId) return;
    getRun(selectedId)
      .then(setRecord)
      .catch((err: Error) => setError(err.message));
  }, [selectedId]);

  const running = record?.status === "running";
  const stream = useRunStream(running ? selectedId : null);

  useEffect(() => {
    if (!running) return;
    const interval = setInterval(() => {
      loadRuns();
      if (selectedId) {
        getRun(selectedId)
          .then(setRecord)
          .catch(() => undefined);
      }
    }, 4000);
    return () => clearInterval(interval);
  }, [running, selectedId, loadRuns]);

  useEffect(() => {
    if (!stream.ended || !selectedId) return;
    getRun(selectedId)
      .then(setRecord)
      .catch(() => undefined);
    loadRuns();
  }, [stream.ended, selectedId, loadRuns]);

  const trace =
    record && running && stream.trace.length > 0 ? stream.trace : record?.trace ?? [];

  const loadCheckpoints = () => {
    if (!selectedId) return;
    getRunCheckpoints(selectedId)
      .then((data) => setCheckpoints(data.checkpoints))
      .catch((err: Error) => setError(err.message));
  };

  return (
    <div>
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">Pipeline</h1>
        <p className="mt-1 max-w-[65ch] text-sm text-zinc-500 dark:text-zinc-400">
          Every document runs through the LangGraph workflow node by node. Each
          node is checkpointed and shows its start, input, output and end.
        </p>
      </header>

      {error && (
        <div className="mb-6 flex items-center gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
          <WarningCircle size={20} weight="duotone" />
          {error}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
        <aside className="h-fit rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
          <div className="flex items-center justify-between px-4 py-3">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
              Runs
            </h2>
            <div className="flex items-center gap-1">
              <button
                onClick={loadRuns}
                aria-label="Refresh runs"
                className="rounded-lg p-1.5 text-zinc-400 transition-colors hover:bg-zinc-100 hover:text-zinc-600 dark:hover:bg-zinc-800"
              >
                <ArrowsClockwise size={14} />
              </button>
              {runs.length > 0 && (
                <button
                  onClick={() => setClearOpen(true)}
                  disabled={
                    clearBusy ||
                    runs.some((run) => run.status === "running")
                  }
                  className="rounded-lg px-2.5 py-1.5 text-xs font-medium text-zinc-500 transition-colors hover:bg-rose-50 hover:text-rose-600 disabled:cursor-not-allowed disabled:opacity-40 dark:text-zinc-400 dark:hover:bg-rose-950 dark:hover:text-rose-400"
                >
                  Clear
                </button>
              )}
            </div>
          </div>
          {loading ? (
            <ul className="space-y-2 p-3">
              {[0, 1].map((i) => (
                <li
                  key={i}
                  className="h-12 animate-pulse rounded-lg bg-zinc-200 dark:bg-zinc-800"
                />
              ))}
            </ul>
          ) : runs.length === 0 ? (
            <p className="px-4 pb-4 text-sm text-zinc-500 dark:text-zinc-400">
              No runs yet. Process a document first.
            </p>
          ) : (
            <ul className="space-y-1 p-2">
              {runs.map((run) => (
                <li key={run.run_id}>
                  <button
                    onClick={() => setSelectedId(run.run_id)}
                    className={`w-full rounded-lg px-3 py-2.5 text-left transition-colors ${
                      selectedId === run.run_id
                        ? "bg-emerald-50 dark:bg-emerald-950"
                        : "hover:bg-zinc-100 dark:hover:bg-zinc-800"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium">
                        {run.document}
                      </span>
                      <span className="ml-auto">
                        <StatusBadge status={run.status} />
                      </span>
                    </div>
                    <p className="mt-0.5 font-mono text-[11px] text-zinc-400">
                      {run.run_id}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <section>
          {!record ? (
            <p className="rounded-xl border border-dashed border-zinc-300 py-16 text-center text-sm text-zinc-500 dark:border-zinc-700 dark:text-zinc-400">
              {loading ? "Loading..." : "Select a run to inspect its nodes."}
            </p>
          ) : (
            <div className="space-y-5">
              <div className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
                <div className="flex items-center gap-3">
                  <FlowArrow size={20} weight="duotone" className="text-emerald-600" />
                  <h2 className="text-lg font-semibold tracking-tight">
                    {record.document}
                  </h2>
                  <StatusBadge status={record.status} />
                </div>
                <p className="mt-1 font-mono text-xs text-zinc-400">
                  {record.run_id} · {record.trace.length} node
                  {record.trace.length === 1 ? "" : "s"} · started{" "}
                  {formatTime(record.started_at)} · ended{" "}
                  {formatTime(record.finished_at)}
                </p>
                {record.error && (
                  <p className="mt-2 text-xs text-rose-600 dark:text-rose-400">
                    {record.error}
                  </p>
                )}
                {record.totals && (
                  <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-6">
                    {[
                      ["pages", record.totals.pages],
                      ["extracted", record.totals.extracted],
                      ["skipped", record.totals.skipped],
                      ["review", record.totals.manual_review],
                      ["documents", record.totals.documents],
                      ["cost", formatUsd(record.cost?.totals.total_cost ?? 0)],
                    ].map(([label, value]) => (
                      <div
                        key={String(label)}
                        className="rounded-lg bg-zinc-50 px-3 py-2 dark:bg-zinc-800"
                      >
                        <p className="text-[11px] uppercase tracking-wide text-zinc-400">
                          {label}
                        </p>
                        <p className="mt-0.5 text-sm font-semibold">{value}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex gap-2">
                <button
                  onClick={() => setTab("nodes")}
                  className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                    tab === "nodes"
                      ? "bg-emerald-600 text-white"
                      : "border border-zinc-300 text-zinc-600 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
                  }`}
                >
                  Nodes
                </button>
                <button
                  onClick={() => {
                    setTab("checkpoints");
                    if (checkpoints === null) loadCheckpoints();
                  }}
                  className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                    tab === "checkpoints"
                      ? "bg-emerald-600 text-white"
                      : "border border-zinc-300 text-zinc-600 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
                  }`}
                >
                  <ListNumbers size={14} />
                  Checkpoints
                </button>
              </div>

              {tab === "nodes" ? (
                <RunTimeline trace={trace} pendingNode={stream.pendingNode} />
              ) : checkpoints === null ? (
                <p className="rounded-xl border border-dashed border-zinc-300 py-10 text-center text-sm text-zinc-500 dark:border-zinc-700 dark:text-zinc-400">
                  Loading checkpoints...
                </p>
              ) : checkpoints.length === 0 ? (
                <p className="rounded-xl border border-dashed border-zinc-300 py-10 text-center text-sm text-zinc-500 dark:border-zinc-700 dark:text-zinc-400">
                  No checkpoint history found for this run.
                </p>
              ) : (
                <CheckpointTable steps={checkpoints} />
              )}
            </div>
          )}
        </section>
      </div>

      <ConfirmDialog
        open={clearOpen}
        title="Clear pipeline runs"
        message={`All ${runs.length} run(s) and their checkpoint history will be permanently deleted. This cannot be undone.`}
        confirmLabel="Clear"
        busy={clearBusy}
        onCancel={() => {
          if (!clearBusy) setClearOpen(false);
        }}
        onConfirm={async () => {
          setClearBusy(true);
          try {
            await clearRuns();
            setClearOpen(false);
            setSelectedId(null);
            setRecord(null);
            setCheckpoints(null);
            loadRuns();
          } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
          } finally {
            setClearBusy(false);
          }
        }}
      />
    </div>
  );
}
