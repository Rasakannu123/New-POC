import { RunNodeChips, StatusBadge } from "./RunTimeline";
import { useRunStream } from "../lib/useRunStream";
import type { RunSummary } from "../lib/runs";

function ActiveRunRow({ run }: { run: RunSummary }) {
  const stream = useRunStream(run.run_id);
  const status = stream.ended ? stream.status ?? run.status : run.status;
  return (
    <li className="rounded-xl border border-zinc-200 bg-white px-4 py-3 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex items-center gap-3">
        <span className="truncate text-sm font-medium">{run.document}</span>
        <StatusBadge status={status} />
        <span className="ml-auto font-mono text-[11px] text-zinc-400">
          {run.run_id}
        </span>
      </div>
      <div className="mt-2">
        <RunNodeChips trace={stream.trace} pendingNode={stream.pendingNode} />
      </div>
    </li>
  );
}

export default function ActiveRunsPanel({ runs }: { runs: RunSummary[] }) {
  return (
    <section className="mt-8">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
        Live pipeline runs
      </h2>
      <ul className="space-y-2">
        {runs.map((run) => (
          <ActiveRunRow key={run.run_id} run={run} />
        ))}
      </ul>
    </section>
  );
}
