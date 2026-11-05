import test from "node:test";
import assert from "node:assert/strict";
import {
  DemoAgentSource,
  type DemoScenario,
} from "../src/lib/agent-activity/demo-source";
import { applyAgentEvent } from "../src/lib/agent-activity/reducer";
import { agentRunSchema } from "../src/lib/agent-activity/contracts";
import { createHttpAgentSource } from "../src/lib/agent-activity/http-source";

test("all sample workflows produce valid snapshots and stop at the expected boundary", async () => {
  for (const scenario of [
    "course_preparation",
    "next_activity",
    "assessment",
    "review",
    "failure",
    "paused",
  ] as DemoScenario[]) {
    const source = new DemoAgentSource(scenario);
    while (source.remainingSteps) source.advance();
    const run = await source.getRun(source.runId);
    assert.ok(agentRunSchema.safeParse(run).success, scenario);
    assert.equal(
      run.status,
      scenario === "course_preparation"
        ? "completed"
        : scenario === "review"
          ? "needs_review"
          : scenario === "failure"
            ? "failed"
            : scenario === "paused"
              ? "paused"
              : "waiting_for_learner",
    );
    assert.equal(
      run.committedChanges.length,
      scenario === "assessment" ? 1 : 0,
    );
    if (scenario === "review")
      assert.equal(run.artifacts[0].status, "candidate");
  }
});
test("replay is idempotent; gaps, wrong scope, unsupported payloads and conflicting cursors fail closed", async () => {
  const source = new DemoAgentSource("assessment");
  const original = await source.getRun(source.runId);
  source.advance();
  const run = await source.getRun(source.runId);
  const event = run.events[0];
  assert.equal(applyAgentEvent(run, event), run);
  assert.throws(() => applyAgentEvent(original, { ...event, sequence: 2 }));
  assert.throws(() =>
    applyAgentEvent(original, { ...event, courseId: "another-course" }),
  );
  assert.throws(() =>
    applyAgentEvent(original, { ...event, privatePrompt: "secret" }),
  );
  assert.throws(() => applyAgentEvent(run, { ...event, id: "conflict" }));
});
test("learner updates require the matching pending proposal and current runtime version", async () => {
  const source = new DemoAgentSource("assessment");
  for (let i = 0; i < 3; i++) source.advance();
  const pending = await source.getRun(source.runId);
  assert.equal(pending.validation.status, "pending");
  source.advance();
  const final = await source.getRun(source.runId);
  const commit = final.events.at(-1)!;
  assert.equal(final.committedChanges.length, 1);
  if (
    commit.type !== "runtime.validation" ||
    commit.payload.status !== "accepted"
  )
    throw new Error("Expected commit");
  const acceptedPayload = commit.payload;
  assert.throws(() =>
    applyAgentEvent({ ...pending, recordVersion: 99 }, commit),
  );
  assert.throws(() =>
    applyAgentEvent(
      {
        ...pending,
        validation: { status: "not_requested", summary: "No proposal" },
      },
      commit,
    ),
  );
  assert.throws(() =>
    applyAgentEvent(pending, {
      ...commit,
      payload: {
        ...acceptedPayload,
        committed: { ...acceptedPayload.committed, conceptId: "adam" },
      },
    }),
  );
});
test("reconnect replays only events beyond cursor and unsubscribes; retry operation is idempotent", async () => {
  const source = new DemoAgentSource("failure");
  while (source.remainingSteps) source.advance();
  let run = await source.getRun(source.runId);
  const seen: unknown[] = [];
  const close = source.watch(
    source.runId,
    1,
    (event) => seen.push(event),
    () => {},
  );
  assert.equal(seen.length, run.lastSequence - 1);
  close();
  const input = {
    kind: "retry" as const,
    operationId: "stable-operation",
    expectedVersion: run.recordVersion,
  };
  const first = await source.command(source.runId, input);
  const cursor = (await source.getRun(source.runId)).lastSequence;
  assert.deepEqual(await source.command(source.runId, input), first);
  assert.equal((await source.getRun(source.runId)).lastSequence, cursor);
  assert.equal(seen.length, run.lastSequence - 1);
  while (source.remainingSteps) source.advance();
  run = await source.getRun(source.runId);
  assert.equal(run.status, "waiting_for_learner");
  assert.equal(run.committedChanges.length, 0);
});
test("HTTP adapter checks snapshot scope and command receipts without a live backend", async () => {
  const source = new DemoAgentSource("assessment");
  const snapshot = await source.getRun(source.runId);
  const urls: string[] = [];
  const mock = (async (input: RequestInfo | URL, init?: RequestInit) => {
    urls.push(String(input));
    return Response.json(
      init?.method === "POST"
        ? { runId: snapshot.id, operationId: "op-1", accepted: true }
        : snapshot,
    );
  }) as typeof fetch;
  const http = createHttpAgentSource("/api/agent-activity", mock);
  assert.equal((await http.getRun(snapshot.id)).id, snapshot.id);
  assert.ok(
    (
      await http.command(snapshot.id, {
        kind: "retry",
        operationId: "op-1",
        expectedVersion: 7,
      })
    ).accepted,
  );
  assert.equal(urls[1], "/api/agent-activity/runs/sample-run/commands");
  await assert.rejects(() => http.getRun("wrong-run"));
});
