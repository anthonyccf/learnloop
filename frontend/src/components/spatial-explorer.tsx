"use client";



import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import type { CourseDetail } from "@/lib/backend";

import { interpolateSelection, selectionEase, SELECTION_MOTION_MS, type SelectionFrame } from "@/lib/selection-motion";

import { conceptConnections, overviewConceptIds, overviewConceptPoint, conceptConnectionPath } from "@/lib/concept-connections";

import { DEFAULT_PYRAMID_CAMERA, PYRAMID_VIEWS, pyramidPlane, fitConnectionView, type PyramidCamera } from "@/lib/pyramid-camera";

import { terraceLayout, terraceSurface, projectTopicDisc } from "@/lib/terrace-layout";

import { layerNames, wrapTopicTitle, type CurriculumLayer } from "@/lib/curriculum-map";

import { DEFAULT_GLOBE_POSE, globePoints, projectGlobe, topicExplorerGraph, type GlobeTopic } from "@/lib/topic-globe";



const states: Record<string, string> = { unassessed: "Not assessed", developing: "Developing", demonstrated: "Demonstrated", review_due: "Review due", neutral: "Course concept" };



const mediaSubscribe = (notify: () => void) => { const media = window.matchMedia("(prefers-reduced-motion: reduce)"); media.addEventListener("change", notify); return () => media.removeEventListener("change", notify); };

const visibilitySubscribe = (notify: () => void) => { document.addEventListener("visibilitychange", notify); return () => document.removeEventListener("visibilitychange", notify); };

const reducedSnapshot = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const hiddenSnapshot = () => document.hidden;

const serverMotion = () => true;



type Props = { graph: CourseDetail["graph"]; matches: Set<string>; query: string; stateAt: (id: string) => string; selectedId?: string; modalOpen: boolean; onOpen: (id: string) => void };

type Choice = { key: string; groupId: string; conceptId: string };

type Preview = { id: string; left: number; top: number; pinned: boolean };


type SelectionMotion = { id: number; context: string; from: SelectionFrame; progress: number };



export function SpatialExplorer({ graph, matches, query, stateAt, selectedId = "", modalOpen, onOpen }: Props) {

  const graphKey = JSON.stringify(graph);

  const scene = useMemo(() => topicExplorerGraph(JSON.parse(graphKey) as CourseDetail["graph"]), [graphKey]);

  const concepts = new Map(graph.concepts.map(c => [c.id, c]));

  const [connectionRoot, setConnectionRoot] = useState("");

  const connections = useMemo(() => conceptConnections(JSON.parse(graphKey) as CourseDetail["graph"], connectionRoot), [graphKey, connectionRoot]);

  const pinnedGroups = new Set(scene.groups.filter(g => g.conceptIds.some(id => connections.ids.has(id))).map(g => g.id));

  const context = JSON.stringify([query, [...matches].sort()]);

  const eligible = scene.groups.filter(g => g.conceptIds.some(id => matches.has(id)));

  const searchIds = graph.concepts.filter(c => matches.has(c.id)).sort((a, b) => Number(b.title.toLowerCase().startsWith(query.toLowerCase())) - Number(a.title.toLowerCase().startsWith(query.toLowerCase())) || a.title.localeCompare(b.title)).map(c => c.id);

  const initialConcept = query.trim() ? searchIds[0] || "" : selectedId;

  const familySize = (group: GlobeTopic) => eligible.filter(g => g.topicId === group.topicId).length;

  const initialGroup = eligible.find(g => g.conceptIds.includes(initialConcept)) || eligible.find(g => g.layer === "intermediate" && /context growth/i.test(g.title)) || eligible.filter(g => g.layer === "intermediate").sort((a, b) => familySize(b) - familySize(a) || b.conceptIds.length - a.conceptIds.length)[0] || eligible[0];

  const [choice, setChoice] = useState<Choice>({ key: "", groupId: "", conceptId: "" });

  const availableGroups = scene.groups.filter(g => eligible.some(e => e.id === g.id) || pinnedGroups.has(g.id));

  const activeGroup = availableGroups.find(g => choice.key === context && g.id === choice.groupId) || initialGroup || availableGroups.find(g => g.conceptIds.includes(connectionRoot));

  const focusedId = choice.key === context && choice.groupId === activeGroup?.id ? choice.conceptId : initialConcept;

  const members = activeGroup?.conceptIds || [];

  const vectors = globePoints(members.length);

  const pose = DEFAULT_GLOBE_POSE;

  const discTurn = 0;

  const [layerView, setLayerView] = useState("all");

  const [zoom, setZoom] = useState(1);

  const [camera, setCamera] = useState<PyramidCamera>(DEFAULT_PYRAMID_CAMERA);



  const [expanded, setExpanded] = useState(false);

  const [listOnly, setListOnly] = useState(false);

  const [atlasMode, setAtlasMode] = useState(true);


  const [topicQuery, setTopicQuery] = useState("");

  const [localQuery, setLocalQuery] = useState({ group: "", text: "" });


  const [motionPreference, setMotionPreference] = useState<"system" | "on" | "off">("system");

  const [motion, setMotion] = useState<SelectionMotion | null>(null);

  const renderedFrame = useRef<SelectionFrame | null>(null);

  const motionSequence = useRef(0);




  const [preview, setPreview] = useState<Preview | null>(null);

  const reducedMotion = useSyncExternalStore(mediaSubscribe, reducedSnapshot, serverMotion);

  const hidden = useSyncExternalStore(visibilitySubscribe, hiddenSnapshot, serverMotion);

  const animateSelection = motionPreference === "on" || motionPreference === "system" && !reducedMotion;

  const motionActive = !!motion && motion.context === context && animateSelection && !hidden;

  const motionId = motion?.id;



  const mapDrag = useRef<{ x: number; y: number; camera: PyramidCamera } | null>(null);

  const canvasRef = useRef<HTMLDivElement>(null);

  const [canvasSize, setCanvasSize] = useState({ width: 600, height: 640 });
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const wheel = (event: WheelEvent) => {
      event.preventDefault(); setMotion(null);
      setZoom(z => Math.max(.35, Math.min(3, z * Math.exp(-event.deltaY * .0015))));
    };
    canvas.addEventListener("wheel", wheel, { passive: false });
    return () => canvas.removeEventListener("wheel", wheel);
  }, []);


  const previewRef = useRef<HTMLDivElement>(null);

  const previewTimer = useRef<number | null>(null);

  const suppressPreview = useRef(false);

  const markerId = useId().replaceAll(":", "");

  const displayLayer = connections.ids.size ? "all" : layerView !== "all" && activeGroup ? activeGroup.layer : layerView;

  const layout = terraceLayout(scene.groups, displayLayer, pinnedGroups);
  const mapWidth = Math.max(1040, ...layout.shelves.map(s => s.width + 80));

  const targetGroups = layout.shelves.flatMap(s => s.groups);

  const localText = localQuery.group === activeGroup?.id ? localQuery.text : "";

  const visibleMembers = members.filter(id => (matches.has(id) || connections.ids.has(id)) && `${concepts.get(id)?.title} ${concepts.get(id)?.summary}`.toLowerCase().includes(localText.toLowerCase()));

  const current = concepts.get(focusedId);

  const panelConcept = current && members.includes(current.id) ? current : concepts.get(visibleMembers[0]);

  const topicSummary = graph.topics?.find(t => t.id === activeGroup?.topicId)?.summary;

  const panelRelated = current ? conceptConnections(graph, current.id).edges.filter(e => e.kind === "related").map(e => e.from === current.id ? e.to : e.from) : [];

  const previewConcept = concepts.get(preview?.id || "");

  const previewGroup = scene.groups.find(g => g.conceptIds.includes(preview?.id || ""));




  const reachable = (id: string) => matches.has(id) || connections.ids.has(id);


  function startSelectionMotion() {

    const from = renderedFrame.current;

    if (!from || !animateSelection || hidden) { setMotion(null); return; }

    setMotion({ id: ++motionSequence.current, context, from, progress: 0 });

  }

  function selectConcept(id: string) {

    const group = scene.groups.find(g => g.conceptIds.includes(id));

    if (!group) return;

    startSelectionMotion();

    suppressPreview.current = true;

    requestAnimationFrame(() => { suppressPreview.current = false; });

    setConnectionRoot(id); setLayerView("all"); chooseGroup(group, id);

    fitConnections(id);

  }

  function fitConnections(root = connectionRoot) {

    const box = canvasRef.current;

    if (!box || !box.clientWidth) return;

    const links = conceptConnections(graph, root);
    if (!links.edges.length) return;
    const pins = new Set(scene.groups.filter(g => g.conceptIds.some(id => links.ids.has(id))).map(g => g.id));
    const nextLayout = terraceLayout(scene.groups, "all", pins);
    const width = Math.max(1040, ...nextLayout.shelves.map(s => s.width + 80));
    const positions = new Map(nextLayout.shelves.flatMap(shelf => {
      const plane = pyramidPlane({ ...camera, x: 0, y: 0 }, shelf.y + shelf.depth / 2, nextLayout.height, true);
      return shelf.groups.flatMap(group => group.conceptIds.filter(id => links.ids.has(id)).map(id => {
        const point = overviewConceptPoint(group, id, 0)!;
        return [id, { ...point, ...plane.point(point) }] as const;
      }));
    }));
    const extents = [...positions.values()].flatMap(p => [{ x: p.x - p.radius - 8, y: p.y - p.radius - 8 }, { x: p.x + p.radius + 8, y: p.y + p.radius + 8 }]);
    for (const edge of links.edges) {
      const a = positions.get(edge.from), b = positions.get(edge.to);
      const curve = a && b ? conceptConnectionPath(a, b) : null;
      if (curve) extents.push({ x: curve.cx, y: curve.cy });
    }
    if (!extents.length) return;
    const view = fitConnectionView({ left: Math.min(...extents.map(p => p.x)), right: Math.max(...extents.map(p => p.x)), top: Math.min(...extents.map(p => p.y)), bottom: Math.max(...extents.map(p => p.y)) },
      { width, height: box.clientHeight * width / box.clientWidth },
      { zoom, x: camera.x, y: camera.y, scrollTop: box.scrollTop * width / box.clientWidth });
    setZoom(view.zoom);
    setCamera(c => ({ ...c, x: view.x, y: view.y }));
    const scrollTop = view.scrollTop * box.clientWidth / width;
    requestAnimationFrame(() => box.scrollTo(0, scrollTop));

  }

  function chooseGroup(group: GlobeTopic, conceptId = "") {

    setChoice({ key: context, groupId: group.id, conceptId }); setPreview(null);

  }

  function focusLayer(value: string) {

    setMotion(null);

    if (value !== "all") {

      const group = eligible.find(g => g.layer === value && g.topicId === activeGroup?.topicId) || eligible.find(g => g.layer === value);

      if (group) chooseGroup(group);

    }

    setLayerView(value); setZoom(1); canvasRef.current?.scrollTo(0, 0);

  }

  function locate(id: string) {

    const group = scene.groups.find(g => g.conceptIds.includes(id));

    if (group) { chooseGroup(group, id); }

  }

  function openLesson(id: string) { setMotion(null); locate(id); setPreview(null); onOpen(id); }

  function cancelClose() { if (previewTimer.current !== null) { window.clearTimeout(previewTimer.current); previewTimer.current = null; } }

  function closeSoon() { cancelClose(); previewTimer.current = window.setTimeout(() => setPreview(p => p?.pinned || previewRef.current?.contains(document.activeElement) ? p : null), 220); }

  function showPreview(id: string, anchor: Element, pinned = false) {

    if (modalOpen || motionActive || suppressPreview.current) return;

    cancelClose();

    const r = anchor.getBoundingClientRect(), width = Math.min(280, window.innerWidth - 24);

    const left = r.right + width + 16 < window.innerWidth ? r.right + 12 : r.left - width - 12;

    setPreview({ id, pinned, left: Math.max(12, Math.min(left, window.innerWidth - width - 12)), top: Math.max(12, Math.min(r.top - 15, window.innerHeight - 240)) });

  }

  useEffect(() => {

    const box = canvasRef.current;

    if (!box) return;

    const observer = new ResizeObserver(([entry]) => { if (entry.contentRect.width > 0 && entry.contentRect.height > 0) setCanvasSize({ width: entry.contentRect.width, height: entry.contentRect.height }); });

    observer.observe(box);

    return () => observer.disconnect();

  }, []);



  useEffect(() => {

    if (!preview) return;

    const escape = (e: KeyboardEvent) => { if (e.key === "Escape") setPreview(null); };

    const outside = (e: PointerEvent) => { if (!previewRef.current?.contains(e.target as Node) && !(e.target as Element).closest("[data-concept]")) setPreview(null); };

    const scroll = () => setPreview(null);

    document.addEventListener("keydown", escape); document.addEventListener("pointerdown", outside); window.addEventListener("scroll", scroll, true);

    return () => { document.removeEventListener("keydown", escape); document.removeEventListener("pointerdown", outside); window.removeEventListener("scroll", scroll, true); };

  }, [preview]); // Position is measured only when a bubble is hovered or focused.

  useEffect(() => () => { if (previewTimer.current !== null) window.clearTimeout(previewTimer.current); }, []);



  function miniature(group: GlobeTopic & { x: number; y: number; r: number }) {

    const ids = overviewConceptIds(group);

    return ids.map(id => ({ id, ...frame.nodes[id] })).map(p => <g key={p.id} data-concept={p.id} transform={`translate(${p.x - group.x} ${p.y - group.y})`} style={{ opacity: p.opacity }} className={`sx-mini-concept ${p.id === connectionRoot ? "is-root" : connections.ids.has(p.id) ? "is-connected" : ""}`} role={reachable(p.id) ? "button" : undefined} tabIndex={reachable(p.id) ? 0 : -1} aria-label={`${concepts.get(p.id)?.title} · ${states[stateAt(p.id)]} · Show connections`} aria-pressed={p.id === connectionRoot} onPointerEnter={e => { if (reachable(p.id) && e.pointerType !== "touch") showPreview(p.id, e.currentTarget); }} onPointerLeave={closeSoon} onFocus={e => { const anchor = e.currentTarget; requestAnimationFrame(() => { if (document.activeElement === anchor) showPreview(p.id, anchor); }); }} onBlur={closeSoon} onClick={e => { e.stopPropagation(); if (reachable(p.id)) selectConcept(p.id); }} onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); if (reachable(p.id)) selectConcept(p.id); } }}><title>{concepts.get(p.id)?.title} — show connections</title><circle r={Math.max(14, p.radius + 3)} fill="transparent" className="sx-mini-hit"/>{connections.ids.has(p.id) && <circle r={p.radius + (p.id === connectionRoot ? 5 : 3)} className="sx-connection-halo"/>}<circle r={p.radius} className={`sx-status ${stateAt(p.id)}`} /></g>);

  }

  function discBearing(turn: number, radius: number, tilt: number) {

    const angle = (turn - 90) * Math.PI / 180;

    return <line className="sx-disc-bearing" x1={Math.cos(angle) * radius * .86} y1={Math.sin(angle) * radius * tilt * .86} x2={Math.cos(angle) * radius * .97} y2={Math.sin(angle) * radius * tilt * .97} aria-hidden="true"/>;

  }

  const targetGlobeNodes = members.map((id, i) => ({ id, index: i, ...(atlasMode ? projectTopicDisc(i, members.length, discTurn) : projectGlobe(vectors[i], pose)) })).sort((a, b) => a.depth - b.depth);

  const bubbleRadius = members.length <= 10 ? 21 : members.length <= 30 ? 14 : members.length <= 75 ? 10.5 : 7;

  const targetFrame: SelectionFrame = {

    groups: Object.fromEntries(targetGroups.map(g => [g.id, { x: g.x, y: g.y, r: g.r, turn: 0, opacity: 1 }])),

    nodes: Object.fromEntries(targetGroups.flatMap(g => overviewConceptIds(g).map(id => [id, { ...overviewConceptPoint(g, id, 0)!, groupId: g.id, scale: 1, opacity: 1 }]))),

    panel: Object.fromEntries(targetGlobeNodes.map(n => [n.id, { x: n.x, y: n.y, radius: bubbleRadius * n.scale, scale: n.scale, groupId: activeGroup?.id || "", opacity: 1 }])),

    shelves: Object.fromEntries(layout.shelves.map(s => [s.layer, { y: s.y, depth: s.depth, labelY: s.labelY, opacity: 1 }])),

    height: layout.height, zoom,

  };

  const frame = motionActive ? interpolateSelection(motion.from, targetFrame, motion.progress) : targetFrame;

  const mapHeight = Math.max(canvasSize.height, frame.height * Math.max(1, frame.zoom) * canvasSize.width / mapWidth);

  const mapGroups = targetGroups.map(g => ({ ...g, ...frame.groups[g.id] }));

  const shelves = layout.shelves.map(s => ({ ...s, ...frame.shelves[s.layer] }));

  const globeNodes = targetGlobeNodes.map(n => ({ ...n, ...frame.panel[n.id] }));

  const linkOpacity = motionActive ? Math.min(1, selectionEase(motion.progress) * 1.5) : 1;

  const planes = new Map(shelves.map(s => [s.layer, pyramidPlane(camera, s.y + s.depth / 2, frame.height, true)]));

  const planeForGroup = (id: string) => planes.get(targetGroups.find(g => g.id === id)?.layer || "basic");

  const conceptPositions = new Map(Object.entries(frame.nodes).map(([id, node]) => [id, { ...node, ...planeForGroup(node.groupId)?.point(node) }]));

  useLayoutEffect(() => { renderedFrame.current = frame; });

  useEffect(() => {

    if (motionId === undefined) return;

    if (!animateSelection || hidden || motion?.context !== context) {

      queueMicrotask(() => setMotion(current => current?.id === motionId ? null : current));

      return;

    }

    let animation = 0, start: number | undefined;

    const tick = (now: number) => {

      start ??= now;

      const progress = Math.min(1, (now - start) / SELECTION_MOTION_MS);

      setMotion(current => current?.id === motionId ? progress === 1 ? null : { ...current, progress } : current);

      if (progress < 1) animation = requestAnimationFrame(tick);

    };

    animation = requestAnimationFrame(tick);

    return () => cancelAnimationFrame(animation);

  }, [motionId, motion?.context, context, animateSelection, hidden]);

  const conceptPaths = connections.edges.flatMap(e => {

    const a = conceptPositions.get(e.from), b = conceptPositions.get(e.to);

    const curve = a && b ? conceptConnectionPath(a, b) : null;

    return curve ? [{ ...e, ...curve }] : [];

  });

  const panelPaths = connections.edges.flatMap(e => {

    const a = globeNodes.find(n => n.id === e.from && n.front), b = globeNodes.find(n => n.id === e.to && n.front);

    const curve = a && b ? conceptConnectionPath({ ...a, radius: a.radius }, { ...b, radius: b.radius }) : null;

    return curve ? [{ ...e, ...curve }] : [];

  });

  return <section data-selection-motion={motionActive ? "running" : "idle"} className={`spatial-explorer ${motionActive ? "sx-is-selecting" : ""} ${expanded ? "sx-expanded" : ""}`} aria-label="3D topic explorer">

    <header className="sx-heading"><div><p className="sx-eyebrow">EXPLORE · CONNECT · UNDERSTAND</p><h2>Your knowledge, in perspective</h2><p>Explore the layers. Choose a topic. Turn its globe to discover the concepts inside.</p></div><span className="sx-course-count"><b>{graph.concepts.length}</b> concepts · {scene.groups.length} topic groups</span></header>

    <div className="sx-workspace">

      <div className="sx-overview">

        <div className="sx-map-toolbar"><div><span className="sx-eyebrow">CURRICULUM OVERVIEW</span><p>Basic <span>→</span> Intermediate <span>→</span> Advanced</p></div><label className="sx-layer-select">{connections.ids.size ? "Connection view" : "Focus layer"}<select disabled={connections.ids.size > 0} title={connections.ids.size ? "Clear connections to focus on one layer" : undefined} aria-label="Focus curriculum layer" value={displayLayer} onChange={e => focusLayer(e.target.value)}><option value="all">All layers</option>{scene.bands.map(b => <option key={b.layer} value={b.layer} disabled={!eligible.some(g => g.layer === b.layer)}>{layerNames[b.layer]} · {b.count}</option>)}</select></label><label className="sx-selection-animation" title={reducedMotion && motionPreference === "system" ? "Reduced motion is enabled. Turn this on to preview selection transitions." : "Animate bubbles and arrows when selecting a concept"}><input type="checkbox" aria-label="Animate concept selection" checked={animateSelection} onChange={e => { setMotionPreference(e.target.checked ? "on" : "off"); if (!e.target.checked) setMotion(null); }}/><span>Animate selection</span></label></div>

        {connections.ids.size > 0 && <div className="sx-connection-toolbar" role="status"><div><span className="sx-eyebrow">CONCEPT CONNECTIONS</span><button className="sx-root-name" onClick={() => selectConcept(connectionRoot)}>{concepts.get(connectionRoot)?.title}</button><p>{connections.edges.length} direct connections · all concepts stay visible on their layers.</p></div><div className="sx-connection-actions"><button onClick={() => fitConnections()}>Fit connections</button><button className="sx-clear-connections" onClick={() => { setMotion(null); setConnectionRoot(""); setZoom(1); }}>Clear connections</button></div></div>}

        <div className="sx-camera-controls" role="group" aria-label="Pyramid camera controls">

          {PYRAMID_VIEWS.map(view => <button key={view.name} aria-pressed={camera.pitch === view.pitch} onClick={() => { setMotion(null); setCamera(c => ({ ...c, yaw: 0, pitch: view.pitch })); }}>{view.name}</button>)}
          <span>Drag background to pan · scroll to zoom · select a concept to show connections</span>
        </div>

        <div ref={canvasRef} className="sx-map-canvas" tabIndex={0} aria-label="Pyramid camera. Drag to pan. Arrow keys pan; plus and minus zoom; Home resets. Choose a preset to change the view."

          onWheel={e => { e.preventDefault(); setMotion(null); setZoom(z => Math.max(.35, Math.min(3, z * Math.exp(-e.deltaY * .0015)))); }}

          onKeyDown={e => {

            if (e.target !== e.currentTarget) return;

            if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "+", "=", "-", "Home"].includes(e.key)) e.preventDefault();

            if (e.key === "Home") { setCamera(DEFAULT_PYRAMID_CAMERA); setZoom(1); }

            if (["+", "="].includes(e.key)) setZoom(z => Math.min(3, z + .2));

            if (e.key === "-") setZoom(z => Math.max(.35, z - .2));

            const dx = e.key === "ArrowLeft" ? -20 : e.key === "ArrowRight" ? 20 : 0, dy = e.key === "ArrowUp" ? -20 : e.key === "ArrowDown" ? 20 : 0;

            if (dx || dy) setCamera(c => ({ ...c, x: c.x + dx, y: c.y + dy }));

          }}

          onPointerDown={e => { if (![0, 1, 2].includes(e.button) || (e.target as Element).closest('[role="button"],button,[data-concept],.sx-topic')) return; e.preventDefault(); setMotion(null); setPreview(null); mapDrag.current = { x: e.clientX, y: e.clientY, camera: { ...camera } }; e.currentTarget.setPointerCapture(e.pointerId); }}

          onContextMenu={e => e.preventDefault()}

          onPointerMove={e => { const d = mapDrag.current; if (!d) return; const dx = e.clientX - d.x, dy = e.clientY - d.y;

            setCamera({ ...d.camera, x: d.camera.x + dx * mapWidth / canvasSize.width / zoom, y: d.camera.y + dy * mapWidth / canvasSize.width / zoom });

          }} onPointerUp={e => { mapDrag.current = null; if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId); }} onPointerCancel={() => { mapDrag.current = null; }}>

          <svg viewBox={`${520 - mapWidth / 2} 0 ${mapWidth} ${mapHeight * mapWidth / canvasSize.width}`} preserveAspectRatio="xMidYMin meet" style={{ width: "100%", height: mapHeight }} role="group" aria-label="Three curriculum terraces. Select a small bubble to show connections.">

            <defs>

              <linearGradient id={`${markerId}-basic`} x1="0" y1="0" x2=".8" y2="1"><stop stopColor="#f3f7e9"/><stop offset=".6" stopColor="#dfe9d3"/><stop offset="1" stopColor="#c6d6bb"/></linearGradient>

              <linearGradient id={`${markerId}-intermediate`} x1="0" y1="0" x2=".7" y2="1"><stop stopColor="#fcf5df"/><stop offset=".6" stopColor="#f0e5c3"/><stop offset="1" stopColor="#ddceaa"/></linearGradient>

              <linearGradient id={`${markerId}-advanced`} x1="0" y1="0" x2=".8" y2="1"><stop stopColor="#fff0e8"/><stop offset=".7" stopColor="#efd6c8"/><stop offset="1" stopColor="#d8bca9"/></linearGradient>

              <linearGradient id={`${markerId}-unassigned`}><stop stopColor="#f5f4ee"/><stop offset="1" stopColor="#dedfd5"/></linearGradient>

              <radialGradient id={`${markerId}-tile`} cx="30%" cy="20%" r="85%"><stop stopColor="#fffef7"/><stop offset="1" stopColor="#e9eddd"/></radialGradient>

              <filter id={`${markerId}-shadow`} x="-20%" y="-25%" width="145%" height="170%"><feGaussianBlur stdDeviation="12"/></filter>

              <marker id={`${markerId}-arrow`} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" fill="#719b47" /></marker>

            </defs>
            <g className="sx-pyramid-camera" transform={`translate(520 0) scale(${frame.zoom}) translate(-520 0)`}>

            {shelves.map(s => <g key={s.layer} style={{ opacity: s.opacity }} transform={planes.get(s.layer)?.transform} className={`sx-shelf sx-${s.layer}`}>

              <path d={terraceSurface(s.x, s.y + 40, s.width, s.depth)} className="sx-terrace-shadow" filter={`url(#${markerId}-shadow)`}/>

              <path d={terraceSurface(s.x, s.y + 28, s.width, s.depth)} className="sx-shelf-depth"/>

              <path d={terraceSurface(s.x, s.y, s.width, s.depth)} className="sx-shelf-surface" style={{ fill: `url(#${markerId}-${s.layer})` }}/>

              <path d={terraceSurface(s.x, s.y, s.width, s.depth)} className="sx-terrace-rim"/>

            </g>)}

            {mapGroups.map(g => {

              const selected = g.id === activeGroup?.id, available = g.conceptIds.some(id => reachable(id));

              const labelLimit = displayLayer === "all" ? 16 : 28, maxLines = displayLayer === "all" ? 3 : 2;

              const allLines = wrapTopicTitle(g.title, labelLimit), lines = allLines.slice(0, maxLines);

              return <g key={g.id} transform={`${planes.get(g.layer)?.transform} translate(${g.x} ${g.y})`} role="group" aria-label={g.title} className={`sx-topic ${selected ? "is-selected" : ""} ${available ? "" : "is-filtered"} ${g.pinned ? "is-pinned" : ""}`} data-topic={g.id} style={{ opacity: g.opacity * (available ? 1 : .2) }} onClick={() => { if (available) chooseGroup(g); }} onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); chooseGroup(g); } }}>

                <title>{g.title} · {layerNames[g.layer]} · {g.conceptIds.length} concepts. Choose a small bubble to show its connections.</title>

                <ellipse cy="13" rx={g.r + 4} ry={g.r * .64} className="sx-topic-shadow"/>

                <ellipse cy="9" rx={g.r} ry={g.r * .62} className={`sx-disc-lip sx-disc-${g.layer}`}/>

                <ellipse rx={g.r} ry={g.r * .62} fill={`url(#${markerId}-${g.layer})`} className={`sx-topic-glass sx-disc-${g.layer}`}/>

                {discBearing(g.turn, g.r, .62)}{miniature(g)}{selected && <ellipse rx={g.r + 5} ry={g.r * .62 + 4} className="sx-selection-ring"/>}

                <text transform={`translate(0 ${g.r * .62 + 28}) scale(1 ${planes.get(g.layer)?.labelScaleY || 1})`} textAnchor="middle" className="sx-topic-name" style={{ fontSize: g.layer === "basic" ? 17 : 18 }} role="button" tabIndex={available ? 0 : -1} aria-label={`${layerNames[g.layer]} topic: ${g.title} · ${g.conceptIds.length} concepts`} aria-pressed={selected} aria-disabled={!available}>{lines.map((line, i) => <tspan key={i} x="0" dy={i ? 18 : 0}>{i === maxLines - 1 && allLines.length > maxLines ? `${line}…` : line}</tspan>)}</text>

              </g>;

            })}

            <g className="sx-concept-connections" style={{ opacity: linkOpacity }} aria-label="Selected concept connections">{conceptPaths.map(e => <path key={`${e.kind}:${e.from}:${e.to}`} data-from={e.from} data-to={e.to} data-kind={e.kind} className={`sx-concept-link ${e.kind}`} d={e.d} markerEnd={e.kind === "prerequisite" ? `url(#${markerId}-arrow)` : undefined}><title>{concepts.get(e.from)?.title} {e.kind === "prerequisite" ? "is a prerequisite for" : "is related to"} {concepts.get(e.to)?.title}</title></path>)}</g>

            {shelves.map(s => <g key={s.layer} style={{ opacity: s.opacity }} transform={`translate(${planes.get(s.layer)?.point({x: s.labelX, y: s.labelY}).x} ${planes.get(s.layer)?.point({x: s.labelX, y: s.labelY}).y})`} className="sx-terrace-caption" textAnchor="middle"><text className="sx-shelf-name">{layerNames[s.layer]}</text><text y="25" className="sx-shelf-count">{s.count} concepts · {s.total} topics</text></g>)}

          </g>
          </svg>

          {!matches.size && !connections.ids.size && <div className="sx-no-results" role="status"><strong>No matching concepts</strong><p>Try another search or clear the filters above.</p></div>}

        </div>

        <div className="sx-map-footer"><span className="sx-visible-count">{layout.shown} of {scene.groups.length} topic groups shown{pinnedGroups.size > 0 && ` · ${pinnedGroups.size} pinned for connections`}</span><div className="sx-map-tools"><button className="sx-minimap" aria-label="Show all curriculum layers" onClick={() => focusLayer("all")}><svg viewBox="0 0 110 78" aria-hidden="true"><ellipse cx="52" cy="59" rx="42" ry="13" fill="#d5e4c8"/><ellipse cx="57" cy="40" rx="33" ry="11" fill="#f0e2ba"/><ellipse cx="62" cy="22" rx="23" ry="9" fill="#efd5c3"/><circle cx="56" cy={activeGroup?.layer === "advanced" ? 20 : activeGroup?.layer === "intermediate" ? 39 : 57} r="5" fill="#fff" stroke="#6d964e" strokeWidth="2"/></svg></button><div><button aria-label="Zoom in overview" disabled={zoom >= 3} onClick={() => setZoom(z => Math.min(3, z + .3))}>+</button><button aria-label="Zoom out overview" disabled={zoom <= .35} onClick={() => setZoom(z => Math.max(.35, z - .3))}>−</button></div><button onClick={() => { setCamera(DEFAULT_PYRAMID_CAMERA); setZoom(1); focusLayer("all"); }}>↺ Reset view</button></div></div>

        <details className="sx-topic-directory" open={!!query.trim()}><summary>{query.trim() ? `Search results · ${matches.size} concepts` : `Browse all ${scene.groups.length} topic groups`}</summary>{query.trim() ? <div className="sx-search-results">{searchIds.map(id => <button key={id} onClick={() => selectConcept(id)} aria-pressed={focusedId === id}><span>{concepts.get(id)?.title}<small>{layerNames[scene.nodes.find(n => n.id === id)!.layer]}</small></span><span aria-hidden="true">↗</span></button>)}</div> : <><input type="search" aria-label="Find a topic group" placeholder="Find a topic…" value={topicQuery} onChange={e => setTopicQuery(e.target.value)} /><div className="sx-directory-items">{eligible.filter(g => `${g.title} ${layerNames[g.layer]}`.toLowerCase().includes(topicQuery.toLowerCase())).map(g => <button key={g.id} onClick={() => chooseGroup(g)} aria-pressed={g.id === activeGroup?.id}><span>{g.title}<small>{layerNames[g.layer]} · {g.conceptIds.length} concepts</small></span><span aria-hidden="true">↗</span></button>)}</div></>}</details>

      </div>

      <aside className="sx-focus-panel" aria-label="Topic focus">

        <div className="sx-panel-heading"><span className="sx-eyebrow">Topic focus</span><button aria-pressed={expanded} onClick={() => setExpanded(v => !v)}>{expanded ? "Show overview" : "Expand topic"}<span aria-hidden="true"> {expanded ? "↙" : "↗"}</span></button></div>

        {activeGroup ? <>

          <div className="sx-family-tabs" aria-label="Topic curriculum layer">{(["basic", "intermediate", "advanced", ...(activeGroup.layer === "unassigned" ? ["unassigned"] : [])] as CurriculumLayer[]).map(level => { const g = availableGroups.find(g => g.topicId === activeGroup.topicId && g.layer === level); return <button key={level} disabled={!g} aria-pressed={activeGroup.layer === level} onClick={() => { if (g) chooseGroup(g); }}>{layerNames[level]}{g && <small>{g.conceptIds.length}</small>}</button>; })}</div>

          <h3>{activeGroup.title}</h3><p className="sx-topic-meta">{layerNames[activeGroup.layer]} · {members.length} concepts <span>· {members.filter(id => matches.has(id)).length} match</span></p>

          <div className="sx-focus-mode"><button aria-pressed={!listOnly && atlasMode} onClick={() => { setListOnly(false); setAtlasMode(true); }}>Topic atlas</button><button aria-pressed={!listOnly && !atlasMode} onClick={() => { setListOnly(false); setAtlasMode(false); }}>Globe</button><button aria-pressed={listOnly} onClick={() => setListOnly(true)}>Concept list</button></div>

          {!listOnly && <>

            <div className={`sx-globe-frame ${atlasMode ? "is-atlas" : ""}`}>

              <svg viewBox="0 0 360 360" role="group" aria-label={`${activeGroup.title} ${atlasMode ? "topic atlas" : "concept globe"}. Select a concept to show its connections; use View lesson to study.`}>

                <defs><radialGradient id={`${markerId}-focus`} cx="31%" cy="24%" r="78%"><stop offset="0" stopColor="#fffef5" /><stop offset=".65" stopColor={activeGroup.layer === "intermediate" ? "#f3ecd5" : activeGroup.layer === "advanced" ? "#f4dfd1" : "#eaf2df"} /><stop offset="1" stopColor={activeGroup.layer === "intermediate" ? "#d9cba5" : activeGroup.layer === "advanced" ? "#d5b7a3" : "#b8ceac"} /></radialGradient><marker id={`${markerId}-panel-arrow`} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" fill="#719b47"/></marker></defs>

                <ellipse cx="180" cy="326" rx="118" ry="16" className="sx-globe-shadow" />

                <g transform="translate(180 173)">{atlasMode ? <><ellipse cy="15" rx="149" ry="125" className={`sx-focus-disc-lip sx-disc-${activeGroup.layer}`}/><ellipse rx="149" ry="125" fill={`url(#${markerId}-focus)`} className="sx-globe-shell"/>{discBearing(frame.groups[activeGroup.id]?.turn ?? discTurn, 149, 125 / 149)}</> : <><circle r="147" fill={`url(#${markerId}-focus)`} className="sx-globe-shell" /><ellipse rx="61" ry="147" className="sx-globe-wire" /><ellipse rx="117" ry="147" className="sx-globe-wire" /><ellipse rx="147" ry="46" className="sx-globe-wire" /><ellipse rx="147" ry="105" className="sx-globe-wire" /></>}

                  {globeNodes.map(n => {

                    const relevant = reachable(n.id), selected = n.id === focusedId, title = concepts.get(n.id)?.title || n.id;

                    return <g key={n.id} data-concept={n.id} transform={`translate(${n.x} ${n.y})`} role={n.front && relevant ? "button" : undefined} aria-label={n.front && relevant ? `${title} · ${states[stateAt(n.id)]} · Show connections` : undefined} aria-hidden={!n.front || !relevant || undefined} aria-pressed={n.id === connectionRoot} tabIndex={n.front && relevant ? 0 : undefined} className={`sx-concept ${n.front ? "is-front" : "is-rear"} ${selected ? "is-selected" : ""} ${relevant ? "" : "is-filtered"}`} style={{ opacity: n.opacity * (relevant ? n.front ? 1 : .2 : .12) }} onPointerEnter={e => { if (n.front && relevant && e.pointerType !== "touch") showPreview(n.id, e.currentTarget); }} onPointerLeave={closeSoon} onFocus={e => { if (n.front && relevant) { const anchor = e.currentTarget; requestAnimationFrame(() => { if (document.activeElement === anchor) showPreview(n.id, anchor); }); } }} onBlur={closeSoon} onClick={e => { e.stopPropagation(); if (n.front && relevant) { selectConcept(n.id); } }} onKeyDown={e => { if ((e.key === "Enter" || e.key === " ") && n.front && relevant) { e.preventDefault(); selectConcept(n.id); } }}>

                      <title>{title}</title>{selected && <circle r={n.radius + 6 * n.scale} className="sx-selected-halo" />}<circle r={n.radius} className={`sx-status ${stateAt(n.id)}`} />{n.front && (!atlasMode || members.length > 8) && members.length <= 75 && <text textAnchor="middle" dy="3.5" fontSize={members.length <= 30 ? 10 : 7}>{n.index + 1}</text>}

                    </g>;

                  })}

                  <g className="sx-concept-connections" style={{ opacity: linkOpacity }}>{panelPaths.map(e => <path key={`${e.kind}:${e.from}:${e.to}`} className={`sx-concept-link ${e.kind}`} d={e.d} markerEnd={e.kind === "prerequisite" ? `url(#${markerId}-panel-arrow)` : undefined}/>)}</g>
                  <g className="sx-panel-labels" pointerEvents="none" aria-hidden="true">{atlasMode && members.length <= 8 && globeNodes.filter(n => n.front).map(n => {
                    const title = concepts.get(n.id)?.title || "Concept", lines = wrapTopicTitle(title, 18);
                    return <text key={n.id} className="sx-disc-concept-label" transform={`translate(${n.x} ${n.y})`} y={n.radius + 16} textAnchor="middle" style={{ opacity: n.opacity * (reachable(n.id) ? 1 : .12) }}>{lines.slice(0, 2).map((line, i) => <tspan key={i} x="0" dy={i ? 13 : 0}>{i === 1 && lines.length > 2 ? `${line}…` : line}</tspan>)}</text>;
                  })}</g>

                </g>

              </svg>

              <span className="sx-drag-hint">Select a concept to trace connections</span>

            </div>



          </>}

          <div className="sx-about-topic"><h4>About this topic</h4><p>{topicSummary || "Explore this topic’s concepts and the connections that build your understanding."}</p></div>

          {panelConcept && <div className="sx-selected-concept"><span className="sx-eyebrow">{current ? "SELECTED CONCEPT" : "START IN THIS TOPIC"}</span><h4>{panelConcept.title}</h4><p>{panelConcept.curriculum?.adds || panelConcept.summary}</p><button className="button dark" onClick={() => openLesson(panelConcept.id)}>Open lesson <span aria-hidden="true">→</span></button></div>}

          <details className="sx-concept-section" open={listOnly || !!localText}><summary>Browse all {members.length} concepts</summary>

          <div className="sx-concept-browser"><label htmlFor={`${markerId}-search`}>Find a concept in this topic</label><input id={`${markerId}-search`} type="search" placeholder="Search this topic…" value={localText} onChange={e => setLocalQuery({ group: activeGroup.id, text: e.target.value })} /><p>{visibleMembers.length} of {members.length} concepts · choose a name to bring it to the front</p><ul>{visibleMembers.map(id => <li key={id}><button className="sx-locate" aria-label={`Locate ${concepts.get(id)?.title}`} aria-pressed={focusedId === id} onClick={() => selectConcept(id)}><span className={`sx-state-dot ${stateAt(id)}`} /><span><b>{members.indexOf(id) + 1}.</b> {concepts.get(id)?.title}<small>{states[stateAt(id)]}</small></span></button><button className="sx-open" aria-label={`Open lesson: ${concepts.get(id)?.title}`} onClick={() => openLesson(id)}>↗</button></li>)}</ul>{!visibleMembers.length && <p role="status">No concepts match in this topic.</p>}</div>

          </details>

          {current && <div className="sx-lineage"><h4>Learning connections</h4>{([true, false] as const).map(before => { const edges = scene.edges.filter(e => before ? e.dependent === current.id : e.prerequisite === current.id); return <div key={String(before)}><strong>{before ? "Builds on" : "Prepares you for"}</strong>{edges.length ? edges.map(e => { const id = before ? e.prerequisite : e.dependent; return <button key={id} onClick={() => selectConcept(id)}>{concepts.get(id)?.title}<small>{layerNames[scene.nodes.find(n => n.id === id)!.layer]}</small></button>; }) : <p>{before ? "No required prerequisites" : "No further required connections"}</p>}</div>; })}{panelRelated.length > 0 && <div><strong>Related concepts</strong>{panelRelated.map(id => <button key={id} onClick={() => selectConcept(id)}>{concepts.get(id)?.title}<small>{layerNames[scene.nodes.find(n => n.id === id)!.layer]}</small></button>)}</div>}</div>}

        </> : <div className="sx-panel-empty"><span aria-hidden="true">◎</span><h3>No matching topics</h3><p>Adjust your search or filters to explore the curriculum.</p></div>}

      </aside>

    </div>

    <footer className="sx-legend">{Object.entries(states).filter(([key]) => key !== "neutral").map(([key, name]) => <span key={key}><i className={`sx-state-dot ${key}`} />{name}</span>)}<span className="sx-link-legend"><i/>Prerequisite →</span><span className="sx-link-legend is-related"><i/>Related</span><span className="sx-legend-note">Height shows curriculum layer · colour shows learning evidence</span></footer>

    {preview && previewConcept && !modalOpen && <div ref={previewRef} className="sx-preview" role="dialog" aria-label="Concept preview" style={{ left: preview.left, top: preview.top }} onPointerEnter={cancelClose} onPointerLeave={closeSoon}><button className="sx-preview-close" aria-label="Close concept preview" onClick={() => setPreview(null)}>×</button><span className="sx-eyebrow">{previewGroup ? layerNames[previewGroup.layer] : "Concept"}</span><h4>{previewConcept.title}</h4><p><i className={`sx-state-dot ${stateAt(preview.id)}`} />{states[stateAt(preview.id)]}</p><button className="sx-preview-open" onClick={() => openLesson(preview.id)}>View details & lesson →</button></div>}

  </section>;

}

