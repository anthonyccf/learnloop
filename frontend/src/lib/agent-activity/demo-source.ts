import {
  agentRunSchema,
  type AgentRun,
  type AgentEvent,
  type RunWorkflow,
  type AgentActivitySource,
  type RunCommand,
  type CommandReceipt,
} from "./contracts";
import { applyAgentEvent } from "./reducer";

export type DemoScenario = RunWorkflow | "failure" | "review" | "paused";
type Step = Pick<AgentEvent, "type" | "payload">;
const status = (
  value: AgentRun["status"],
  summary: string,
  allowedCommands: ("retry" | "resume")[] = [],
): Step => ({
  type: "run.status",
  payload: {
    status: value,
    summary,
    allowedCommands,
    checkpointId: "sample-checkpoint",
  },
});
const step = (
  role: "expert" | "tutoring" | "assessing",
  task: string,
  detail: string,
  tool?:
    | "retrieve_evidence"
    | "assign_activity"
    | "assess_response"
    | "load_learner_state",
  state: "running" | "completed" | "needs_review" | "failed" = "running",
): Step => ({
  type: "agent.step",
  payload: { role, status: state, task, detail, tool },
});
const pending = (
  scope: "course_resources" | "activity" | "learner_state",
): Step => ({
  type: "runtime.validation",
  payload: {
    status: "pending",
    scope,
    summary: "Checking evidence, permissions and record version.",
    ...(scope === "learner_state"
      ? {
          candidate: {
            conceptId: "descent",
            before: "developing" as const,
            after: "demonstrated" as const,
            difficulty: "intermediate" as const,
          },
        }
      : {}),
  },
});
const accepted = (
  scope: "course_resources" | "activity" | "learner_state",
  previousVersion = 7,
): Step => ({
  type: "runtime.validation",
  payload: {
    status: "accepted",
    scope,
    summary:
      scope === "learner_state"
        ? "Sample assessment accepted; learner evidence committed."
        : "Sample output validated and accepted.",
    previousVersion,
    newVersion: previousVersion + 1,
    ...(scope === "learner_state"
      ? {
          committed: {
            conceptId: "descent",
            before: "developing" as const,
            after: "demonstrated" as const,
            difficulty: "intermediate" as const,
            learnerVersion: 43,
          },
        }
      : {}),
  },
});
export class DemoAgentSource implements AgentActivitySource {
  readonly mode = "demo" as const;
  readonly runId = "sample-run";
  private run: AgentRun;
  private listeners = new Set<(value: unknown) => void>();
  private queue: Step[];
  private receipts = new Map<string, CommandReceipt>();
  constructor(public scenario: DemoScenario) {
    const workflow: RunWorkflow =
      scenario === "review"
        ? "course_preparation"
        : scenario === "failure" || scenario === "paused"
          ? "next_activity"
          : scenario;
    this.run = agentRunSchema.parse({
      schemaVersion: 1,
      id: this.runId,
      courseId: "comp7608b-demo",
      workflow,
      label: "Training & optimization · sample run",
      status: "queued",
      summary: "Ready to step through the sample workflow.",
      recordVersion: 7,
      lastSequence: 0,
      currentAgent: null,
      allowedCommands: [],
      agents: Object.fromEntries(
        ["expert", "tutoring", "assessing"].map((role) => [
          role,
          {
            role,
            status: "not_started",
            task:
              role === "expert"
                ? "Prepare grounded course resources"
                : role === "tutoring"
                  ? "Select and adapt learning activities"
                  : "Assess responses and propose evidence",
            detail: "Runs when this workflow needs this agent.",
          },
        ]),
      ),
      validation: {
        status: "not_requested",
        summary: "No update proposed yet.",
      },
      committedChanges: [],
      artifacts: [],
      references: [],
      events: [],
    });
    const tutoring = [
      step(
        "tutoring",
        "Load learner evidence",
        "Check prerequisites and review needs.",
        "load_learner_state",
      ),
      step(
        "tutoring",
        "Choose the next activity",
        "Retrieve a grounded explanation and an eligible multiple-choice question.",
        "retrieve_evidence",
      ),
      pending("activity"),
      accepted("activity"),
      step(
        "tutoring",
        "Activity ready",
        "The learner can now answer the selected question.",
        "assign_activity",
        "completed",
      ),
      status(
        "waiting_for_learner",
        "Waiting for a learner response. No agent needs to run while the learner thinks.",
      ),
    ];
    this.queue = [status("running", "The sample workflow has started.")];
    if (workflow === "course_preparation")
      this.queue.push(
        step(
          "expert",
          "Retrieve course evidence",
          "Locate passages supporting concepts and prerequisite relationships.",
          "retrieve_evidence",
        ),
        {
          type: "agent.step",
          payload: {
            role: "expert",
            status: "waiting_for_validation",
            task: "Propose course graph",
            detail:
              "Submit concepts and source-backed edges for runtime validation.",
            references: [
              {
                documentId: "training-notes",
                label: "Sample training notes",
                page: 12,
              },
            ],
            artifacts: [
              {
                id: "sample-graph",
                kind: "graph",
                label: "Concepts and prerequisites",
                status: "candidate",
              },
            ],
          },
        },
        pending("course_resources"),
        ...(scenario === "review"
          ? [
              {
                type: "runtime.validation",
                payload: {
                  status: "rejected",
                  scope: "course_resources",
                  summary:
                    "A prerequisite edge needs a source citation. Resources remain unpublished.",
                  retryable: false,
                },
              } as Step,
              step(
                "expert",
                "Resource review needed",
                "Resolve the missing citation before publication.",
                undefined,
                "needs_review",
              ),
              status(
                "needs_review",
                "Course preparation needs staff review. Nothing has been published.",
              ),
            ]
          : [
              accepted("course_resources"),
              {
                type: "agent.step",
                payload: {
                  role: "expert",
                  status: "completed",
                  task: "Course resources published",
                  detail:
                    "Validated resources are ready for the Tutoring Agent.",
                  artifacts: [
                    {
                      id: "sample-graph",
                      kind: "graph",
                      label: "Concepts and prerequisites",
                      status: "published",
                    },
                  ],
                },
              } as Step,
              status(
                "completed",
                "Course preparation is complete. A learning session can now be started.",
              ),
            ]),
      );
    else if (scenario === "failure")
      this.queue.push(
        step(
          "tutoring",
          "Evidence retrieval interrupted",
          "The sample retrieval service is temporarily unavailable.",
          "retrieve_evidence",
          "failed",
        ),
        status(
          "failed",
          "No activity was assigned. Retry from the saved checkpoint.",
          ["retry"],
        ),
      );
    else if (scenario === "paused")
      this.queue.push(
        status("paused", "The run paused at a safe checkpoint.", ["resume"]),
      );
    else if (workflow === "next_activity") this.queue.push(...tutoring);
    else
      this.queue.push(
        step(
          "assessing",
          "Assess a submitted response",
          "Sample: a second independent correct response at the target difficulty.",
          "assess_response",
        ),
        pending("learner_state"),
        accepted("learner_state"),
        step(
          "assessing",
          "Assessment recorded",
          "The runtime accepted the proposed learner update.",
          undefined,
          "completed",
        ),
        {
          type: "agent.handoff",
          payload: {
            from: "assessing",
            to: "tutoring",
            reason:
              "Use the newly committed evidence to adapt the next activity.",
          },
        },
        step(
          "tutoring",
          "Revise the learning plan",
          "Select the next eligible concept using the accepted evidence.",
          "load_learner_state",
        ),
        pending("activity"),
        accepted("activity", 8),
        step(
          "tutoring",
          "Next activity ready",
          "Waiting for the learner.",
          undefined,
          "completed",
        ),
        status(
          "waiting_for_learner",
          "The learning loop returns to the learner.",
        ),
      );
  }
  get remainingSteps() {
    return this.queue.length;
  }
  async getRun(runId: string) {
    this.check(runId);
    return structuredClone(this.run);
  }
  watch(
    runId: string,
    after: number,
    onEvent: (event: unknown) => void,
    onConnection: (state: "connected") => void,
  ) {
    this.check(runId);
    this.listeners.add(onEvent);
    this.run.events.filter((e) => e.sequence > after).forEach(onEvent);
    onConnection("connected");
    return () => {
      this.listeners.delete(onEvent);
    };
  }
  advance() {
    const value = this.queue.shift();
    if (!value) return;
    const sequence = this.run.lastSequence + 1;
    const event = {
      ...value,
      schemaVersion: 1,
      id: `sample-event-${sequence}`,
      runId: this.runId,
      courseId: this.run.courseId,
      sequence,
      at: new Date(Date.UTC(2026, 9, 18, 2, 0, sequence)).toISOString(),
    };
    this.run = applyAgentEvent(this.run, event);
    this.listeners.forEach((listener) => listener(event));
  }
  async command(runId: string, input: RunCommand) {
    this.check(runId);
    const prior = this.receipts.get(input.operationId);
    if (prior) return prior;
    if (
      input.expectedVersion !== this.run.recordVersion ||
      !this.run.allowedCommands.includes(input.kind)
    )
      throw new Error("This command is no longer available. Refresh the run.");
    const receipt = { runId, operationId: input.operationId, accepted: true };
    this.receipts.set(input.operationId, receipt);
    this.queue = [
      status("running", "Resumed from the sample checkpoint."),
      step(
        "tutoring",
        "Retrieve evidence again",
        "The sample retrieval service is available.",
        "retrieve_evidence",
      ),
      pending("activity"),
      accepted("activity"),
      step(
        "tutoring",
        "Activity ready",
        "Recovered without duplicating a learner update.",
        "assign_activity",
        "completed",
      ),
      status("waiting_for_learner", "Waiting for the learner."),
    ];
    this.advance();
    return receipt;
  }
  private check(id: string) {
    if (id !== this.runId) throw new Error("Unknown sample run.");
  }
}
