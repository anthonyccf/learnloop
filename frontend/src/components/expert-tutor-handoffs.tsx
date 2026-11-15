"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AssessmentActivity, type AssessmentRun } from "./assessment-activity";
import type { TutorHandoff } from "./tutor-handoffs";
import { api } from "../lib/backend";

type Memory = { id: string; name: string; courseId: string; handoffs?: TutorHandoff[]; runs: AssessmentRun[] };
type Event = NonNullable<AssessmentRun["events"]>[number];

// Expert handoffs are recorded on the parent Tutor run. Match the known
// lesson/question markers when a run contains both kinds of request.
export function expertHandoffEvents(handoff: TutorHandoff, events: Event[], handoffs: TutorHandoff[]) {
  const shared = handoffs.some(other => other.runId === handoff.runId && other.request.requestId !== handoff.request.requestId);
  const kind = handoff.request.task === "generate_lesson" ? "lesson" : "question";
  return events.filter(event => {
    if (event.type !== "agent.step" || event.payload?.role !== "expert") return false;
    if (!shared) return true;
    const detail = typeof event.payload.detail === "string" ? event.payload.detail.toLowerCase() : "";
    return detail.includes(kind);
  });
}

export function ExpertTutorHandoffs({ courseId, concepts }: { courseId: string; concepts: { id: string; title: string }[] }) {
  const [loaded, setLoaded] = useState<Memory | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const memory = loaded?.courseId === courseId ? loaded : null;

  useEffect(() => {
    let active = true;
    let timer: number;
    const refresh = async () => {
      try {
        const items = await api<{ id: string }[]>(`workbench/courses/${courseId}/memories`);
        let saved = "";
        try { saved = localStorage.getItem(`learnloop-tutor-memory:${courseId}`) || ""; } catch {}
        const id = items.some(item => item.id === saved) ? saved : items[0]?.id;
        const data = id ? await api<Memory>(`workbench/memories/${id}`) : null;
        if (active) { setLoaded(data?.courseId === courseId ? data : null); setError(""); }
      } catch (cause) { if (active) setError((cause as Error).message); }
      finally { if (active) { setLoading(false); timer = window.setTimeout(refresh, 3000); } }
    };
    void refresh();
    return () => { active = false; window.clearTimeout(timer); };
  }, [courseId]);

  const handoffs = (memory?.handoffs || []).filter(item => item.request.targetAgent === "expert");
  return <section className="expert-card tutor-workbench-card" aria-labelledby="expert-tutor-handoffs-title">
    <div className="expert-card-heading"><div><h2 id="expert-tutor-handoffs-title">Tutor requests to Expert</h2><p>{memory ? `Selected Tutor memory: ${memory.name} · Current session · Updates automatically` : "Expert handoffs from the selected Tutor memory appear here."}</p></div></div>
    <p className="tutor-workbench-note">These requests use published course materials and are separate from material ingestion. The workspace material filter does not restrict them.</p>
    {error ? <p className="expert-alert" role="alert">Could not load Tutor handoffs: {error}</p> : loading && !memory ? <p className="expert-muted" role="status">Loading Tutor handoffs…</p> : handoffs.length ? <AssessmentActivity handoffs={handoffs} runs={memory?.runs || []} conceptName={id => concepts.find(item => item.id === id)?.title || id} eventsForHandoff={(handoff, events) => expertHandoffEvents(handoff, events, handoffs)} /> : <p className="expert-muted">No Expert handoffs in the selected Tutor session yet.</p>}
    {handoffs.some(item => item.retryable) && <p className="tutor-workbench-note">Open the Tutor run to retry an eligible handoff.</p>}
    <p className="tutor-workbench-note"><Link href="/workbench/tutor">Open Tutor run</Link> to change the selected memory or start a learning activity.</p>
  </section>;
}
