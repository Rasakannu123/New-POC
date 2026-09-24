import { useCallback, useEffect, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import {
  ArrowLeft,
  WarningCircle,
  MagnifyingGlass,
  FilePdf,
  Trash,
} from "@phosphor-icons/react";
import ConfirmDialog from "./ConfirmDialog";
import {
  type Bucket,
  type BucketItem,
  type DocumentEntry,
  type PageEntry,
  clearBucket,
  deleteDocument,
  deletePage,
  formatTokens,
  formatUsd,
  imageUrl,
  listBucket,
  pdfUrl,
  tierLabel,
} from "../lib/api";

const META_KEYS: {
  key: keyof (PageEntry["record"] & DocumentEntry["record"]);
  label: string;
}[] = [
  { key: "document", label: "Document" },
  { key: "file", label: "File" },
  { key: "page", label: "Page" },
  { key: "page_count", label: "Page count" },
  { key: "quality_score", label: "Quality score" },
  { key: "quality_tier", label: "Quality tier" },
  { key: "model_used", label: "Model" },
  { key: "models_used", label: "Models" },
  { key: "confidence_score", label: "Overall confidence" },
  { key: "extraction_success", label: "Extraction success" },
  { key: "processing_time_seconds", label: "Processing time" },
  { key: "skip_reason", label: "Skip reason" },
  { key: "split_reply", label: "Split reply" },
  { key: "split_reason", label: "Split reason" },
  { key: "error", label: "Error" },
];

const TIER_STYLES: Record<string, string> = {
  clear: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  blurry: "bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  very_blurry: "bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
};

function tierClass(tier: string | undefined): string {
  return (
    TIER_STYLES[tier ?? ""] ??
    "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
  );
}

function ScoreBadge({ score }: { score: number | undefined }) {
  if (score === undefined) return null;
  return (
    <span className="rounded-md bg-zinc-900/80 px-2 py-1 font-mono text-xs text-white backdrop-blur-sm dark:bg-zinc-100/85 dark:text-zinc-900">
      q{Math.round(score)}
    </span>
  );
}

function rateLabel(rate: number | undefined): string {
  if (rate === undefined) return "mixed";
  return `$${rate}/1M`;
}

function CostSection({ record }: { record: DocumentEntry["record"] }) {
  const cost = record.cost;
  if (!cost) return null;
  const models = Object.entries(cost.by_model);
  const single = models.length === 1 ? models[0][1] : undefined;
  return (
    <section className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
        Cost
      </h3>
      <dl className="divide-y divide-zinc-100 dark:divide-zinc-800">
        <div className="flex items-baseline justify-between gap-4 py-2">
          <dt className="text-xs text-zinc-500 dark:text-zinc-400">Input</dt>
          <dd className="font-mono text-xs text-zinc-800 dark:text-zinc-200">
            {formatTokens(cost.totals.input_tokens)} x{" "}
            {rateLabel(single?.input_rate)} = {formatUsd(cost.totals.input_cost)}
          </dd>
        </div>
        <div className="flex items-baseline justify-between gap-4 py-2">
          <dt className="text-xs text-zinc-500 dark:text-zinc-400">Output</dt>
          <dd className="font-mono text-xs text-zinc-800 dark:text-zinc-200">
            {formatTokens(cost.totals.output_tokens)} x{" "}
            {rateLabel(single?.output_rate)} ={" "}
            {formatUsd(cost.totals.output_cost)}
          </dd>
        </div>
        <div className="flex items-baseline justify-between gap-4 py-2">
          <dt className="text-xs font-medium text-zinc-700 dark:text-zinc-200">
            Total
          </dt>
          <dd className="font-mono text-sm font-semibold text-emerald-600 dark:text-emerald-400">
            {formatUsd(cost.totals.total_cost)}
          </dd>
        </div>
        {models.length > 1 &&
          models.map(([model, bucket]) => (
            <div
              key={model}
              className="flex items-baseline justify-between gap-4 py-2"
            >
              <dt className="truncate font-mono text-[11px] text-zinc-400 dark:text-zinc-500">
                {model}
              </dt>
              <dd className="shrink-0 font-mono text-xs text-zinc-600 dark:text-zinc-300">
                {rateLabel(bucket.input_rate)} / {rateLabel(bucket.output_rate)}{" "}
                = {formatUsd(bucket.total_cost)}
              </dd>
            </div>
          ))}
      </dl>
    </section>
  );
}

function MetaTable({ record }: { record: DocumentEntry["record"] }) {
  const rows = META_KEYS.filter((meta) => record[meta.key] !== undefined);
  if (rows.length === 0) return null;
  return (
    <dl className="divide-y divide-zinc-100 dark:divide-zinc-800">
      {rows.map(({ key, label }) => {
        const value = record[key];
        return (
          <div key={key} className="flex items-baseline justify-between gap-4 py-2">
            <dt className="text-xs text-zinc-500 dark:text-zinc-400">{label}</dt>
            <dd className="max-w-[60%] truncate text-right font-mono text-xs text-zinc-800 dark:text-zinc-200">
              {Array.isArray(value) ? value.join(", ") : String(value)}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

function FieldList({ record }: { record: PageEntry["record"] }) {
  const fields = record.extracted_fields ?? {};
  const scores = record.field_confidence_scores ?? {};
  const names = Object.keys(fields);

  if (names.length === 0) {
    return (
      <p className="text-sm text-zinc-500 dark:text-zinc-400">
        No fields were extracted from this page.
      </p>
    );
  }

  return (
    <ul className="space-y-3">
      {names.map((name) => {
        const value = fields[name];
        const confidence = scores[name] ?? 0;
        return (
          <li key={name}>
            <div className="flex items-baseline justify-between gap-4">
              <span className="text-xs font-medium text-zinc-600 dark:text-zinc-300">
                {name}
              </span>
              <span className="font-mono text-xs text-zinc-500 dark:text-zinc-400">
                {confidence}%
              </span>
            </div>
            <p className="mt-0.5 font-mono text-sm text-zinc-900 dark:text-zinc-100">
              {value === null || value === undefined ? (
                <span className="italic text-zinc-400 dark:text-zinc-500">null</span>
              ) : (
                String(value)
              )}
            </p>
            <div className="mt-1.5 h-1 w-full rounded-full bg-zinc-100 dark:bg-zinc-800">
              <div
                className={`h-1 rounded-full ${confidence >= 60 ? "bg-emerald-500" : confidence > 0 ? "bg-amber-500" : "bg-zinc-300 dark:bg-zinc-700"}`}
                style={{ width: `${confidence}%` }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function CardSkeleton() {
  return (
    <div className="animate-pulse">
      <div className="aspect-[3/4] rounded-xl bg-zinc-200 dark:bg-zinc-800" />
      <div className="mt-3 h-3.5 w-2/3 rounded bg-zinc-200 dark:bg-zinc-800" />
      <div className="mt-2 h-3 w-1/3 rounded bg-zinc-200 dark:bg-zinc-800" />
    </div>
  );
}

interface PageBrowserProps {
  bucket: Bucket;
  title: string;
  description: string;
  emptyTitle: string;
  emptyHint: string;
}

export default function PageBrowser({
  bucket,
  title,
  description,
  emptyTitle,
  emptyHint,
}: PageBrowserProps) {
  const [items, setItems] = useState<BucketItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<BucketItem | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteAllOpen, setDeleteAllOpen] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const reduceMotion = useReducedMotion();

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    listBucket(bucket)
      .then((data) => setItems(data.items as BucketItem[]))
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [bucket]);

  useEffect(load, [load]);

  const handleDelete = async () => {
    if (!selected) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      if (selected.kind === "document") {
        await deleteDocument(bucket, selected.name.split("/")[0]);
      } else {
        await deletePage(bucket, selected.name);
      }
      setDeleteOpen(false);
      setSelected(null);
      load();
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeleteBusy(false);
    }
  };

  const handleDeleteAll = async () => {
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await clearBucket(bucket);
      setDeleteAllOpen(false);
      load();
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeleteBusy(false);
    }
  };

  const deleteTarget = selected
    ? selected.kind === "document"
      ? `This removes the whole document "${selected.name.split("/")[0]}" with all of its invoice PDFs and records.`
      : `This removes "${selected.name}" (image and record) from this folder.`
    : "";

  const header = (
    <header className="mb-8 flex items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-1 max-w-[65ch] text-sm text-zinc-500 dark:text-zinc-400">
          {description}
        </p>
      </div>
      {items.length > 0 && !loading && (
        <button
          onClick={() => {
            setDeleteError(null);
            setDeleteAllOpen(true);
          }}
          className="flex shrink-0 items-center gap-2 rounded-lg border border-zinc-300 px-3 py-2 text-xs font-medium text-zinc-600 transition-colors hover:border-rose-300 hover:bg-rose-50 hover:text-rose-700 active:scale-[0.98] dark:border-zinc-700 dark:text-zinc-300 dark:hover:border-rose-800 dark:hover:bg-rose-950 dark:hover:text-rose-400"
        >
          <Trash size={14} />
          Delete all
        </button>
      )}
    </header>
  );

  const deleteAllDialog = (
    <ConfirmDialog
      open={deleteAllOpen}
      title={`Delete all ${title.toLowerCase()}`}
      message={`All ${items.length} item(s) in this folder will be permanently deleted. This cannot be undone.`}
      confirmLabel="Delete all"
      busy={deleteBusy}
      onCancel={() => {
        if (!deleteBusy) setDeleteAllOpen(false);
      }}
      onConfirm={handleDeleteAll}
    />
  );

  if (error) {
    return (
      <>
        {header}
        {deleteAllDialog}
        <div className="flex items-center gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
          <WarningCircle size={20} weight="duotone" />
          <span>{error}</span>
          <button
            onClick={load}
            className="ml-auto rounded-lg border border-rose-300 px-3 py-1.5 text-xs font-medium hover:bg-rose-100 dark:border-rose-800 dark:hover:bg-rose-900"
          >
            Retry
          </button>
        </div>
      </>
    );
  }

  if (selected && selected.kind === "document") {
    return (
      <div>
        <div className="mb-6 flex items-center justify-between gap-4">
          <button
            onClick={() => setSelected(null)}
            className="flex items-center gap-2 text-sm text-zinc-500 transition-colors hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
          >
            <ArrowLeft size={16} />
            Back to all documents
          </button>
          <button
            onClick={() => {
              setDeleteError(null);
              setDeleteOpen(true);
            }}
            className="flex items-center gap-2 rounded-lg border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-600 transition-colors hover:border-rose-300 hover:bg-rose-50 hover:text-rose-700 active:scale-[0.98] dark:border-zinc-700 dark:text-zinc-300 dark:hover:border-rose-800 dark:hover:bg-rose-950 dark:hover:text-rose-400"
          >
            <Trash size={14} />
            Delete
          </button>
        </div>
        {deleteError && (
          <div className="mb-4 flex items-center gap-3 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
            <WarningCircle size={18} weight="duotone" />
            {deleteError}
          </div>
        )}

        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
          <div className="rounded-2xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
            <iframe
              src={pdfUrl(bucket, selected.pdf)}
              title={selected.name}
              className="h-[80vh] w-full rounded-lg"
            />
          </div>

          <div className="space-y-6">
            <div>
              <h2 className="font-mono text-sm text-zinc-500 dark:text-zinc-400">
                {selected.name}
              </h2>
              {typeof selected.record.page_count === "number" && (
                <span className="mt-2 inline-block rounded-md bg-zinc-100 px-2 py-1 text-[11px] font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                  {selected.record.page_count} page(s)
                </span>
              )}
            </div>

            <section className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
                Document metadata
              </h3>
              <MetaTable record={selected.record} />
            </section>

            <CostSection record={selected.record} />

            <section className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
              <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
                Extracted fields
              </h3>
              <FieldList record={selected.record} />
            </section>
          </div>
        </div>

        <ConfirmDialog
          open={deleteOpen}
          title="Delete document"
          message={deleteTarget}
          confirmLabel="Delete"
          busy={deleteBusy}
          onCancel={() => {
            if (!deleteBusy) setDeleteOpen(false);
          }}
          onConfirm={handleDelete}
        />
      </div>
    );
  }

  if (selected) {
    return (
      <div>
        <div className="mb-6 flex items-center justify-between gap-4">
          <button
            onClick={() => setSelected(null)}
            className="flex items-center gap-2 text-sm text-zinc-500 transition-colors hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
          >
            <ArrowLeft size={16} />
            Back to all pages
          </button>
          <button
            onClick={() => {
              setDeleteError(null);
              setDeleteOpen(true);
            }}
            className="flex items-center gap-2 rounded-lg border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-600 transition-colors hover:border-rose-300 hover:bg-rose-50 hover:text-rose-700 active:scale-[0.98] dark:border-zinc-700 dark:text-zinc-300 dark:hover:border-rose-800 dark:hover:bg-rose-950 dark:hover:text-rose-400"
          >
            <Trash size={14} />
            Delete
          </button>
        </div>
        {deleteError && (
          <div className="mb-4 flex items-center gap-3 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
            <WarningCircle size={18} weight="duotone" />
            {deleteError}
          </div>
        )}

        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
          <div className="rounded-2xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
            <img
              src={imageUrl(bucket, selected.image)}
              alt={`Page ${selected.name}`}
              className="max-h-[80vh] w-full rounded-lg object-contain"
            />
          </div>

          <div className="space-y-6">
            <div>
              <h2 className="font-mono text-sm text-zinc-500 dark:text-zinc-400">
                {selected.name}
              </h2>
              {selected.record.quality_tier && (
                <span
                  className={`mt-2 inline-block rounded-md px-2 py-1 text-[11px] font-medium ${tierClass(selected.record.quality_tier)}`}
                >
                  {tierLabel(selected.record.quality_tier)}
                  {selected.record.quality_score !== undefined &&
                    ` - score ${selected.record.quality_score}`}
                </span>
              )}
            </div>

            <section className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
                Page metadata
              </h3>
              <MetaTable record={selected.record} />
            </section>

            <section className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
              <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
                Extracted fields
              </h3>
              <FieldList record={selected.record} />
            </section>
          </div>
        </div>

        <ConfirmDialog
          open={deleteOpen}
          title="Delete page"
          message={deleteTarget}
          confirmLabel="Delete"
          busy={deleteBusy}
          onCancel={() => {
            if (!deleteBusy) setDeleteOpen(false);
          }}
          onConfirm={handleDelete}
        />
      </div>
    );
  }

  return (
    <div>
      {header}
      {deleteAllDialog}

      {loading ? (
        <div className="grid grid-cols-2 gap-6 md:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 8 }, (_, i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-zinc-300 py-24 text-center dark:border-zinc-700">
          <MagnifyingGlass size={32} weight="duotone" className="text-zinc-400" />
          <h2 className="mt-4 text-base font-medium">{emptyTitle}</h2>
          <p className="mt-1 max-w-[45ch] text-sm text-zinc-500 dark:text-zinc-400">
            {emptyHint}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-6 md:grid-cols-3 xl:grid-cols-4">
          {items.map((entry, index) => (
            <motion.button
              key={entry.name}
              onClick={() => setSelected(entry)}
              initial={reduceMotion ? false : { opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{
                duration: 0.4,
                delay: reduceMotion ? 0 : Math.min(index * 0.05, 0.4),
                ease: [0.16, 1, 0.3, 1],
              }}
              className="group text-left"
            >
              {entry.kind === "document" ? (
                <div className="flex aspect-[3/4] items-center justify-center rounded-xl border border-zinc-200 bg-zinc-50 transition-all duration-300 group-hover:-translate-y-1 group-hover:shadow-lg group-hover:shadow-zinc-900/10 dark:border-zinc-800 dark:bg-zinc-800/60 dark:group-hover:shadow-black/40">
                  <div className="flex flex-col items-center gap-2">
                    <FilePdf size={36} weight="duotone" className="text-rose-500" />
                    <span className="font-mono text-xs text-zinc-500 dark:text-zinc-400">
                      {entry.record.page_count ?? "?"} pages
                    </span>
                  </div>
                </div>
              ) : (
                <div className="relative aspect-[3/4] overflow-hidden rounded-xl border border-zinc-200 bg-white transition-all duration-300 group-hover:-translate-y-1 group-hover:shadow-lg group-hover:shadow-zinc-900/10 dark:border-zinc-800 dark:bg-zinc-900 dark:group-hover:shadow-black/40">
                  <img
                    src={imageUrl(bucket, entry.image)}
                    alt={`Page ${entry.name}`}
                    loading="lazy"
                    className="size-full object-cover"
                  />
                  <div className="absolute top-2 right-2">
                    <ScoreBadge score={entry.record.quality_score} />
                  </div>
                  {entry.record.page_skipped && (
                    <span className="absolute bottom-2 left-2 rounded-md bg-zinc-900/80 px-2 py-0.5 text-[11px] text-white backdrop-blur-sm dark:bg-zinc-100/85 dark:text-zinc-900">
                      skipped
                    </span>
                  )}
                  {entry.record.manual_review && (
                    <span className="absolute bottom-2 left-2 rounded-md bg-amber-500/90 px-2 py-0.5 text-[11px] text-white">
                      review
                    </span>
                  )}
                </div>
              )}
              <div className="mt-3 flex items-center justify-between gap-2">
                <p className="truncate text-sm font-medium">{entry.name}</p>
                {entry.record.quality_tier && (
                  <span
                    className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${tierClass(entry.record.quality_tier)}`}
                  >
                    {tierLabel(entry.record.quality_tier)}
                  </span>
                )}
              </div>
              <p className="truncate text-xs text-zinc-500 dark:text-zinc-400">
                {entry.kind === "document"
                  ? `Document - ${entry.record.page_count ?? "?"} page(s)`
                  : entry.record.model_used ??
                    entry.record.skip_reason ??
                    "No extraction"}
              </p>
            </motion.button>
          ))}
        </div>
      )}
    </div>
  );
}
