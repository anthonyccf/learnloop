"use client";

import Link from "next/link";
import { createContext, useContext, useEffect, useRef, useState } from "react";
import katex from "katex";
import { api, overallState, type LearningMaterial } from "@/lib/backend";
import { useWorkspace } from "./workspace-provider";
import { SourceLink } from "./related-slides";
import { LessonPicker } from "./lesson-picker";
import { RichText } from "./rich-text";
import { AgentPortrait } from "./agent-portrait";
import { PreparationStatus } from "./learning-status";
import { WorkedExample } from "./worked-example";

const LessonMath = createContext<string[]>([]);
type PracticeRequest = { id: string; conceptId: string };
const PracticeNavigation = createContext<{ request: PracticeRequest | null; backToStudy: () => void; clearRequest: () => void; retryRequest: () => void }>({ request: null, backToStudy: () => {}, clearRequest: () => {}, retryRequest: () => {} });
export const usePracticeNavigation = () => useContext(PracticeNavigation);
function MathText({ text, block = false, className = "" }: { text: string; block?: boolean; className?: string }) {
  const equations = useContext(LessonMath);
  return <RichText inline={!block} className={className} mathExpressions={equations}>{text}</RichText>;
}

export function LearningWorkspace({ practice }: { practice: React.ReactNode }) {
  const [mode, setMode] = useState<"study" | "practice">("study");
  const [request, setRequest] = useState<PracticeRequest | null>(null);
  const readingPosition = useRef(0);
  const practicePanel = useRef<HTMLDivElement>(null);
  const practiceButton = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const sync = (event?: PopStateEvent) => {
      const params = new URLSearchParams(window.location.search);
      const next = params.get("mode") === "practice" ? "practice" : "study";
      setMode(next);
      const conceptId = params.get("concept");
      if (event && next === "practice" && conceptId && params.get("scope") !== "course") setRequest(previous => previous?.conceptId === conceptId ? previous : { id: crypto.randomUUID(), conceptId });
    };
    sync(); window.addEventListener("popstate", sync); return () => window.removeEventListener("popstate", sync);
  }, []);
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      if (mode === "practice") { practicePanel.current?.focus({ preventScroll: true }); practicePanel.current?.scrollIntoView({ block: "start" }); }
      else { window.scrollTo({ top: readingPosition.current, behavior: "instant" }); practiceButton.current?.focus({ preventScroll: true }); }
    });
    return () => cancelAnimationFrame(frame);
  }, [mode]);
  function changeMode(next: "study" | "practice", conceptId?: string) {
    if (next === "practice") {
      readingPosition.current = window.scrollY;
      practiceButton.current = document.activeElement as HTMLElement;
      if (conceptId && request?.conceptId !== conceptId) setRequest({ id: crypto.randomUUID(), conceptId });
      if (!conceptId) setRequest(null);
    }
    const url = new URL(window.location.href);
    if (conceptId) url.searchParams.set("concept", conceptId);
    if (next === "practice") { url.searchParams.set("mode", "practice"); if (conceptId) url.searchParams.delete("scope"); else url.searchParams.set("scope", "course"); }
    else { url.searchParams.delete("mode"); url.searchParams.delete("scope"); }
    window.history.pushState(null, "", url);
    setMode(next);
  }
  return <PracticeNavigation.Provider value={{ request, backToStudy: () => changeMode("study"), clearRequest: () => setRequest(null), retryRequest: () => setRequest(previous => previous ? { ...previous, id: crypto.randomUUID() } : null) }}>
    <div hidden={mode !== "study"}><StudyMaterials onPractice={conceptId => changeMode("practice", conceptId)} onGeneralPractice={() => changeMode("practice")} /></div>
    <div ref={practicePanel} tabIndex={-1} id="lesson-practice" className="simple-practice" hidden={mode !== "practice"}>
      <button className="learning-back-link" onClick={() => changeMode("study")}>← Back to lesson</button>
      <h1 className="simple-practice-title">Practice</h1>
      {practice}
    </div>
  </PracticeNavigation.Provider>;
}

export function GenerateMaterials() {
  const { course, refresh, runs } = useWorkspace();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = runs.some(run => run.workflow === "course_preparation" && ["queued", "running", "paused"].includes(run.status));
  const missing = course?.documents.filter(doc => doc.status === "published" && doc.lessonCount < (course?.graph.concepts.filter(concept => concept.id.startsWith(`${doc.id}:`)).length || 0)) || [];
  const needingReview = course?.documents.filter(doc => doc.status === "published" && doc.coverage?.analysisVersion !== 2) || [];
  const oldStyle = course?.documents.filter(doc => doc.status === "published" && (doc.postLessonCount ?? doc.lessonCount) < doc.lessonCount) || [];
  if (pending) return <PreparationStatus />;
  if (!missing.length && !needingReview.length && !oldStyle.length && !pending) return <PreparationStatus />;
  return <><PreparationStatus /><div className="generation-note"><p>{needingReview.length ? "Review every section of your existing material to discover additional learning goals. Saved lessons and progress are retained." : oldStyle.length ? "Refresh learning posts with clear bullet points and worked examples that explain calculations step by step." : "Ask the Expert to prepare explanations, worked examples, flashcards, and tests from your existing upload."}</p>
    <button className="button dark" disabled={busy || pending} onClick={async () => {
      setBusy(true); setError("");
      try {
        for (const doc of needingReview) await api(`documents/${doc.id}/analyze`, {});
        for (const doc of missing.filter(doc => !needingReview.some(review => review.id === doc.id))) await api(`documents/${doc.id}/materials`, {});
        for (const doc of oldStyle.filter(doc => !missing.some(m => m.id === doc.id) && !needingReview.some(r => r.id === doc.id))) await api(`documents/${doc.id}/materials`, {});
        await refresh();
      }
      catch (e) { setError((e as Error).message); } finally { setBusy(false); }
    }}>{busy ? "Starting…" : pending ? "Expert is working…" : needingReview.length ? "Review all sections and expand lessons" : oldStyle.length ? "Refresh lesson formatting" : "Generate lessons and tests"}</button>
    {error && <p className="live-error" role="alert">{error}</p>}
  </div></>;
}

function StudyMaterials({ onPractice, onGeneralPractice }: { onPractice: (conceptId: string) => void; onGeneralPractice: () => void }) {
  const { materials, course, learner } = useWorkspace();
  const levels = ["basic", "intermediate", "advanced"] as const;
  const [selectedId, setSelectedId] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [expandedTopic, setExpandedTopic] = useState("");
  useEffect(() => {
    const sync = () => { const id = new URLSearchParams(window.location.search).get("concept") || ""; queueMicrotask(() => { setSelectedId(id); setExpandedTopic(""); }); };
    sync(); window.addEventListener("popstate", sync); return () => window.removeEventListener("popstate", sync);
  }, []);
  const selected = materials.materials.find(material => material.conceptId === selectedId) || materials.materials[0];
  const index = selected ? materials.materials.indexOf(selected) : 0;
  const topics = course?.graph.topics || [];
  const topicFor = (conceptId: string) => topics.find(topic => topic.conceptIds.includes(conceptId))?.id || "__other__";
  const grouped = new Set(topics.flatMap(topic => topic.conceptIds));
  const topicGroups = [
    ...topics.map(topic => ({ id: topic.id, title: topic.title, conceptIds: topic.conceptIds, lessons: materials.materials.filter(item => topic.conceptIds.includes(item.conceptId)) })),
    { id: "__other__", title: topics.length ? "Other lessons" : "Course lessons", conceptIds: materials.materials.filter(item => !grouped.has(item.conceptId)).map(item => item.conceptId), lessons: materials.materials.filter(item => !grouped.has(item.conceptId)) },
  ].filter(group => group.lessons.length);
  const statusLabels: Record<string, string> = { unassessed: "Not assessed", developing: "Developing", demonstrated: "Demonstrated", review_due: "Review due" };
  const topicStatus = (conceptIds: string[]) => {
    const states = conceptIds.map(id => (course?.graph.concepts.find(c => c.id === id) ? overallState(course.graph.concepts.find(c => c.id === id)!, learner) : "unassessed"));
    if (states.includes("review_due")) return "review_due";
    if (states.length && states.every(state => state === "demonstrated")) return "demonstrated";
    if (states.some(state => state === "developing" || state === "demonstrated")) return "developing";
    return "unassessed";
  };
  const heading = useRef<HTMLHeadingElement>(null);
  function selectLesson(id: string) {
    setSelectedId(id); setPickerOpen(false);
    setExpandedTopic(topicFor(id));
    const url = new URL(window.location.href);
    url.searchParams.set("concept", id); url.searchParams.delete("mode");
    window.history.pushState(null, "", url);
    requestAnimationFrame(() => { heading.current?.focus({ preventScroll: true }); heading.current?.scrollIntoView({ block: "start" }); });
  }
  return <LessonMath.Provider value={selected?.lesson.equations.map(equation => equation.latex) || []}>
    <div className="simple-learn-layout">
      <div className="simple-learn-main">
        <div className="simple-learn-toolbar"><div><p>{course?.title}</p><h1>Learn</h1></div>{selected && <button className="lesson-picker-trigger" aria-haspopup="dialog" aria-expanded={pickerOpen} onClick={() => setPickerOpen(true)}>Choose lesson <span className="lesson-picker-chevron" aria-hidden="true" /></button>}</div>
        <PreparationStatus />
        {materials.materials.some(m => m.curriculum) && <nav className="curriculum-pyramid" aria-label="Learning pyramid">
          {[...levels].reverse().map((level, i) => {
            const lessons = materials.materials.filter(m => m.curriculum?.layer === level);
            const total = course?.graph.concepts.filter(c => c.curriculum?.layer === level).length || lessons.length;
            return <button key={level} style={{ width: `${50 + i * 25}%` }} disabled={!lessons.length} aria-current={selected?.curriculum?.layer === level ? "step" : undefined} onClick={() => selectLesson(lessons[0].conceptId)}><strong>{level[0].toUpperCase() + level.slice(1)}</strong><span>{total} {total === 1 ? "lesson" : "lessons"}{lessons.length < total ? ` · ${lessons.length} ready` : ""} · {level === "basic" ? "Foundations" : level === "intermediate" ? "Connect and apply" : "Integrate and judge"}</span></button>;
          })}
        </nav>}
        {!selected ? <section className="simple-lesson-empty"><h2>Learn the idea, then test it</h2><p>{course?.documents.length ? "Your lessons will appear as your materials are prepared." : "Upload your first course material to begin."}</p><Link className="button dark" href="/materials">View materials</Link></section> : <>
        <article className="study-lesson simple-lesson" key={`lesson:${selected.conceptId}`}>
          <h2 ref={heading} tabIndex={-1}>{selected.lesson.title}</h2><p className="lesson-objective"><MathText text={selected.lesson.objective} /></p>
          <div className="simple-lesson-byline"><span><AgentPortrait role="expert" size={26} />Expert · Lesson {index + 1} · <span aria-label={`Curriculum layer: ${selected.curriculum?.layer || "intermediate"}`}>{selected.curriculum?.layer || "intermediate"}</span></span><SourceLink references={selected.sources} context="lesson" /></div>
          {selected.curriculum && <div className="curriculum-connections">
            <p><strong>What this adds:</strong> {selected.curriculum.adds}</p>
            {!!selected.curriculum.assumes.length && <div><strong>Builds on:</strong> {selected.curriculum.assumes.map(id => {
              const parent = course?.graph.concepts.find(c => c.id === id);
              return <button className="learning-back-link" key={id} onClick={() => selectLesson(id)} disabled={!materials.materials.some(m => m.conceptId === id)}>{parent?.title || id}</button>;
            })}</div>}
          </div>}
          <LessonContents material={selected} />
          <div className="lesson-practice"><button className="button dark" onClick={() => onPractice(selected.conceptId)}>Practice this lesson <span aria-hidden="true">→</span></button></div>
          <nav className="simple-lesson-navigation" aria-label="Study lessons"><button disabled={index === 0} onClick={() => selectLesson(materials.materials[index - 1].conceptId)}>← Previous lesson</button><button disabled={index >= materials.materials.length - 1} onClick={() => selectLesson(materials.materials[index + 1].conceptId)}>Next lesson →</button></nav>
        </article>
        {pickerOpen && <LessonPicker selectedId={selected.conceptId} onSelect={selectLesson} onPractice={() => { setPickerOpen(false); onGeneralPractice(); }} onClose={() => setPickerOpen(false)} />}
        </>}
      </div>
      {selected && <aside className="learn-topic-rail" aria-label="Course topics">
        <p className="eyebrow">COURSE TOPICS</p>
        <nav aria-label="Topics and lessons">
          {topicGroups.map(group => {
            const status = topicStatus(group.conceptIds);
            const expanded = (expandedTopic === "" ? topicFor(selected.conceptId) : expandedTopic) === group.id;
            return <section className="learn-topic-group" key={group.id}>
              <button className="learn-topic-toggle" aria-expanded={expanded} onClick={() => setExpandedTopic(expanded ? "__closed__" : group.id)}>
                <span className="learn-topic-title">{group.title}</span>
                <span className={`learn-topic-status ${status}`} title={statusLabels[status]}>{statusLabels[status]}</span>
                <span className="learn-topic-chevron" aria-hidden="true">{expanded ? "⌄" : "›"}</span>
              </button>
              {expanded && <ul>{group.lessons.map(item => <li key={item.conceptId}><button className="learn-subtopic" aria-current={selected.conceptId === item.conceptId ? "page" : undefined} onClick={() => selectLesson(item.conceptId)}>{item.lesson.title}</button></li>)}</ul>}
            </section>;
          })}
        </nav>
      </aside>}
    </div>
  </LessonMath.Provider>;
}

/** Shared reading content for Learn and the map's concept modal. */
export function LessonContents({ material }: { material: LearningMaterial }) {
  return <LessonMath.Provider value={material.lesson.equations.map(equation => equation.latex)}>
          <MathText block className="lesson-explanation lesson-post" text={material.lesson.explanation} />
          {material.lesson.equations.map((equation, i) => <div className="lesson-equation" key={i}><div dangerouslySetInnerHTML={{ __html: katex.renderToString(equation.latex, { displayMode: true, throwOnError: false, trust: false, strict: "ignore", maxExpand: 500, maxSize: 20 }) }} /><p><MathText text={equation.explanation} /></p></div>)}
          <WorkedExample example={material.lesson.workedExample} mathExpressions={material.lesson.equations.map(equation => equation.latex)} />
          <div className="lesson-takeaway"><h3>The key idea</h3><p><MathText text={material.lesson.takeaway} /></p></div>
          <section className="lesson-mistake"><h3>A common mistake</h3><p><MathText text={material.lesson.commonMistake} /></p></section>
          <section className="lesson-flashcards"><h3>Quick recall</h3><p>Try answering before revealing the explanation.</p>{material.lesson.flashcards.map((card, i) => <details key={i}><summary><MathText text={card.front} /></summary><p><MathText text={card.back} /></p></details>)}</section>
  </LessonMath.Provider>;
}
