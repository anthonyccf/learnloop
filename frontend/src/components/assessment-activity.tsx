import type { TutorHandoff } from "./tutor-handoffs";
import { TutorHandoffs } from "./tutor-handoffs";

export type AssessmentRun = { id: string; events?: { type: string; at: string; sequence?: number; payload?: Record<string, unknown> }[] };

function field(payload: Record<string, unknown> | undefined, key: string) {
  return typeof payload?.[key] === "string" ? payload[key] as string : "";
}

export function AssessmentActivity({ handoffs, runs, conceptName, eventsForHandoff }: { handoffs: TutorHandoff[]; runs: AssessmentRun[]; conceptName: (id: string) => string; eventsForHandoff?: (handoff: TutorHandoff, events: NonNullable<AssessmentRun["events"]>) => NonNullable<AssessmentRun["events"]> }) {
  return <div className="assessing-activity-list">{handoffs.map(handoff => {
    const run = runs.find(item => item.id === handoff.runId);
    const runEvents = run?.events || [];
    const events = (eventsForHandoff ? eventsForHandoff(handoff, runEvents) : runEvents).filter(event => ["agent.step", "runtime.validation", "run.status"].includes(event.type));
    return <div key={handoff.request.requestId}>
      <TutorHandoffs handoffs={[handoff]} busy={false} conceptName={conceptName} onRetry={() => {}} />
      <details className="assessing-activity-details" open>
        <summary>Agent activity {events.length > 0 && <span>· {events.length} events</span>}</summary>
        {events.length ? <ol>{events.map((event, index) => {
          const status = field(event.payload, "status").replaceAll("_", " ");
          const task = field(event.payload, "task");
          const title = event.type === "agent.step" ? task || "Agent step" : event.type === "runtime.validation" ? `Validation ${status || "updated"}` : `Run ${status || "updated"}`;
          const detail = field(event.payload, "detail") || field(event.payload, "summary");
          const tool = field(event.payload, "tool");
          const scope = field(event.payload, "scope");
          const date = new Date(event.at);
          return <li key={`${event.sequence ?? index}-${event.at}`}><div className="assessing-activity-heading"><strong>{title}</strong>{!Number.isNaN(date.getTime()) && <time dateTime={event.at}>{date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })}</time>}</div>
            {detail && <p>{detail}</p>}
            {(tool || scope) && <small>{tool ? `Tool: ${tool}` : `Scope: ${scope.replaceAll("_", " ")}`}</small>}
          </li>;
        })}</ol> : <p className="expert-muted">No detailed activity was recorded for this handoff.</p>}
      </details>
    </div>;
  })}</div>;
}
