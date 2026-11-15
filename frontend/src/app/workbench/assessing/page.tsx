"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AssessmentActivity, type AssessmentRun } from "@/components/assessment-activity";
import { AssessmentDetails } from "@/components/assessment-details";
import { ExpertWorkbenchShell } from "@/components/expert-workbench-shell";
import { RichText } from "@/components/rich-text";
import { type TutorHandoff } from "@/components/tutor-handoffs";
import { useWorkspace } from "@/components/workspace-provider";
import { api, type Assessment } from "@/lib/backend";
import { readExpertTemplates, type AgentPromptTemplate } from "@/lib/expert-templates";

type Memory = {
  id: string; name: string; courseId: string;
  history: { id: string; conceptId: string; difficulty: string; assessment: Assessment }[];
  handoffs?: TutorHandoff[];
  runs: AssessmentRun[];
};
const TEMPLATE_KEY = "learnloop-tutor-run-template-id";

export default function AssessingWorkbenchPage() {
  const ws = useWorkspace();
  const [templates, setTemplates] = useState<AgentPromptTemplate[]>([]);
  const [templateId, setTemplateId] = useState("");
  const [loadedMemory, setMemory] = useState<Memory | null>(null);
  const memory = loadedMemory?.courseId === ws.courseId ? loadedMemory : null;
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const update = () => {
      const available = readExpertTemplates().filter(item => item.agent === "tutor");
      setTemplates(available);
      let saved = "";
      try { saved = localStorage.getItem(TEMPLATE_KEY) || ""; } catch {}
      setTemplateId(available.some(item => item.id === saved) ? saved : "");
    };
    update();
    window.addEventListener("storage", update);
    window.addEventListener("learnloop-expert-templates-updated", update);
    return () => { window.removeEventListener("storage", update); window.removeEventListener("learnloop-expert-templates-updated", update); };
  }, []);

  useEffect(() => {
    let active = true;
    if (!ws.courseId) return;
    let first = true;
    const refresh = async () => {
      if (first) setLoading(true);
      try {
        const items = await api<{ id: string; name: string }[]>(`workbench/courses/${ws.courseId}/memories`);
        let saved = "";
        try { saved = localStorage.getItem(`learnloop-tutor-memory:${ws.courseId}`) || ""; } catch {}
        const id = items.some(item => item.id === saved) ? saved : items[0]?.id;
        const data = id ? await api<Memory>(`workbench/memories/${id}`) : null;
        if (active) { setMemory(data?.courseId === ws.courseId ? data : null); setError(""); }
      } catch (cause) { if (active) setError((cause as Error).message); }
      finally { if (active && first) setLoading(false); first = false; }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, [ws.courseId]);

  function selectTemplate(id: string) {
    setTemplateId(id);
    try { if (id) localStorage.setItem(TEMPLATE_KEY, id); else localStorage.removeItem(TEMPLATE_KEY); } catch {}
  }
  const handoffs = (memory?.handoffs || []).filter(item => item.request.targetAgent === "assessing");
  const conceptName = (id: string) => ws.course?.graph.concepts.find(item => item.id === id)?.title || id;

  return <ExpertWorkbenchShell activePage="run" activeAgent="assessing">
    <div className="expert-page-heading"><div><p className="expert-eyebrow">ASSESSING AGENT · RUN</p><h1>Assessing · Run</h1><p className="expert-page-description">Follow assessments requested by the Tutor and review the feedback returned to its learning memory.</p></div></div>
    {(error || ws.error) && <p className="expert-alert" role="alert">{error || ws.error}</p>}
    {!ws.courseId ? <section className="expert-empty"><h2>Choose a course</h2><p>Select a course to view Tutor assessment activity.</p></section> : <div className="expert-columns">
      <div className="expert-left-column">
        <section className="expert-card tutor-workbench-card"><div className="expert-card-heading"><div><h2>Start with the Tutor</h2><p>The Tutor requests an assessment when an answer is submitted.</p></div></div>
          <label className="expert-field-label">Tutor template<select value={templateId} onChange={event => selectTemplate(event.target.value)}><option value="">Backend defaults</option>{templates.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <p className="tutor-workbench-note">This selection is shared with the Tutor run page. The Tutor uses its learning plan and response prompts and model settings; its question prompt and tool switches are not applied.</p>
          <Link href="/workbench/tutor" className="expert-button primary">Open Tutor run</Link>
          <p className="tutor-workbench-note">Choose or create a test memory there, run a quiz, and submit an answer. Assessment runs automatically and is saved to that memory.</p>
          <p className="tutor-workbench-note">Assessing uses backend defaults; Assessing templates are not connected to the runtime yet.</p>
        </section>
        <section className="expert-card tutor-workbench-card"><div className="expert-card-heading"><div><h2>Assessment feedback</h2><p>{memory ? `Selected Tutor memory: ${memory.name}` : "The selected Tutor memory will appear here."}</p></div></div>
          {loading ? <p className="expert-muted">Loading assessment activity…</p> : memory?.history.length ? memory.history.map(item => <article className="tutor-feedback" key={item.id}><strong>{conceptName(item.conceptId)} · {item.difficulty} · {item.assessment.uncertain ? "Review needed" : item.assessment.correct ? "Correct" : "Keep practicing"}</strong><RichText>{item.assessment.feedback}</RichText><RichText>{item.assessment.explanation}</RichText><AssessmentDetails assessment={item.assessment} /></article>) : <p className="expert-muted">No completed assessments in the selected Tutor memory yet.</p>}
        </section>
      </div>
      <div className="expert-left-column"><section className="expert-card tutor-workbench-card tutor-trace"><div className="expert-card-heading"><div><h2>Assessment handoffs</h2><p>Requests and their status for the selected Tutor memory. Updates automatically.</p></div></div>
        {handoffs.length ? <AssessmentActivity handoffs={handoffs} runs={memory?.runs || []} conceptName={conceptName} /> : <p className="expert-muted">A handoff appears here after the Tutor submits an answer for assessment.</p>}
        {handoffs.some(item => item.retryable) && <p className="tutor-workbench-note">Open the Tutor run to retry an eligible handoff.</p>}
      </section></div>
    </div>}
  </ExpertWorkbenchShell>;
}
