import {
  agentRunSchema,
  commandSchema,
  receiptSchema,
  type AgentActivitySource,
} from "./contracts";

/** Proposed backend transport. Instantiation is explicit; the demo never opens a connection. */
export function createHttpAgentSource(
  baseUrl: string,
  request: typeof fetch = fetch,
  events: (url: string) => EventSource = (url) =>
    new EventSource(url, { withCredentials: true }),
): AgentActivitySource {
  const endpoint = (id: string) =>
    `${baseUrl.replace(/\/$/, "")}/runs/${encodeURIComponent(id)}`;
  return {
    mode: "backend",
    async getRun(id, signal) {
      const response = await request(endpoint(id), {
        signal,
        credentials: "include",
        cache: "no-store",
      });
      if (!response.ok)
        throw new Error(`Cannot load run (${response.status}).`);
      const run = agentRunSchema.parse(await response.json());
      if (run.id !== id) throw new Error("Snapshot run mismatch.");
      return run;
    },
    watch(id, after, onEvent, onConnection) {
      const stream = events(`${endpoint(id)}/events?after_sequence=${after}`);
      stream.onopen = () => onConnection("connected");
      stream.onerror = () =>
        onConnection(stream.readyState === 2 ? "offline" : "reconnecting");
      stream.onmessage = (message) => {
        try {
          onEvent(JSON.parse(message.data));
        } catch {
          onEvent(null);
        }
      };
      return () => stream.close();
    },
    async command(id, input, signal) {
      commandSchema.parse(input);
      const response = await request(`${endpoint(id)}/commands`, {
        method: "POST",
        signal,
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input),
      });
      if (!response.ok)
        throw new Error(
          `Command not accepted (${response.status}). Refresh before retrying.`,
        );
      const receipt = receiptSchema.parse(await response.json());
      if (receipt.runId !== id || receipt.operationId !== input.operationId)
        throw new Error("Command receipt mismatch.");
      return receipt;
    },
  };
}
