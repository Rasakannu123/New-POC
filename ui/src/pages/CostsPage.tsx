import { useCallback, useEffect, useState } from "react";
import { WarningCircle, Coins } from "@phosphor-icons/react";
import {
  type CostSummary,
  formatTokens,
  formatUsd,
  getCosts,
} from "../lib/api";

export default function CostsPage() {
  const [summary, setSummary] = useState<CostSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    getCosts()
      .then(setSummary)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const models = summary ? Object.entries(summary.by_model) : [];

  return (
    <div>
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">Cost Tracker</h1>
        <p className="mt-1 max-w-[65ch] text-sm text-zinc-500 dark:text-zinc-400">
          Token usage and USD cost across every document, page, and model.
          Costs come from the token counts reported by each API response, priced
          per model from the configured rates.
        </p>
      </header>

      {loading ? (
        <div className="space-y-6">
          <div className="h-28 animate-pulse rounded-2xl bg-zinc-200 dark:bg-zinc-800" />
          <div className="h-64 animate-pulse rounded-2xl bg-zinc-200 dark:bg-zinc-800" />
        </div>
      ) : error ? (
        <div className="flex items-center gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
          <WarningCircle size={20} weight="duotone" />
          {error}
          <button
            onClick={load}
            className="ml-auto rounded-lg border border-rose-300 px-3 py-1.5 text-xs font-medium hover:bg-rose-100 dark:border-rose-800 dark:hover:bg-rose-900"
          >
            Retry
          </button>
        </div>
      ) : models.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-zinc-300 py-24 text-center dark:border-zinc-700">
          <Coins size={32} weight="duotone" className="text-zinc-400" />
          <h2 className="mt-4 text-base font-medium">No model usage recorded yet</h2>
          <p className="mt-1 max-w-[45ch] text-sm text-zinc-500 dark:text-zinc-400">
            Process a document on the Documents page - every extraction call
            will be priced and shown here.
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          <section className="grid gap-4 sm:grid-cols-3">
            <div className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                Total cost
              </p>
              <p className="mt-1 font-mono text-2xl font-semibold tracking-tight text-emerald-600 dark:text-emerald-400">
                {formatUsd(summary!.totals.total_cost)}
              </p>
            </div>
            <div className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                Input tokens
              </p>
              <p className="mt-1 font-mono text-2xl font-semibold tracking-tight">
                {formatTokens(summary!.totals.input_tokens)}
              </p>
              <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                {formatUsd(summary!.totals.input_cost)}
              </p>
            </div>
            <div className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                Output tokens
              </p>
              <p className="mt-1 font-mono text-2xl font-semibold tracking-tight">
                {formatTokens(summary!.totals.output_tokens)}
              </p>
              <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                {formatUsd(summary!.totals.output_cost)}
              </p>
            </div>
          </section>

          <section className="overflow-hidden rounded-2xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
            <div className="flex items-baseline justify-between border-b border-zinc-200 px-5 py-4 dark:border-zinc-800">
              <h2 className="text-sm font-semibold">Cost per model</h2>
              <span className="font-mono text-xs text-zinc-400">
                {summary!.cost_blocks_scanned} cost block
                {summary!.cost_blocks_scanned === 1 ? "" : "s"} scanned
              </span>
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-100 text-left text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-5 py-3 font-medium">Model</th>
                  <th className="px-5 py-3 text-right font-medium">Rate in / 1M</th>
                  <th className="px-5 py-3 text-right font-medium">Rate out / 1M</th>
                  <th className="px-5 py-3 text-right font-medium">Input tokens</th>
                  <th className="px-5 py-3 text-right font-medium">Output tokens</th>
                  <th className="px-5 py-3 text-right font-medium">Total cost</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                {models.map(([model, bucket]) => (
                  <tr key={model} className="transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/40">
                    <td className="px-5 py-3 font-mono text-xs">{model}</td>
                    <td className="px-5 py-3 text-right font-mono text-xs text-zinc-500 dark:text-zinc-400">
                      {bucket.input_rate !== undefined
                        ? `$${bucket.input_rate}/1M`
                        : "-"}
                    </td>
                    <td className="px-5 py-3 text-right font-mono text-xs text-zinc-500 dark:text-zinc-400">
                      {bucket.output_rate !== undefined
                        ? `$${bucket.output_rate}/1M`
                        : "-"}
                    </td>
                    <td className="px-5 py-3 text-right font-mono text-xs">
                      {formatTokens(bucket.input_tokens)}
                    </td>
                    <td className="px-5 py-3 text-right font-mono text-xs">
                      {formatTokens(bucket.output_tokens)}
                    </td>
                    <td className="px-5 py-3 text-right font-mono text-xs font-semibold">
                      {formatUsd(bucket.total_cost)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
      )}
    </div>
  );
}
