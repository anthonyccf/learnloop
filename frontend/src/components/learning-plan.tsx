"use client";

import { useEffect, useState } from "react";
import { api, type LearningPlan as Plan } from "@/lib/backend";
import { useWorkspace } from "./workspace-provider";

export function LearningPlan({ current }: { current?: Plan }) {
  const { course, courseId } = useWorkspace();
  const [plan, setPlan] = useState<Plan | null>(null);
  const [description, setDescription] = useState("");
  const [scope, setScope] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    if (courseId) void api<Plan>(`courses/${courseId}/plan`).then(next => {
      if (active) { setPlan(next); setDescription(next.goal.description); setScope(next.goal.conceptIds[0] || ""); }
    }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [courseId]);
  const latest = current && (!plan || current.version >= plan.version) ? current : plan;
  async function save() {
    if (!latest) return;
    setBusy(true); setMessage(""); setError("");
    try {
      const learner = await api<{ version: number }>(`courses/${courseId}/learner-state`);
      const next = await api<Plan>(`courses/${courseId}/plan/revise`, {
        operationId: crypto.randomUUID(), expectedPlanVersion: latest.version, expectedLearnerVersion: learner.version,
        goal: { description, conceptIds: scope ? [scope] : [] },
        activityIds: [],
        reviewDates: Object.entries(latest.reviewDates || {}).map(([conceptId, reviewAt]) => ({ conceptId, reviewAt })),
      });
      setPlan(next); setMessage("Goal saved. Your tutor will use it when preparing the next activity.");
    } catch (e) {
      setError((e as Error).message);
      try { setPlan(await api<Plan>(`courses/${courseId}/plan`)); } catch {}
    } finally { setBusy(false); }
  }
  return <section className="tutor-session-note learning-plan-panel" aria-label="Learning goal and plan">
    <h3>Your learning goal</h3><p>Your tutor uses this goal for upcoming activities. A focused session keeps its selected topic.</p>
    <label>What would you like to understand?<textarea value={description} maxLength={600} rows={3} onChange={event => setDescription(event.target.value)} /></label>
    <label>Goal topic<select value={scope} onChange={event => setScope(event.target.value)}><option value="">Whole course</option>{course?.graph.concepts.map(c => <option key={c.id} value={c.id}>{c.title}</option>)}</select></label>
    <button className="button secondary" disabled={busy || !latest || description.trim().length < 5} onClick={() => void save()}>{busy ? "Saving…" : "Save goal and revise plan"}</button>
    {latest?.selected && <><p><strong>Current step: {latest.selected.action.replaceAll("_", " ")}</strong> · {latest.selected.difficulty}</p><p>{latest.selected.title}</p><p>{latest.reason}</p></>}
    {message && <p role="status">{message}</p>}{error && <p className="live-error" role="alert">{error}</p>}
  </section>;
}
