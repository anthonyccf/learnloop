import { z } from "zod";

const text = z.string().min(1).max(3000);
const id = z.string().min(1).max(200);
const version = z.number().int().nonnegative();
export const agentRoles = ["expert", "tutoring", "assessing"] as const;
export const roleSchema = z.enum(agentRoles);
export const workflowSchema = z.enum([
  "course_preparation",
  "next_activity",
  "assessment",
]);
export const agentStatusSchema = z.enum([
  "not_started",
  "queued",
  "running",
  "waiting_for_input",
  "waiting_for_validation",
  "completed",
  "needs_review",
  "failed",
  "paused",
]);
export const runStatusSchema = z.enum([
  "queued",
  "running",
  "waiting_for_learner",
  "needs_review",
  "paused",
  "completed",
  "failed",
]);
const conceptState = z.enum([
  "unassessed",
  "developing",
  "demonstrated",
  "review_due",
]);
const candidateSchema = z
  .object({
    conceptId: id,
    before: conceptState,
    after: conceptState,
    difficulty: z.enum(["basic", "intermediate", "advanced"]),
  })
  .strict();
const committedSchema = candidateSchema
  .extend({ learnerVersion: version })
  .strict();
export const artifactSchema = z
  .object({
    id,
    kind: z.enum(["graph", "activity", "assessment", "evidence"]),
    label: text,
    status: z.enum(["candidate", "published", "committed"]),
  })
  .strict();
export const referenceSchema = z
  .object({
    documentId: id,
    label: text,
    page: z.number().int().positive().optional(),
    conceptId: id.optional(),
  })
  .strict();
const toolSchema = z.enum([
  "retrieve_evidence",
  "publish_resources",
  "load_learner_state",
  "assign_activity",
  "assess_response",
  "record_assessment",
  "revise_plan",
]);
const errorSchema = z
  .object({ code: id, message: text, retryable: z.boolean() })
  .strict();
const scopeSchema = z.enum(["course_resources", "activity", "learner_state"]);
const common = z.object({
  schemaVersion: z.literal(1),
  id,
  runId: id,
  courseId: id,
  sequence: z.number().int().positive(),
  at: z.iso.datetime({ offset: true }),
});

export const agentEventSchema = z.discriminatedUnion("type", [
  common
    .extend({
      type: z.literal("agent.step"),
      payload: z
        .object({
          role: roleSchema,
          status: agentStatusSchema,
          task: text,
          detail: text,
          tool: toolSchema.optional(),
          references: z.array(referenceSchema).max(100).optional(),
          artifacts: z.array(artifactSchema).max(100).optional(),
          error: errorSchema.optional(),
        })
        .strict(),
    })
    .strict(),
  common
    .extend({
      type: z.literal("agent.handoff"),
      payload: z
        .object({ from: roleSchema, to: roleSchema, reason: text })
        .strict(),
    })
    .strict(),
  common
    .extend({
      type: z.literal("runtime.validation"),
      payload: z.discriminatedUnion("status", [
        z
          .object({
            status: z.literal("pending"),
            scope: scopeSchema,
            summary: text,
            candidate: candidateSchema.optional(),
          })
          .strict(),
        z
          .object({
            status: z.literal("accepted"),
            scope: scopeSchema,
            summary: text,
            previousVersion: version,
            newVersion: version,
            committed: committedSchema.optional(),
          })
          .strict(),
        z
          .object({
            status: z.literal("rejected"),
            scope: scopeSchema,
            summary: text,
            retryable: z.boolean(),
          })
          .strict(),
      ]),
    })
    .strict(),
  common
    .extend({
      type: z.literal("run.status"),
      payload: z
        .object({
          status: runStatusSchema,
          summary: text,
          checkpointId: id.optional(),
          allowedCommands: z.array(z.enum(["retry", "resume"])).max(2),
          error: errorSchema.optional(),
        })
        .strict(),
    })
    .strict(),
]);
export type AgentEvent = z.infer<typeof agentEventSchema>;
export type AgentRole = z.infer<typeof roleSchema>;
export type RunWorkflow = z.infer<typeof workflowSchema>;
export type RunStatus = z.infer<typeof runStatusSchema>;
export type Artifact = z.infer<typeof artifactSchema>;
const stageSchema = z
  .object({
    role: roleSchema,
    status: agentStatusSchema,
    task: text,
    detail: text,
    tool: toolSchema.optional(),
    error: errorSchema.optional(),
  })
  .strict();
const validationSchema = z
  .object({
    status: z.enum(["not_requested", "pending", "accepted", "rejected"]),
    scope: scopeSchema.optional(),
    summary: text,
    candidate: candidateSchema.optional(),
  })
  .strict();
export const agentRunSchema = z
  .object({
    schemaVersion: z.literal(1),
    id,
    courseId: id,
    workflow: workflowSchema,
    conceptId: id.optional(),
    label: text,
    status: runStatusSchema,
    summary: text,
    recordVersion: version,
    lastSequence: version,
    lastEventId: id.optional(),
    checkpointId: id.optional(),
    allowedCommands: z.array(z.enum(["retry", "resume"])).max(2),
    currentAgent: roleSchema.nullable(),
    agents: z
      .object({
        expert: stageSchema,
        tutoring: stageSchema,
        assessing: stageSchema,
      })
      .strict(),
    validation: validationSchema,
    committedChanges: z.array(committedSchema).max(100),
    artifacts: z.array(artifactSchema).max(100),
    references: z.array(referenceSchema).max(100),
    events: z.array(agentEventSchema).max(1000),
    error: errorSchema.optional(),
  })
  .strict()
  .superRefine((run, ctx) => {
    for (const role of agentRoles)
      if (run.agents[role].role !== role)
        ctx.addIssue({
          code: "custom",
          message: "Agent stage role does not match its key.",
        });
    if (
      run.events.some(
        (event) =>
          event.runId !== run.id ||
          event.courseId !== run.courseId ||
          event.sequence > run.lastSequence,
      )
    )
      ctx.addIssue({
        code: "custom",
        message: "Snapshot contains events outside its run or cursor.",
      });
  });
export type AgentRun = z.infer<typeof agentRunSchema>;
export const commandSchema = z
  .object({
    kind: z.enum(["retry", "resume"]),
    operationId: id,
    expectedVersion: version,
  })
  .strict();
export type RunCommand = z.infer<typeof commandSchema>;
export const receiptSchema = z
  .object({ runId: id, operationId: id, accepted: z.boolean() })
  .strict();
export type CommandReceipt = z.infer<typeof receiptSchema>;
export type ConnectionState =
  "connecting" | "connected" | "reconnecting" | "offline" | "error";
export interface AgentActivitySource {
  readonly mode: "demo" | "backend";
  getRun(runId: string, signal?: AbortSignal): Promise<AgentRun>;
  watch(
    runId: string,
    afterSequence: number,
    onEvent: (value: unknown) => void,
    onConnection: (state: ConnectionState) => void,
  ): () => void;
  command(
    runId: string,
    input: RunCommand,
    signal?: AbortSignal,
  ): Promise<CommandReceipt>;
}
