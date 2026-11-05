"use client";

import { useEffect, useId, useState, type ReactNode } from "react";
import { api, targetDifficulty, type Difficulty, type LearningMaterial } from "@/lib/backend";
import { useWorkspace } from "./workspace-provider";
import { LessonContents } from "./study-materials";
import { Practice } from "./practice";
import { RelatedSlides } from "./related-slides";
import { useLearningDialogTitle } from "./learning-dialog";

const tabs = ["Goals", "Learning material", "Quizzes"];

export function ConceptStudy({ conceptId, resource, children }: {
  conceptId: string; resource?: LearningMaterial; children: ReactNode;
}) {
  const [tab, setTab] = useState(0);
  const [practiceConceptId, setPracticeConceptId] = useState<string | null>(null);
  const setDialogTitle = useLearningDialogTitle();
  const ws = useWorkspace();
  const practiceTitle = ws.course?.graph.concepts.find(c => c.id === practiceConceptId)?.title;
  useEffect(() => {
    setDialogTitle(tab === 2 ? practiceTitle || null : null);
    return () => setDialogTitle(null);
  }, [tab, practiceTitle, setDialogTitle]);
  const [savingTarget, setSavingTarget] = useState(false);
  const [targetError, setTargetError] = useState("");
  const concept = ws.course?.graph.concepts.find(c => c.id === conceptId);
  const selectedMaterial = resource;
  async function changeTarget(targetDifficulty: Difficulty) {
    if (!ws.learner) return;
    setSavingTarget(true); setTargetError("");
    try {
      await api(`courses/${ws.courseId}/concepts/${encodeURIComponent(conceptId)}/target`, { targetDifficulty, expectedLearnerVersion: ws.learner.version });
      await ws.refresh();
    } catch (error) { setTargetError((error as Error).message); await ws.refresh(); }
    finally { setSavingTarget(false); }
  }
  const id = useId();
  return <div className="concept-study">
    <div className="concept-study-tabs" role="tablist" aria-label="Study this concept">
      {tabs.map((label, index) => <button key={label} id={`${id}-tab-${index}`} role="tab" aria-selected={tab === index} aria-controls={`${id}-panel-${index}`} tabIndex={tab === index ? 0 : -1} onClick={() => setTab(index)} onKeyDown={event => {
        const next = event.key === "ArrowRight" ? (index + 1) % tabs.length : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
        if (next === null) return;
        event.preventDefault(); setTab(next);
        document.getElementById(`${id}-tab-${next}`)?.focus();
      }}>{label}</button>)}
    </div>
    <section role="tabpanel" id={`${id}-panel-0`} aria-labelledby={`${id}-tab-0`} tabIndex={0} hidden={tab !== 0}>{children}
      {concept?.curriculum && <p>Learning target: <strong>{concept.curriculum.layer[0].toUpperCase() + concept.curriculum.layer.slice(1)}</strong> · Matches this lesson’s curriculum layer.</p>}
      {concept && !concept.curriculum && <div className="live-actions"><label>Learning target <select aria-label="Learning target difficulty" value={targetDifficulty(concept)} disabled={savingTarget || !ws.learner} onChange={event => void changeTarget(event.target.value as Difficulty)}>{["basic", "intermediate", "advanced"].map(level => <option key={level} value={level}>{level[0].toUpperCase() + level.slice(1)}</option>)}</select></label><p>Progress and prerequisite readiness use this target. Practice difficulty adjusts with your answers.</p></div>}
      {targetError && <p role="alert" className="live-error">{targetError}</p>}
    </section>
    <section role="tabpanel" id={`${id}-panel-1`} aria-labelledby={`${id}-tab-1`} tabIndex={0} hidden={tab !== 1}>
      {selectedMaterial ? <article className="study-lesson simple-lesson concept-study-lesson">
        {resource?.curriculum && <p>Curriculum layer: {resource.curriculum.layer}</p>}
        <h3>{selectedMaterial.lesson.title}</h3>
        <LessonContents material={selectedMaterial} />
        <details className="concept-study-sources"><summary>Original source material</summary><RelatedSlides references={selectedMaterial.sources} context="lesson" /></details>
      </article> : <p role="status">The learning material for this concept is still being prepared. You can review its goal in the Goals tab.</p>}
    </section>
    <section role="tabpanel" id={`${id}-panel-2`} aria-labelledby={`${id}-tab-2`} tabIndex={0} hidden={tab !== 2}>
      <div className="simple-practice concept-study-practice"><Practice compact conceptId={conceptId} onTopicChange={setPracticeConceptId} /></div>
    </section>
  </div>;
}
