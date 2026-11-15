"use client";

import { useId, useRef, useState } from "react";
import type { Difficulty } from "@/lib/backend";
import { hierarchy, type HierarchyTopic } from "@/lib/topic-hierarchy";

type Status = "unassessed" | "developing" | "demonstrated" | "review_due";
export type BrainGraph = {
  concepts: { id: string; title: string; targetDifficulty: Difficulty }[];
  prerequisites: { prerequisite: string; dependent: string }[];
  related: { first: string; second: string }[];
  topics?: HierarchyTopic[];
};
export type BrainStates = Record<string, Record<Difficulty, Status>>;

const levels: Difficulty[] = ["basic", "intermediate", "advanced"];
const labels: Record<Status, string> = { unassessed: "Not assessed", developing: "Developing", demonstrated: "Demonstrated", review_due: "Review due" };
const colors: Record<Status, string> = { unassessed: "#e7edf2", developing: "#f5d18b", demonstrated: "#87bba2", review_due: "#e7a496" };
const abbreviations = { basic: "B", intermediate: "I", advanced: "A" };
const boxWidth = 205, boxHeight = 112, stepX = 255, stepY = 165;

function splitTitle(title: string): string[] {
  const lines: string[] = [];
  for (const word of title.split(/\s+/)) {
    const last = lines.length - 1;
    if (last < 0 || `${lines[last]} ${word}`.length > 22) lines.push(word);
    else lines[last] += ` ${word}`;
  }
  if (lines.length > 2) return [lines[0], `${lines.slice(1).join(" ").slice(0, 20).trimEnd()}…`];
  return lines;
}

export function TutorBrainMemory({ graph, states, gaps, currentConceptId, showEvidence = true, onOpenConcept, onStartLearning }: {
  graph: BrainGraph; states: BrainStates; gaps: Record<string, { gap?: { summary?: string } | null }>;
  currentConceptId?: string | null;
  showEvidence?: boolean; onOpenConcept?: (id: string) => void; onStartLearning?: (id: string, title: string) => void;
}) {
  const marker = useId().replaceAll(":", "");
  const [selectedId, setSelectedId] = useState("");
  const [zoom, setZoom] = useState(100);
  const [topicId, setTopicId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const pointer = useRef<{ id: number; x: number; y: number; panX: number; panY: number; moved: boolean } | null>(null);
  const suppressClick = useRef(false);
  const concepts = graph.concepts;
  const tree = hierarchy(graph.topics || [], concepts.map(concept => concept.id));
  const currentTopic = topicId ? tree.byId.get(topicId) : undefined;
  const visibleTopics = tree.children(currentTopic?.id || null);
  const directIds = currentTopic ? currentTopic.conceptIds : tree.ungrouped;
  const visibleConcepts = concepts.filter(concept => directIds.includes(concept.id));
  const items = [...visibleTopics.map(topic => ({ kind: "topic" as const, id: topic.id, topic })), ...visibleConcepts.map(concept => ({ kind: "concept" as const, id: concept.id, concept }))];
  const selected = concepts.find(concept => concept.id === selectedId) || concepts.find(concept => concept.id === currentConceptId) || concepts[0];
  const columns = Math.min(3, Math.max(1, items.length));
  const rows = Math.ceil(items.length / columns);
  const width = columns * stepX + 40;
  const height = Math.max(180, rows * stepY + 25);
  const points = new Map(items.map((item, index) => [`${item.kind}:${item.id}`, { x: 45 + (index % columns) * stepX, y: 35 + Math.floor(index / columns) * stepY }]));
  function edge(from: string, to: string) {
    const a = points.get(`concept:${from}`), b = points.get(`concept:${to}`);
    if (!a || !b || from === to) return null;
    const dx = b.x - a.x, dy = b.y - a.y;
    const scale = Math.max(Math.abs(dx) / (boxWidth / 2 + 5), Math.abs(dy) / (boxHeight / 2 + 5));
    return { x1: a.x + boxWidth / 2 + dx / scale, y1: a.y + boxHeight / 2 + dy / scale, x2: b.x + boxWidth / 2 - dx / scale, y2: b.y + boxHeight / 2 - dy / scale };
  }
  const stateFor = (id: string, level: Difficulty): Status => states[id]?.[level] || "unassessed";
  const selectedPrerequisites = graph.prerequisites.filter(e => e.dependent === selected?.id).map(e => concepts.find(c => c.id === e.prerequisite)?.title).filter(Boolean);
  const selectedRelated = graph.related.filter(e => e.first === selected?.id || e.second === selected?.id).map(e => concepts.find(c => c.id === (e.first === selected?.id ? e.second : e.first))?.title).filter(Boolean);
  const counts = concepts.reduce((result, concept) => { const status = stateFor(concept.id, concept.targetDifficulty); result[status]++; return result; }, { unassessed: 0, developing: 0, demonstrated: 0, review_due: 0 });
  if (!concepts.length) return <p className="expert-muted">No published concepts are available for this memory yet.</p>;

  function openTopic(id: string | null) { setTopicId(id); setZoom(100); setPan({ x: 0, y: 0 }); }
  const results = query.trim() ? [...(graph.topics || []).filter(topic => topic.title.toLowerCase().includes(query.trim().toLowerCase())).map(topic => ({ kind: "topic" as const, id: topic.id, title: topic.title })), ...concepts.filter(concept => concept.title.toLowerCase().includes(query.trim().toLowerCase())).map(concept => ({ kind: "concept" as const, id: concept.id, title: concept.title }))].slice(0, 20) : [];

  return <div className="tutor-brain">
    <p className="tutor-brain-intro">Open a topic to explore its concepts{showEvidence ? " and evidence at three levels" : ""}.</p>
    <p className="tutor-brain-counts"><strong>{concepts.length} concepts</strong>{showEvidence && <> · At course target: {Object.entries(counts).filter(([, count]) => count > 0).map(([status, count]) => `${count} ${labels[status as Status].toLowerCase()}`).join(" · ")}</>}</p>
    <div className="tutor-hierarchy-search"><label>Find a topic or concept<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search the learning map" /></label>{query.trim() && <div className="tutor-hierarchy-results">{results.length ? results.map(result => <button type="button" key={`${result.kind}:${result.id}`} onClick={() => { if (result.kind === "topic") openTopic(result.id); else { const topic = (graph.topics || []).find(item => item.conceptIds.includes(result.id)); openTopic(topic?.id || null); setSelectedId(result.id); } setQuery(""); }}>{result.title} <small>{result.kind}</small></button>) : <span>No matching topics or concepts.</span>}</div>}</div>
    <nav className="tutor-hierarchy-breadcrumbs" aria-label="Topic path"><button type="button" onClick={() => openTopic(null)}>Course</button>{currentTopic && tree.path(currentTopic.id).map(topic => <span key={topic.id}> / <button type="button" onClick={() => openTopic(topic.id)} aria-current={topic.id === currentTopic.id ? "page" : undefined}>{topic.title}</button></span>)}</nav>
    <div className="tutor-brain-toolbar"><div className="tutor-brain-legend">{showEvidence && (Object.keys(labels) as Status[]).map(status => <span key={status}><i style={{ background: colors[status] }} />{labels[status]}</span>)}</div><div className="tutor-brain-zoom" aria-label="Graph zoom"><button type="button" aria-label="Zoom out" disabled={zoom <= 100} onClick={() => setZoom(z => Math.max(100, z - 25))}>−</button><span>{zoom}%</span><button type="button" aria-label="Zoom in" disabled={zoom >= 200} onClick={() => setZoom(z => Math.min(200, z + 25))}>+</button><button type="button" className="tutor-brain-reset" aria-label="Return to course topics and reset map position and zoom" onClick={() => openTopic(null)}>Reset view</button></div></div>
    {showEvidence && visibleTopics.length > 0 && <div className="tutor-topic-progress-legend"><span>Topic progress · demonstrated at course target</span><span className="tutor-topic-progress-scale"><span className="tutor-topic-unlearned" aria-hidden="true" />Not learned <span>Less familiar</span><i aria-hidden="true" /><span>Demonstrated</span></span></div>}
    <p className="tutor-brain-map-help">Drag to move the map. Use the zoom controls or arrow keys to explore.</p>
    <div className={`tutor-brain-canvas${dragging ? " dragging" : ""}`} tabIndex={0} aria-label="Learning map. Drag or use arrow keys to move; select a concept for details."
      onPointerDown={event => {
        if (!event.isPrimary || event.button !== 0) return;
        suppressClick.current = false;
        pointer.current = { id: event.pointerId, x: event.clientX, y: event.clientY, panX: pan.x, panY: pan.y, moved: false };
      }}
      onPointerMove={event => {
        const start = pointer.current;
        if (!start || start.id !== event.pointerId) return;
        const dx = event.clientX - start.x, dy = event.clientY - start.y;
        if (!start.moved && Math.hypot(dx, dy) >= 5) {
          start.moved = true;
          event.currentTarget.setPointerCapture(event.pointerId);
          setDragging(true);
        }
        if (start.moved) { event.preventDefault(); setPan({ x: start.panX + dx, y: start.panY + dy }); }
      }}
      onPointerUp={event => { if (pointer.current?.id === event.pointerId) { suppressClick.current = pointer.current.moved; pointer.current = null; setDragging(false); } }}
      onPointerCancel={() => { pointer.current = null; suppressClick.current = false; setDragging(false); }}
      onClickCapture={event => { if (suppressClick.current) { event.preventDefault(); event.stopPropagation(); suppressClick.current = false; } }}
      onKeyDown={event => {
        if (event.target !== event.currentTarget) return;
        const delta: Record<string, [number, number]> = { ArrowLeft: [40, 0], ArrowRight: [-40, 0], ArrowUp: [0, 40], ArrowDown: [0, -40] };
        if (delta[event.key]) { event.preventDefault(); const [x, y] = delta[event.key]; setPan(current => ({ x: current.x + x, y: current.y + y })); }
      }}>
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: `${zoom}%`, transform: `translate(${pan.x}px, ${pan.y}px)` }} role="group" aria-label="Concept map; select a concept to see its learning memory">
        <defs><marker id={marker} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#71889a" /></marker></defs>
        <svg x="0" y="0" width={width} height={height} viewBox="0 0 800 540" preserveAspectRatio="none" aria-hidden="true"><path d="M 400 68 C 361 18 290 34 266 75 C 196 44 139 89 137 148 C 69 156 52 214 83 260 C 40 309 79 367 135 374 C 128 439 194 470 249 447 C 292 500 359 493 400 459 C 441 493 508 500 551 447 C 606 470 672 439 665 374 C 721 367 760 309 717 260 C 748 214 731 156 663 148 C 661 89 604 44 534 75 C 510 34 439 18 400 68 Z" fill="#eef5f3" stroke="#dceae7" strokeWidth="3" /><path d="M400 68 C 381 145 416 200 400 270 C 384 340 416 395 400 459" fill="none" stroke="#dceae7" strokeWidth="3" /></svg>
        {graph.related.map((item, index) => { const line = edge(item.first, item.second); return line && <line key={`r${index}`} {...line} stroke="#9baab5" strokeWidth="2" strokeDasharray="6 5" />; })}
        {graph.prerequisites.map((item, index) => { const line = edge(item.prerequisite, item.dependent); return line && <line key={`p${index}`} {...line} stroke="#71889a" strokeWidth="2" markerEnd={`url(#${marker})`} />; })}
        {visibleTopics.map(topic => {
          const point = points.get(`topic:${topic.id}`)!, title = splitTitle(topic.title), members = tree.descendants(topic.id);
          const summary = (Object.keys(labels) as Status[]).map(status => ({ status, count: members.filter(id => { const concept = concepts.find(item => item.id === id); return concept && stateFor(id, concept.targetDifficulty) === status; }).length })).filter(item => item.count);
          const summaryText = summary.map(item => `${item.count} ${labels[item.status].toLowerCase()}`).join(" · ");
          const countText = `${members.length} concept${members.length === 1 ? "" : "s"}`;
          const demonstrated = summary.find(item => item.status === "demonstrated")?.count || 0;
          const progress = members.length ? Math.round(demonstrated / members.length * 100) : 0;
          const unassessed = summary.find(item => item.status === "unassessed")?.count || 0;
          const progressFill = !members.length || unassessed === members.length ? "#fff" : `rgb(${Math.round(255 - progress * 1.05)}, ${Math.round(232 - progress * 0.40)}, ${Math.round(166 - progress * 0.04)})`;
          const progressText = !members.length ? "No concepts yet" : unassessed === members.length ? "Not learned yet" : `${progress}% demonstrated at course target`;
          return <g key={`topic:${topic.id}`} transform={`translate(${point.x} ${point.y})`} role="button" tabIndex={0} aria-label={`Open topic ${topic.title}, ${countText}${showEvidence ? `, ${progressText}${summaryText ? `, ${summaryText}` : ""}` : ""}`} onClick={() => openTopic(topic.id)} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openTopic(topic.id); } }} className="tutor-brain-node">
            <title>{`${topic.title}${showEvidence ? ` · ${progressText}${summaryText ? ` · ${summaryText}` : ""}` : ""}`}</title><rect width={boxWidth} height={boxHeight} rx="12" fill={showEvidence ? progressFill : "#edf5f4"} stroke={showEvidence ? "#b4c4b7" : "#8fb7b1"} strokeWidth="1.5" />
            <text x="12" y="23" fontSize="13" fontWeight="700" fill="#172d45">{title.map((line, index) => <tspan key={index} x="12" dy={index ? "16" : "0"}>{line}</tspan>)}</text><text x="12" y="61" fontSize="12" fill="#506c73">{countText}</text>
            {showEvidence && <text x="12" y="78" fontSize="10" fill="#345a83">{progressText}</text>}<text x="12" y="98" fontSize="12" fontWeight="700" fill="#2169a0">Open topic →</text>
          </g>;
        })}
        {visibleConcepts.map(concept => { const point = points.get(`concept:${concept.id}`)!; const title = splitTitle(concept.title); const active = selected?.id === concept.id; return <g key={concept.id} transform={`translate(${point.x} ${point.y})`} role="button" tabIndex={0} aria-pressed={active} aria-label={`${concept.title}, target ${concept.targetDifficulty}${showEvidence ? `. ${levels.map(level => `${level}: ${labels[stateFor(concept.id, level)]}`).join(", ")}` : ""}`} onClick={() => setSelectedId(concept.id)} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelectedId(concept.id); } }} className="tutor-brain-node">
          <title>{concept.title}</title><rect width={boxWidth} height={boxHeight} rx="12" fill="white" stroke={active ? "#2169d9" : "#cbd9e2"} strokeWidth={active ? 3 : 1.5} />
          <text x="12" y="23" fontSize="13" fontWeight="700" fill="#172d45">{title.map((line, index) => <tspan key={index} x="12" dy={index ? "16" : "0"}>{line}</tspan>)}</text>
          <text x="12" y="62" fontSize="11" fill="#5c7083">Course target: {concept.targetDifficulty}</text>
          {showEvidence && levels.map((level, index) => <g key={level} transform={`translate(${12 + index * 62} 73)`}><rect width="55" height="26" rx="7" fill={colors[stateFor(concept.id, level)]} /><text x="27.5" y="18" textAnchor="middle" fontSize="12" fontWeight="700" fill="#233b4b">{abbreviations[level]}</text></g>)}
        </g>; })}
      </svg>
    </div>
    <p className="tutor-brain-edge-legend"><span>→ Prerequisite</span><span>┄ Related concept</span><span>B Basic · I Intermediate · A Advanced</span></p>
    {selected && visibleConcepts.some(concept => concept.id === selected.id) && <div className="tutor-brain-details" aria-live="polite"><div className="tutor-brain-details-heading"><div><small>SELECTED CONCEPT</small><h3>{selected.title}</h3></div><span>Target: {selected.targetDifficulty}</span></div>{showEvidence && <div className="tutor-brain-levels">{levels.map(level => <div key={level}><span>{level[0].toUpperCase() + level.slice(1)}</span><strong><i style={{ background: colors[stateFor(selected.id, level)] }} />{labels[stateFor(selected.id, level)]}</strong></div>)}</div>}{gaps[selected.id]?.gap?.summary && <p><strong>Learning gap:</strong> {gaps[selected.id].gap?.summary}</p>}{Boolean(selectedPrerequisites.length) && <p><strong>Prerequisites:</strong> {selectedPrerequisites.join(", ")}</p>}{Boolean(selectedRelated.length) && <p><strong>Related:</strong> {selectedRelated.join(", ")}</p>}{onOpenConcept && <button type="button" className="expert-button secondary" onClick={() => onOpenConcept(selected.id)}>View concept details</button>}{onStartLearning && <button type="button" className="expert-button primary" onClick={() => onStartLearning(selected.id, selected.title)}>Start learning here</button>}</div>}
  </div>;
}
