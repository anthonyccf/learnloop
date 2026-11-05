"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/backend";
import { agentRoles, type AgentRole, type AgentRun, type AgentEvent } from "@/lib/agent-activity/contracts";
import { newestRuns, workingStates, blockedStates } from "@/lib/learning-status";
import { AgentPortrait, agentNames } from "./agent-portrait";
import { useWorkspace } from "./workspace-provider";

const owners: Record<string, AgentRole> = { course_preparation: "expert", next_activity: "tutoring", assessment: "assessing" };
const workflowNames: Record<string, string> = { course_preparation: "Course preparation", next_activity: "Practice activity", assessment: "Answer review" };
const readable = (value: string) => value.replaceAll("_", " ");
function Status({ value }: { value: string }) {
  return <span className={`activity-status activity-status-${value}`}><i aria-hidden="true" />{readable(value)}</span>;
}
function timestamp(value?: string | null) {
  return value ? new Date(value).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "Time unavailable";
}
function groupEvents(events: AgentEvent[]) {
  const groups: AgentEvent[][] = [];
  for (const event of [...events].sort((a, b) => a.sequence - b.sequence)) {
    const previous = groups.at(-1)?.[0];
    if (event.type === "agent.step" && previous?.type === "agent.step" && event.payload.role === previous.payload.role && event.payload.task === previous.payload.task) groups[groups.length - 1].push(event);
    else groups.push([event]);
  }
  return groups;
}
function EventItem({ event }: { event: AgentEvent }) {
  const title = event.type === "agent.step" ? event.payload.task : event.type === "agent.handoff" ? `${agentNames[event.payload.from]} → ${agentNames[event.payload.to]}` : event.type === "runtime.validation" ? "Validation check" : "Workflow update";
  const detail = event.type === "agent.step" ? event.payload.detail : event.type === "agent.handoff" ? event.payload.reason : event.payload.summary;
  return <li className="activity-event"><span className="activity-event-dot" aria-hidden="true" /><div><div className="activity-event-heading"><strong>{title}</strong><time dateTime={event.at}>{timestamp(event.at)}</time></div><p>{detail}</p>{event.type === "agent.step" && <div className="activity-event-meta"><span>{agentNames[event.payload.role]}</span><Status value={event.payload.status} />{event.payload.tool && <span>{readable(event.payload.tool)}</span>}</div>}</div></li>;
}

export function AgentActivityWorkspace() {
  const { runs, courseId, course, refresh } = useWorkspace();
  const [role, setRole] = useState<AgentRole | "all">(() => {
    if (typeof window === "undefined") return "all";
    const value = new URLSearchParams(window.location.search).get("agent");
    return agentRoles.includes(value as AgentRole) ? value as AgentRole : "all";
  });
  const [filter, setFilter] = useState(() => {
    if (typeof window === "undefined") return "all";
    const value = new URLSearchParams(window.location.search).get("status");
    return ["working", "waiting", "attention", "completed"].includes(value || "") ? value! : "all";
  });
  const [query, setQuery] = useState(() => typeof window === "undefined" ? "" : new URLSearchParams(window.location.search).get("q") || "");
  const [selectedId, setSelectedId] = useState(() => new URLSearchParams(typeof window === "undefined" ? "" : window.location.search).get("run") || "");
  const [snapshot, setSnapshot] = useState<AgentRun | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const detailPanel = useRef<HTMLElement>(null);
  const listScrollY = useRef(0);
  const [showAll, setShowAll] = useState(false);
  const ordered = newestRuns(runs);
  const visible = ordered.filter(run => (role === "all" || owners[run.workflow] === role) && (filter === "all" || (filter === "working" ? workingStates.has(run.status) : filter === "attention" ? blockedStates.has(run.status) : filter === "waiting" ? run.status === "waiting_for_learner" : run.status === "completed")) && `${run.summary} ${workflowNames[run.workflow] || run.workflow} ${course?.documents.find(d => d.id === run.documentId)?.filename || ""}`.toLowerCase().includes(query.trim().toLowerCase()));
  const shown = showAll ? visible : visible.slice(0, 8);
  const id = selectedId;
  const run = snapshot?.id === id && snapshot.courseId === courseId ? snapshot : null;
  const activeFilters = Number(role !== "all") + Number(filter !== "all") + Number(!!query.trim());
  function syncUrl(patch: Partial<{ run: string | null; agent: string; status: string; q: string }>, push = false) {
    const url = new URL(window.location.href);
    for (const [key, value] of Object.entries(patch)) {
      if (!value || (key === "agent" && value === "all") || (key === "status" && value === "all")) url.searchParams.delete(key);
      else url.searchParams.set(key, value);
    }
    const next = `${url.pathname}${url.search}${url.hash}`;
    window.history[push ? "pushState" : "replaceState"](null, "", next);
  }
  useEffect(() => {
    const syncFromHistory = () => {
      const params = new URLSearchParams(window.location.search);
      const agent = params.get("agent"); const status = params.get("status");
      setSelectedId(params.get("run") || "");
      setRole(agentRoles.includes(agent as AgentRole) ? agent as AgentRole : "all");
      setFilter(["working", "waiting", "attention", "completed"].includes(status || "") ? status! : "all");
      setQuery(params.get("q") || "");
    };
    window.addEventListener("popstate", syncFromHistory);
    return () => window.removeEventListener("popstate", syncFromHistory);
  }, []);
  useEffect(() => {
    if (selectedId && window.matchMedia("(max-width: 850px)").matches) requestAnimationFrame(() => detailPanel.current?.scrollIntoView({ block: "start" }));
  }, [selectedId]);
  useEffect(() => {
    if (!id) return;
    let active = true;
    const update = () => api<AgentRun>(`agent-activity/runs/${id}`).then(value => {
      if (!active) return;
      if (value.courseId !== courseId) { setError("This activity belongs to another course."); return; }
      setSnapshot(value); setError("");
    }).catch(e => { if (active) setError(e.message); });
    void update();
    const timer = setInterval(update, 4000);
    return () => { active = false; clearInterval(timer); };
  }, [id, courseId]);
  function clearSelection(restorePosition = false) {
    setSelectedId(""); setError(""); syncUrl({ run: null });
    if (restorePosition) requestAnimationFrame(() => window.scrollTo(0, listScrollY.current));
  }
  function updateFilters(next: { role?: AgentRole | "all"; filter?: string; query?: string }) {
    const nextRole = next.role ?? role; const nextFilter = next.filter ?? filter; const nextQuery = next.query ?? query;
    if (next.role !== undefined) setRole(next.role);
    if (next.filter !== undefined) setFilter(next.filter);
    if (next.query !== undefined) setQuery(next.query);
    setShowAll(false); clearSelection();
    syncUrl({ agent: nextRole, status: nextFilter, q: nextQuery });
  }
  async function command(kind: "retry" | "resume") {
    if (!run || busy) return;
    setBusy(true); setError("");
    try {
      await api(`agent-activity/runs/${run.id}/commands`, { kind, operationId: crypto.randomUUID(), expectedVersion: run.recordVersion });
      setSnapshot(await api<AgentRun>(`agent-activity/runs/${run.id}`));
      await refresh();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  const events = run?.events || [];
  const roleCounts = Object.fromEntries(agentRoles.map(agent => [agent, ordered.filter(item => owners[item.workflow] === agent).length])) as Record<AgentRole, number>;
  return <div className="activity-workspace">
    <div className="activity-overview"><p>{ordered.length} {ordered.length === 1 ? "activity" : "activities"}<span aria-hidden="true"> · </span>{agentRoles.map((agent, index) => <span key={agent}>{index > 0 && <span aria-hidden="true"> · </span>}{agentNames[agent]} {roleCounts[agent]}</span>)}</p><span className="activity-update"><i />Live updates</span></div>
    <div className="activity-toolbar">{selectedId ? <span>Activity details</span> : <><details className="activity-filter-menu"><summary>Filter activity{activeFilters > 0 && <span>{activeFilters}</span>}</summary><div className="activity-filter-panel"><label>Agent<select value={role} onChange={event => updateFilters({ role: event.target.value as AgentRole | "all" })}><option value="all">All agents</option>{agentRoles.map(agent => <option key={agent} value={agent}>{agentNames[agent]}</option>)}</select></label><label>Status<select value={filter} onChange={event => updateFilters({ filter: event.target.value })}><option value="all">All activity</option><option value="working">In progress</option><option value="waiting">Waiting for you</option><option value="attention">Needs attention</option><option value="completed">Completed</option></select></label><label className="activity-search">Search activity or material<input type="search" placeholder="Search activity or material…" value={query} onChange={event => updateFilters({ query: event.target.value })} /></label>{activeFilters > 0 && <button className="text-link" onClick={() => updateFilters({ role: "all", filter: "all", query: "" })}>Clear filters</button>}</div></details><span>{`${visible.length} matching ${visible.length === 1 ? "activity" : "activities"}`}</span></>}</div>
    {selectedId ? <section ref={detailPanel} className="activity-detail activity-detail-page" aria-label="Selected activity details" aria-busy={!run && !error}>
      <button className="activity-back" onClick={() => clearSelection(true)}>← Back to activity</button>
      {error && <p className="live-error" role="alert">{error}</p>}
      {!run ? <div className="activity-empty"><span className="activity-empty-symbol" aria-hidden="true">◎</span><h3>{error ? "Activity unavailable" : "Loading activity…"}</h3><p>{error ? "Return to the activity list to choose another run." : "Loading the recorded work and results."}</p></div> : <>
        <div className="activity-detail-header"><div><p className="eyebrow">{agentNames[owners[run.workflow]] || "LEARNING TEAM"} · {timestamp(run.events[0]?.at)}</p><h2>{workflowNames[run.workflow] || run.label}</h2>{run.conceptId && course?.graph.concepts.find(concept => concept.id === run.conceptId)?.title && <p className="activity-concept-name">{course.graph.concepts.find(concept => concept.id === run.conceptId)?.title}</p>}</div><Status value={run.status} /></div><p className="activity-summary">{run.summary}</p>
        {run.error && <p className="live-error" role="alert">{run.error.message}</p>}
        {!!run.allowedCommands.length && <div className="activity-next-action"><strong>Next action</strong><div className="live-actions">{run.allowedCommands.map(kind => <button key={kind} disabled={busy} className="button dark" onClick={() => void command(kind)}>{busy ? "Processing…" : kind === "retry" ? "Retry processing" : "Resume processing"}</button>)}</div></div>}
        <div className="activity-stages"><details><summary><span>Agent stages</span><span>{agentRoles.length} agents</span></summary><div>{agentRoles.map(agent => { const stage = run.agents[agent]; return <details className="activity-stage" key={agent}><summary><AgentPortrait role={agent} size={32} /><strong>{agentNames[agent]}</strong><Status value={stage.status} /></summary><div><h3>{stage.task}</h3><p>{stage.detail}</p>{stage.tool && <small>Tool: {readable(stage.tool)}</small>}{stage.error && <p className="live-error">{stage.error.message}</p>}</div></details>; })}</div></details></div>
        <div className="activity-results"><details><summary>Work timeline <span>{events.length} steps</span></summary><div>{events.length ? <ol className="activity-event-list">{groupEvents(events).map(group => group.length === 1 ? <EventItem key={group[0].id} event={group[0]} /> : <li className="activity-event-group" key={group[0].id}><details><summary><strong>{group[0].type === "agent.step" ? group[0].payload.task : "Task updates"}</strong><span>{group.length} updates</span></summary><p>{group.at(-1)?.type === "agent.step" ? (group.at(-1) as Extract<AgentEvent, { type: "agent.step" }>).payload.detail : ""}</p><ol>{group.map(event => <EventItem key={event.id} event={event} />)}</ol></details></li>)}</ol> : <p>No recorded steps yet.</p>}</div></details>
          <details><summary>Outputs & sources <span>{run.artifacts.length} outputs · {run.references.length} sources</span></summary><div>{!run.artifacts.length && <p>No outputs recorded yet.</p>}{run.artifacts.map(a => <div className="activity-result" key={a.id}><strong>{a.label}</strong><Status value={a.status} /></div>)}{run.references.map((reference, index) => <p key={index}>{reference.label}{reference.page ? ` · p. ${reference.page}` : ""}</p>)}</div></details>
          <details><summary>Validation & saved changes <Status value={run.validation.status} /></summary><div><p>{run.validation.summary}</p>{run.validation.candidate && <p>Proposed: {run.validation.candidate.conceptId} · {readable(run.validation.candidate.before)} → {readable(run.validation.candidate.after)}</p>}{run.committedChanges.map((change, index) => <p key={index}>{change.conceptId} · {change.difficulty}: {readable(change.before)} → {readable(change.after)}</p>)}{!run.committedChanges.length && <p>No learner-state changes saved in this run.</p>}</div></details></div>
      </>}
    </section> : <>
      <div className="activity-list-heading"><h2>{role === "all" ? "Latest activity" : `${agentNames[role]} activity`}</h2><span>{visible.length} {visible.length === 1 ? "result" : "results"}</span></div>
      <section className="activity-run-list" aria-label="Activity runs">
        {!visible.length && <div className="activity-empty"><h3>{runs.length ? "No matching activity" : "Your team is ready"}</h3><p>{runs.length ? "Try another agent, status, or search term." : "Upload course materials to give your Expert its first task."}</p>{!runs.length && <Link className="text-link" href="/materials">Add materials →</Link>}</div>}
        {shown.map(item => <button key={item.id} className="activity-run-item" onClick={() => { listScrollY.current = window.scrollY; setSelectedId(item.id); setError(""); syncUrl({ run: item.id }, true); }}><div className="activity-run-item-top"><span>{agentNames[owners[item.workflow]] || "Team"}</span><Status value={item.status} /></div><div className="activity-run-item-main"><h3>{workflowNames[item.workflow] || readable(item.workflow)}</h3><p>{item.summary}</p></div><div className="activity-run-item-bottom"><time dateTime={item.startedAt || undefined}>{timestamp(item.startedAt)}</time>{item.documentId && <span className="activity-material-name">{course?.documents.find(d => d.id === item.documentId)?.filename || "Course material"}</span>}<span aria-hidden="true">→</span></div></button>)}
      </section>
      {visible.length > 8 && <button className="activity-show-more" onClick={() => setShowAll(value => !value)}>{showAll ? "Show recent activities" : `Show all ${visible.length} activities`}</button>}
    </>}
  </div>;
}

