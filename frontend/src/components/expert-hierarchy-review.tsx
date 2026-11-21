"use client";

import { useEffect, useState } from "react";
import { api, type CourseDetail } from "@/lib/backend";
import { hierarchy, type HierarchyTopic } from "@/lib/topic-hierarchy";

export type SavedHierarchy = { runId: string; createdAt: string; filenames: string[]; ready: boolean; published: boolean; releaseId?: string | null; revision: number };

export function ExpertHierarchyReview({ course, runId, active, preview, source, onPublished }: {
  course: CourseDetail; runId: string; active: boolean; preview: boolean; source?: SavedHierarchy; onPublished: () => Promise<void>;
}) {
  const [snapshot, setSnapshot] = useState<{ graph: CourseDetail["graph"]; revision: number } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const savedId = source?.runId;
  const revision = source?.revision ?? 0;
  useEffect(() => {
    if (!savedId) return;
    let current = true;
    api<CourseDetail["graph"]>(`courses/${course.id}/hierarchy-runs/${savedId}`).then(value => {
      if (current) { setSnapshot({ graph: value, revision }); setError(""); }
    }).catch(cause => { if (current) setError((cause as Error).message); });
    return () => { current = false; };
  }, [course.id, savedId, revision]);
  async function publish() {
    setBusy(true); setError("");
    try { await api(`courses/${course.id}/hierarchy-runs/${runId}/publish`, {}); await onPublished(); }
    catch (cause) { setError((cause as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="expert-card expert-hierarchy-review">
    <div className="expert-card-heading"><div><h2>{preview && runId ? "Starting hierarchy" : "Run topic hierarchy"}</h2>
      <p>{source ? source.filenames.join(", ") || "Published course hierarchy" : active ? "Waiting for this run to save its hierarchy." : runId ? "This run has no saved hierarchy." : "Select a run to see its saved hierarchy."}</p></div>
      {preview ? null : source?.published ? <span className="expert-status-tag">Published</span> : source?.ready && <button type="button" className="expert-button secondary" disabled={busy} onClick={() => void publish()}>{busy ? "Publishing…" : "Publish to course"}</button>}
    </div>
    {error && <p role="alert" className="expert-alert">{error}</p>}
    {source && snapshot && <HierarchyTree key={source.runId + ":" + snapshot.revision} course={{ ...course, graph: snapshot.graph }} editable={Boolean(!preview && source.releaseId && course.release?.id === source.releaseId)} onSaved={onPublished} />}
  </section>;
}

function HierarchyTree({ course, editable, onSaved }: { course: CourseDetail; editable: boolean; onSaved: () => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [topics, setTopics] = useState<HierarchyTopic[]>(() => (course.graph.topics || []).map(topic => ({ ...topic, parentId: topic.parentId || null, conceptIds: [...topic.conceptIds] })));
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(["__course__", ...(course.graph.topics || []).map(topic => topic.id)]));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const tree = hierarchy(topics, course.graph.concepts.map(concept => concept.id));
  const concepts = new Map(course.graph.concepts.map(concept => [concept.id, concept]));
  function update(id: string, change: Partial<HierarchyTopic>) { setTopics(items => items.map(topic => topic.id === id ? { ...topic, ...change } : topic)); }
  function moveConcept(id: string, destination: string) { setTopics(items => items.map(topic => ({ ...topic, conceptIds: topic.id === destination ? [...topic.conceptIds.filter(value => value !== id), id] : topic.conceptIds.filter(value => value !== id) }))); }
  function toggle(id: string) { setExpanded(current => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next; }); }
  function expandAll() { setExpanded(new Set(["__course__", ...topics.map(topic => topic.id)])); }
  function collapseAll() { setExpanded(new Set()); }
  function renderTopic(topic: HierarchyTopic): React.ReactNode {
    const childTopics = tree.children(topic.id);
    const childConcepts = topic.conceptIds.filter(id => concepts.has(id));
    return <li className="expert-hierarchy-branch" key={topic.id}>
      <article className="expert-hierarchy-topic" role="treeitem" aria-selected="false" aria-expanded={expanded.has(topic.id)}><div className="expert-hierarchy-topic-title"><button type="button" className="expert-hierarchy-toggle" aria-label={`${expanded.has(topic.id) ? "Collapse" : "Expand"} ${topic.title}`} aria-expanded={expanded.has(topic.id)} onClick={() => toggle(topic.id)}>{expanded.has(topic.id) ? "▾" : "▸"}</button>{editing ? <label className="expert-field-label">Topic name<input maxLength={100} value={topic.title} onChange={event => update(topic.id, { title: event.target.value })} /></label> : <div><strong>{topic.title}</strong><small>{topic.summary}</small></div>}</div>
        {editing ? <label className="expert-field-label">Parent topic<select value={topic.parentId || ""} onChange={event => update(topic.id, { parentId: event.target.value || null })}><option value="">Course root</option>{topics.filter(candidate => candidate.id !== topic.id && !tree.path(candidate.id).some(ancestor => ancestor.id === topic.id)).map(candidate => <option key={candidate.id} value={candidate.id}>{candidate.title}</option>)}</select></label> : null}
        <span className="expert-hierarchy-count">{tree.descendants(topic.id).length} {tree.descendants(topic.id).length === 1 ? "concept" : "concepts"}</span>
        {!childConcepts.length && !childTopics.length && <p className="expert-hierarchy-empty">No concepts in this topic yet.</p>}
        {!childConcepts.length && !childTopics.length && editing && <button type="button" className="expert-text-button" onClick={() => setTopics(items => items.filter(item => item.id !== topic.id))}>Remove empty topic</button>}
      </article>
      {expanded.has(topic.id) && (childTopics.length > 0 || childConcepts.length > 0) && <ul className="expert-hierarchy-children" aria-label={`Items in ${topic.title}`}>
        {childTopics.map(child => renderTopic(child))}
        {childConcepts.map(id => <li className="expert-hierarchy-concept" role="treeitem" aria-selected="false" key={id}><span className="expert-hierarchy-leaf" aria-hidden="true">◦</span>{editing ? <><strong>{concepts.get(id)?.title || id}</strong><label className="expert-field-label"><span className="tutor-visually-hidden">Move concept</span><select aria-label={`Move ${concepts.get(id)?.title || id} to topic`} value={topic.id} onChange={event => moveConcept(id, event.target.value)}>{topics.map(candidate => <option key={candidate.id} value={candidate.id}>{candidate.title}</option>)}</select></label></> : <span>{concepts.get(id)?.title || id}</span>}</li>)}
      </ul>}
    </li>;
  }
  async function save() {
    if (!course.release) return;
    setBusy(true); setMessage("");
    try {
      await api(`courses/${course.id}/hierarchy`, { expectedReleaseId: course.release.id, topics });
      await onSaved();
      setTopics((course.graph.topics || []).map(topic => ({ ...topic, conceptIds: [...topic.conceptIds] })));
      setMessage("Edited hierarchy published as a new course release."); setEditing(false);
    } catch (error) { setMessage((error as Error).message); } finally { setBusy(false); }
  }
  return <div>{editable && <button type="button" className="expert-button secondary" disabled={busy} onClick={() => { setTopics((course.graph.topics || []).map(topic => ({ ...topic, conceptIds: [...topic.conceptIds] }))); setEditing(v => !v); }}>{editing ? "Cancel" : "Edit published hierarchy"}</button>}
    <div className="expert-hierarchy-summary"><div className="expert-hierarchy-summary-stats"><span><strong>{topics.length}</strong> topics</span><span><strong>{course.graph.concepts.length}</strong> concepts</span></div><div className="expert-hierarchy-tree-controls"><button type="button" onClick={expandAll}>Expand all</button><button type="button" onClick={collapseAll}>Collapse all</button></div></div>{editing && <p className="expert-help-note">Topics contain concepts and may contain nested topics. Saving validates and publishes the complete course.</p>}<div className="expert-hierarchy-tree-scroll"><div className="expert-hierarchy-tree" role="tree" aria-label="Course topic hierarchy"><div className="expert-hierarchy-root" role="treeitem" aria-selected="false" aria-expanded={expanded.has("__course__")}><button type="button" className="expert-hierarchy-toggle" aria-label={`${expanded.has("__course__") ? "Collapse" : "Expand"} course topics`} aria-expanded={expanded.has("__course__")} onClick={() => toggle("__course__")}>{expanded.has("__course__") ? "▾" : "▸"}</button><strong>{course.title}</strong><small>COURSE ROOT</small></div>{expanded.has("__course__") && <ul className="expert-hierarchy-roots" role="group">{tree.children(null).map(topic => renderTopic(topic))}{tree.ungrouped.length > 0 && <li className="expert-hierarchy-branch"><article className="expert-hierarchy-topic" role="treeitem" aria-selected="false"><strong>Ungrouped concepts</strong><small>{tree.ungrouped.length} concepts awaiting a topic</small></article><ul className="expert-hierarchy-children" role="group">{tree.ungrouped.map(id => <li className="expert-hierarchy-concept" role="treeitem" aria-selected="false" key={id}><span className="expert-hierarchy-leaf" aria-hidden="true">◦</span><span>{concepts.get(id)?.title || id}</span>{editing && topics.length > 0 && <select aria-label={`Move ${concepts.get(id)?.title || id} to topic`} value="" onChange={event => moveConcept(id, event.target.value)}><option value="">Choose topic</option>{topics.map(candidate => <option key={candidate.id} value={candidate.id}>{candidate.title}</option>)}</select>}</li>)}</ul></li>}</ul>}</div></div>
    {editing && <div className="expert-hierarchy-actions"><button type="button" className="expert-button secondary" onClick={() => setTopics(items => [...items, { id: `topic-${crypto.randomUUID()}`, title: "New topic", summary: "A group of related course topics and concepts.", parentId: null, conceptIds: [] }])}>+ Add topic group</button><button type="button" className="expert-button primary" disabled={busy || !topics.length || topics.some(topic => !topic.title.trim())} onClick={() => void save()}>{busy ? "Publishing…" : "Save and publish"}</button></div>}
    {message && <p role="status" className="expert-help-note">{message}</p>}
  </div>;
}
