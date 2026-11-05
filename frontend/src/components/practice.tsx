"use client";

import { useEffect, useRef, useState } from "react";
import { api, overallState, type StudySession } from "@/lib/backend";
import { useWorkspace } from "./workspace-provider";
import { usePracticeNavigation } from "./study-materials";
import { SourceLink } from "./related-slides";
import { RichText } from "./rich-text";
import { AgentPortrait } from "./agent-portrait";
import { PracticeStatus } from "./learning-status";
import { AssessmentDetails } from "./assessment-details";

export function Practice({ conceptId, onTopicChange, compact = false }: { conceptId?: string; onTopicChange?: (conceptId: string | null) => void; compact?: boolean }) {
  const ws = useWorkspace(); const [session, setSession] = useState<StudySession | null>(null);
  const navigation = usePracticeNavigation();
  const request = navigation.request;
  const [handledRequest, setHandledRequest] = useState("");
  const [focusError, setFocusError] = useState("");
  const [choice, setChoice] = useState(""); const [hint, setHint] = useState("");
  const [reasoning, setReasoning] = useState("");
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const [pendingTask, setPendingTask] = useState<"question" | "hint" | "save" | null>(null);
  const operation = useRef<{ activity: string; choice: string; reasoning: string | null; version: number; id: string } | null>(null);
  const lock = useRef(false);
  const requestVersion = useRef(0);
  const sessionId = session?.id; const sessionStatus = session?.status;
  const activityId = session?.activity?.id;
  const focusCourseId = ws.courseId, refreshWorkspace = ws.refresh;
  const requestedId = request?.id, requestedConcept = request?.conceptId;
  useEffect(() => {
    if (!requestedId || !requestedConcept) return;
    let active = true;
    lock.current = true;
    requestVersion.current += 1;
    void (async () => {
      try {
        let focused: StudySession | null = null;
        for (;;) {
          try {
            const state = await api<{ version: number }>(`courses/${focusCourseId}/learner-state`);
            focused = await api<StudySession>(`courses/${focusCourseId}/sessions`, { expectedLearnerVersion: state.version, conceptId: requestedConcept });
            break;
          } catch (error) {
            const message = (error as Error).message;
            if (!active || !message.includes("already preparing a question")) throw error;
            await new Promise(resolve => setTimeout(resolve, 2000));
            if (!active) return;
          }
        }
        if (active && focused) { setSession(focused); setFocusError(""); setChoice(""); setHint(""); operation.current = null; await refreshWorkspace(); }
      } catch (error) { if (active) setFocusError((error as Error).message); }
      finally { if (active) { setHandledRequest(requestedId); lock.current = false; } }
    })();
    return () => { active = false; lock.current = false; };
  }, [requestedId, requestedConcept, focusCourseId, refreshWorkspace]);
  useEffect(() => { queueMicrotask(() => { setChoice(""); setHint(""); setReasoning(""); }); }, [activityId]);
  useEffect(() => {
    if (activityId && session?.activity?.status === "pending") void api(`activities/${activityId}/present`, {}).catch(() => {});
  }, [activityId, session?.activity?.status]);
  useEffect(() => {
    if (!sessionId || sessionStatus !== "active") return;
    let active = true;
    const timer = setInterval(() => { if (lock.current) return; const version = requestVersion.current; api<StudySession>(`sessions/${sessionId}`).then(s => { if (!active || lock.current || version !== requestVersion.current) return; setSession(s); setError(previous => previous.startsWith("Cannot reach the learning server.") ? "" : previous); }).catch(e => { if (active) setError(e.message); }); }, 3000);
    return () => { active = false; clearInterval(timer); };
  }, [sessionId, sessionStatus]);
  async function action(work: () => Promise<void>, task: typeof pendingTask = null) { if (lock.current) return; lock.current = true; requestVersion.current += 1; setBusy(true); setPendingTask(task); setError(""); try { await work(); await ws.refresh(); } catch (e) { setError((e as Error).message); } finally { lock.current = false; setBusy(false); setPendingTask(null); } }
  const a = session?.activity && (!conceptId || !session.targetConceptId || session.activity.conceptId === conceptId) ? session.activity : null;
  const activeConcept = ws.course?.graph.concepts.find(c => c.id === a?.conceptId);
  const topicComplete = activeConcept && overallState(activeConcept, ws.learner) === "demonstrated";
  const displayedConceptId = a?.conceptId || session?.targetConceptId || null;
  useEffect(() => { onTopicChange?.(displayedConceptId); }, [displayedConceptId, onTopicChange]);
  // Practice is shared across the workspace. Another view can change its target
  // while this modal stays open. Course-wide continuation lets the tutor move
  // to another topic once the selected concept is complete.
  if (conceptId && session?.targetConceptId && session.targetConceptId !== conceptId) return <section className="practice-question-panel">
    <h3>Practice this concept</h3><p>Your active practice is on another concept. Resume here to practice this topic.</p>
    <button className="button dark" disabled={busy} onClick={() => void action(async () => {
      const state = await api<{ version: number }>(`courses/${ws.courseId}/learner-state`);
      setSession(await api<StudySession>(`courses/${ws.courseId}/sessions`, { expectedLearnerVersion: state.version, conceptId }));
      setChoice(""); setHint(""); operation.current = null;
    }, "question")}>Resume this concept</button>
    {error && <p role="alert" className="live-error">{error}</p>}
  </section>;
  if (request && (handledRequest !== request.id || focusError)) return <section className="live-card practice-question-panel">
    <div className="practice-agent-heading"><AgentPortrait role="tutoring" size={64} /><div><p className="eyebrow">PRACTICE THIS LESSON</p><h2>{ws.course?.graph.concepts.find(c => c.id === request.conceptId)?.title || "Your selected lesson"}</h2></div></div>
    {handledRequest !== request.id ? <PracticeStatus session={null} pending="question" /> : <><p className="live-error" role="alert">{focusError}</p><div className="live-actions"><button className="button secondary" onClick={navigation.retryRequest}>Try again</button>{session && <button className="button secondary" onClick={() => { setFocusError(""); navigation.clearRequest(); }}>Return to current practice</button>}</div></>}
  </section>;
  return <><div className={`simple-practice-content${compact ? " compact-quiz" : ""}`}><section className="live-card practice-question-panel">{!compact && <div className="practice-agent-heading"><AgentPortrait role="tutoring" size={64} /><div><p className="eyebrow">YOUR TUTOR · ONE STEP AT A TIME</p><h2>{a ? ws.course?.graph.concepts.find(c => c.id === a.conceptId)?.title || "Practice" : "Let’s put your ideas to work"}</h2></div></div>}
    {!compact && <>{a?.rationale && <p>{a.rationale}</p>}{a && <div className="simple-practice-meta"><span>{a.difficulty}</span><SourceLink key={a.id} references={a.sources} /></div>}
    {(a || session?.targetConceptId) && <p className="practice-topic-label">Practicing: {ws.course?.graph.concepts.find(c => c.id === (a?.conceptId || session?.targetConceptId))?.title}</p>}
    {conceptId && a && a.conceptId !== conceptId && <p role="status">Topic complete. Your tutor has selected this topic for you to practice next.</p>}</>}
    {!session && <><p>{compact ? "Choose an answer to test your understanding." : conceptId ? "Practice this concept here. Your tutor can offer a hint, and your reviewer will explain the answer." : "Try a question from your course. Your tutor can offer a hint, and your reviewer will explain the answer."}</p><button className="button dark" disabled={busy || !ws.learner || !ws.course?.graph.concepts.length} onClick={() => void action(async () => { const state = await api<{ version: number }>(`courses/${ws.courseId}/learner-state`); const params = new URLSearchParams(window.location.search); const targetConceptId = conceptId || (params.get("scope") === "course" ? undefined : params.get("concept") || undefined); setSession(await api<StudySession>(`courses/${ws.courseId}/sessions`, { expectedLearnerVersion: state.version, ...(targetConceptId ? { conceptId: targetConceptId } : {}) })); }, "question")}>{compact ? "Start quiz" : "Start or resume practice"}</button>{!ws.course?.graph.concepts.length && <p>Upload materials and wait for published concepts first.</p>}</>}
    {session?.notice && <p role="status">{session.notice}</p>}
    {(!a || pendingTask === "question") && <PracticeStatus session={session} pending={pendingTask} />}
    {a && <>{a.extendedTopic && <div className="quiz-extension"><span className="quiz-extension-badge">Extended topics</span><p>Beyond the supplied lecture materials. Your Expert considers this important for understanding.{a.extensionReason && <> {a.extensionReason}</>}</p></div>}{!compact && <p className="live-pill">{a.difficulty[0].toUpperCase() + a.difficulty.slice(1)} practice</p>}<RichText className="live-prompt">{a.prompt}</RichText><fieldset disabled={busy || a.status !== "pending" || session?.status !== "active"}><legend>Choose an answer</legend>{a.choices.map(c => <label className="live-choice" key={c.id}><input type="radio" name="answer" value={c.id} checked={(session?.selectedChoiceId || choice) === c.id} onChange={() => setChoice(c.id)} />{c.text}</label>)}</fieldset>
      {a.status === "pending" && (compact ? <details className="compact-quiz-extra" key={a.id}><summary>Add an explanation (optional)</summary><label className="answer-reasoning">Your explanation<textarea rows={3} maxLength={4000} value={reasoning} disabled={busy} onChange={event => setReasoning(event.target.value)} /></label></details> : <label className="answer-reasoning">Explain your choice (optional)<textarea rows={3} maxLength={4000} value={reasoning} disabled={busy} onChange={event => setReasoning(event.target.value)} /></label>)}
      {a.status === "pending" && session?.status === "active" && <div className="live-actions"><button className="button dark" disabled={busy || !choice} onClick={() => void action(async () => {
        if (!operation.current || operation.current.activity !== a.id || operation.current.choice !== choice || operation.current.reasoning !== (reasoning.trim() || null)) { const state = await api<{ version: number }>(`courses/${ws.courseId}/learner-state`); operation.current = { activity: a.id, choice, reasoning: reasoning.trim() || null, version: state.version, id: crypto.randomUUID() }; }
        const op = operation.current;
        await api<{ submissionId: string }>(`activities/${a.id}/responses`, { operationId: op.id, expectedLearnerVersion: op.version, choiceId: op.choice, reasoning: op.reasoning }); setSession(await api<StudySession>(`sessions/${session!.id}`));
      }, "save")}>Submit answer</button><button className="button secondary" disabled={busy} onClick={() => void action(async () => { const result = await api<{ hint: string }>(`activities/${a.id}/hint`, {}); setHint(result.hint); }, "hint")}>{a.hintUsed ? "Show hint again" : "Get a hint"}</button></div>}
      {hint && <RichText className="live-notice">{hint}</RichText>}{(a.status === "submitted" || pendingTask === "hint" || pendingTask === "save") && <PracticeStatus session={session} pending={pendingTask} />}
      {session?.assessment && a.status === "assessed" && <div className="live-notice" aria-live="polite">{!compact && <div className="lesson-author"><AgentPortrait role="assessing" size={38} /><p>YOUR REVIEWER · ANSWER ANALYSIS</p></div>}<h3>{session?.assessment?.uncertain ? "Needs another check" : session?.assessment?.correct && (session.assessment.rubricScore ?? 1) >= 1 ? "Correct" : "Keep learning"}</h3><RichText>{session?.assessment?.feedback}</RichText>{compact ? <details className="compact-quiz-extra" key={a.id}><summary>Answer explanation</summary><RichText>{session.assessment.explanation}</RichText><AssessmentDetails assessment={session.assessment} /></details> : <><RichText>{session.assessment.explanation}</RichText><AssessmentDetails assessment={session.assessment} /></>}</div>}
      {a.status === "assessed" && session?.status === "active" && <button className="button dark" disabled={busy} onClick={() => void action(async () => { const state = await api<{ version: number }>(`courses/${ws.courseId}/learner-state`); await api(`sessions/${session!.id}/next`, { expectedLearnerVersion: state.version }); setChoice(""); setHint(""); setSession(await api<StudySession>(`sessions/${session!.id}`)); }, "question")}>{topicComplete ? "Next topic" : "Next question"}</button>}
    </>}
    {session?.status === "active" && (compact ? <details className="compact-quiz-extra" key={a?.id || "preparing"}><summary>Quiz details</summary>{a && <><p>Difficulty: {a.difficulty}</p>{a.rationale && <p>{a.rationale}</p>}<SourceLink references={a.sources} /></>}<div><button disabled={busy} className="button secondary" onClick={() => void action(async () => { await api(`sessions/${session.id}/end`, {}); setSession(null); setChoice(""); setHint(""); })}>End session</button></div></details> : <button disabled={busy} className="button secondary" onClick={() => void action(async () => { await api(`sessions/${session.id}/end`, {}); setSession(null); setChoice(""); setHint(""); })}>End session</button>)}
    {error && <p className="live-error" role="alert">{error}</p>}
  </section></div></>;
}

