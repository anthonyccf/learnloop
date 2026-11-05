import type { Assessment } from "@/lib/backend";

export function AssessmentDetails({ assessment }: { assessment: Assessment }) {
  if (!assessment.rubricCoverage?.length) return null;
  return <details className="assessment-details"><summary>Rubric coverage · {Math.round((assessment.rubricScore || 0) * 100)}%</summary>
    <ul>{assessment.rubricCoverage.map(c => <li key={c.criterionId}><strong>{c.description}: {Math.round(c.score * 100)}%</strong><p>{c.reason}</p></li>)}</ul>
    {assessment.partial && <p>This answer met part of the rubric. It does not count as independent demonstrated evidence.</p>}
    {assessment.confirmedWeakness ? <p>Two distinct independent rubric failures confirm a weakness at this difficulty. Progress is Developing. Earlier evidence is retained; two fresh independent rubric-meeting answers are needed to demonstrate recovery.</p> : assessment.contradiction && <p>This conflicts with earlier evidence and needs reassessment.</p>}
    {assessment.evidenceOutcome === "recovery_progress" && <p>Recovery is in progress. One more distinct independent rubric-meeting answer is needed at this difficulty.</p>}
    {assessment.misconceptions?.map((m, i) => <p key={i}>{m.description} — “{m.responseQuote}”</p>)}
  </details>;
}
