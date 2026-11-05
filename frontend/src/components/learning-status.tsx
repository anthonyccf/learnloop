"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, RunSummary, StudySession } from "@/lib/backend";
import type { AgentRun } from "@/lib/agent-activity/contracts";
import { blockedStates, currentPracticeRun, currentPreparationRun, preparationPhase, workingStates } from "@/lib/learning-status";
import { useWorkspace } from "./workspace-provider";
import { AgentPortrait, LearningRole, agentNames } from "./agent-portrait";

type Task = "prepare" | "question" | "assessment" | "hint" | "save";
const copy: Record<Task, { role: LearningRole; title: string; detail: string }> = {
  prepare: { role: "expert", title: "Preparing your learning materials", detail: "You can keep learning while new material is prepared." },
  question: { role: "tutoring", title: "Preparing your next question", detail: "Your tutor is choosing a useful question for you." },
  assessment: { role: "assessing", title: "Checking your answer", detail: "Your answer stays here while the reviewer prepares feedback." },
  hint: { role: "tutoring", title: "Finding a helpful hint", detail: "Keep your question in view. A small nudge is on the way." },
  save: { role: "assessing", title: "Saving your answer", detail: "Your question will stay here while we check it." },
};

function TaskStrip({ task, run, inline = false }: { task: Task; run?: RunSummary; inline?: boolean }) {
  const { refresh, course } = useWorkspace();
  const [snapshot, setSnapshot] = useState<AgentRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const id = run?.id, status = run?.status;
  useEffect(() => {
    if (!id) return;
    let active = true;
    const update = () => api<AgentRun>(`agent-activity/runs/${id}`).then(value => { if (active) setSnapshot(value); }).catch(() => { /* The workspace's connection message handles connectivity. */ });
    void update();
    const timer = setInterval(() => void update(), inline ? 2000 : 4000);
    return () => { active = false; clearInterval(timer); };
  }, [id, status, inline]);
  const current = snapshot?.id === id ? snapshot : null;
  const blocked = blockedStates.has(current?.status || status || "");
  const roleCopy = copy[task];
  const activeRole = inline && current?.currentAgent ? current.currentAgent : roleCopy.role;
  const agent = inline && current?.currentAgent ? current.agents[current.currentAgent] : null;
  const liveTask = agent?.status !== "not_started" ? agent?.task : null;
  const spinning = !blocked && (!current && !status || workingStates.has(current?.status || status || ""));
  const phase = task === "prepare" ? preparationPhase(current?.agents.expert.task || "") : null;
  const material = task === "prepare" ? course?.documents.find(doc => doc.id === run?.documentId) : null;
  const command = current?.allowedCommands.includes("resume") ? "resume" : current?.allowedCommands.includes("retry") ? "retry" : null;
  const progress = task === "prepare" ? current?.agents.expert.detail.match(/(?:Saved|Prepared)\s+(\d+)\/(\d+)/i) : null;
  return <div className={`learning-task-strip ${blocked ? "task-blocked" : ""}`}>
    <AgentPortrait role={activeRole} size={44} />
    <div className="learning-task-copy" role="status" aria-live="polite" aria-atomic="true"><span className="learning-task-role">{agentNames[activeRole]}{inline ? spinning && <i className="learning-task-spinner" aria-hidden="true" /> : !blocked && <i className="learning-task-dot" aria-hidden="true" />}</span><strong>{blocked ? task === "prepare" ? "Material preparation is paused" : task === "assessment" || task === "save" ? "Answer checking is paused" : "Question preparation is paused" : inline ? liveTask || current?.summary || run?.summary || roleCopy.title : phase?.title || roleCopy.title}</strong><p>{blocked ? inline ? current?.error?.message || current?.summary || run?.summary || "Your current work is saved. This task needs attention." : command ? "Your current work stays saved. Retry when you’re ready." : "Your current work stays saved. Open activity to see what needs attention." : inline ? agent?.detail || roleCopy.detail : progress ? `${progress[1]} of ${progress[2]} learning posts ready. You can keep learning.` : phase?.detail || roleCopy.detail}</p>{material && <small className="learning-task-material" title={material.filename}>{material.filename}</small>}</div>
    <div className="learning-task-actions">{blocked && command && <button className="button secondary" disabled={busy} onClick={async () => {
      setBusy(true); setError("");
      try { const latest = await api<AgentRun>(`agent-activity/runs/${id}`); if (latest.allowedCommands.includes(command)) await api(`agent-activity/runs/${id}/commands`, { kind: command, operationId: crypto.randomUUID(), expectedVersion: latest.recordVersion }); setSnapshot(await api<AgentRun>(`agent-activity/runs/${id}`)); await refresh(); }
      catch { setError(inline ? "Couldn’t restart this task. Please try again." : "Couldn’t restart this task. Open activity for details."); } finally { setBusy(false); }
    }}>{busy ? "Starting…" : command === "resume" ? "Resume" : "Retry"}</button>}{!inline && <Link href={id ? `/agents?run=${encodeURIComponent(id)}` : "/agents"}>View activity <span aria-hidden="true">↗</span></Link>}</div>
    {error && <p className="learning-task-error" role="alert">{error}</p>}
  </div>;
}

export function PreparationStatus() {
  const { runs, course } = useWorkspace();
  const run = currentPreparationRun(runs, course);
  return run ? <TaskStrip key={run.id} task="prepare" run={run} /> : null;
}

export function PracticeStatus({ session, pending }: { session: StudySession | null; pending?: Task | null }) {
  const { runs } = useWorkspace();
  const run = currentPracticeRun(runs, session);
  const task = session?.activity?.status === "submitted" ? "assessment" : "question";
  if (pending) return <TaskStrip inline key={pending} task={pending} />;
  if (!session || session.status !== "active" || session.notice || session.activity && session.activity.status !== "submitted") return null;
  const relevant = run && (workingStates.has(run.status) || blockedStates.has(run.status)) ? run : undefined;
  return <TaskStrip inline key={relevant?.id || task} task={task} run={relevant} />;
}
