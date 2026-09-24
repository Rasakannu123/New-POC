import { useEffect, useState } from "react";
import { runStreamUrl } from "./runs";
import type { NodeTrace, RunEvent } from "./runs";

export interface RunStreamState {
  trace: NodeTrace[];
  pendingNode: string | null;
  ended: boolean;
  status: string | null;
  error: string | null;
}

const EMPTY: RunStreamState = {
  trace: [],
  pendingNode: null,
  ended: false,
  status: null,
  error: null,
};

export function useRunStream(
  runId: string | null,
  enabled = true,
): RunStreamState {
  const [state, setState] = useState<RunStreamState>(EMPTY);

  useEffect(() => {
    if (!runId || !enabled) return;
    setState(EMPTY);
    const source = new EventSource(runStreamUrl(runId));
    source.onmessage = (message) => {
      const event = JSON.parse(message.data) as RunEvent;
      setState((prev) => {
        if (event.type === "node_start" && event.node) {
          return { ...prev, pendingNode: event.node };
        }
        if (event.type === "node" && event.trace) {
          const incoming = event.trace;
          const seen = prev.trace.some(
            (item) => item.seq === incoming.seq && item.node === incoming.node,
          );
          if (seen) return prev;
          return {
            ...prev,
            trace: [...prev.trace, incoming],
            pendingNode: null,
          };
        }
        if (event.type === "run_end") {
          return {
            ...prev,
            pendingNode: null,
            ended: true,
            status: event.status ?? null,
            error: event.error ?? null,
          };
        }
        return prev;
      });
    };
    source.onerror = () => source.close();
    return () => source.close();
  }, [runId, enabled]);

  return state;
}
