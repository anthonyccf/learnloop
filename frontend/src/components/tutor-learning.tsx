"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ExpertWorkbenchShell } from "@/components/expert-workbench-shell";
import { Icon } from "@/components/icons";
import { SourceLink } from "@/components/related-slides";
import { RichText } from "@/components/rich-text";
import { MixedAnswer } from "@/components/mixed-answer";
import { AssessmentDetails } from "@/components/assessment-details";
import { TutorHandoffs, type TutorHandoff } from "@/components/tutor-handoffs";
import { TutorBrainMemory, type BrainGraph, type BrainStates } from "@/components/tutor-brain-memory";
import { useWorkspace } from "@/components/workspace-provider";
import { api, type Assessment, type LearningMaterial, type Reference, type SavedMixedAnswer, type StudySession } from "@/lib/backend";
import { formatTemplateTemperature, readExpertTemplates, type AgentPromptTemplate } from "@/lib/expert-templates";

type Mode = "auto" | "lesson" | "quiz" | "pre_assessment";
type RunEvent = { type: string; at: string; sequence?: number; payload?: Record<string, unknown> };
type Run = { id: string; status: string; summary: string; allowedCommands: string[]; events: RunEvent[] };
type ChatTurn = { role: "user" | "assistant"; text: string; operationId?: string; nextAction?: "lesson" | "quiz" | "none"; sources?: Reference[] };
type Memory = {
  id: string; name: string; courseId: string; sessionId: string | null; stepId: string | null; version: number; request: string; mode: Mode; branch?: string;
  evidence: Record<string, Record<string, { state?: string; attempts?: number }>>;
  graph?: BrainGraph; evidenceStates?: BrainStates;
  courseGraph?: BrainGraph; courseEvidenceStates?: BrainStates;
  memory: Record<string, { status: string; gap?: { summary?: string } | null }>;
  courseMemory?: Record<string, { status: string; gap?: { summary?: string } | null }>;
  lesson?: LearningMaterial | null; activity: StudySession["activity"]; assessment: Assessment | null;
  preAssessmentResume?: boolean;
  preAssessment?: { total: number; completed: number; round: number; remaining: number; results: { conceptId: string; correct: boolean; uncertain: boolean; demonstrated: boolean; feedback: string }[] } | null;
  selectedChoiceId?: string | null; runs: Run[];
  answer?: SavedMixedAnswer;
  handoffs?: TutorHandoff[];
  history: { id: string; conceptId: string; difficulty: string; assessment: Assessment; preAssessment?: boolean }[];
  chat: ChatTurn[];
  statistics: { sessions: number; loadDurationMs: number | null; loadUsage: { calls: number | null; inputTokens: number | null; outputTokens: number | null; costUsd: number | null } };
};
type MemoryOption = { id: string; name: string };
const RUN_TEMPLATE_STORAGE_KEY = "learnloop-tutor-run-template-id";

function eventLabel(event: RunEvent) {
  const payload = event.payload || {};
  if (event.type === "agent.step") return String(payload.task || "Agent step");
  if (event.type === "run.status") return `Run ${String(payload.status || "updated").replaceAll("_", " ")}`;
  if (event.type === "runtime.validation") return `Validation ${String(payload.status || "updated")}`;
  return event.type.replaceAll(".", " ");
}

function formatCost(cost: number | null | undefined) {
  if (cost == null) return "Not reported";
  if (cost > 0 && cost < 0.000001) return "<$0.000001";
  return `$${cost.toFixed(6)}`;
}

export function TutorLearning({ learner = false }: { learner?: boolean }) {
  const ws = useWorkspace();
  const [memories, setMemories] = useState<MemoryOption[]>([]);
  const [memoryId, setMemoryId] = useState("");
  const [memory, setMemory] = useState<Memory | null>(null);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [request, setRequest] = useState("");
  const [mode, setMode] = useState<Mode>("auto");
  const [choice, setChoice] = useState("");
  const [chatDraft, setChatDraft] = useState("");
  const [setupForSession, setSetupForSession] = useState("");
  const [templates, setTemplates] = useState<AgentPromptTemplate[]>([]);
  const [templateId, setTemplateId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const operation = useRef<{ activity: string; choice: string; version: number; id: string } | null>(null);
  const notSureOperation = useRef<{ activity: string; version: number; id: string } | null>(null);
  const chatOperation = useRef<{ session: string; step: string | null; text: string; id: string } | null>(null);
  const hydrated = useRef("");
  const activeMemory = useRef("");
  const requestSequence = useRef(0);
  const busyRef = useRef(false);

  useEffect(() => {
    const update = () => {
      const available = readExpertTemplates().filter(item => item.agent === "tutor");
      setTemplates(available);
      let saved = "";
      try { saved = localStorage.getItem(RUN_TEMPLATE_STORAGE_KEY) || ""; } catch {}
      setTemplateId(current => {
        const preferred = current || saved;
        if (preferred && available.some(item => item.id === preferred)) return preferred;
        try { localStorage.removeItem(RUN_TEMPLATE_STORAGE_KEY); } catch {}
        return "";
      });
    };
    update();
    window.addEventListener("storage", update);
    window.addEventListener("learnloop-expert-templates-updated", update);
    return () => { window.removeEventListener("storage", update); window.removeEventListener("learnloop-expert-templates-updated", update); };
  }, []);

  useEffect(() => {
    let active = true;
    activeMemory.current = ""; requestSequence.current++;
    if (!ws.courseId) return;
    api<MemoryOption[]>(`workbench/courses/${ws.courseId}/memories`).then(items => {
      if (!active) return;
      setMemories(items);
      let saved = "";
      try { saved = localStorage.getItem(`learnloop-tutor-memory:${ws.courseId}`) || ""; } catch {}
      const nextId = items.some(item => item.id === saved) ? saved : items[0]?.id || "";
      activeMemory.current = nextId; requestSequence.current++;
      setMemoryId(nextId);
      setMemory(null); setRequest(""); setChoice(""); hydrated.current = "";
    }).catch(cause => { if (active) setError((cause as Error).message === "Not Found" ? "The running backend does not support Tutor workbench yet. Apply the database migration and restart the API and worker." : (cause as Error).message); });
    return () => { active = false; };
  }, [ws.courseId]);

  const loadMemory = useCallback(async () => {
    if (!memoryId || busyRef.current) return;
    const sequence = ++requestSequence.current;
    const data = await api<Memory>(`workbench/memories/${memoryId}`);
    if (data.id !== memoryId || data.courseId !== ws.courseId || activeMemory.current !== memoryId || sequence !== requestSequence.current) return;
    setMemory(data);
    if (hydrated.current !== memoryId) {
      hydrated.current = memoryId; setRequest(data.request || ""); setMode(data.mode || "auto"); setChoice(data.selectedChoiceId || "");
    }
  }, [memoryId, ws.courseId]);

  useEffect(() => {
    if (!memoryId) return;
    let active = true;
    const refresh = () => { void loadMemory().catch(cause => { if (active) setError((cause as Error).message); }); };
    refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, [memoryId, loadMemory]);

  function selectMemory(id: string) {
    activeMemory.current = id; requestSequence.current++;
    setMemory(null); setMemoryId(id); setError(""); setChoice(""); setChatDraft(""); setSetupForSession(""); hydrated.current = "";
    try { localStorage.setItem(`learnloop-tutor-memory:${ws.courseId}`, id); } catch {}
  }
  function selectTemplate(id: string) {
    setTemplateId(id);
    try { if (id) localStorage.setItem(RUN_TEMPLATE_STORAGE_KEY, id); else localStorage.removeItem(RUN_TEMPLATE_STORAGE_KEY); } catch {}
  }
  async function action(fn: () => Promise<void>) {
    busyRef.current = true; requestSequence.current++; setBusy(true); setError("");
    try { await fn(); } catch (cause) { setError((cause as Error).message); } finally { busyRef.current = false; setBusy(false); }
  }
  async function createMemory() {
    const item = await api<MemoryOption>(`workbench/courses/${ws.courseId}/memories`, { name: name.trim() });
    setMemories(current => [...current, item]); setName(""); setCreating(false); selectMemory(item.id);
  }
  async function start(nextMode: Mode = mode, continuation = false, learningRequest = request, conceptId?: string, nextRound = false) {
    const template = learner ? undefined : templates.find(item => item.id === templateId);
    const result = await api<Memory>(`workbench/memories/${memoryId}/start`, {
      request: learningRequest.trim(), ...(conceptId ? { conceptId } : {}), mode: nextMode, continuation, ...(nextRound ? { nextRound: true } : {}), ...(continuation ? { stepId: memory?.stepId ?? null } : {}),
      promptTemplate: template ? { id: template.id, name: template.name, agent: template.agent, prompts: template.prompts, enabledTools: template.enabledTools, model: template.model, temperature: template.temperature } : null,
    });
    operation.current = null; chatOperation.current = null; setMemory(result); setMode(nextMode); setChoice(""); setSetupForSession("");
  }
  function startLearningHere(conceptId: string, title: string) {
    const learningRequest = `Help me learn ${title}`;
    setRequest(learningRequest); setMode("auto"); setError("");
    if (!ready) {
      if (memory?.sessionId) setSetupForSession(memory.sessionId);
      setError(waiting ? "Answer the current question or clear the session before starting a new concept." : inProgress ? "Wait for the current Tutor run to finish before starting a new concept." : assessmentsPending ? "Wait for the answer assessment to finish before starting a new concept." : "Select a memory session before starting a concept.");
      document.getElementById("tutor-inputs-heading")?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    void action(() => start("auto", false, learningRequest, conceptId));
  }
  async function submit() {
    if (!memory?.activity || !choice) return;
    if (!operation.current || operation.current.activity !== memory.activity.id || operation.current.choice !== choice) {
      operation.current = { activity: memory.activity.id, choice, version: memory.version, id: crypto.randomUUID() };
    }
    const op = operation.current;
    setMemory(await api<Memory>(`workbench/memories/${memoryId}/answer`, { operationId: op.id, expectedLearnerVersion: op.version, choiceId: op.choice }));
  }
  async function submitNotSure() {
    if (!memory?.activity) return;
    if (!notSureOperation.current || notSureOperation.current.activity !== memory.activity.id) {
      notSureOperation.current = { activity: memory.activity.id, version: memory.version, id: crypto.randomUUID() };
    }
    const op = notSureOperation.current;
    setMemory(await api<Memory>(`workbench/memories/${memoryId}/not-sure`, { operationId: op.id, activityId: op.activity, expectedLearnerVersion: op.version }));
  }
  async function clearSession() {
    if (!memory?.sessionId) return;
    const result = await api<Memory>(`workbench/memories/${memoryId}/clear`, { sessionId: memory.sessionId, stepId: memory.stepId });
    operation.current = null; chatOperation.current = null; setMemory(result); setRequest(""); setChoice(""); setChatDraft(""); setSetupForSession("");
  }
  async function sendChat() {
    const text = chatDraft.trim();
    if (!memory?.sessionId || !text) return;
    if (!chatOperation.current || chatOperation.current.session !== memory.sessionId || chatOperation.current.step !== memory.stepId || chatOperation.current.text !== text) {
      chatOperation.current = { session: memory.sessionId, step: memory.stepId, text, id: crypto.randomUUID() };
    }
    const op = chatOperation.current;
    const result = await api<Memory>(`workbench/memories/${memoryId}/chat`, { sessionId: op.session, stepId: memory.stepId, operationId: op.id, message: op.text });
    chatOperation.current = null; setMemory(result); setChatDraft("");
  }

  const lastRun = memory?.runs.at(-1);
  const waiting = memory?.activity?.status === "pending";
  const inProgress = lastRun && ["queued", "running", "paused"].includes(lastRun.status);
  const assessmentsPending = memory?.activity?.status === "submitted" && !memory.assessment;
  const events = memory?.runs.flatMap(run => run.events || []) || [];
  const ready = Boolean(ws.courseId && memoryId && memory?.id === memoryId && memory.courseId === ws.courseId && !busy && !waiting && !inProgress && !assessmentsPending);
  const sessionOpen = Boolean(memory?.sessionId);
  const showSetup = !sessionOpen || setupForSession === memory?.sessionId;
  const canChat = Boolean(sessionOpen && !busy && !inProgress && !assessmentsPending && (memory?.activity || memory?.lesson));
  const latestSuggestion = [...(memory?.chat || [])].reverse().find(turn => turn.role === "assistant")?.nextAction;
  const conceptName = (id: string) => memory?.graph?.concepts.find(item => item.id === id)?.title || ws.course?.graph.concepts.find(item => item.id === id)?.title || id;

  const templateRail = <section className="expert-run-template-list" aria-label="Prompt templates">
    <div className="expert-rail-template-heading"><h2>Prompt templates</h2><Link href="/workbench/expert/edit?agent=tutor" className="expert-icon-button" aria-label="Create or edit Tutor prompt templates">＋</Link></div>
    <label className={`expert-run-template-option ${!templateId ? "selected" : ""}`}>
      <input type="radio" name="tutor-run-template" checked={!templateId} onChange={() => selectTemplate("")} />
      <span><strong>Backend defaults</strong><small>Use configured prompts and model</small></span>
    </label>
    {templates.map(template => <label key={template.id} className={`expert-run-template-option ${templateId === template.id ? "selected" : ""}`}>
      <input type="radio" name="tutor-run-template" checked={templateId === template.id} onChange={() => selectTemplate(template.id)} />
      <span><strong title={template.name}>{template.name}</strong><small>{template.model} · {formatTemplateTemperature(template.temperature)}</small></span>
    </label>)}
    {!templates.length && <p className="expert-run-template-empty">Save a Tutor template in Edit agent to use it here.</p>}
  </section>;

  const content = <>
    <div className="expert-page-heading"><div><p className="expert-eyebrow">{learner ? "YOUR LEARNING SPACE" : "TUTOR AGENT · RUN"}</p><h1>{learner ? "Learning" : "Tutor · Run"}</h1><p className="expert-page-description">{learner ? "Choose how you want to learn, and pick up at your own pace." : "Test lessons and quizzes with isolated learning memories."}</p></div></div>
    {(error || ws.error) && !sessionOpen && <p className="expert-alert" role="alert">{error || ws.error}</p>}
    {!ws.courseId ? <section className="expert-empty"><h2>Choose a course</h2><p>Prepare course materials before starting a Tutor run.</p><Link href="/materials" className="expert-button primary">Open Materials</Link></section> : <div className="expert-columns tutor-workbench-columns">
      <div className="expert-left-column">
        {showSetup && <section className="expert-card tutor-workbench-card" aria-labelledby="tutor-inputs-heading">
          <div className="expert-card-heading"><div><h2 id="tutor-inputs-heading">Learning inputs</h2><p>{learner ? "Choose a topic, learning mode and saved session." : "Choose what to learn and which test memory to use."}</p></div></div>
          <label className="expert-field-label">Learning request <span>Optional · leave blank to let the Tutor choose a topic</span><textarea rows={3} maxLength={2000} value={request} onChange={event => setRequest(event.target.value)} placeholder="e.g. Help me understand gradient descent" /></label>
          <div className="expert-field-label">Learning mode<div className="tutor-mode-switch" role="group" aria-label="Learning mode">{([ ["auto", "Auto"], ["lesson", "Lesson"], ["quiz", "Quiz"], ["pre_assessment", "Pre-assessment"] ] as const).map(([item, label]) => <button key={item} type="button" aria-pressed={mode === item} onClick={() => setMode(item)}>{label}</button>)}</div></div>
          <div className="tutor-memory-row"><label className="expert-field-label">Learning session<select disabled={busy} value={memoryId} onChange={event => selectMemory(event.target.value)}><option value="">Select a memory</option>{memories.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><button type="button" className="expert-button secondary" disabled={busy} onClick={() => setCreating(!creating)}>+ New session</button></div>
          {creating && <form className="tutor-memory-create" onSubmit={event => { event.preventDefault(); void action(createMemory); }}><label className="expert-field-label">Session name<input autoFocus maxLength={200} value={name} onChange={event => setName(event.target.value)} placeholder="e.g. Practice learner A" /></label><button className="expert-button primary" disabled={busy || !name.trim()}>Create session</button></form>}
          {mode === "pre_assessment" && <p className="tutor-workbench-note">Answer up to 15 questions per round to identify what you already know. Later rounds cover remaining concepts and revisit some earlier ones. An independent, fully correct answer can mark that concept as demonstrated. Results are saved to the selected memory; the learning request does not limit course coverage.</p>}
          {!learner && <div className="tutor-memory-row"><label className="expert-field-label">Run template<select value={templateId} onChange={event => selectTemplate(event.target.value)}><option value="">Backend defaults</option>{templates.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><button type="button" className="expert-button primary" disabled={!ready} aria-describedby={waiting ? "tutor-run-waiting" : undefined} onClick={() => void action(() => start())}>{busy ? "Working…" : "Run tutor"}</button></div>}
          {learner && <button type="button" className="expert-button primary" disabled={!ready} onClick={() => void action(() => start())}>{busy ? "Working…" : "Start learning"}</button>}
          {waiting && <p id="tutor-run-waiting" className="tutor-workbench-note" role="status">Answer the <a href="#tutor-output-heading">current question</a> or clear the session before starting a new run. Your learning request can stay empty.</p>}
          <p className="tutor-workbench-note">{learner ? "Sessions save their own learning progress, separate from the previous learner progress. Learning uses all published course materials." : <>Test memories are isolated. Tutor runs use all published course materials{ws.materialId ? "; the material filter does not restrict this run" : ""}.</>}</p>
          {!learner && templateId && <p className="tutor-workbench-note">The learning plan and Tutor response prompts and Tutor model settings apply. Question selection and tool switches do not apply to this run.</p>}
        </section>}
        <section className="expert-card tutor-workbench-card" aria-labelledby="tutor-output-heading"><div className="expert-card-heading"><div><h2 id="tutor-output-heading">Tutor output</h2><p>{memory?.activity ? `${conceptName(memory.activity.conceptId)} · ${memory.activity.difficulty}` : memory?.lesson ? conceptName(memory.lesson.conceptId) : "Your lesson or question appears here."}</p></div>{memory?.sessionId && <div className="tutor-output-actions"><button type="button" className="expert-button secondary" aria-expanded={showSetup} onClick={() => setSetupForSession(showSetup ? "" : memory.sessionId || "")}>{showSetup ? "Hide inputs" : "Learning inputs"}</button><button type="button" className="expert-button secondary" disabled={busy || Boolean(inProgress) || Boolean(assessmentsPending)} onClick={() => void action(clearSession)}>Clear session</button></div>}</div>
          {sessionOpen && (error || ws.error) && <p className="expert-alert" role="alert">{error || ws.error}</p>}
          {memory?.lesson && <><h3>{memory.lesson.lesson.title}</h3><RichText>{memory.lesson.lesson.explanation}</RichText><p><strong>Key idea:</strong> <RichText inline mathExpressions={(memory.lesson.lesson.equations || []).map(equation => equation.latex)}>{memory.lesson.lesson.takeaway}</RichText></p><SourceLink references={memory.lesson.sources} context="lesson" /><button className="expert-button primary" disabled={!ready} onClick={() => void action(() => start("auto", true))}>Continue</button></>}
          {memory?.activity && <>{memory.preAssessment && <p role="status"><strong>Pre-assessment · Round {memory.preAssessment.round} · Question {Math.min(memory.preAssessment.completed + (memory.assessment ? 0 : 1), memory.preAssessment.total)} of {memory.preAssessment.total}</strong></p>}<div className="tutor-workbench-question"><RichText>{memory.activity.prompt}</RichText></div>{memory.activity.format ? <MixedAnswer key={memory.activity.id} activity={memory.activity} courseId={memory.courseId} saved={memory.answer} disabled={!waiting || busy} workbench={{ memoryId, version: memory.version, onResult: result => setMemory(result as Memory) }} onSubmit={submitMixed => void action(submitMixed)} /> : <><fieldset className="tutor-workbench-choices" disabled={!waiting || busy}><legend className="tutor-visually-hidden">Choose an answer</legend>{memory.activity.choices.map(option => <label key={option.id} className={(memory.selectedChoiceId || choice) === option.id ? "selected" : ""}><input type="radio" name="workbench-answer" checked={(memory.selectedChoiceId || choice) === option.id} onChange={() => setChoice(option.id)} /><strong>{option.id.toUpperCase()}.</strong><RichText>{option.text}</RichText></label>)}</fieldset>{waiting && <button type="button" className="expert-button primary tutor-submit" disabled={!choice || busy} onClick={() => void action(submit)}>Submit answer</button>}</>}{memory.preAssessment && waiting && <button type="button" className="expert-button secondary tutor-submit" disabled={busy} onClick={() => void action(submitNotSure)}>Not sure</button>}{assessmentsPending && <p role="status">Assessing your answer…</p>}{memory.assessment && <><div className="tutor-feedback"><strong>{memory.assessment.notSure ? "Not sure" : memory.assessment.uncertain ? "Review needed" : memory.assessment.correct ? "Correct" : "Keep practicing"}</strong><RichText>{memory.assessment.feedback}</RichText><RichText>{memory.assessment.explanation}</RichText><AssessmentDetails assessment={memory.assessment} /><small>{learner ? "Assessment saved to this learning session." : "Assessment saved to this test memory."}</small></div>{memory.preAssessment ? (memory.preAssessment.completed < memory.preAssessment.total ? <button type="button" className="expert-button primary tutor-submit" disabled={!ready} onClick={() => void action(() => start("pre_assessment", true))}>Next question</button> : <div className="tutor-feedback"><strong>Round {memory.preAssessment.round} complete</strong><p>{memory.preAssessment.results.filter(result => result.demonstrated).length} of {memory.preAssessment.total} concepts were demonstrated by the assessment.</p><p>Concepts to review: {memory.preAssessment.results.filter(result => !result.demonstrated).map(result => conceptName(result.conceptId)).join(", ") || "None identified"}.</p><p>{memory.preAssessment.remaining > 0 ? `${memory.preAssessment.remaining} course concepts remain for later rounds.` : "All course concepts have been assessed. Another round can revisit them."}</p><button type="button" className="expert-button secondary tutor-submit" disabled={!ready} onClick={() => void action(() => start("pre_assessment", true, request, undefined, true))}>Start next round</button><p>Review the results in assessment history, or start a lesson on a concept that needs attention.</p><button type="button" className="expert-button primary tutor-submit" disabled={!ready} onClick={() => void action(() => start("lesson", true))}>Start lesson</button></div>) : <button type="button" className="expert-button primary tutor-submit" disabled={!ready} onClick={() => void action(() => start("auto", true))}>Continue</button>}</>}</>}
          {memory?.preAssessmentResume && <p><button type="button" className="expert-button secondary tutor-submit" disabled={!ready} onClick={() => void action(() => start("pre_assessment", true, request, undefined, true))}>Continue pre-assessment: next round</button></p>}
          {!memory?.activity && !memory?.lesson && <p className="expert-muted">{inProgress ? "Preparing the next learning activity…" : learner ? "Choose a session and start learning when you are ready." : "Run the Tutor to begin, with or without a request."}</p>}
          {learner && lastRun && (lastRun.allowedCommands || []).some(command => command === "retry" || command === "resume") && <button className="expert-button secondary" disabled={busy} onClick={() => void action(async () => setMemory(await api<Memory>(`workbench/memories/${memoryId}/retry`, {})))}>Retry / resume</button>}
        </section>
        {sessionOpen && <section className="expert-card tutor-workbench-card tutor-workbench-conversation" aria-label="Conversation with tutor"><div className="expert-card-heading"><div><h2>Ask your tutor</h2><p>Ask a question or share extra information. Your current question stays open.</p></div></div>{Boolean(memory?.chat?.length) && <div className="tutor-workbench-messages" role="log" aria-live="polite">{memory?.chat.map((turn, index) => <article key={`${turn.operationId || index}-${turn.role}`}><strong>{turn.role === "user" ? "You" : "Tutor"}</strong><RichText>{turn.text}</RichText>{Boolean(turn.sources?.length) && <SourceLink references={turn.sources || []} context="lesson" />}</article>)}</div>}{latestSuggestion && latestSuggestion !== "none" && <p className="tutor-workbench-note">Tutor suggests a {latestSuggestion} next{waiting ? ", after this question" : ""}. Continue lets the Tutor decide.</p>}{waiting && memory?.activity?.hintUsed && <p className="tutor-workbench-note">Tutor help counts as assistance for this question.</p>}<form className="tutor-chat-composer" onSubmit={event => { event.preventDefault(); if (canChat && chatDraft.trim()) void action(sendChat); }}><textarea aria-label="Message your tutor" rows={2} maxLength={2000} value={chatDraft} disabled={!canChat} onChange={event => setChatDraft(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder="Ask a question, or tell me what’s unclear…" /><button type="submit" aria-label="Send message" disabled={!canChat || !chatDraft.trim()}><Icon name="arrow" size={20} /></button></form><p className="tutor-chat-caption">Ask a question or share what you know<span>Enter to send · Shift+Enter for a new line</span></p></section>}
      </div>
      <div className="expert-left-column">
        <section className="expert-card tutor-workbench-card tutor-memory-summary"><div className="expert-card-heading"><div><h2>{learner ? "Your understanding" : "Brain memory"}</h2><p>{learner ? "Your learning map" : "Selected memory"}: {memory?.name || "None"} · Includes all published course materials</p></div>{!learner && <span className="expert-status-tag">Isolated</span>}</div>{memory ? (memory.courseGraph || memory.graph) && (memory.courseEvidenceStates || memory.evidenceStates) ? <TutorBrainMemory key={memory.id} graph={memory.courseGraph || memory.graph!} states={memory.courseEvidenceStates || memory.evidenceStates!} gaps={memory.courseMemory || memory.memory} currentConceptId={memory.activity?.conceptId || memory.lesson?.conceptId} onStartLearning={startLearningHere} /> : <p className="expert-muted">The learning map is unavailable. Restart the learning server to load it.</p> : <p className="expert-muted">Select or create a memory session.</p>}{Boolean(memory?.history.length) && <details className="tutor-brain-history"><summary>Assessment history ({memory?.history.length})</summary><ul>{memory?.history.map(item => <li key={item.id}><strong>{conceptName(item.conceptId)}</strong> · {item.preAssessment ? "Pre-assessment · " : ""}{item.difficulty} · {item.assessment.notSure ? "not sure" : item.assessment.uncertain ? "uncertain" : item.assessment.correct ? "correct" : "needs practice"}<p>{item.assessment.feedback}</p></li>)}</ul></details>}</section>
        {!learner && <section className="expert-card tutor-workbench-card tutor-trace" aria-labelledby="tutor-trace-heading"><div className="expert-card-heading"><div><h2 id="tutor-trace-heading">Tutor activity trace</h2><p>{lastRun?.summary || (memory?.lesson ? "Lesson ready for review." : "Run events appear here.")}</p></div>{lastRun && <span className={`expert-status-tag ${lastRun.status}`}>{lastRun.status.replaceAll("_", " ")}</span>}</div>
          {memory && <><div className="tutor-workbench-stats" aria-label="Tutor statistics"><div><strong>{memory.statistics?.sessions ?? "—"}</strong><span>Sessions in this memory</span></div><div><strong>{memory.statistics?.loadDurationMs == null ? "—" : `${(memory.statistics.loadDurationMs / 1000).toFixed(1)} s`}</strong><span>Latest load time</span></div><div><strong>{formatCost(memory.statistics?.loadUsage?.costUsd)}</strong><span>Latest load cost (USD)</span></div></div><p className="tutor-workbench-note">Load time includes queue time. Cost covers loading the latest activity when reported by the provider; chat and assessment are not included.</p></>}
          <h3 className="tutor-handoffs-title">Agent handoffs</h3>
          <TutorHandoffs handoffs={(memory?.handoffs || []).map(handoff => handoff.status === "failed" && handoff.runId === lastRun?.id && ["queued", "running"].includes(lastRun.status) ? { ...handoff, status: lastRun.status, summary: lastRun.summary } : handoff)} lastRunId={lastRun?.id} busy={busy} conceptName={conceptName} onRetry={() => void action(async () => setMemory(await api<Memory>(`workbench/memories/${memoryId}/retry`, {})))} />
          {Boolean(events.length) && <details className="tutor-trace-details"><summary>Run details</summary><ol>{events.filter(event => event.type === "agent.step" || event.type === "runtime.validation" || event.type === "run.status").map((event, index) => <li key={`${event.at}-${index}`}><strong>{eventLabel(event)}</strong><p>{String(event.payload?.detail || event.payload?.summary || "")}</p></li>)}</ol></details>}
          {lastRun && !(memory?.handoffs || []).some(handoff => handoff.runId === lastRun.id && handoff.retryable) && (lastRun.allowedCommands || []).some(command => command === "retry" || command === "resume") && <button className="expert-button secondary" disabled={busy} onClick={() => void action(async () => setMemory(await api<Memory>(`workbench/memories/${memoryId}/retry`, {})))}>Retry / resume</button>}
        </section>}
      </div>
    </div>}
  </>;
  return learner ? <div className="expert-workbench learner-workbench">{content}</div> : <ExpertWorkbenchShell activePage="run" activeAgent="tutor" railContent={templateRail}>{content}</ExpertWorkbenchShell>;
}
