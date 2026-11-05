"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { layoutBubbleGraph, bubbleBounds, bubbleLink } from "@/lib/bubble-layout";
import { knowledgeViewUrl, readKnowledgeView, type KnowledgeView } from "@/lib/knowledge-view";
import { useWorkspace } from "./workspace-provider";
import { RichText } from "./rich-text";
import { ConceptStudy } from "./concept-study";
import { LearningDialog } from "./learning-dialog";
import { api, overallState, targetDifficulty } from "@/lib/backend";
import { CurriculumMap } from "./curriculum-map";
import { SpatialExplorer } from "./spatial-explorer";
import { layerOf, layerNames, layerBadge, type CurriculumLayer } from "@/lib/curriculum-map";
import { placeMapPreview } from "@/lib/map-preview";

const states: Record<string, string> = { unassessed: "Not assessed", developing: "Developing", demonstrated: "Demonstrated", review_due: "Review due" };

export function KnowledgeMap() {
  const { course, learner, runs, refresh, materials } = useWorkspace();
  const [selection, setSelection] = useState<KnowledgeView>(() => readKnowledgeView(new URLSearchParams()));
  const [panel, setPanel] = useState<"filters" | "options" | "concept" | null>(null);
  const [mobile, setMobile] = useState(false);
  const [zoom, setZoom] = useState(1);
  const zoomValue = useRef(1);
  const zoomTarget = useRef(1);
  const zoomSurface = useRef<HTMLDivElement>(null);
  const zoomCanvas = useRef<HTMLDivElement>(null);
  const zoomDisplayTimer = useRef<number | null>(null);
  const wheelDelta = useRef(0);
  const wheelPoint = useRef<{ x: number; y: number } | null>(null);
  const wheelFrame = useRef<number | null>(null);
  const [organizing, setOrganizing] = useState(false);
  const [organizationMessage, setOrganizationMessage] = useState("");
  const [preview, setPreview] = useState<({ id: string; pinned: boolean } & ReturnType<typeof placeMapPreview>) | null>(null);
  const mapFrame = useRef<HTMLDivElement>(null);
  const previewBox = useRef<HTMLDivElement>(null);
  const previewAnchor = useRef<HTMLButtonElement | null>(null);
  const previewTimer = useRef<number | null>(null);
  const suppressPreviewFocus = useRef(false);
  const bubblePointerType = useRef("mouse");
  const viewport = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const dragFrame = useRef<number | null>(null);
  const graphKey = JSON.stringify(course?.graph || { concepts: [], prerequisites: [] });
  const layout = useMemo(() => layoutBubbleGraph(JSON.parse(graphKey) as Parameters<typeof layoutBubbleGraph>[0]), [graphKey]);
  const { query, topic: topicFilter, material, status } = selection;
  const selected = layout.nodes.find(node => node.id === selection.id);
  const personal = selection.mode === "personal";
  const topics = course?.graph.topics || [];
  const topicFor = new Map(layout.groups.flatMap(topic => topic.conceptIds.map(id => [id, topic.id] as const)));
  const bubbleTitles = new Map(materials.materials.map(item => [item.conceptId, item.lesson.title]));
  const evidenceLevel = (id: string) => {
    const concept = course?.graph.concepts.find(c => c.id === id);
    return concept ? targetDifficulty(concept) : "intermediate";
  };
  const stateAt = (id: string) => learner?.concepts[id]?.[evidenceLevel(id)]?.state || "unassessed";
  const matches = new Set(layout.nodes.filter(node => {
    const topic = layout.groups.find(item => item.id === node.groupId);
    return `${node.title} ${bubbleTitles.get(node.id) || ""} ${topic?.title || ""}`.toLowerCase().includes(query.trim().toLowerCase()) &&
      (selection.layer === "all" || layerOf(node) === selection.layer) &&
      (topicFilter === "all" || topicFor.get(node.id) === topicFilter) &&
      (material === "all" || node.id.startsWith(`${material}:`)) &&
      (!personal || status === "all" || stateAt(node.id) === status);
  }).map(node => node.id));
  const positions = new Map(layout.nodes.map(node => [node.id, node]));
  const previewNode = positions.get(preview?.id || "");
  const activeNode = previewNode || selected;
  const topicRoutes = new Map<string, { from: typeof layout.groups[number]; to: typeof layout.groups[number] }>();
  for (const [first, second] of [...layout.edges.map(edge => [edge.prerequisite, edge.dependent]), ...layout.related.map(edge => [edge.first, edge.second])]) {
    const from = layout.groups.find(group => group.id === positions.get(first)?.groupId), to = layout.groups.find(group => group.id === positions.get(second)?.groupId);
    if (from && to && from.id !== to.id) topicRoutes.set(JSON.stringify([from.id, to.id].sort()), { from, to });
  }
  const showList = selection.display === "list" || (selection.display === "auto" && mobile && selection.layout === "atlas");
  const expertWorking = organizing || runs.some(run => run.workflow === "course_preparation" && ["queued", "running", "paused"].includes(run.status));
  const filterCount = Number(selection.layer !== "all") + Number(topicFilter !== "all") + Number(material !== "all") + Number(personal && status !== "all");

  function applyZoom(value: number, announce = true) {
    zoomValue.current = value;
    if (zoomSurface.current) { zoomSurface.current.style.width = `${layout.width * value}px`; zoomSurface.current.style.height = `${layout.height * value}px`; }
    if (zoomCanvas.current) zoomCanvas.current.style.transform = `scale(${value})`;
    if (announce) { zoomTarget.current = value; setZoom(value); }
  }

  function cancelPreviewClose() { if (previewTimer.current !== null) { window.clearTimeout(previewTimer.current); previewTimer.current = null; } }
  function closePreview(restoreFocus = false) {
    cancelPreviewClose(); setPreview(null);
    if (restoreFocus) { suppressPreviewFocus.current = true; previewAnchor.current?.focus({ preventScroll: true }); queueMicrotask(() => { suppressPreviewFocus.current = false; }); }
  }
  function openPreview(id: string, button: HTMLButtonElement, pinned = false) {
    if (panel !== null || button.disabled || suppressPreviewFocus.current || !mapFrame.current) return;
    cancelPreviewClose(); previewAnchor.current = button;
    const anchor = button.getBoundingClientRect(), frame = mapFrame.current.getBoundingClientRect();
    const placement = placeMapPreview({ left: anchor.left - frame.left, top: anchor.top - frame.top, width: anchor.width, height: anchor.height }, frame);
    setPreview(current => ({ id, pinned: pinned || (current?.id === id && current.pinned), ...placement }));
  }
  function schedulePreviewClose() {
    cancelPreviewClose(); previewTimer.current = window.setTimeout(() => setPreview(current => current?.pinned || previewAnchor.current === document.activeElement || previewBox.current?.contains(document.activeElement) ? current : null), 220);
  }
  function openPreviewDetails(id: string) {
    suppressPreviewFocus.current = true; previewAnchor.current?.focus({ preventScroll: true });
    closePreview(); select({ id }); queueMicrotask(() => { suppressPreviewFocus.current = false; });
  }

  useEffect(() => {
    const sync = () => { const next = readKnowledgeView(new URLSearchParams(window.location.search)); if (window.matchMedia("(max-width: 700px)").matches && next.layout === "space") next.layout = "pyramid"; setSelection(next); setPanel(next.id ? "concept" : null); };
    const media = window.matchMedia("(max-width: 700px)");
    const resize = () => setMobile(media.matches);
    sync(); resize(); window.addEventListener("popstate", sync); media.addEventListener("change", resize);
    return () => { window.removeEventListener("popstate", sync); media.removeEventListener("change", resize); };
  }, []);
  useEffect(() => {
    if (showList || !viewport.current) return;
    const frame = requestAnimationFrame(() => {
      const filtering = selection.layer !== "all" || topicFilter !== "all" || query.trim() || material !== "all" || status !== "all";
      const matchingGroups = layout.groups.filter(group => group.conceptIds.some(id => matches.has(id)));
      const anchor = layout.groups.find(group => group.id === topics[0]?.id) || layout.groups[0];
      const nearby = [...layout.groups].sort((a, b) => Math.hypot(a.cx - anchor.cx, a.cy - anchor.cy) - Math.hypot(b.cx - anchor.cx, b.cy - anchor.cy)).slice(0, 2);
      const focused = filtering ? matchingGroups : nearby;
      if (!focused.length) return;
      const box = bubbleBounds(focused.map(group => ({ x: group.cx, y: group.cy, radius: group.radius }))), element = viewport.current!;
      const value = Math.max(.8, Math.min(1, element.clientWidth / box.width, element.clientHeight / box.height));
      applyZoom(value);
      requestAnimationFrame(() => element.scrollTo({ left: Math.max(0, (box.x + box.width / 2) * value - element.clientWidth / 2), top: Math.max(0, (box.y + box.height / 2) * value - element.clientHeight / 2), behavior: "instant" }));
    });
    return () => cancelAnimationFrame(frame);
    // Reframe on content/filter changes, without overriding manual pan or zoom.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layout, topicFilter, query, material, status, showList, selection.layout, selection.layer]);

  function update(next: Partial<KnowledgeView>, push = false) {
    closePreview();
    const value = { ...selection, ...next };
    if (value.mode === "course") value.status = "all";
    setSelection(value);
    window.history[push ? "pushState" : "replaceState"](null, "", knowledgeViewUrl(value));
  }
  function select(next: Partial<KnowledgeView>, center = false) {
    const value = { ...next };
    if (next.id && topicFilter !== "all" && topicFor.get(next.id) !== topicFilter) value.topic = topicFor.get(next.id) || "all";
    update(value, true); setPanel("concept");
    if (center && next.id && viewport.current) {
      const node = positions.get(next.id);
      if (node) viewport.current.scrollTo({ left: node.x * zoom - viewport.current.clientWidth / 2, top: node.y * zoom - viewport.current.clientHeight / 2, behavior: "instant" });
    }
  }
  function closePanel() { setPanel(null); }
  function clearFilters() { update({ query: "", topic: "all", material: "all", status: "all", layer: "all" }); }
  function adjustZoom(delta: number) {
    closePreview();
    const element = viewport.current;
    if (!element) return;
    const before = zoomValue.current;
    const value = Math.max(.1, Math.min(2, before + delta));
    const x = (element.scrollLeft + element.clientWidth / 2) / before, y = (element.scrollTop + element.clientHeight / 2) / before;
    applyZoom(value);
    requestAnimationFrame(() => element.scrollTo({ left: x * value - element.clientWidth / 2, top: y * value - element.clientHeight / 2, behavior: "instant" }));
  }
  function fit(wholeMap = false) {
    closePreview();
    const element = viewport.current;
    if (!element) return;
    const topic = layout.topicBoxes.find(item => item.id === (topicFilter !== "all" ? topicFilter : selected ? topicFor.get(selected.id) : undefined)) || layout.topicBoxes[0];
    const filtering = selection.layer !== "all" || query.trim() || material !== "all" || status !== "all";
    const matchedGroups = layout.groups.filter(group => group.conceptIds.some(id => matches.has(id)));
    const box = !wholeMap && filtering ? bubbleBounds(matchedGroups.map(group => ({ x: group.cx, y: group.cy, radius: group.radius }))) : !wholeMap && topic ? topic : bubbleBounds(layout.groups.map(group => ({ x: group.cx, y: group.cy, radius: group.radius })));
    const value = Math.max(.1, Math.min(1.4, element.clientWidth / box.width, element.clientHeight / box.height));
    applyZoom(value);
    requestAnimationFrame(() => element.scrollTo({ top: Math.max(0, (box.y + box.height / 2) * value - element.clientHeight / 2), left: Math.max(0, (box.x + box.width / 2) * value - element.clientWidth / 2), behavior: "instant" }));
  }

  useEffect(() => () => { if (previewTimer.current !== null) window.clearTimeout(previewTimer.current); if (zoomDisplayTimer.current !== null) window.clearTimeout(zoomDisplayTimer.current); if (dragFrame.current !== null) cancelAnimationFrame(dragFrame.current); }, []);
  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      closePreview();
      const rect = element.getBoundingClientRect();
      wheelPoint.current = { x: event.clientX - rect.left, y: event.clientY - rect.top };
      const wheelAmount = event.shiftKey && event.deltaX ? event.deltaX : event.deltaY || event.deltaX;
      const delta = wheelAmount * (event.deltaMode === WheelEvent.DOM_DELTA_LINE ? 16 : event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? element.clientHeight : 1);
      wheelDelta.current += delta;
      if (wheelFrame.current !== null) return;
      const animate = () => {
        wheelFrame.current = null;
        const pendingDelta = wheelDelta.current;
        wheelDelta.current = 0;
        if (pendingDelta) zoomTarget.current = Math.max(.1, Math.min(2, zoomTarget.current * Math.exp(-pendingDelta * .001)));
        const point = wheelPoint.current;
        const before = zoomValue.current;
        const distance = zoomTarget.current - before;
        const value = Math.abs(distance) < .001 ? zoomTarget.current : before + distance * .24;
        if (!point || value === before) return;
        const x = (element.scrollLeft + point.x) / before, y = (element.scrollTop + point.y) / before;
        applyZoom(value, false);
        element.scrollTo({ left: x * value - point.x, top: y * value - point.y, behavior: "instant" });
        if (value !== zoomTarget.current) wheelFrame.current = requestAnimationFrame(animate);
        else {
          if (zoomDisplayTimer.current !== null) window.clearTimeout(zoomDisplayTimer.current);
          zoomDisplayTimer.current = window.setTimeout(() => { setZoom(zoomValue.current); zoomDisplayTimer.current = null; }, 70);
        }
      };
      wheelFrame.current = requestAnimationFrame(animate);
    };
    element.addEventListener("wheel", onWheel, { passive: false });
    return () => { element.removeEventListener("wheel", onWheel); if (wheelFrame.current !== null) cancelAnimationFrame(wheelFrame.current); };
    // This listener reads stable refs; rebuilding on dimensions changes keeps the
    // scaled canvas size current if a newly published graph changes its bounds.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layout.width, layout.height, selection.layout, showList]);
  useEffect(() => {
    if (!preview) return;
    const dismiss = (event: PointerEvent) => { const target = event.target as Node; if (!previewBox.current?.contains(target) && !previewAnchor.current?.contains(target)) setPreview(null); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape" && panel === null) { event.preventDefault(); closePreview(true); } };
    const resize = () => setPreview(null);
    document.addEventListener("pointerdown", dismiss); document.addEventListener("keydown", escape); window.addEventListener("resize", resize);
    return () => { document.removeEventListener("pointerdown", dismiss); document.removeEventListener("keydown", escape); window.removeEventListener("resize", resize); };
    // Geometry is captured when the preview opens; scrolling/zooming dismisses it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preview?.id, panel]);


  if (!course?.graph.concepts.length) return <section className="simple-map"><header className="simple-map-heading"><div><p>{course?.title}</p><h1>My understanding</h1></div></header><h2>Your map starts with your materials</h2><p>Concepts and connections appear when your materials are ready.</p><Link href="/materials" className="button dark">View materials</Link></section>;
  const groups = [...topics.map(topic => ({ id: topic.id, title: topic.title, nodes: topic.conceptIds.flatMap(id => { const node = positions.get(id); return node && matches.has(id) ? [node] : []; }) })),
    { id: "ungrouped", title: topics.length ? "Other concepts" : "Course concepts", nodes: layout.nodes.filter(node => !topicFor.has(node.id) && matches.has(node.id)) }].filter(group => group.nodes.length);

  return <div className="simple-map">
    <header className="simple-map-heading"><div><p>{course.title}</p><h1>My understanding</h1></div><button onClick={() => setPanel("options")} aria-label="Map options">Options <span className="map-options-chevron" aria-hidden="true" /></button></header>
    <div className="simple-map-search"><input type="search" aria-label="Find a concept" placeholder="Search concepts or topics…" value={query} onChange={event => update({ query: event.target.value })} /><button onClick={() => setPanel("filters")}>Filters{filterCount > 0 ? ` (${filterCount})` : ""}</button></div>
    <div className="curriculum-view-toolbar"><div role="group" aria-label="Map layout">{([['pyramid','Learning pyramid'],['atlas','Topic atlas'],['space','Explore in 3D']] as const).map(([value,label])=><button key={value} aria-pressed={selection.layout===value} onClick={()=>update({layout:value})}>{label}</button>)}</div><button onClick={()=>update({display:showList?"map":"list"})}>{showList?"Show map":"List view"}</button></div>
    <div className="curriculum-layer-filters" role="group" aria-label="Curriculum layer"><span>Curriculum</span>{(["all","basic","intermediate","advanced",...(layout.nodes.some(n=>layerOf(n)==="unassigned")?["unassigned"]:[])] as const).map(value=><button key={value} aria-pressed={selection.layer===value} onClick={()=>update({layer:value as KnowledgeView["layer"]})}>{value==="all"?"All":layerNames[value as CurriculumLayer]} <b>{layout.nodes.filter(n=>value==="all"||layerOf(n)===value).length}</b></button>)}</div>
    <div className="simple-map-summary">{personal ? <><span>Evidence at each concept’s curriculum difficulty</span><span>: {Object.entries(states).map(([state, label]) => `${layout.nodes.filter(node => stateAt(node.id) === state).length} ${label.toLowerCase()}`).join(" · ")}</span></> : <span>Course structure · {layout.nodes.length} concepts · {layout.edges.length} prerequisite links</span>}</div>
    {(filterCount > 0 || query) && <div className="simple-map-active"><span>{matches.size} of {layout.nodes.length} concepts match</span>{selection.layer !== "all" && <button onClick={()=>update({layer:"all"})}>Layer: {selection.layer} ×</button>}{topicFilter !== "all" && <button onClick={() => update({ topic: "all" })}>Topic: {topics.find(topic => topic.id === topicFilter)?.title || "Unavailable topic"} ×</button>}{material !== "all" && <button onClick={() => update({ material: "all" })}>Material: {course.documents.find(doc => doc.id === material)?.filename || "Unavailable material"} ×</button>}{personal && status !== "all" && <button onClick={() => update({ status: "all" })}>{states[status]} ×</button>}<button onClick={clearFilters}>Clear filters</button></div>}
    {!matches.size && showList ? <div className="simple-map-empty" role="status"><h2>No concepts match</h2><p>Try another search or clear your filters.</p><button className="button secondary" onClick={clearFilters}>Clear search and filters</button></div> : showList ? <div className="simple-map-list" aria-label="Course concepts by topic">{groups.map(group => <section key={group.id}><h2>{group.title}</h2><ul>{group.nodes.map(node => <li key={node.id}><button onClick={() => select({ id: node.id })}><span>{node.title}{personal && <small>{states[stateAt(node.id)]}</small>}<small>Curriculum: {layerNames[layerOf(node)]}</small></span><span aria-hidden="true">→</span></button></li>)}</ul></section>)}</div> : selection.layout === "space" ? <SpatialExplorer key={course.id} graph={course.graph} matches={matches} query={query} selectedId={selected?.id} modalOpen={panel !== null} stateAt={id=>personal?stateAt(id):"neutral"} onOpen={id=>select({id})}/> : selection.layout !== "atlas" ? <CurriculumMap key={`${course.id}:pyramid`} graph={course.graph} space={false} matches={matches} stateAt={id=>personal?stateAt(id):"neutral"} selectedId={selected?.id} onClear={()=>update({id:""})} onOpen={id=>select({id})}/> : <section className="simple-map-graph bubble-map" aria-label="Knowledge map">
        <div ref={mapFrame} className="map-frame" onBlur={event => { if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget as Node)) closePreview(); }}>
        <div ref={viewport} className="km-viewport" onScroll={() => closePreview()} role="region" tabIndex={0} aria-label="Knowledge map. Scroll to zoom around the pointer; drag the background to pan."
          onPointerDown={event => { if (event.pointerType === "touch" || event.button !== 0 || (event.target as Element).closest("button")) return; closePreview(); const box = event.currentTarget; drag.current = { x: event.clientX, y: event.clientY, left: box.scrollLeft, top: box.scrollTop }; box.setPointerCapture(event.pointerId); }}
          onPointerMove={event => { if (!drag.current) return; const box = event.currentTarget; const state = drag.current; const left = state.left - event.clientX + state.x, top = state.top - event.clientY + state.y; if (dragFrame.current !== null) cancelAnimationFrame(dragFrame.current); dragFrame.current = requestAnimationFrame(() => { box.scrollLeft = left; box.scrollTop = top; dragFrame.current = null; }); }}
          onPointerUp={event => { drag.current = null; if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); }} onPointerCancel={() => { drag.current = null; }}>
          <div ref={zoomSurface} style={{ width: layout.width * zoom, height: layout.height * zoom }}><div ref={zoomCanvas} className="km-canvas" style={{ width: layout.width, height: layout.height, transform: `scale(${zoom})` }}>
            <svg width={layout.width} height={layout.height} aria-hidden="true">
              <defs><marker id="km-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0 L7 3.5 L0 7" fill="#5f8069" /></marker></defs>
              {[...topicRoutes.entries()].map(([key, { from, to }]) => {
                const line = bubbleLink({ x: from.cx, y: from.cy, radius: from.radius }, { x: to.cx, y: to.cy, radius: to.radius });
                return <path key={key} className="map-topic-route" d={`M${line.x1} ${line.y1} Q${(line.x1 + line.x2) / 2 + 18} ${(line.y1 + line.y2) / 2 - 18} ${line.x2} ${line.y2}`} />;
              })}
              {layout.edges.filter(edge => edge.prerequisite === activeNode?.id || edge.dependent === activeNode?.id).map(edge => {
                const from = positions.get(edge.prerequisite)!, to = positions.get(edge.dependent)!;
                return <line key={`${from.id}-${to.id}`} {...bubbleLink(from, to, true)} stroke="#5f8069" strokeWidth="2" markerEnd="url(#km-arrow)" />;
              })}
              {layout.related.filter(edge => edge.first === activeNode?.id || edge.second === activeNode?.id).map(edge => {
                const from = positions.get(edge.first)!, to = positions.get(edge.second)!;
                return <line key={`related-${from.id}-${to.id}`} {...bubbleLink(from, to)} stroke="#7b91b3" strokeWidth="2" strokeDasharray="6 5" />;
              })}
            </svg>
            {layout.groups.map((group, index) => <div key={group.id} className={`km-topic-bubble ${group.conceptIds.some(id => matches.has(id)) ? "" : "dimmed"}`} style={{ left: group.x, top: group.y, width: group.width, height: group.height }} role="group" aria-label={group.title}>
              <h3 id={`bubble-topic-${index}`} title={group.title}>{group.title}</h3>
              {group.conceptIds.map(id => positions.get(id)!).map(node => <button key={node.id} className={`km-bubble ${personal ? stateAt(node.id) : "neutral"} ${node.id === selected?.id ? "selected" : ""} ${matches.has(node.id) ? "" : "dimmed"}`} style={{ left: node.x - group.x - node.radius, top: node.y - group.y - node.radius, width: node.radius * 2, height: node.radius * 2 }} aria-label={`${node.title} · ${layerNames[layerOf(node)]} · ${group.title}${personal ? `: ${states[stateAt(node.id)]} at ${evidenceLevel(node.id)}` : ""}`} aria-pressed={node.id === selected?.id} aria-haspopup="dialog" aria-expanded={preview?.id === node.id} aria-controls={preview?.id === node.id ? "map-concept-preview" : undefined} onPointerEnter={event => { if (event.pointerType !== "touch") openPreview(node.id, event.currentTarget); }} onPointerLeave={schedulePreviewClose} onPointerDown={event => { bubblePointerType.current = event.pointerType; }} onFocus={event => { if (suppressPreviewFocus.current) return; const button = event.currentTarget; requestAnimationFrame(() => { if (document.activeElement === button) openPreview(node.id, button); }); }} onBlur={event => { if (!previewBox.current?.contains(event.relatedTarget as Node)) schedulePreviewClose(); }} tabIndex={matches.has(node.id) ? 0 : -1} disabled={!matches.has(node.id)} onClick={event => { if (event.detail === 0 || bubblePointerType.current !== "touch" || (preview?.id === node.id && preview.pinned)) openPreviewDetails(node.id); else openPreview(node.id, event.currentTarget, true); }}><span className="atlas-layer-badge" aria-hidden="true">{layerBadge[layerOf(node)]}</span></button>)}
            </div>)}
          </div></div>
        </div>

        <div className="map-atlas-label"><strong>Course atlas</strong><span>{layout.groups.length} topic regions</span></div>
        <button className="map-overview-button" onClick={() => fit(true)}>All topics ↗</button>
        <div className="map-navigation" aria-label="Map navigation"><button aria-label="Zoom in map" onClick={() => adjustZoom(.15)}>+</button><span aria-label={`Map zoom ${Math.round(zoom * 100)} percent`}>{Math.round(zoom * 100)}%</span><button aria-label="Zoom out map" onClick={() => adjustZoom(-.15)}>−</button><button aria-label="Fit topic in map" onClick={() => fit()}>Fit</button></div>
        <div className="map-evidence-legend" aria-label={personal ? "Evidence colors" : "Map key"}><span>B Basic · I Intermediate · A Advanced</span>{personal ? Object.entries(states).map(([state, label]) => <span key={state}><i className={state} aria-hidden="true" />{label}</span>) : <span>Course structure</span>}</div>
        {!matches.size && <div className="map-no-results" role="status"><strong>No concepts match</strong><span>Try a different search or clear your filters.</span><button className="button secondary" onClick={clearFilters}>Clear search and filters</button></div>}
        {preview && previewNode && <div ref={previewBox} id="map-concept-preview" className="map-concept-preview" role="dialog" aria-label="Concept preview" style={{ left: preview.left, top: preview.top, width: preview.width, maxHeight: preview.maxHeight }} onPointerEnter={cancelPreviewClose} onPointerLeave={schedulePreviewClose}>
          <button className="map-preview-close" aria-label="Close concept preview" onClick={() => closePreview(true)}>×</button>
          <p className="map-preview-topic">{layout.groups.find(group => group.id === previewNode.groupId)?.title}</p>
          <h3>{bubbleTitles.get(previewNode.id) || previewNode.title}</h3><p>{layerNames[layerOf(previewNode)]} curriculum layer</p>
          {personal && <p className="map-preview-state"><i className={stateAt(previewNode.id)} aria-hidden="true" />{states[stateAt(previewNode.id)]} · {evidenceLevel(previewNode.id)}</p>}
          <button className="map-preview-details" onClick={() => openPreviewDetails(previewNode.id)}>View details <span aria-hidden="true">→</span></button>
        </div>}
        </div>
        <p className="map-interaction-hint">Scroll to zoom · drag to explore. Hover or tap a small bubble to preview; choose View details to open the full explanation.</p>
    </section>}
    {panel === "filters" && <LearningDialog title="Map filters" onClose={closePanel}><div className="simple-map-filter-form">
      <label>Topic<select value={topicFilter} onChange={event => update({ topic: event.target.value })}><option value="all">All topics</option>{topics.map(topic => <option key={topic.id} value={topic.id}>{topic.title}</option>)}</select></label>
      <label>Material<select value={material} onChange={event => update({ material: event.target.value })}><option value="all">All materials</option>{course.documents.map(doc => <option key={doc.id} value={doc.id}>{doc.filename}</option>)}</select></label>
      {personal && <><label>Evidence state<select value={status} onChange={event => update({ status: event.target.value })}><option value="all">All states</option>{Object.entries(states).map(([state, label]) => <option value={state} key={state}>{label}</option>)}</select></label></>}
      <label className="simple-map-course-toggle"><input type="checkbox" checked={!personal} onChange={event => update({ mode: event.target.checked ? "course" : "personal" })} />Show course structure without personal evidence</label>
      <p>Evidence and mastery targets follow each concept’s curriculum layer: Basic, Intermediate or Advanced. Concepts without a layer use their saved learning target.</p>
      <button className="button dark" onClick={closePanel}>Show {matches.size} {matches.size === 1 ? "concept" : "concepts"}</button>
    </div></LearningDialog>}
    {panel === "options" && <LearningDialog title="Map options" onClose={closePanel}><div className="simple-map-options">
      <button onClick={() => { update({ display: showList ? "map" : "list" }, true); setPanel(null); }}>View as {showList ? "map" : "list"} →</button>
      {!showList && selection.layout === "atlas" && <><button onClick={() => { setZoom(1); viewport.current?.scrollTo(0, 0); setPanel(null); }}>Reset map position</button><button onClick={() => { fit(true); setPanel(null); }}>Fit whole map</button></>}
      <details><summary>About this map</summary><p>Large circles contain the course’s published topic groups; their size accommodates the number of concepts, not mastery. Each small circle is a concept: B/I/A marks its curriculum layer, and its fill shows learning evidence. Hover or tap a small circle for a compact preview, then choose View details for its full explanation and lesson. Faint paths connect topics with published relationships. Published cross-topic connections guide group spacing, without numerical similarity scores. Related links never gate practice. Drag the background to pan.</p>{course.graph.organization ? <p>{course.graph.organization.groupedConceptCount} of {course.graph.organization.conceptCount} concepts organized into {topics.length} topics.</p> : <><p>Organize your published concepts into topics.</p><button disabled={expertWorking} onClick={async () => { setOrganizing(true); setOrganizationMessage(""); try { const result = await api<{ status: string }>(`courses/${course.id}/organize`, {}); setOrganizationMessage(result.status === "ready" ? "Organization is ready." : "Organization is in progress. View Agent activity for details."); await refresh(); } catch (error) { setOrganizationMessage((error as Error).message); } finally { setOrganizing(false); } }}>{expertWorking ? "Expert is working…" : "Organize course map"}</button></>}{organizationMessage && <p role="status">{organizationMessage}</p>}<Link href="/agents">View agent activity →</Link></details>
    </div></LearningDialog>}
    {panel === "concept" && selected && <LearningDialog title={selected.title} onClose={closePanel}><KnowledgeDetails key={selected.id} conceptId={selected.id} personal={personal} topicTitle={layout.groups.find(group => group.id === selected.groupId)?.title || "Course concepts"} onSelect={id => select({ id }, true)} /></LearningDialog>}
    {selection.id && !selected && <p role="status">This concept is no longer available. <button onClick={() => update({ id: "" })}>Clear selection</button></p>}
  </div>;
}

function KnowledgeDetails({ conceptId, personal, topicTitle, onSelect }: { conceptId: string; personal: boolean; topicTitle: string; onSelect: (id: string) => void }) {
  const { course, learner, materials } = useWorkspace();
  const concept = course!.graph.concepts.find(c => c.id === conceptId)!;
  const parents = course!.graph.prerequisites.filter(edge => edge.dependent === conceptId).map(edge => edge.prerequisite);
  const dependents = course!.graph.prerequisites.filter(edge => edge.prerequisite === conceptId).map(edge => edge.dependent);
  const unmet = parents.filter(id => (course!.graph.concepts.find(c => c.id === id) ? overallState(course!.graph.concepts.find(c => c.id === id)!, learner) : "unassessed") !== "demonstrated");
  const resource = materials.materials.find(item => item.conceptId === conceptId);
  const level = targetDifficulty(concept);
  const levelState = learner?.concepts[conceptId]?.[level];
  const topic = course!.graph.topics?.find(t => t.conceptIds.includes(conceptId));
  const related = (course!.graph.related || []).filter(e => e.first === conceptId || e.second === conceptId);
  const title = (id: string) => course!.graph.concepts.find(c => c.id === id)?.title || id;
  return <ConceptStudy conceptId={conceptId} resource={resource}><div id="knowledge-details" className="simple-map-details">
    <p className="km-popup-topic">{topicTitle} · {layerNames[layerOf(concept)]} curriculum</p>
    {personal && <><p className={`km-state ${levelState?.state || "unassessed"}`}>{states[levelState?.state || "unassessed"]} · Evidence: {level[0].toUpperCase() + level.slice(1)}</p><p className="km-evidence-note">Assessment evidence and the mastery target follow this lesson’s curriculum difficulty. Earlier assessment results remain available in assessment history.</p></>}
    <h3>Learning goal</h3>
    <RichText>{resource?.lesson.objective || concept.summary}</RichText>
    {resource && <><h3>About this concept</h3><RichText>{concept.summary}</RichText></>}
    {personal && <><h3>Practice readiness</h3><p>{unmet.length ? "Demonstrate each prerequisite at its own target difficulty before practicing this concept. You can read its lesson at any time." : "Prerequisites met. Your tutor can include this concept when it needs practice."}</p></>}
    {parents.length > 0 && <><h3>Prerequisites</h3><div className="km-detail-links">{parents.map(id => <button key={id} onClick={() => onSelect(id)}>{title(id)}{personal && <small>{(course!.graph.concepts.find(c => c.id === id) ? overallState(course!.graph.concepts.find(c => c.id === id)!, learner) : "unassessed") === "demonstrated" ? "Demonstrated" : "Needs evidence"}</small>}<small>{course!.graph.prerequisites.find(e => e.prerequisite === id && e.dependent === conceptId)?.rationale}</small></button>)}</div></>}
    {topic && <details><summary>About this topic</summary><p>{topic.summary}</p></details>}
    {dependents.length > 0 && <details><summary>Leads to ({dependents.length})</summary><div className="km-detail-links">{dependents.map(id => <button key={id} onClick={() => onSelect(id)}>{title(id)}</button>)}</div></details>}
    {related.length > 0 && <details><summary>Related concepts ({related.length})</summary><p>Useful connections; these do not block practice.</p><div className="km-detail-links">{related.map(edge => { const id = edge.first === conceptId ? edge.second : edge.first; return <button key={id} onClick={() => onSelect(id)}>{title(id)}<small>{edge.rationale}</small></button>; })}</div></details>}
    {personal && <Link className="simple-map-history-link" href="/progress">View assessment history →</Link>}
    <details className="km-source-notes"><summary>Generated source notes</summary>{concept.sources.map((source, i) => <blockquote key={`${source.chunkId}-${i}`}>{source.quote}</blockquote>)}</details>
  </div></ConceptStudy>;
}
