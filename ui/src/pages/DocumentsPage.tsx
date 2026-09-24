import { useCallback, useEffect, useRef, useState } from "react";
import {
  UploadSimple,
  FilePdf,
  WarningCircle,
  ArrowsClockwise,
  Cpu,
  CheckCircle,
  Trash,
} from "@phosphor-icons/react";
import ConfirmDialog from "../components/ConfirmDialog";
import ActiveRunsPanel from "../components/ActiveRunsPanel";
import {
  type InputFile,
  type ProcessStatus,
  clearBucket,
  deleteInputFile,
  formatBytes,
  getProcessStatus,
  listBucket,
  startProcess,
  uploadFiles,
} from "../lib/api";
import type { RunSummary } from "../lib/runs";

export default function DocumentsPage() {
  const [files, setFiles] = useState<InputFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [processing, setProcessing] = useState(false);
  const [processError, setProcessError] = useState<string | null>(null);
  const [statusNote, setStatusNote] = useState<string | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [deleting, setDeleting] = useState<InputFile | null>(null);
  const [deletingAll, setDeletingAll] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    listBucket("input")
      .then((data) => setFiles(data.items as InputFile[]))
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  useEffect(() => {
    getProcessStatus()
      .then((status: ProcessStatus) => {
        setProcessing(status.running);
        setRuns(status.runs ?? []);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!processing) return;
    const interval = setInterval(async () => {
      try {
        const status = await getProcessStatus();
        setRuns(status.runs ?? []);
        if (!status.running) {
          setProcessing(false);
          if (status.error) {
            setStatusNote(null);
            setProcessError(`Pipeline crashed: ${status.error}`);
          } else if (status.last_exit_code === 0) {
            setStatusNote("Pipeline finished successfully.");
          } else {
            setStatusNote(
              "Pipeline finished with failures - check the API console log.",
            );
          }
          load();
        }
      } catch {
        return;
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [processing, load]);

  const handleProcess = async () => {
    setProcessing(true);
    setRuns([]);
    setStatusNote(null);
    setProcessError(null);
    try {
      await startProcess();
    } catch (err) {
      setProcessError(err instanceof Error ? err.message : String(err));
      setProcessing(false);
    }
  };

  const handleFiles = async (selected: FileList | null) => {
    if (!selected || selected.length === 0) return;
    setUploading(true);
    setUploadError(null);
    try {
      await uploadFiles(Array.from(selected));
      await Promise.resolve(load());
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : String(err));
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <div>
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">Documents</h1>
        <p className="mt-1 max-w-[65ch] text-sm text-zinc-500 dark:text-zinc-400">
          Add PDF documents to the pipeline input folder. Every file here is
          processed by <code className="font-mono text-xs">main.py</code>.
        </p>
      </header>

      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          handleFiles(event.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed py-16 text-center transition-colors ${
          dragging
            ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-950/40"
            : "border-zinc-300 hover:border-zinc-400 dark:border-zinc-700 dark:hover:border-zinc-600"
        }`}
      >
        <UploadSimple
          size={36}
          weight="duotone"
          className="text-zinc-400 dark:text-zinc-500"
        />
        {uploading ? (
          <p className="mt-4 flex items-center gap-2 text-sm font-medium">
            <ArrowsClockwise size={16} className="animate-spin" />
            Uploading
          </p>
        ) : (
          <>
            <p className="mt-4 text-sm font-medium">
              Drop PDFs here or click to browse
            </p>
            <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
              Files are saved to <span className="font-mono">data/input</span>
            </p>
          </>
        )}
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,application/pdf"
          multiple
          hidden
          onChange={(event) => handleFiles(event.target.files)}
        />
      </div>

      {uploadError && (
        <div className="mt-4 flex items-center gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
          <WarningCircle size={20} weight="duotone" />
          {uploadError}
        </div>
      )}

      {processError && (
        <div className="mt-4 flex items-center gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
          <WarningCircle size={20} weight="duotone" />
          {processError}
        </div>
      )}

      {statusNote && (
        <div className="mt-4 flex items-center gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300">
          <CheckCircle size={20} weight="duotone" />
          {statusNote}
        </div>
      )}

      {processing && (
        <p className="mt-4 flex items-center gap-2 text-sm text-zinc-500 dark:text-zinc-400">
          <ArrowsClockwise size={14} className="animate-spin" />
          Pipeline is running - this can take around a minute per document.
        </p>
      )}

      {processing && runs.length > 0 && <ActiveRunsPanel runs={runs} />}

      <section className="mt-10">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
            Input folder
          </h2>
          <div className="flex items-center gap-3">
            {files.length > 0 && (
              <>
                <span className="font-mono text-xs text-zinc-400">
                  {files.length} file{files.length === 1 ? "" : "s"}
                </span>
                <button
                  onClick={() => {
                    setDeleteError(null);
                    setDeletingAll(true);
                  }}
                  disabled={processing || deleting !== null}
                  className="rounded-lg border border-zinc-300 px-3 py-2 text-xs font-medium text-zinc-600 transition-colors hover:border-rose-300 hover:bg-rose-50 hover:text-rose-700 active:scale-[0.98] disabled:opacity-40 dark:border-zinc-700 dark:text-zinc-300 dark:hover:border-rose-800 dark:hover:bg-rose-950 dark:hover:text-rose-400"
                >
                  Delete all
                </button>
              </>
            )}
            <button
              onClick={handleProcess}
              disabled={processing || uploading || files.length === 0}
              className="flex items-center gap-2 rounded-lg bg-emerald-600 px-3.5 py-2 text-xs font-medium text-white transition-all hover:bg-emerald-700 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {processing ? (
                <ArrowsClockwise size={14} className="animate-spin" />
              ) : (
                <Cpu size={14} weight="duotone" />
              )}
              {processing ? "Processing" : "Process"}
            </button>
          </div>
        </div>

        {loading ? (
          <ul className="space-y-2">
            {Array.from({ length: 3 }, (_, i) => (
              <li
                key={i}
                className="h-14 animate-pulse rounded-xl bg-zinc-200 dark:bg-zinc-800"
              />
            ))}
          </ul>
        ) : error ? (
          <div className="flex items-center gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
            <WarningCircle size={20} weight="duotone" />
            {error}
          </div>
        ) : files.length === 0 ? (
          <p className="rounded-xl border border-dashed border-zinc-300 py-10 text-center text-sm text-zinc-500 dark:border-zinc-700 dark:text-zinc-400">
            No PDFs yet. Add your first document above.
          </p>
        ) : (
          <ul className="divide-y divide-zinc-100 rounded-xl border border-zinc-200 bg-white dark:divide-zinc-800 dark:border-zinc-800 dark:bg-zinc-900">
            {files.map((file) => (
              <li key={file.name} className="flex items-center gap-4 px-4 py-3.5">
                <FilePdf
                  size={22}
                  weight="duotone"
                  className="shrink-0 text-rose-500"
                />
                <span className="truncate text-sm font-medium">{file.name}</span>
                <span className="ml-auto shrink-0 font-mono text-xs text-zinc-400">
                  {formatBytes(file.size)}
                </span>
                <button
                  onClick={() => {
                    setDeleteError(null);
                    setDeleting(file);
                  }}
                  disabled={processing || deleting !== null}
                  aria-label={`Delete ${file.name}`}
                  className="shrink-0 rounded-lg p-2 text-zinc-400 transition-colors hover:bg-rose-50 hover:text-rose-600 disabled:opacity-40 dark:hover:bg-rose-950 dark:hover:text-rose-400"
                >
                  <Trash size={16} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {deleteError && (
        <div className="mt-4 flex items-center gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
          <WarningCircle size={20} weight="duotone" />
          {deleteError}
        </div>
      )}

      <ConfirmDialog
        open={deletingAll}
        title="Delete all documents"
        message={`All ${files.length} PDF(s) in the input folder will be permanently deleted. This cannot be undone.`}
        confirmLabel="Delete all"
        busy={deleteBusy}
        onCancel={() => {
          if (!deleteBusy) setDeletingAll(false);
        }}
        onConfirm={async () => {
          setDeleteBusy(true);
          try {
            await clearBucket("input");
            setDeletingAll(false);
            await Promise.resolve(load());
          } catch (err) {
            setDeleteError(err instanceof Error ? err.message : String(err));
          } finally {
            setDeleteBusy(false);
          }
        }}
      />

      <ConfirmDialog
        open={deleting !== null}
        title="Delete document"
        message={
          deleting
            ? `"${deleting.name}" will be removed from the input folder. It will no longer be processed.`
            : ""
        }
        confirmLabel="Delete"
        busy={deleteBusy}
        onCancel={() => {
          if (!deleteBusy) setDeleting(null);
        }}
        onConfirm={async () => {
          if (!deleting) return;
          setDeleteBusy(true);
          try {
            await deleteInputFile(deleting.name);
            setDeleting(null);
            await Promise.resolve(load());
          } catch (err) {
            setDeleteError(err instanceof Error ? err.message : String(err));
          } finally {
            setDeleteBusy(false);
          }
        }}
      />
    </div>
  );
}
