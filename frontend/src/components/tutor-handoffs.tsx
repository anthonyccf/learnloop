"use client";

export type TutorHandoff = {
  runId: string; status: string; summary: string; retryable: boolean;
  result: { assessmentId?: string; learnerVersion?: number; sourceCount?: number } | null;
  request: { requestId: string; parentRunId: string | null; targetAgent: string; task: string; conceptId?: string; difficulty?: string };
};

export function TutorHandoffs({ handoffs, lastRunId, busy, onRetry, conceptName }: {
  handoffs: TutorHandoff[]; lastRunId?: string; busy: boolean;
  onRetry: () => void; conceptName: (id: string) => string;
}) {
  if (!handoffs.length) return <p className="tutor-handoffs-empty">Agent handoffs appear here when the Tutor requests help.</p>;
  return <div className="tutor-handoffs" aria-label="Agent handoffs" aria-live="polite">{handoffs.map(handoff => {
    const expert = handoff.request.targetAgent === "expert";
    const item = handoff.request.task === "generate_lesson" ? "lesson" : "question";
    const status = handoff.status.replaceAll("_", " ");
    return <article className={`tutor-handoff tutor-handoff-${handoff.status}`} key={handoff.request.requestId}>
      <div className="tutor-handoff-heading"><strong>Tutor → {expert ? "Expert" : "Assessing"}</strong><span className="tutor-handoff-status">{status}</span></div>
      <p>{expert ? `Prepare a ${item}` : "Assess the submitted answer"}{handoff.request.conceptId ? ` · ${conceptName(handoff.request.conceptId)}` : ""}{handoff.request.difficulty ? ` · ${handoff.request.difficulty}` : ""}</p>
      {handoff.result ? <p className="tutor-handoff-result"><strong>{expert ? "Expert → Tutor" : "Assessing → Tutor"}:</strong> {expert ? `Source-validated ${item} ready.` : "Feedback and learning memory saved."}</p> : <p>{handoff.summary}</p>}
      {handoff.status === "failed" || handoff.status === "needs_review" ? <p>Check the message above, or choose another learning activity.</p> : null}
      {handoff.retryable && handoff.runId === lastRunId && <button type="button" className="expert-button secondary" disabled={busy} onClick={onRetry}>Retry handoff</button>}
    </article>;
  })}</div>;
}
