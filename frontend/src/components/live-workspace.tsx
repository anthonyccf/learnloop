"use client";
import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import { api, Reference, Assessment } from "@/lib/backend";
import { AgentActivityWorkspace } from "./agent-activity-workspace";
import { useWorkspace } from "./workspace-provider";
import { SlideViewer } from "./related-slides";
import { LearningDialog } from "./learning-dialog";
import { GenerateMaterials, LearningWorkspace } from "./study-materials";
import { RichText } from "./rich-text";
import { KnowledgeMap } from "./knowledge-map";
import { Practice } from "./practice";
import { TodayWorkspace } from "./today-workspace";
import { TutorSession } from "./tutor-session";
import { Icon } from "./icons";


const labels: Record<string, string> = { today: "Your learning workspace", materials: "Course materials", learn: "Learn from your materials", map: "My understanding", progress: "Your progress", agents: "Agent activity", summary: "Session summary" };
const readable = (s: string) => s.replaceAll("_", " ");
export function LiveWorkspace({ view }: { view: string }) {
  const ws = useWorkspace();
  return <div className="live-workspace">
    {(view === "learn" || view === "map" || view === "tutor") && ws.course ? null : view === "today" ? <header className="today-heading"><p>{ws.course?.title || "Your workspace"}</p><h1>Today</h1></header> : <div className="page-heading"><div><p className="eyebrow">{ws.course?.title || "YOUR WORKSPACE"}</p><h1>{labels[view]}</h1><p className="subtitle">{view === "materials" ? "Keep your course files and prepared lessons together." : view === "map" ? "Explore how your course concepts connect and where your understanding is growing." : view === "progress" ? "Review your assessed understanding and saved practice history." : view === "agents" ? "Follow your learning team, explore their work, and see what happens next." : "Your materials, learning activities, and progress in one place."}</p></div>{view !== "materials" && view !== "progress" && view !== "agents" && <button className="button secondary" onClick={() => { void ws.loadCourses().then(ws.refresh); }}>Refresh</button>}</div>}
    {ws.error && <p className="live-error" role="alert">{ws.error}</p>}
    {ws.loading ? <p role="status">Connecting to your workspace…</p> : <>
      {view === "materials" ? <Materials /> : !ws.courseId ? <section className="live-card"><h2>Start with your course materials</h2><p>Create a course and upload a PDF or text file to begin.</p><Link className="button dark" href="/materials">Add course materials</Link></section> : !ws.course ? <p role="status">Loading course…</p> : <>
        {view === "today" && <TodayWorkspace key={ws.courseId} />}
        {view === "tutor" && <TutorSession key={ws.courseId} />}
        {view === "learn" && <LearningWorkspace key={ws.courseId} practice={<Practice key={ws.courseId} />} />}
        {view === "map" && <KnowledgeMap key={ws.courseId} />}
        {view === "progress" && <ProgressWorkspace key={ws.courseId} />}
        {view === "agents" && <AgentActivityWorkspace key={ws.courseId} />}
        {view === "summary" && <><AssessmentHistory key={ws.courseId} /><Concepts /></>}
      </>}
    </>}
  </div>;
}

function Materials() {
  const ws = useWorkspace();
  const [title, setTitle] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<{ kind: "course" } | { kind: "document"; id: string } | null>(null);
  const [renameTitle, setRenameTitle] = useState("");
  const input = useRef<HTMLInputElement>(null);
  async function create(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError("");
    try { const course = await api<{ id: string }>("courses", { title: title.trim() }); await ws.loadCourses(); ws.selectCourse(course.id); setTitle(""); setCreateOpen(false); setMessage("Course created. Add your first material when you’re ready."); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function upload(e: FormEvent) {
    e.preventDefault(); const id = ws.courseId; setBusy(true); setError(""); setMessage("");
    const completed: string[] = [];
    try {
      for (const file of files) {
        if (!/\.(pdf|txt)$/i.test(file.name) || file.size === 0 || file.size > 20 * 1024 * 1024) throw new Error(`${file.name}: choose a non-empty PDF or text file up to 20 MiB.`);
        const form = new FormData(); form.append("file", file);
        const receipt = await api<{ duplicate: boolean }>(`courses/${id}/documents`, form);
        completed.push(file.name); setMessage(`${completed.length} of ${files.length} saved${receipt.duplicate ? " (existing material reused)" : ""}. Processing continues in the background.`);
      }
      setFiles([]); if (input.current) input.current.value = ""; setUploadOpen(false);
    } catch (e) { setError((e as Error).message); setFiles(files.filter(f => !completed.includes(f.name))); }
    finally { await ws.refresh(); setBusy(false); }
  }
  function beginCourseRename() {
    setError(""); setRenameTitle(courseName); setRenameTarget({ kind: "course" });
  }
  function beginDocumentRename(doc: NonNullable<typeof ws.course>["documents"][number]) {
    setError(""); setRenameTitle(doc.filename.replace(/\.(pdf|txt)$/i, "")); setRenameTarget({ kind: "document", id: doc.id });
  }
  async function rename(e: FormEvent) {
    e.preventDefault(); if (!renameTarget) return;
    setBusy(true); setError("");
    try {
      if (renameTarget.kind === "course") {
        await api(`courses/${ws.courseId}/rename`, { title: renameTitle.trim() });
        await ws.loadCourses(); await ws.refresh();
        setMessage("Course renamed.");
      } else {
        await api(`documents/${renameTarget.id}/rename`, { title: renameTitle.trim() });
        await ws.refresh();
        setMessage("Material title renamed.");
      }
      setRenameTarget(null);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  const courseName = ws.courses.find(course => course.id === ws.courseId)?.title || "this course";
  const documents = ws.course?.documents || [];
  return <div className="materials-workspace">
    {!ws.courseId ? <section className="materials-empty"><div className="materials-empty-mark" aria-hidden="true">＋</div><h2>Start with a course</h2><p>Create a course to give your readings and notes a home.</p><button className="button dark" onClick={() => { setError(""); setCreateOpen(true); }}>Create a course</button></section> : !ws.course ? <p role="status">Loading course materials…</p> : <>
      <div className="materials-toolbar"><p>{documents.length ? `${documents.length} ${documents.length === 1 ? "file" : "files"} in ${courseName}` : `No files in ${courseName} yet`}</p><div><button className="button secondary" onClick={beginCourseRename}>Rename course</button><button className="button secondary" onClick={() => { setError(""); setCreateOpen(true); }}>New course</button><button className="button dark" onClick={() => { setError(""); setFiles([]); setUploadOpen(true); }}>Add materials</button></div></div>
      {message && <p className="materials-message" role="status">{message}</p>}{error && <p className="live-error" role="alert">{error}</p>}
      <section className="materials-library" aria-labelledby="materials-list-title">
        <header><div><h2 id="materials-list-title">Saved materials</h2><p>Source files and their prepared learning resources.</p></div></header>
        {!documents.length ? <div className="materials-library-empty"><p>Your course is ready for its first reading or set of notes.</p><button className="button secondary" onClick={() => setUploadOpen(true)}>Add a file</button></div> : <ul className="materials-list">{documents.map(doc => {
          const state = doc.status === "published" ? "ready" : doc.status === "needs_review" ? "review" : "working";
          const stateLabel = doc.status === "published" ? "Ready" : doc.status === "needs_review" ? "Needs review" : readable(doc.status);
          const extension = doc.filename.split(".").pop()?.toUpperCase() || "FILE";
          return <li className="materials-item" key={doc.id}><span className="materials-file-icon" aria-hidden="true">{extension}</span><div className="materials-file-copy"><div className="materials-file-heading"><h3 title={doc.filename}>{doc.filename}</h3><button type="button" className="materials-rename-link" aria-label={`Rename ${doc.filename}`} title="Rename material" onClick={() => beginDocumentRename(doc)}><Icon name="edit" size={14} /></button></div><p>{[doc.pages ? `${doc.pages} pages` : "", doc.lessonCount ? `${doc.lessonCount} lessons` : "", doc.testCount ? `${doc.testCount} quizzes` : ""].filter(Boolean).join(" · ") || "Learning resources are being prepared."}</p>{doc.status === "needs_review" && <p className="materials-file-note">Generated resources need review before they can be used.</p>}{doc.coverage?.analysisVersion === 2 && <details className="materials-coverage"><summary>Coverage reviewed</summary><p>{doc.coverage.processedPassages} passages across {doc.coverage.totalSections} sections</p></details>}</div><span className={`materials-state materials-state-${state}`}>{stateLabel}</span>{doc.pages > 0 && <SourceButton reference={{ documentId: doc.id, label: doc.filename, page: 1 }} />}</li>;
        })}</ul>}
      </section>
      {ws.courseId && <GenerateMaterials />}
    </>}
    {createOpen && <LearningDialog title="Create a course" onClose={() => setCreateOpen(false)}><form onSubmit={create} className="materials-dialog-form"><label htmlFor="new-course-title">Course title</label><input id="new-course-title" autoFocus required maxLength={200} value={title} onChange={e => setTitle(e.target.value)} placeholder="e.g. Machine learning foundations" /><p>Give your readings and notes a shared home.</p>{error && <p role="alert" className="live-error">{error}</p>}<button className="button dark" disabled={busy || !title.trim()}>{busy ? "Creating…" : "Create course"}</button></form></LearningDialog>}
    {renameTarget && <LearningDialog title={renameTarget.kind === "course" ? "Rename course" : "Rename material"} onClose={() => setRenameTarget(null)}><form onSubmit={rename} className="materials-dialog-form"><label htmlFor="rename-title">{renameTarget.kind === "course" ? "Course title" : "Material title"}</label><input id="rename-title" autoFocus required maxLength={renameTarget.kind === "course" ? 200 : 235} value={renameTitle} onChange={e => setRenameTitle(e.target.value)} />{renameTarget.kind === "document" && <p>The original file extension stays in place.</p>}{error && <p role="alert" className="live-error">{error}</p>}<button className="button dark" disabled={busy || !renameTitle.trim()}>{busy ? "Saving…" : "Save title"}</button></form></LearningDialog>}
    {uploadOpen && ws.courseId && <LearningDialog title={`Add materials to ${courseName}`} onClose={() => setUploadOpen(false)}><form onSubmit={upload} className="materials-dialog-form"><p>Choose PDF or UTF-8 text files up to 20 MiB each. PDFs can have up to 200 pages; scanned PDFs need text recognition before upload.</p><label htmlFor="material-files">Course materials</label><input ref={input} id="material-files" type="file" accept=".pdf,.txt,application/pdf,text/plain" multiple disabled={busy} onChange={e => { setFiles(Array.from(e.target.files || [])); setError(""); }} />{files.length > 0 && <ul className="materials-selected-files">{files.map((file, index) => <li key={`${file.name}-${index}`}>{file.name} <span>{(file.size / (1024 * 1024)).toFixed(1)} MiB</span></li>)}</ul>}{error && <p role="alert" className="live-error">{error}</p>}<button className="button dark" disabled={busy || !files.length}>{busy ? "Saving…" : `Upload${files.length ? ` ${files.length} ${files.length === 1 ? "file" : "files"}` : " materials"}`}</button></form></LearningDialog>}
  </div>;
}

function Concepts() {
  const { course, learner } = useWorkspace();
  if (!course?.graph.concepts.length) return <section className="live-card"><h2>Your understanding starts here</h2><p>Published concepts will appear once your materials finish processing.</p><Link className="button secondary" href="/materials">View materials</Link></section>;
  return <section className="live-card"><h2>Concepts and evidence</h2><p>Progress reflects assessed practice at each difficulty.</p>{course.graph.concepts.map(c => <article className="live-concept" key={c.id}><h3>{c.title}</h3><p>{c.summary}</p><div className="live-actions">{["basic", "intermediate", "advanced"].map(level => <span className="live-pill" key={level}>{level}: {readable(learner?.concepts[c.id]?.[level]?.state || "unassessed")}</span>)}</div>{course.graph.prerequisites.filter(p => p.dependent === c.id).map(p => <p key={p.prerequisite}>Prerequisite: {course.graph.concepts.find(x => x.id === p.prerequisite)?.title || p.prerequisite}</p>)}<details><summary>Generated source notes</summary>{c.sources.map(s => <blockquote key={s.chunkId}>{s.quote}</blockquote>)}</details></article>)}</section>;
}

const progressLevels = ["basic", "intermediate", "advanced"] as const;
const progressStates = ["demonstrated", "developing", "review_due", "unassessed"] as const;
const progressStateLabels: Record<(typeof progressStates)[number], string> = {
  demonstrated: "Demonstrated",
  developing: "Developing",
  review_due: "Review due",
  unassessed: "Not assessed",
};

function ProgressWorkspace() {
  const { course, learner } = useWorkspace();
  const concepts = course?.graph.concepts || [];
  const counts = Object.fromEntries(progressLevels.map(level => [level, Object.fromEntries(progressStates.map(state => [state, concepts.filter(concept => (learner?.concepts[concept.id]?.[level]?.state || "unassessed") === state).length]))])) as Record<(typeof progressLevels)[number], Record<(typeof progressStates)[number], number>>;

  return <div className="progress-workspace">
    <section className="progress-evidence" aria-labelledby="progress-evidence-title">
      <div className="progress-section-heading"><div><h2 id="progress-evidence-title">Evidence by difficulty</h2><p>Progress comes from assessed practice, not time spent reading.</p></div><span>{concepts.length} concepts</span></div>
      {concepts.length ? <div className="progress-levels" role="table" aria-label="Evidence counts by difficulty">
        <div className="progress-level-header" role="row"><span role="columnheader">Difficulty</span>{progressStates.map(state => <span role="columnheader" key={state}>{progressStateLabels[state]}</span>)}</div>
        {progressLevels.map(level => <div className="progress-level-row" role="row" key={level}><strong role="rowheader">{readable(level)}</strong>{progressStates.map(state => <span role="cell" key={state}>{counts[level][state]}</span>)}</div>)}
      </div> : <p className="progress-empty">Concept evidence will appear after your course materials are prepared.</p>}
    </section>
    <AssessmentHistory key={course?.id} compact />
    <ProgressConceptBrowser concepts={concepts} prerequisites={course?.graph.prerequisites || []} learner={learner} />
  </div>;
}

function ProgressConceptBrowser({ concepts, prerequisites, learner }: { concepts: NonNullable<ReturnType<typeof useWorkspace>["course"]>["graph"]["concepts"]; prerequisites: NonNullable<ReturnType<typeof useWorkspace>["course"]>["graph"]["prerequisites"]; learner: ReturnType<typeof useWorkspace>["learner"] }) {
  const [query, setQuery] = useState("");
  const [showAll, setShowAll] = useState(false);
  const filtered = concepts.filter(concept => `${concept.title} ${concept.summary}`.toLowerCase().includes(query.trim().toLowerCase())).sort((a, b) => a.title.localeCompare(b.title));
  const visible = showAll || query.trim() ? filtered : filtered.slice(0, 8);
  return <section className="progress-concept-browser" aria-labelledby="progress-concepts-title">
    <details>
      <summary id="progress-concepts-title"><span>Browse concepts</span><small>{concepts.length} concepts</small></summary>
      <div className="progress-concept-content">
        <label className="progress-search-label" htmlFor="progress-concept-search">Find a concept</label>
        <input id="progress-concept-search" type="search" value={query} onChange={event => { setQuery(event.target.value); setShowAll(false); }} placeholder="Search by concept or topic" />
        <p className="progress-result-count" aria-live="polite">{filtered.length} {filtered.length === 1 ? "concept" : "concepts"}</p>
        {!filtered.length ? <p className="progress-empty">No concepts match “{query}”. Try another search.</p> : <div className="progress-concept-list">{visible.map(concept => <details className="progress-concept" key={concept.id}>
          <summary><span>{concept.title}</span><span className="progress-concept-states">{progressLevels.map(level => { const state = learner?.concepts[concept.id]?.[level]?.state || "unassessed"; return <span key={level} title={`${readable(level)}: ${progressStateLabels[state as keyof typeof progressStateLabels] || readable(state)}`}><i className={`progress-state-dot ${state}`} aria-hidden="true" />{readable(level)}</span>; })}</span></summary>
          <div className="progress-concept-detail"><p>{concept.summary}</p>
            {prerequisites.filter(edge => edge.dependent === concept.id).length > 0 && <p className="progress-prerequisites">Prerequisites: {prerequisites.filter(edge => edge.dependent === concept.id).map(edge => concepts.find(parent => parent.id === edge.prerequisite)?.title || edge.prerequisite).join(", ")}</p>}
            {concept.sources.length > 0 && <details><summary>Source notes</summary>{concept.sources.map(source => <blockquote key={source.chunkId}>{source.quote}</blockquote>)}</details>}
          </div>
        </details>)}</div>}
        {!query.trim() && filtered.length > 8 && <button className="progress-show-more" onClick={() => setShowAll(value => !value)}>{showAll ? "Show fewer" : `Show all ${filtered.length} concepts`}</button>}
      </div>
    </details>
  </section>;
}

function AssessmentHistory({ compact = false }: { compact?: boolean }) {
  const { courseId, course, learner } = useWorkspace();
  const [items, setItems] = useState<{ id: string; conceptId: string; at: string; difficulty: string; assessment: Assessment | null }[]>([]);
  const [error, setError] = useState("");
  const [showAll, setShowAll] = useState(false);
  useEffect(() => {
    let active = true;
    api<typeof items>(`courses/${courseId}/assessments`).then(data => { if (active) { setItems(data); setError(""); } }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [courseId, learner?.version]);
  const recent = [...items].sort((a, b) => b.at.localeCompare(a.at));
  const visible = compact && !showAll ? recent.slice(0, 5) : recent;
  return <section className={compact ? "progress-history" : "live-card"} aria-labelledby={compact ? "progress-history-title" : undefined}>
    <div className={compact ? "progress-section-heading" : ""}><div><h2 id={compact ? "progress-history-title" : undefined}>{compact ? "Recent practice" : "Saved practice history"}</h2>{compact && <p>{items.length ? `${items.length} saved ${items.length === 1 ? "answer" : "answers"}` : "Your assessed answers will appear here."}</p>}</div>{compact && <Link href="/learn">Continue learning</Link>}</div>
    {error && <p role="alert" className="live-error">{error}</p>}{!items.length && !error && <p className={compact ? "progress-empty" : ""}>No answers submitted yet. Start a learning session to build evidence.</p>}
    {visible.map(item => {
      const title = course?.graph.concepts.find(concept => concept.id === item.conceptId)?.title || item.conceptId;
      const result = item.assessment ? item.assessment.uncertain ? "Needs another check" : item.assessment.correct ? "Correct" : "Incorrect" : "Awaiting assessment";
      const date = new Date(item.at);
      const detail = [item.assessment?.feedback, item.assessment?.explanation].filter((value, index, values) => value && values.indexOf(value) === index);
      return compact ? <details className="progress-history-item" key={item.id}><summary><span className="progress-history-title">{title}</span><span className="progress-history-meta">{date.toLocaleDateString(undefined, { month: "short", day: "numeric" })} · {readable(item.difficulty)} · {result}{item.assessment?.hinted ? " · Hint used" : ""}</span></summary>{detail.map((text, index) => <div className="progress-history-feedback" key={index}>{index > 0 && <h3>Explanation</h3>}<RichText>{text}</RichText></div>)}</details>
        : <div className="live-concept" key={item.id}><h3>{title}</h3><p>{date.toLocaleString()} · {readable(item.difficulty)} · {result}</p><RichText>{item.assessment?.feedback}</RichText><RichText>{item.assessment?.explanation}</RichText></div>;
    })}
    {compact && recent.length > 5 && <button className="progress-show-more" onClick={() => setShowAll(value => !value)}>{showAll ? "Show recent only" : `Show all ${recent.length} answers`}</button>}
    {!compact && <Link className="button secondary" href="/learn">Continue learning</Link>}
  </section>;
}

function SourceButton({ reference }: { reference: Reference }) {
  const [open, setOpen] = useState(false);
  return <div className="material-preview"><button className="button secondary" aria-expanded={open} onClick={() => setOpen(value => !value)}>{open ? "Hide source" : "View source"}</button>{open && <SlideViewer key={`${reference.documentId}-${reference.page}`} reference={reference} />}</div>;
}

