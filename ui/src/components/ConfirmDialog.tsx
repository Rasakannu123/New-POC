import { useEffect } from "react";
import { Warning } from "@phosphor-icons/react";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  busy,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, busy, onCancel]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-zinc-900/50 p-4 backdrop-blur-sm"
      onClick={() => {
        if (!busy) onCancel();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        className="w-full max-w-sm rounded-2xl border border-zinc-200 bg-white p-6 shadow-xl dark:border-zinc-800 dark:bg-zinc-900"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start gap-3">
          <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-rose-50 text-rose-600 dark:bg-rose-950 dark:text-rose-400">
            <Warning size={18} weight="fill" />
          </span>
          <div>
            <h2 className="text-sm font-semibold">{title}</h2>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
              {message}
            </p>
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <button
            onClick={onCancel}
            disabled={busy}
            className="rounded-lg border border-zinc-300 px-3.5 py-2 text-xs font-medium transition-colors hover:border-zinc-400 hover:text-zinc-900 active:scale-[0.98] disabled:opacity-50 dark:border-zinc-700 dark:hover:border-zinc-600 dark:hover:text-zinc-100"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={busy}
            className="rounded-lg bg-rose-600 px-3.5 py-2 text-xs font-medium text-white transition-all hover:bg-rose-700 active:scale-[0.98] disabled:opacity-50"
          >
            {busy ? "Deleting" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
