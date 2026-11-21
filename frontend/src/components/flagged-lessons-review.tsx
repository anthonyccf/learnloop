"use client";
import { useEffect, useState } from "react";
import { api, LearningMaterial } from "@/lib/backend";
import { LearningDialog } from "./learning-dialog";
import { LessonContents } from "./study-materials";
import { useWorkspace } from "./workspace-provider";

type FlaggedLesson = {
  conceptId: string; title: string; code: string; message: string; reviewNotes: string[];
  draft: { lesson: LearningMaterial["lesson"]; questions: { difficulty: string; prompt: string; choices: { id: string; text: string }[] }[] } | null;
  canApprove: boolean; approvalBlocker: string | null;
};

export function FlaggedLessonsReview({ documentId, filename, onClose }: { documentId: string; filename: string; onClose: () => void }) {
  const { refresh } = useWorkspace();
  const [lessons, setLessons] = useState<FlaggedLesson[] | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const fetchLessons = () => api<{ lessons: FlaggedLesson[] }>(`documents/${documentId}/flagged-lessons`);
  function show(data: { lessons: FlaggedLesson[] }) {
    setLessons(data.lessons);
    setSelectedId(current => data.lessons.some(lesson => lesson.conceptId === current) ? current : data.lessons[0]?.conceptId || "");
  }
  useEffect(() => {
    api<{ lessons: FlaggedLesson[] }>(`documents/${documentId}/flagged-lessons`).then(show, e => setError((e as Error).message));
  }, [documentId]);

  const selected = lessons?.find(lesson => lesson.conceptId === selectedId);
  async function act(action: "approve" | "regenerate") {
    if (!selected) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const path = `documents/${documentId}/flagged-lessons/${encodeURIComponent(selected.conceptId)}/${action}`;
      const result = await api<{ remaining?: number; runId?: string }>(path, action === "regenerate" ? { notes } : {});
      setMessage(action === "regenerate"
        ? `The Expert is regenerating "${selected.title}" with your notes. Check the activity log for the result.`
        : result.runId ? `Approved "${selected.title}". All flagged lessons are resolved; the course is being published.` : `Approved "${selected.title}". ${result.remaining} flagged ${result.remaining === 1 ? "lesson remains" : "lessons remain"}.`);
      setNotes("");
      const [data] = await Promise.all([fetchLessons(), refresh()]);
      show(data);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  return <LearningDialog wide title={`Review flagged lessons · ${filename}`} onClose={onClose}>
    <div className="flagged-review">
      {message && <p className="materials-message" role="status">{message}</p>}
      {error && <p className="live-error" role="alert">{error}</p>}
      {!lessons ? <p role="status">Loading flagged lessons…</p> : !lessons.length ? <p>No lessons are waiting for manual review.</p> : <div className="flagged-review-layout">
        <ul className="flagged-review-list" aria-label="Flagged lessons">{lessons.map(lesson => <li key={lesson.conceptId}>
          <button type="button" aria-current={lesson.conceptId === selectedId} onClick={() => { setSelectedId(lesson.conceptId); setNotes(""); setError(""); }}>
            <strong>{lesson.title}</strong><span>{lesson.draft ? "Draft saved" : "No draft"} · {lesson.code.replaceAll("_", " ")}</span>
          </button>
        </li>)}</ul>
        {selected && <section className="flagged-review-detail" aria-label={selected.title}>
          <h3>{selected.title}</h3>
          <div className="flagged-review-feedback"><h4>Why the Expert flagged it</h4><ul>{selected.reviewNotes.map((note, i) => <li key={i}>{note}</li>)}</ul></div>
          {selected.draft ? <>
            <h4>Rejected draft: {selected.draft.lesson.title}</h4>
            <div className="flagged-review-draft"><LessonContents material={{ lesson: selected.draft.lesson }} /></div>
            <h4>Draft questions ({selected.draft.questions.length})</h4>
            <ol className="flagged-review-questions">{selected.draft.questions.map((question, i) => <li key={i}><p><span className="flagged-review-level">{question.difficulty}</span> {question.prompt}</p><ul>{question.choices.map(choice => <li key={choice.id}>{choice.id.toUpperCase()}. {choice.text}</li>)}</ul></li>)}</ol>
            <p className="flagged-review-hint">Answer keys stay private. Approving accepts the lesson and its questions without the failed automatic check.</p>
          </> : <p className="flagged-review-hint">No draft was saved for this lesson (it was flagged before drafts were kept). Regenerate it with notes to produce a reviewable draft.</p>}
          <label htmlFor="flagged-review-notes">Notes for the Expert</label>
          <textarea id="flagged-review-notes" rows={3} maxLength={2000} value={notes} onChange={e => setNotes(e.target.value)} placeholder="e.g. Add the harmonic-mean formula and a short numeric example." />
          <div className="flagged-review-actions">
            <button type="button" className="button secondary" disabled={busy} onClick={() => act("regenerate")}>{busy ? "Working…" : "Regenerate with notes"}</button>
            <button type="button" className="button dark" disabled={busy || !selected.canApprove} title={selected.approvalBlocker || undefined} onClick={() => act("approve")}>Approve draft</button>
          </div>
          {!selected.canApprove && selected.draft && <p className="flagged-review-hint">{selected.approvalBlocker}</p>}
        </section>}
      </div>}
    </div>
  </LearningDialog>;
}
