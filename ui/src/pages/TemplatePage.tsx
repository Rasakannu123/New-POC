import { useEffect, useState } from "react";
import { Plus, X, FloppyDisk, ArrowsClockwise, CheckCircle, WarningCircle } from "@phosphor-icons/react";
import { type Template, getTemplate, saveTemplate } from "../lib/api";

function FieldListEditor({
  title,
  hint,
  names,
  onChange,
}: {
  title: string;
  hint: string;
  names: string[];
  onChange: (names: string[]) => void;
}) {
  const update = (index: number, value: string) => {
    onChange(names.map((name, i) => (i === index ? value : name)));
  };

  const remove = (index: number) => {
    onChange(names.filter((_, i) => i !== index));
  };

  const add = () => onChange([...names, ""]);

  return (
    <section className="rounded-2xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="mb-1 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold">{title}</h2>
        <span className="font-mono text-xs text-zinc-400">
          {names.length} field{names.length === 1 ? "" : "s"}
        </span>
      </div>
      <p className="mb-4 text-xs text-zinc-500 dark:text-zinc-400">{hint}</p>

      {names.length === 0 ? (
        <p className="rounded-lg border border-dashed border-zinc-300 py-6 text-center text-xs text-zinc-500 dark:border-zinc-700 dark:text-zinc-400">
          No fields configured.
        </p>
      ) : (
        <ul className="space-y-2">
          {names.map((name, index) => (
            <li key={index} className="flex items-center gap-2">
              <input
                value={name}
                onChange={(event) => update(index, event.target.value)}
                placeholder="field_name"
                spellCheck={false}
                className="w-full rounded-lg border border-zinc-300 bg-transparent px-3 py-2 font-mono text-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/20 dark:border-zinc-700"
              />
              <button
                onClick={() => remove(index)}
                aria-label={`Remove ${name || "field"}`}
                className="shrink-0 rounded-lg p-2 text-zinc-400 transition-colors hover:bg-rose-50 hover:text-rose-600 dark:hover:bg-rose-950 dark:hover:text-rose-400"
              >
                <X size={16} />
              </button>
            </li>
          ))}
        </ul>
      )}

      <button
        onClick={add}
        className="mt-3 flex items-center gap-1.5 rounded-lg border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-600 transition-colors hover:border-zinc-400 hover:text-zinc-900 active:scale-[0.98] dark:border-zinc-700 dark:text-zinc-300 dark:hover:border-zinc-600 dark:hover:text-zinc-100"
      >
        <Plus size={14} weight="bold" />
        Add field
      </button>
    </section>
  );
}

export default function TemplatePage() {
  const [template, setTemplate] = useState<Template | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    getTemplate()
      .then(setTemplate)
      .catch((err: Error) => setLoadError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const save = async () => {
    if (!template) return;
    setSaving(true);
    setSaved(false);
    setSaveError(null);
    try {
      const result = await saveTemplate(template);
      setTemplate(result);
      setSaved(true);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div>
        <div className="mb-8 h-8 w-48 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
        <div className="grid gap-6 lg:grid-cols-2">
          {Array.from({ length: 2 }, (_, i) => (
            <div
              key={i}
              className="h-72 animate-pulse rounded-2xl bg-zinc-200 dark:bg-zinc-800"
            />
          ))}
        </div>
      </div>
    );
  }

  if (loadError || !template) {
    return (
      <div className="flex items-center gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
        <WarningCircle size={20} weight="duotone" />
        {loadError ?? "Template not found"}
      </div>
    );
  }

  const hasChanges = true;

  return (
    <div>
      <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Template</h1>
          <p className="mt-1 max-w-[65ch] text-sm text-zinc-500 dark:text-zinc-400">
            Defines which fields the extraction model returns and which page
            markers send a page to the skip folder. Stored in{" "}
            <span className="font-mono text-xs">data/Template/test.json</span>.
          </p>
        </div>
        <button
          onClick={save}
          disabled={saving || !hasChanges}
          className="flex items-center gap-2 rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-medium text-white transition-all hover:bg-emerald-700 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? (
            <ArrowsClockwise size={16} className="animate-spin" />
          ) : saved ? (
            <CheckCircle size={16} weight="fill" />
          ) : (
            <FloppyDisk size={16} weight="duotone" />
          )}
          {saving ? "Saving" : saved ? "Saved" : "Save template"}
        </button>
      </header>

      {saveError && (
        <div className="mb-6 flex items-center gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
          <WarningCircle size={20} weight="duotone" />
          {saveError}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <FieldListEditor
          title="Extracted fields"
          hint="The model returns exactly these fields for every page; unreadable ones come back as null."
          names={Object.keys(template.extracted_fields)}
          onChange={(names) =>
            setTemplate({
              ...template,
              extracted_fields: Object.fromEntries(
                names.map((name) => [name, ""]),
              ),
            })
          }
        />
        <FieldListEditor
          title="No-need page markers"
          hint="If a page contains any of these fields, the split gate skips it into the skip folder."
          names={Object.keys(template.no_need_page)}
          onChange={(names) =>
            setTemplate({
              ...template,
              no_need_page: Object.fromEntries(
                names.map((name) => [name, ""]),
              ),
            })
          }
        />
        <FieldListEditor
          title="Multiple documents (grouping)"
          hint="Pages sharing the same value of the first field are joined into one PDF. Empty means grouping is off and the whole file becomes one document."
          names={Object.keys(
            template["multiple-docs"]?.["same-words-every-pages"] ?? {},
          )}
          onChange={(names) =>
            setTemplate({
              ...template,
              "multiple-docs": {
                "same-words-every-pages": Object.fromEntries(
                  names.map((name) => [name, ""]),
                ),
              },
            })
          }
        />
      </div>
    </div>
  );
}
