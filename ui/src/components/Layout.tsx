import type { JSX } from "react";
import { NavLink, Outlet } from "react-router-dom";
import {
  UploadSimple,
  FlowArrow,
  FileText,
  WarningCircle,
  SkipForward,
  SlidersHorizontal,
  Sparkle,
  Coins,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { checkHealth } from "../lib/api";

const NAV_ITEMS: { to: string; label: string; icon: JSX.Element }[] = [
  { to: "/", label: "Documents", icon: <UploadSimple size={18} weight="duotone" /> },
  { to: "/pipeline", label: "Pipeline", icon: <FlowArrow size={18} weight="duotone" /> },
  { to: "/extractions", label: "Extractions", icon: <FileText size={18} weight="duotone" /> },
  { to: "/review", label: "Manual Review", icon: <WarningCircle size={18} weight="duotone" /> },
  { to: "/skipped", label: "Skipped", icon: <SkipForward size={18} weight="duotone" /> },
  { to: "/template", label: "Template", icon: <SlidersHorizontal size={18} weight="duotone" /> },
  { to: "/costs", label: "Cost Tracker", icon: <Coins size={18} weight="duotone" /> },
];

export default function Layout() {
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    checkHealth().then(setOnline);
  }, []);

  return (
    <div className="flex min-h-[100dvh]">
      <aside className="fixed inset-y-0 left-0 z-20 flex w-60 flex-col border-r border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <div className="flex items-center gap-2.5 px-5 pt-6 pb-5">
          <span className="flex size-8 items-center justify-center rounded-lg bg-emerald-600 text-white">
            <Sparkle size={18} weight="fill" />
          </span>
          <div className="leading-tight">
            <p className="text-sm font-semibold tracking-tight">DocExtract</p>
            <p className="text-[11px] text-zinc-500 dark:text-zinc-400">POC console</p>
          </div>
        </div>

        <nav className="flex-1 px-3">
          <ul className="space-y-1">
            {NAV_ITEMS.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) =>
                    `flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                      isActive
                        ? "bg-emerald-50 font-medium text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
                        : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
                    }`
                  }
                >
                  {item.icon}
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        <div className="flex items-center gap-2 border-t border-zinc-200 px-5 py-4 text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
          <span
            className={`size-2 rounded-full ${
              online === null
                ? "bg-zinc-400"
                : online
                  ? "bg-emerald-500"
                  : "bg-rose-500"
            }`}
          />
          {online === null ? "Checking API" : online ? "API connected" : "API offline"}
        </div>
      </aside>

      <main className="ml-60 flex-1">
        <div className="mx-auto max-w-[1400px] px-8 py-10">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
