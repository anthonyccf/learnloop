"use client";
import Link from "next/link";
import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { agentRoles } from "@/lib/agent-activity/contracts";
import { DemoAgentSource, type DemoScenario } from "@/lib/agent-activity/demo-source";
import { PageHeading } from "./ui";
import { Icon } from "./icons";
import { useAgentRun } from "./use-agent-run";

const titles = {
  expert: "Expert Agent",
  tutoring: "Tutoring Agent",
  assessing: "Assessing Agent",
};
const scenarios: Record<DemoScenario, string> = {
  course_preparation: "Prepare course resources",
  next_activity: "Choose a learning activity",
  assessment: "Assess and adapt",
  review: "Preparation needs review",
  failure: "Recover a failed run",
  paused: "Resume a paused run",
};
const readable = (text: string) => text.replaceAll("_", " ");
export function AgentContextNotice({
  workflow,
}: {
  workflow: "course_preparation" | "next_activity";
}) {
  return (
    <div className="agent-context">
      <Icon name="spark" size={20} />
      <p>
        {workflow === "course_preparation"
          ? "The Expert Agent will prepare concepts and source-backed relationships."
          : "The Tutoring Agent will guide activities; the Assessing Agent will evaluate responses."}{" "}
        <span>Current practice uses local rules and authored questions.</span>
      </p>
      <Link href={`/agents?workflow=${workflow}`} className="text-link">
        See agent activity <Icon name="arrow" size={16} />
      </Link>
    </div>
  );
}
export function AgentActivity() {
  const params = useSearchParams();
  const initial = params.get("workflow");
  const [source, setSource] = useState(
    () =>
      new DemoAgentSource(
        initial && Object.hasOwn(scenarios, initial)
          ? (initial as DemoScenario)
          : "course_preparation",
      ),
  );
  const scenario = source.scenario;
  const { run, connection, error, busy, command, refresh } = useAgentRun(
    source,
    source.runId,
  );
  return (
    <>
      <PageHeading
        eyebrow="THE LEARNING TEAM"
        title="Three agents. One learning loop."
        description="Follow the work, the handoffs, and the evidence behind each update."
      />
      <div className="notice inline">
        <Icon name="spark" />
        <p>
          <strong>Scripted frontend preview.</strong> Advance each sample step
          to explore the workflow. No agents are executing. These runs do not
          modify your saved practice or graph.
        </p>
      </div>
      <div className="agent-controls">
        <label>
          Sample workflow
          <select
            value={scenario}
            onChange={(event) =>
              setSource(new DemoAgentSource(event.target.value as DemoScenario))
            }
          >
            {Object.entries(scenarios).map(([key, label]) => (
              <option value={key} key={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <button
          className="button dark"
          disabled={
            !run || connection !== "connected" || !source.remainingSteps
          }
          onClick={() => source.advance()}
        >
          Advance demo step <Icon name="arrow" size={16} />
        </button>
        <button
          className="button secondary"
          onClick={() => setSource(new DemoAgentSource(scenario))}
        >
          Start over
        </button>
      </div>
      {error && (
        <div className="notice" role="alert">
          <p>{error}</p>
          <button className="button secondary" onClick={refresh}>
            Refresh run snapshot
          </button>
        </div>
      )}
      {!run ? (
        <p role="status">Loading run snapshot…</p>
      ) : (
        <>
          <section className="panel run-heading" aria-live="polite">
            <div>
              <span className="eyebrow">{run.label}</span>
              <h2>{readable(run.status)}</h2>
              <p>{run.summary}</p>
            </div>
            <div className="run-meta">
              <span>Demo transport · {connection}</span>
              <span>
                Event {run.lastSequence} · record v{run.recordVersion}
              </span>
              {run.checkpointId && <span>Checkpoint available</span>}
              {run.allowedCommands.map((kind) => (
                <button
                  className="button secondary"
                  key={kind}
                  disabled={busy || connection !== "connected"}
                  onClick={() => command(kind)}
                >
                  {busy ? "Sending…" : `${readable(kind)} from checkpoint`}
                </button>
              ))}
            </div>
          </section>
          <div className="agent-grid">
            {agentRoles.map((role, index) => {
              const agent = run.agents[role];
              return (
                <section
                  key={role}
                  className={`panel agent-card ${run.currentAgent === role ? "agent-current" : ""}`}
                >
                  <div className="agent-card-top">
                    <span className="agent-number">0{index + 1}</span>
                    <span className={`agent-status status-${agent.status}`}>
                      {readable(agent.status)}
                    </span>
                  </div>
                  <h2>{titles[role]}</h2>
                  <h3>{agent.task}</h3>
                  <p>{agent.detail}</p>
                  {agent.tool && (
                    <p className="agent-tool">
                      Tool · <code>{agent.tool}</code>
                    </p>
                  )}
                  {agent.error && <p role="alert">{agent.error.message}</p>}
                </section>
              );
            })}
          </div>
          <div className="agent-detail-grid">
            <section className="panel agent-validation">
              <span className="eyebrow">
                RUNTIME VALIDATION · SYSTEM CONTROL
              </span>
              <h2>{readable(run.validation.status)}</h2>
              <p>{run.validation.summary}</p>
              {run.validation.candidate && (
                <div className="candidate-change">
                  <strong>Proposed learner update</strong>
                  <p>
                    {run.validation.candidate.conceptId} ·{" "}
                    {run.validation.candidate.difficulty}
                    <br />
                    {readable(run.validation.candidate.before)} →{" "}
                    {readable(run.validation.candidate.after)}
                  </p>
                </div>
              )}
              {run.committedChanges.length > 0 ? (
                <div className="committed-change">
                  <strong>Accepted sample evidence</strong>
                  {run.committedChanges.map((change, index) => (
                    <p key={index}>
                      {change.conceptId} → {readable(change.after)} · learner v
                      {change.learnerVersion}
                    </p>
                  ))}
                  <small>
                    This sample commit is isolated from your practice progress.
                  </small>
                </div>
              ) : (
                <p className="muted">
                  No learner-state change committed in this run.
                </p>
              )}
              <p className="agent-help">
                Agents propose outputs. The runtime validates and persists
                accepted updates. Validation is a system control, separate from
                the three agents.
              </p>
            </section>
            <section className="panel agent-outputs">
              <span className="eyebrow">OUTPUTS & SOURCES</span>
              <h2>What the work produces</h2>
              {run.artifacts.length ? (
                run.artifacts.map((artifact) => (
                  <p key={artifact.id}>
                    <strong>{artifact.label}</strong>
                    <br />
                    <span className="tag">{artifact.status}</span>
                  </p>
                ))
              ) : (
                <p>Outputs will appear when an agent produces them.</p>
              )}
              {run.references.map((reference, index) => (
                <p key={index}>
                  {reference.label}
                  {reference.page ? ` · p. ${reference.page}` : ""}
                  <br />
                  <small>Illustrative source reference</small>
                </p>
              ))}
              <Link href="/map" className="text-link">
                Open your course context <Icon name="arrow" size={16} />
              </Link>
            </section>
          </div>
          <section className="panel agent-timeline">
            <span className="eyebrow">PUBLIC ACTIVITY LOG</span>
            <h2>Work and handoffs</h2>
            <p>
              Structured task summaries and tool outcomes. No private reasoning
              or prompts.
            </p>
            {!run.events.length ? (
              <p>Advance the demo to see the first event.</p>
            ) : (
              <ol>
                {run.events.map((event) => (
                  <li key={event.id}>
                    <span className="event-index">
                      {String(event.sequence).padStart(2, "0")}
                    </span>
                    <div>
                      <strong>
                        {event.type === "agent.step"
                          ? `${titles[event.payload.role]} · ${event.payload.task}`
                          : event.type === "agent.handoff"
                            ? `${titles[event.payload.from]} → ${titles[event.payload.to]}`
                            : event.type === "runtime.validation"
                              ? `Runtime · ${event.payload.status}`
                              : `Workflow · ${readable(event.payload.status)}`}
                      </strong>
                      <p>
                        {event.type === "agent.step"
                          ? event.payload.detail
                          : event.type === "agent.handoff"
                            ? event.payload.reason
                            : event.payload.summary}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </>
      )}
    </>
  );
}
