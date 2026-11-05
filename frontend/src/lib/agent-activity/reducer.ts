import { agentEventSchema, type AgentRun } from "./contracts";
export class AgentProtocolError extends Error {}
export function applyAgentEvent(run: AgentRun, value: unknown): AgentRun {
  const parsed = agentEventSchema.safeParse(value);
  if (!parsed.success)
    throw new AgentProtocolError(
      "The event does not match the supported v1 contract. Reload the run snapshot.",
    );
  const event = parsed.data;
  if (event.runId !== run.id || event.courseId !== run.courseId)
    throw new AgentProtocolError(
      "Event scope does not match the selected course and run.",
    );
  if (event.sequence <= run.lastSequence) {
    if (
      event.sequence === run.lastSequence &&
      run.lastEventId &&
      event.id !== run.lastEventId
    )
      throw new AgentProtocolError("Conflicting events share the same cursor.");
    return run;
  }
  if (event.sequence !== run.lastSequence + 1)
    throw new AgentProtocolError(
      "An event is missing or out of order. Reload the authoritative snapshot before continuing.",
    );
  const next: AgentRun = {
    ...run,
    lastSequence: event.sequence,
    lastEventId: event.id,
    events: [...run.events, event].slice(-1000),
  };
  if (event.type === "agent.step") {
    const { role, references, artifacts, ...stage } = event.payload;
    next.agents = { ...run.agents, [role]: { role, ...stage } };
    if (["running", "waiting_for_validation"].includes(stage.status))
      next.currentAgent = role;
    else if (run.currentAgent === role) next.currentAgent = null;
    if (references)
      next.references = [
        ...new Map(
          [...run.references, ...references].map((item) => [
            `${item.documentId}:${item.page || ""}:${item.conceptId || ""}`,
            item,
          ]),
        ).values(),
      ];
    if (artifacts)
      next.artifacts = [
        ...new Map(
          [...run.artifacts, ...artifacts].map((item) => [item.id, item]),
        ).values(),
      ];
  } else if (event.type === "agent.handoff") {
    next.currentAgent = event.payload.to;
    next.agents = {
      ...run.agents,
      [event.payload.to]: {
        ...run.agents[event.payload.to],
        status: "queued",
        task: "Handoff received",
        detail: event.payload.reason,
      },
    };
  } else if (event.type === "run.status") {
    next.status = event.payload.status;
    next.summary = event.payload.summary;
    next.allowedCommands = event.payload.allowedCommands;
    next.checkpointId = event.payload.checkpointId || run.checkpointId;
    next.error = event.payload.error;
    if (!["running", "queued"].includes(next.status)) next.currentAgent = null;
  } else {
    const payload = event.payload;
    if (payload.status === "pending" && run.currentAgent)
      next.agents = {
        ...run.agents,
        [run.currentAgent]: {
          ...run.agents[run.currentAgent],
          status: "waiting_for_validation",
        },
      };
    if (
      payload.status === "rejected" &&
      (run.validation.status !== "pending" ||
        run.validation.scope !== payload.scope)
    )
      throw new AgentProtocolError(
        "Validation rejection does not match a pending proposal.",
      );
    if (payload.status === "accepted") {
      if (
        run.validation.status !== "pending" ||
        run.validation.scope !== payload.scope ||
        payload.previousVersion !== run.recordVersion ||
        payload.newVersion !== payload.previousVersion + 1
      )
        throw new AgentProtocolError(
          "The commit does not match the pending validation or current run version. Reload the snapshot.",
        );
      if (payload.scope === "learner_state") {
        const candidate = run.validation.candidate;
        const committed = payload.committed;
        if (
          !candidate ||
          !committed ||
          candidate.conceptId !== committed.conceptId ||
          candidate.before !== committed.before ||
          candidate.after !== committed.after ||
          candidate.difficulty !== committed.difficulty
        )
          throw new AgentProtocolError(
            "The committed learner update does not match the proposed update.",
          );
        if (
          run.committedChanges.some(
            (change) => change.learnerVersion >= committed.learnerVersion,
          )
        )
          throw new AgentProtocolError("Learner version must advance.");
        next.committedChanges = [...run.committedChanges, committed];
      } else if (payload.committed)
        throw new AgentProtocolError(
          "A non-learner validation cannot commit a learner-state change.",
        );
      next.recordVersion = payload.newVersion;
    }
    next.validation = {
      status: payload.status,
      scope: payload.scope,
      summary: payload.summary,
      candidate:
        payload.status === "pending"
          ? payload.candidate
          : run.validation.candidate,
    };
  }
  return next;
}
