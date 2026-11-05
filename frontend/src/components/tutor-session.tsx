"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api, type Assessment, type Reference, type StudySession } from "@/lib/backend";
import { useWorkspace } from "./workspace-provider";
import { AgentPortrait } from "./agent-portrait";
import { RichText } from "./rich-text";
import { WorkedExample } from "./worked-example";
import { SourceLink } from "./related-slides";
import { PracticeStatus } from "./learning-status";
import { Icon } from "./icons";
import { LearningPlan } from "./learning-plan";
import { AssessmentDetails } from "./assessment-details";

const stateLabels: Record<string, string> = { unassessed: "Not assessed", developing: "Developing", demonstrated: "Demonstrated", review_due: "Review due" };
const colors: Record<string, string> = { unassessed: "#e4e9e1", developing: "#edc783", demonstrated: "#438062", review_due: "#d88d75" };
type Activity = NonNullable<StudySession["activity"]>;
type Message = {
  id: string;
  role: "tutor" | "user" | "reviewer";
  kind: "text" | "lesson" | "question" | "feedback";
  text?: string;
  activity?: Activity;
  assessment?: Assessment;
  sources?: Reference[];
};
type Task = "question" | "hint" | "save" | "chat";

function ChatBubble({ role, children }: { role: Message["role"]; children: ReactNode }) {
  return <article className={`tutor-chat-message tutor-chat-message-${role}`}>
    {role !== "user" && <AgentPortrait role={role === "reviewer" ? "assessing" : "tutoring"} size={30} />}
    <div className="tutor-chat-message-content">
      <span className="tutor-chat-speaker">{role === "user" ? "You" : role === "reviewer" ? "Your reviewer" : "Your tutor"}</span>
      <div className="tutor-chat-bubble">{children}</div>
    </div>
  </article>;
}

export function TutorSession() {
  const { course, courseId, learner, materials, refresh } = useWorkspace();
  const [session, setSession] = useState<StudySession | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [focus, setFocus] = useState("");
  const [revealed, setRevealed] = useState("");
  const [choice, setChoice] = useState("");
  const [reasoning, setReasoning] = useState("");
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [pendingTask, setPendingTask] = useState<Task | null>(null);
  const [error, setError] = useState("");
  const [failedChat, setFailedChat] = useState<{ id: string; text: string } | null>(null);
  const [reviewed, setReviewed] = useState<string[]>([]);
  const lock = useRef(false);
  const epoch = useRef(0);
  const mounted = useRef(true);
  const operation = useRef<{ activity: string; choice: string; reasoning: string | null; version: number; id: string } | null>(null);
  const seen = useRef(new Set<string>());
  const transcript = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const composer = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; epoch.current += 1; }; }, []);

  const addMessage = useCallback((message: Message) => {
    if (mounted.current) setMessages(previous => previous.some(item => item.id === message.id) ? previous : [...previous, message]);
  }, []);
  function say(text: string) {
    follow.current = true;
    addMessage({ id: crypto.randomUUID(), role: "user", kind: "text", text });
  }
  const acceptSession = useCallback((next: StudySession) => {
    if (!mounted.current) return;
    setSession(next);
    const activity = next.activity;
    if (!activity) return;
    if (!seen.current.has(`lesson:${activity.id}`)) {
      seen.current.add(`lesson:${activity.id}`);
      setReasoning("");
      if (activity.action === "practice" || activity.action === "reassess") {
        setRevealed(activity.id);
        addMessage({ id: `question:${activity.id}`, role: "tutor", kind: "question", activity });
        if (activity.status === "pending") void api(`activities/${activity.id}/present`, {}).catch(() => {});
      } else addMessage({ id: `lesson:${activity.id}`, role: "tutor", kind: "lesson", activity });
    }
    if (activity.status !== "pending") {
      addMessage({ id: `question:${activity.id}`, role: "tutor", kind: "question", activity });
      const answer = activity.choices.find(item => item.id === next.selectedChoiceId);
      if (answer) addMessage({ id: `answer:${activity.id}`, role: "user", kind: "text", text: answer.text });
    }
    if (activity.status === "assessed" && next.assessment && !seen.current.has(`feedback:${activity.id}`)) {
      seen.current.add(`feedback:${activity.id}`);
      addMessage({ id: `feedback:${activity.id}`, role: "reviewer", kind: "feedback", activity, assessment: next.assessment });
      setReviewed(previous => [...previous, activity.id]);
      void refresh();
    }
  }, [addMessage, refresh]);
  const sessionId = session?.id;
  const sessionStatus = session?.status;
  useEffect(() => {
    if (!sessionId || sessionStatus !== "active") return;
    let active = true, fetching = false;
    const timer = setInterval(async () => {
      if (lock.current || fetching) return;
      fetching = true;
      const version = epoch.current;
      try {
        const next = await api<StudySession>(`sessions/${sessionId}`);
        if (active && !lock.current && version === epoch.current) acceptSession(next);
      } catch (e) { if (active && version === epoch.current) setError((e as Error).message); }
      finally { fetching = false; }
    }, 2500);
    return () => { active = false; clearInterval(timer); };
  }, [sessionId, sessionStatus, acceptSession]);
  useEffect(() => {
    if (follow.current && transcript.current) transcript.current.scrollTo({ top: transcript.current.scrollHeight, behavior: "instant" });
  }, [messages.length, busy, session?.activity?.status]);

  async function act(work: () => Promise<void>, task: Task = "question") {
    if (lock.current) return false;
    lock.current = true; epoch.current += 1; setBusy(true); setPendingTask(task); setError("");
    try { await work(); if (mounted.current) await refresh(); return true; }
    catch (e) { if (mounted.current) setError((e as Error).message); return false; }
    finally { lock.current = false; if (mounted.current) { setBusy(false); setPendingTask(null); } }
  }
  async function version() { return (await api<{ version: number }>(`courses/${courseId}/learner-state`)).version; }
  const activity = session?.activity;
  const concept = course?.graph.concepts.find(item => item.id === activity?.conceptId);
  const stage = activity?.status === "assessed" ? "review" : activity?.status === "submitted" || revealed === activity?.id ? "assess" : "teach";
  const canChat = Boolean(session?.status === "active" && activity && activity.status !== "submitted" && !busy);

  async function revealQuestion() {
    if (!activity || busy) return;
    await act(async () => {
      await api(`activities/${activity.id}/present`, {});
      say("I’m ready to try."); setRevealed(activity.id); setChoice("");
      addMessage({ id: `question:${activity.id}`, role: "tutor", kind: "question", activity });
    });
  }
  async function submitAnswer(id: string) {
    if (!session || !activity || activity.status !== "pending" || lock.current) return;
    const answer = activity.choices.find(item => item.id === id);
    if (!answer) return;
    follow.current = true;
    await act(async () => {
      if (!operation.current || operation.current.activity !== activity.id || operation.current.choice !== id || operation.current.reasoning !== (reasoning.trim() || null)) {
        operation.current = { activity: activity.id, choice: id, reasoning: reasoning.trim() || null, version: await version(), id: crypto.randomUUID() };
      }
      const op = operation.current;
      await api(`activities/${activity.id}/responses`, { operationId: op.id, expectedLearnerVersion: op.version, choiceId: op.choice, reasoning: op.reasoning });
      addMessage({ id: `answer:${activity.id}`, role: "user", kind: "text", text: answer.text });
      acceptSession(await api<StudySession>(`sessions/${session.id}`));
      if (mounted.current) setDraft("");
    }, "save");
  }
  async function sendChat(text: string, retryId?: string) {
    if (!canChat || !session || !activity || lock.current || !text.trim()) return;
    const messageId = retryId || crypto.randomUUID();
    follow.current = true;
    addMessage({ id: messageId, role: "user", kind: "text", text });
    setDraft(""); setFailedChat(null);
    const success = await act(async () => {
      const history = messages.filter(item => item.kind === "text" && item.text && item.id !== messageId)
        .slice(-12).map(item => ({ role: item.role === "user" ? "user" : "assistant", text: item.text }));
      const result = await api<{ reply: string; sources: Reference[]; assistanceUsed: boolean }>(`sessions/${session.id}/chat`, { activityId: activity.id, message: text, history });
      addMessage({ id: `reply:${messageId}`, role: "tutor", kind: "text", text: result.reply, sources: result.sources });
      acceptSession(await api<StudySession>(`sessions/${session.id}`));
    }, "chat");
    if (!success && mounted.current) { setFailedChat({ id: messageId, text }); setDraft(text); }
    if (mounted.current) composer.current?.focus({ preventScroll: true });
  }
  function sendDraft() {
    const text = draft.trim();
    if (!text || !canChat) return;
    const answer = stage === "assess" && activity?.status === "pending"
      ? activity.choices.find(item => item.id.toLowerCase() === text.toLowerCase() || item.text.toLowerCase() === text.toLowerCase()) : null;
    if (answer) void submitAnswer(answer.id);
    else void sendChat(text, failedChat?.text === text ? failedChat.id : undefined);
  }

  return <div className="tutor-page tutor-chat-page">
    <header className="tutor-page-heading"><div><p className="eyebrow">LEARN THROUGH CONVERSATION</p><h1>Let’s talk it through.</h1><p>Ask, explore, and test your understanding with your personal tutor.</p></div><Link href="/learn">Browse lessons <Icon name="arrow" size={16} /></Link></header>
    <div className="tutor-layout">
      <section className="tutor-session-panel tutor-chat-panel" aria-label="Tutor conversation">
        <header className="tutor-session-header"><div><AgentPortrait role="tutoring" size={42} /><div><strong>Your tutor</strong><span>{busy ? "Thinking through your next step…" : session ? `${concept?.title || "Choosing your next idea"} · ${stage === "review" ? "Reflecting" : stage === "assess" ? "Checking understanding" : "Learning together"}` : "Here to help you understand"}</span></div></div>{session && <button className="tutor-end" disabled={busy || activity?.status === "submitted"} onClick={() => void act(async () => { await api(`sessions/${session.id}/end`, {}); if (mounted.current) { setSession(null); setFailedChat(null); setDraft(""); addMessage({ id: crypto.randomUUID(), role: "tutor", kind: "text", text: "A good place to pause. Your assessed answers are saved. Start again whenever you’re ready, and we’ll keep building on your understanding." }); } })}>End session</button>}</header>
        <div className="tutor-chat-transcript" ref={transcript} role="log" aria-label="Conversation messages" aria-live="polite" aria-relevant="additions" onScroll={event => { const pane = event.currentTarget; follow.current = pane.scrollHeight - pane.scrollTop - pane.clientHeight < 100; }}>
          <div className="tutor-chat-date">Your learning conversation</div>
          <ChatBubble role="tutor"><p>Hi! I’m your tutor. We’ll work through one idea at a time. Ask me questions whenever something feels unclear, and I’ll check your understanding as we go.</p></ChatBubble>
          {messages.map(message => {
            const item = message.activity;
            const pack = materials.materials.find(entry => entry.conceptId === item?.conceptId);
            const material = pack ? { ...pack, lesson: pack.lessonsByDifficulty?.[item?.difficulty as "basic" | "intermediate" | "advanced"] || pack.lesson, sources: pack.sourcesByDifficulty?.[item?.difficulty as "basic" | "intermediate" | "advanced"] || pack.sources } : undefined;
            const topic = course?.graph.concepts.find(entry => entry.id === item?.conceptId);
            return <ChatBubble key={message.id} role={message.role}>
              {message.kind === "text" && <><RichText>{message.text}</RichText>{Boolean(message.sources?.length) && <SourceLink references={message.sources!} context="lesson" />}</>}
              {message.kind === "lesson" && <>
                <p className="tutor-chat-topic">LET’S EXPLORE · {item?.difficulty}</p><h2>{topic?.title || "Your next learning step"}</h2>
                {item?.rationale && <p>{item.rationale}</p>}
                <RichText>{material?.lesson.objective || topic?.summary}</RichText>
                {material && <><RichText>{material.lesson.explanation}</RichText><div className="tutor-chat-takeaway"><strong>The key idea</strong><RichText>{material.lesson.takeaway}</RichText></div><details className="tutor-chat-example"><summary>Walk through an example</summary><WorkedExample example={material.lesson.workedExample} mathExpressions={material.lesson.equations.map(equation => equation.latex)} /></details></>}
                <SourceLink references={material?.sources || item?.sources || []} context="lesson" /><p className="tutor-chat-invite">What would you like to unpack? Or we can try a quick question.</p>
              </>}
              {message.kind === "question" && item && <>
                <p className="tutor-chat-topic">A QUICK CHECK · {item.difficulty}</p><RichText className="tutor-question">{item.prompt}</RichText>
                <fieldset className="tutor-answers" disabled={busy || activity?.id !== item.id || activity.status !== "pending" || session?.status !== "active"}>
                  <legend>Choose an answer, or type its letter below.</legend>{item.choices.map((option, index) => <label key={option.id} className={activity?.id === item.id && (session?.selectedChoiceId || choice) === option.id ? "selected" : ""}>
                    <input type="radio" name={`tutor-answer-${item.id}`} checked={activity?.id === item.id && (session?.selectedChoiceId || choice) === option.id} onChange={() => setChoice(option.id)} /><span aria-hidden="true">{String.fromCharCode(65 + index)}</span><RichText>{option.text}</RichText>
                  </label>)}
                </fieldset>
                {item.id === activity?.id && activity.status === "pending" && <label className="answer-reasoning">Explain your choice (optional)<textarea rows={3} maxLength={4000} value={reasoning} disabled={busy} onChange={event => setReasoning(event.target.value)} placeholder="What led you to this answer?" /></label>}
              </>}
              {message.kind === "feedback" && message.assessment && <>
                <p className="tutor-chat-topic">YOUR ANSWER REVIEW</p><h3>{message.assessment.uncertain ? "Let’s check this once more" : message.assessment.correct && (message.assessment.rubricScore ?? 1) >= 1 ? "That’s coming together!" : "Let’s work through this together"}</h3>
                <RichText>{message.assessment.feedback}</RichText><RichText>{message.assessment.explanation}</RichText><AssessmentDetails assessment={message.assessment} /><p className="tutor-chat-saved"><Icon name="check" size={14} />Answer saved to your assessment history</p><p>Ready to keep going, or would you like to talk about this idea a little more?</p>
              </>}
            </ChatBubble>;
          })}
          {!session && <ChatBubble role="tutor"><p>{messages.length ? "Where would you like to pick up?" : "Where shall we start? Choose a topic, or let me find a useful next step."}</p><label className="tutor-focus">Session focus<select value={focus} disabled={busy} onChange={event => setFocus(event.target.value)}><option value="">Let my tutor choose</option>{course?.graph.concepts.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label><button className="button dark" disabled={busy || !learner || !course?.graph.concepts.length} onClick={() => { follow.current = true; void act(async () => { const next = await api<StudySession>(`courses/${courseId}/sessions`, { expectedLearnerVersion: await version(), ...(focus ? { conceptId: focus } : {}) }); say(focus ? `Let’s work on ${course?.graph.concepts.find(item => item.id === focus)?.title}.` : "Let’s get started. Choose a useful next step for me."); acceptSession(next); if (mounted.current) { setChoice(""); setFailedChat(null); } }); }}>Start or resume session<Icon name="arrow" size={16} /></button>{!course?.graph.concepts.length && <p>Prepare your <Link href="/materials">course materials</Link> to begin.</p>}</ChatBubble>}
          {session?.notice && <p className="tutor-chat-notice" role="status">{session.notice}</p>}
          {(busy || (session && !activity && !session.notice) || activity?.status === "submitted") && <ChatBubble role="tutor"><div className="tutor-chat-thinking" role="status"><span aria-hidden="true">•••</span>{pendingTask === "chat" ? "Thinking about your question…" : pendingTask === "hint" ? "Finding a helpful nudge…" : activity?.status === "submitted" || pendingTask === "save" ? "Reviewing your answer…" : "Preparing your next learning step…"}</div></ChatBubble>}
          {session && !busy && (!activity || activity.status === "submitted") && <PracticeStatus session={session} />}
          {session && session.status !== "active" && <p className="tutor-chat-notice">This session has finished. <button className="tutor-text-button" onClick={() => setSession(null)}>Start another conversation</button></p>}
          {error && <div className="live-error" role="alert"><p>{error}</p><button className="tutor-text-button" disabled={busy} onClick={() => { if (failedChat) void sendChat(failedChat.text, failedChat.id); else void act(async () => { if (session) acceptSession(await api<StudySession>(`sessions/${session.id}`)); }); }}>{failedChat ? "Retry message" : "Refresh session"}</button></div>}
        </div>
        <div className="tutor-chat-dock">
          {canChat && <div className="tutor-chat-suggestions" aria-label="Suggested replies">
            {stage === "teach" && <button onClick={revealQuestion}>I’m ready to try<Icon name="arrow" size={13} /></button>}
            {stage === "assess" && activity?.status === "pending" && <>
              <button onClick={() => { if (!activity || !session) return; say("Could I have a hint?"); void act(async () => { const result = await api<{ hint: string }>(`activities/${activity.id}/hint`, {}); addMessage({ id: crypto.randomUUID(), role: "tutor", kind: "text", text: result.hint }); acceptSession(await api<StudySession>(`sessions/${session.id}`)); }, "hint"); }}><Icon name="hint" size={14} />Give me a hint</button>
              {choice && <button className="tutor-chat-send-choice" onClick={() => void submitAnswer(choice)}>Send answer<Icon name="arrow" size={13} /></button>}
            </>}
            {stage === "review" && <button onClick={() => { if (!session) return; say("Let’s continue learning."); void act(async () => { await api(`sessions/${session.id}/next`, { expectedLearnerVersion: await version() }); if (mounted.current) { setChoice(""); setDraft(""); setFailedChat(null); operation.current = null; } acceptSession(await api<StudySession>(`sessions/${session.id}`)); }); }}>Continue learning<Icon name="arrow" size={13} /></button>}
            <button onClick={() => void sendChat("Could you explain that in a simpler way?")}>Explain another way</button>
            <button onClick={() => void sendChat("Can you walk me through a different example?")}>Show me an example</button>
          </div>}
          <form className="tutor-chat-composer" onSubmit={event => { event.preventDefault(); sendDraft(); }}>
            <textarea ref={composer} aria-label="Message your tutor" placeholder={!session ? "Start a session to chat with your tutor…" : activity?.status === "submitted" ? "Your answer is being reviewed…" : "Ask a question, or tell me what’s unclear…"} rows={2} maxLength={2000} value={draft} disabled={!canChat} onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} />
            <button type="submit" aria-label="Send message" disabled={!canChat || !draft.trim()}><Icon name="arrow" size={20} /></button>
          </form>
          <p className="tutor-chat-caption">{activity?.hintUsed ? "Coaching used for this question · assessment records assisted evidence" : "Ask freely · your graph changes after assessed answers"}<span>Enter to send</span></p>
        </div>
      </section>
      <aside className="tutor-rail"><LearningPlan current={session?.plan} /><SessionGraph activeConcept={concept?.id} /><section className="tutor-session-note"><Icon name="leaf" size={22} /><h3>A conversation that moves you forward.</h3><p>Explore an idea, try a question, then use the feedback to decide what to learn next.</p><div><strong>{reviewed.length}</strong><span>answers reviewed this visit</span></div>{session?.targetConceptId && <p>Focused on: {course?.graph.concepts.find(item => item.id === session.targetConceptId)?.title}</p>}</section></aside>
    </div>
  </div>;
}

function SessionGraph({ activeConcept }: { activeConcept?: string }) {
  const { course, learner } = useWorkspace();
  const [level, setLevel] = useState("intermediate");
  const [selected, setSelected] = useState("");
  const all = course?.graph.concepts || [];
  const center = all.find(item => item.id === (selected || activeConcept)) || all[0];
  const edges = course?.graph.prerequisites || [];
  const neighbors = new Set(edges.filter(edge => edge.prerequisite === center?.id || edge.dependent === center?.id).flatMap(edge => [edge.prerequisite, edge.dependent]));
  const visible = center ? [center, ...all.filter(item => item.id !== center.id && neighbors.has(item.id)), ...all.filter(item => item.id !== center.id && !neighbors.has(item.id))].slice(0, 7) : [];
  const nodes = visible.map((item, index) => ({ ...item, x: index === 0 ? 160 : 160 + Math.cos((index - 1) / (visible.length - 1) * Math.PI * 2 - Math.PI / 2) * 112, y: index === 0 ? 150 : 150 + Math.sin((index - 1) / (visible.length - 1) * Math.PI * 2 - Math.PI / 2) * 112 }));
  const stateFor = (id: string) => learner?.concepts[id]?.[level]?.state || "unassessed";
  const count = all.filter(item => stateFor(item.id) === "demonstrated").length;
  return <section className="tutor-graph-panel"><header><div><p className="eyebrow">YOUR UNDERSTANDING</p><h2>Assessment graph</h2></div><span className="tutor-live-label"><i />Live</span></header><label className="tutor-graph-level">Evidence level<select value={level} onChange={event => setLevel(event.target.value)}>{["basic", "intermediate", "advanced"].map(item => <option key={item} value={item}>{item[0].toUpperCase() + item.slice(1)}</option>)}</select></label>{nodes.length ? <><svg className="tutor-graph" viewBox="0 0 320 300" role="group" aria-label="Concept evidence and prerequisite connections">{edges.map(edge => { const from = nodes.find(node => node.id === edge.prerequisite), to = nodes.find(node => node.id === edge.dependent); return from && to ? <line key={`${from.id}:${to.id}`} x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke="#ccd7ca" strokeWidth="1.5" /> : null; })}{nodes.map((node, index) => <g key={node.id} role="button" tabIndex={0} aria-label={`${node.title}: ${stateLabels[stateFor(node.id)]}`} onClick={() => setSelected(node.id)} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelected(node.id); } }}><title>{node.title} · {stateLabels[stateFor(node.id)]}</title>{node.id === activeConcept && <circle cx={node.x} cy={node.y} r={index === 0 ? 29 : 22} fill="none" stroke="#285c43" strokeDasharray="3 4" />}<circle cx={node.x} cy={node.y} r={index === 0 ? 22 : 15} fill={colors[stateFor(node.id)] || colors.unassessed} stroke="white" strokeWidth="3" /><text x={node.x} y={node.y + (index === 0 ? 40 : 32)} textAnchor="middle">{node.title.length > 19 ? `${node.title.slice(0, 17)}…` : node.title}</text></g>)}</svg><div className="tutor-graph-current"><strong>{center?.title}</strong><span>{stateLabels[stateFor(center.id)]}</span></div><p className="tutor-graph-caption">{visible.length} of {all.length} concepts shown · lines show prerequisites</p></> : <p className="tutor-graph-caption">Your concepts will appear when course materials are ready.</p>}<div className="tutor-graph-legend">{Object.entries(stateLabels).map(([state, label]) => <span key={state}><i style={{ background: colors[state] }} />{label}</span>)}</div><div className="tutor-graph-summary" aria-live="polite"><span><strong>{count}</strong> / {all.length} demonstrated</span><Link href="/map">Full graph <Icon name="arrow" size={15} /></Link></div></section>;
}
