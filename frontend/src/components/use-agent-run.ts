"use client";
import { useEffect, useRef, useState } from "react";
import {
  agentRunSchema,
  type AgentActivitySource,
  type AgentRun,
  type ConnectionState,
} from "@/lib/agent-activity/contracts";
import { applyAgentEvent } from "@/lib/agent-activity/reducer";

export function useAgentRun(source: AgentActivitySource, runId: string) {
  const [run, setRun] = useState<AgentRun | null>(null);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [busy, setBusy] = useState(false);
  const operation = useRef<{ key: string; id: string } | null>(null);
  const generation = useRef(0);
  useEffect(() => {
    let active = true;
    let close: (() => void) | undefined;
    let broken = false;
    let current: AgentRun;
    const controller = new AbortController();
    generation.current += 1;
    Promise.resolve()
      .then(() => {
        if (!active) return null;
        setRun(null);
        setError("");
        setConnection("connecting");
        setBusy(false);
        return source.getRun(runId, controller.signal);
      })
      .then((value) => {
        if (!active || !value) return;
        current = agentRunSchema.parse(value);
        if (current.id !== runId) throw new Error("Snapshot run mismatch.");
        setRun(current);
        close = source.watch(
          runId,
          current.lastSequence,
          (event) => {
            if (!active || broken) return;
            try {
              current = applyAgentEvent(current, event);
              setRun(current);
            } catch (err) {
              broken = true;
              close?.();
              setConnection("error");
              setError(
                err instanceof Error ? err.message : "Invalid run event.",
              );
            }
          },
          (state) => {
            if (active && !broken) setConnection(state);
          },
        );
        if (broken) close();
      })
      .catch((err) => {
        if (active) {
          setConnection("error");
          setError(err instanceof Error ? err.message : "Unable to load run.");
        }
      });
    return () => {
      active = false;
      generation.current += 1;
      controller.abort();
      close?.();
    };
  }, [source, runId, reload]);
  async function command(kind: "retry" | "resume") {
    if (
      !run ||
      busy ||
      connection !== "connected" ||
      !run.allowedCommands.includes(kind)
    )
      return;
    const key = `${run.id}:${kind}:${run.recordVersion}:${run.lastSequence}`;
    if (operation.current?.key !== key)
      operation.current = { key, id: crypto.randomUUID() };
    setBusy(true);
    setError("");
    const started = generation.current;
    try {
      const receipt = await source.command(run.id, {
        kind,
        operationId: operation.current.id,
        expectedVersion: run.recordVersion,
      });
      if (!receipt.accepted)
        throw new Error("The runtime declined this command. Refresh the run.");
    } catch (err) {
      if (started === generation.current)
        setError(err instanceof Error ? err.message : "Command failed.");
    } finally {
      if (started === generation.current) setBusy(false);
    }
  }
  return {
    run,
    connection,
    error,
    busy,
    command,
    refresh: () => setReload((value) => value + 1),
  };
}
