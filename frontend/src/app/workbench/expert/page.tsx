"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CourseMaterialPicker } from "@/components/course-material-picker";
import { uploadCourseFile, api } from "@/lib/backend";
import { useWorkspace } from "@/components/workspace-provider";
import { ExpertWorkbenchShell } from "@/components/expert-workbench-shell";
import { ExpertTutorHandoffs } from "@/components/expert-tutor-handoffs";
import { InspectorPreview } from "@/components/inspector-preview";
import { ExpertHierarchyReview, type SavedHierarchy } from "@/components/expert-hierarchy-review";
import { formatTemplateTemperature, loadSharedTemplates, type AgentPromptTemplate } from "@/lib/expert-templates";

type InspectionKind = "source_chunks" | "concepts" | "lessons" | "questions" | "embeddings";
type InspectionRow = Record<string, unknown>;
type Inspection = {
  runId: string | null;
  inspectionMode: "live" | "snapshot";
  inspectionScope?: "changes" | "saved";
  document: {
    id: string;
    filename: string;
    status: string;
    pages: number;
    missingTextPages?: number[];
    analysisComplete: boolean;
    lessonsReady?: boolean | null;
    coverage?: { processedPassages?: number; totalPassages?: number; totalSections?: number; mergedConceptCount?: number } | null;
  };
  counts: Record<InspectionKind, number>;
  savedCounts?: Record<InspectionKind, number>;
  sourceWarningCount?: number;
  kind: InspectionKind;
  offset: number;
  limit: number;
  total: number;
  items: InspectionRow[];
  relationship?: Relationship | null;
};
type Relationship = {
  selected: { kind: InspectionKind; id: string; title: string };
  preview?: Record<string, unknown> | null;
  pageContent?: { page: number; chunks: { id: string; ordinal: number; text: string }[] } | null;
  sourceChunks: { id: string; page: number; ordinal: number; text: string; embedded: boolean }[];
  concepts: { id: string; title: string; summary: string; sourceChunkIds: string[] }[];
  lessons: { id: string; conceptId: string; title: string; objective: string; sourceChunkIds: string[] }[];
  questions: { id: string; conceptId: string; prompt: string; difficulty: string; format: string; sourceChunkIds: string[] }[];
};
type ConceptMapNode = { id: string; title: string; summary: string; sourceChunkIds: string[]; lessonCount: number; questionCount: number; lesson: { id: string; title: string; objective: string } | null };
type ConceptMapData = { documentId: string; runId: string; nodes: ConceptMapNode[] };
type RunDetail = {
  id: string;
  status: string;
  summary?: string;
  currentAgent?: string | null;
  events?: RunEvent[];
  agents?: { expert?: { task?: string; detail?: string; status?: string } };
};
type RunEvent = { type: string; at: string; sequence?: number; payload?: Record<string, unknown> };
type PseudoRunSession = {
  id: string;
  courseId?: string;
  course: string;
  material: string;
  materialId: string;
  materialSource?: "published" | "workbench_generated" | "legacy";
  workbenchRunId?: string | null;
  createdAt: string;
  status: string;
  phase?: string;
  message?: string;
  progress: { learnerName: string; condition: string; status: string; activitiesCompleted: number; activityLimit: number }[];
  report?: { completed: number; failedOrStopped: number; preparationUsage: { calls: number; costUsd: number | null } } | null;
};
type RunReceipt = { runId: string; status: string };

const tabs: { id: InspectionKind; label: string }[] = [
  { id: "source_chunks", label: "Source chunks" },
  { id: "concepts", label: "Concepts" },
  { id: "lessons", label: "Lessons" },
  { id: "questions", label: "Questions" },
  { id: "embeddings", label: "Embeddings" },
];
const readable = (value: string) => value.replaceAll("_", " ");
const formatCost = (value: number) => value > 0 && value < 0.000001 ? "< $0.000001" : `$${value.toFixed(value > 0 && value < 0.0001 ? 6 : 4)}`;
const isWorking = (status?: string) => status === "queued" || status === "running" || status === "paused";
const terminalStatuses = new Set(["completed", "failed", "needs_review", "waiting_for_learner", "stopped"]);
function eventText(event: RunEvent, key: string) {
  const value = event.payload?.[key];
  return typeof value === "string" ? value : "";
}
function eventTitle(event: RunEvent) {
  if (event.type === "agent.step") {
    const role = eventText(event, "role");
    const task = eventText(event, "task") || "Agent step";
    return `${role ? `${readable(role)} · ` : ""}${task}`;
  }
  if (event.type === "run.status") return eventText(event, "status") === "completed" && /warnings/i.test(eventText(event, "summary")) ? "Run completed with warnings" : `Run ${readable(eventText(event, "status") || "updated")}`;
  if (event.type === "runtime.validation") return `Validation ${readable(eventText(event, "status") || "updated")}`;
  if (event.type === "agent.handoff") return `Agent handoff${eventText(event, "to") ? ` · ${readable(eventText(event, "to"))}` : ""}`;
  return readable(event.type);
}
function eventDescription(event: RunEvent) {
  return eventText(event, "detail") || eventText(event, "summary") || eventText(event, "reason") || eventText(event, "message") || eventText(event, "tool");
}
function activityEventStatus(event: RunEvent, runStatus: string) {
  const status = eventText(event, "status");
  return status === "running" && terminalStatuses.has(runStatus) ? "done" : status;
}
function eventTone(event: RunEvent, status = eventText(event, "status")) {
  if (event.type === "agent.step" && eventText(event, "task") === "Source review warning") return "attention";
  if (event.type === "run.status" && /warnings/i.test(eventText(event, "summary"))) return "attention";
  if (["failed", "needs_review", "rejected"].includes(status)) return "attention";
  if (["completed", "accepted", "supported", "done"].includes(status)) return "complete";
  return "active";
}
function eventTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export default function ExpertWorkbenchPage() {
  const ws = useWorkspace();
  const relationshipDialog = useRef<HTMLDialogElement>(null);
  const activityLogRef = useRef<HTMLDivElement>(null);
  const conceptMapRef = useRef<ConceptMapData | null>(null);
  const mapScrollRef = useRef<HTMLDivElement>(null);
  const mapDragRef = useRef<{ pointerId: number; x: number; y: number; left: number; top: number; moved: boolean } | null>(null);
  const suppressMapClick = useRef(false);
  const inspectionRequestRef = useRef(0);
  const graphRequestRef = useRef(0);
  const [documentId, setDocumentId] = useState("");
  const [kind, setKind] = useState<InspectionKind>("source_chunks");
  const [inspectorView, setInspectorView] = useState<"records" | "graph">("records");
  const [offset, setOffset] = useState(0);
  const [inspectionState, setInspection] = useState<Inspection | null>(null);
  const [inspectionError, setInspectionError] = useState("");
  const [requestedRunId, setRequestedRunId] = useState("");
  const [pendingRunId, setPendingRunId] = useState("");
  const [pendingRunDocumentId, setPendingRunDocumentId] = useState("");
  const [conceptMap, setConceptMap] = useState<ConceptMapData | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState("");
  const [mapZoom, setMapZoom] = useState(100);
  const [mapDragging, setMapDragging] = useState(false);
  const [runDetailState, setRunDetail] = useState<RunDetail | null>(null);
  const [selectedRowId, setSelectedRowId] = useState("");
  const [relationshipOpen, setRelationshipOpen] = useState(false);
  const [relationship, setRelationship] = useState<Relationship | null>(null);
  const [relationshipBusy, setRelationshipBusy] = useState(false);
  const [relationshipError, setRelationshipError] = useState("");
  const [showAllActivity, setShowAllActivity] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [materialSourceTab, setMaterialSourceTab] = useState<"upload" | "existing">("upload");
  const [busy, setBusy] = useState(false);
  const [startingRuns, setStartingRuns] = useState(false);
  const [stoppingRunId, setStoppingRunId] = useState("");
  const [runTemplates, setRunTemplates] = useState<AgentPromptTemplate[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [hierarchyMode, setHierarchyMode] = useState<"continue" | "new">("new");
  const [reanalyze, setReanalyze] = useState(false);
  const [publishRevision, setPublishRevision] = useState(0);
  const [hierarchySources, setHierarchySources] = useState<SavedHierarchy[]>([]);
  const [hierarchySourceId, setHierarchySourceId] = useState("");
  const [hierarchySourcesError, setHierarchySourcesError] = useState("");
  const [pseudoRuns, setPseudoRuns] = useState<PseudoRunSession[]>([]);
  const [pseudoRunId, setPseudoRunId] = useState("");
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [now, setNow] = useState(0);

  const hierarchySourcesRevision = ws.runs.map(run => `${run.id}:${run.status}`).join("|");
  useEffect(() => { setHierarchySourceId(""); setHierarchySources([]); setHierarchyMode("new"); setReanalyze(false); setPseudoRunId(""); }, [ws.courseId]);
  useEffect(() => {
    let active = true;
    setHierarchySourcesError("");
    const refreshSources = () => ws.courseId && void api<SavedHierarchy[]>(`courses/${ws.courseId}/hierarchy-runs`).then(sources => { if (active) setHierarchySources(sources); }).catch(error => { if (active) setHierarchySourcesError((error as Error).message); });
    refreshSources();
    const timer = /:(queued|running)/.test(hierarchySourcesRevision) ? setInterval(refreshSources, 5000) : undefined;
    return () => { active = false; clearInterval(timer); };
  }, [ws.courseId, hierarchySourcesRevision, publishRevision]);
  const refreshPseudoRuns = useCallback(async () => {
    if (!ws.courseId) { setPseudoRuns([]); return; }
    try {
      const items = await api<PseudoRunSession[]>("evaluations/pseudo-runs");
      setPseudoRuns(items.filter((run) => run.courseId === ws.courseId).sort((a, b) => b.createdAt.localeCompare(a.createdAt)));
    } catch { /* Keep the last progress snapshot if the local API is briefly unavailable. */ }
  }, [ws.courseId]);
  useEffect(() => {
    void refreshPseudoRuns();
    const timer = setInterval(() => void refreshPseudoRuns(), 7000);
    return () => clearInterval(timer);
  }, [refreshPseudoRuns]);

  useEffect(() => {
    const map = mapScrollRef.current;
    if (!map) return;
    let accumulated = 0;
    function zoomWithWheel(event: WheelEvent) {
      if (!event.deltaY) return;
      event.preventDefault();
      accumulated += event.deltaY * (event.deltaMode === WheelEvent.DOM_DELTA_LINE ? 16 : event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? map!.clientHeight : 1);
      if (Math.abs(accumulated) < 60) return;
      const direction = accumulated > 0 ? -1 : 1;
      accumulated = 0;
      setMapZoom(value => Math.max(100, Math.min(400, value + direction * 25)));
    }
    map.addEventListener("wheel", zoomWithWheel, { passive: false });
    return () => map.removeEventListener("wheel", zoomWithWheel);
  });

  useEffect(() => {
    const dialog = relationshipDialog.current;
    if (relationshipOpen && dialog && !dialog.open) dialog.showModal();
    if (!relationshipOpen && dialog?.open) dialog.close();
  }, [relationshipOpen]);

  const documents = ws.course?.documents || [];
  const selectedMaterialId = documents.some((doc) => doc.id === ws.materialId) ? ws.materialId : "";
  const materialSelection = selectedMaterialId || documentId;
  const activeDocumentId = materialSelection === "all" ? documents[0]?.id || "" : documents.some((doc) => doc.id === materialSelection) ? materialSelection : "";
  const selectedDocument = documents.find((doc) => doc.id === activeDocumentId) || null;
  const selectedRunTemplate = runTemplates.find((template) => template.id === selectedTemplateId) || null;
  const runTargets = materialSelection === "all" ? documents : documents.filter((doc) => doc.id === activeDocumentId && activeDocumentId);
  const activeRunDocumentIds = new Set(ws.runs.filter((run) => run.workflow === "course_preparation" && isWorking(run.status)).flatMap((run) => run.documentIds || [run.documentId]).filter((id): id is string => Boolean(id)));
  const runnableTargets = runTargets.filter((doc) => !activeRunDocumentIds.has(doc.id));
  const relatedRuns = useMemo(
    () => ws.runs.filter((run) => run.workflow === "course_preparation")
      .sort((a, b) => (b.startedAt || "").localeCompare(a.startedAt || "")),
    [ws.runs],
  );
  const materialRuns = useMemo(() => relatedRuns.filter((run) => (run.documentIds || [run.documentId]).includes(activeDocumentId)), [relatedRuns, activeDocumentId]);
  const pendingForDocument = pendingRunDocumentId === activeDocumentId ? pendingRunId : "";
  const currentRun = useMemo(() => materialRuns.find((run) => run.id === (pendingForDocument || requestedRunId)) || (!pendingForDocument && !requestedRunId ? materialRuns.find((run) => isWorking(run.status)) : null) || null, [materialRuns, pendingForDocument, requestedRunId]);
  const selectedPseudoRun = pseudoRuns.find((run) => run.id === pseudoRunId) || null;
  const coursePseudoRuns = pseudoRuns.filter((run) =>
    (run.courseId ? run.courseId === ws.courseId : run.course === ws.course?.title) &&
    (!selectedMaterialId || run.materialId === "__all__" || run.materialId === selectedMaterialId),
  );
  const displayedHierarchyId = currentRun?.id || (hierarchyMode === "continue" ? hierarchySourceId : "");
  const inspection = !startingRuns && inspectionState?.document.id === activeDocumentId && inspectionState.runId === currentRun?.id ? inspectionState : null;
  const runDetail = currentRun && runDetailState?.id === currentRun.id ? runDetailState : null;

  useEffect(() => {
    if (pendingRunId && materialRuns.some((run) => run.id === pendingRunId)) setPendingRunId("");
  }, [materialRuns, pendingRunId]);

  const loadConceptMap = useCallback(async (docId: string, runId: string) => {
    const requestId = ++graphRequestRef.current;
    if (conceptMapRef.current?.documentId !== docId || conceptMapRef.current?.runId !== runId) setGraphLoading(true);
    setGraphError("");
    try {
      const firstPage = await api<Inspection>(`documents/${docId}/inspection?run_id=${encodeURIComponent(runId)}&kind=concepts&offset=0&limit=100`);
      if (firstPage.runId !== runId) throw new Error("The API server needs to be restarted to support run snapshots.");
      const items = [...firstPage.items];
      for (let pageOffset = firstPage.limit; pageOffset < firstPage.total; pageOffset += firstPage.limit) {
        const page = await api<Inspection>(`documents/${docId}/inspection?run_id=${encodeURIComponent(runId)}&kind=concepts&offset=${pageOffset}&limit=${firstPage.limit}`);
        items.push(...page.items);
      }
      const lessonPage = await api<Inspection>(`documents/${docId}/inspection?run_id=${encodeURIComponent(runId)}&kind=lessons&offset=0&limit=100`);
      const lessons = [...lessonPage.items];
      for (let pageOffset = lessonPage.limit; pageOffset < lessonPage.total; pageOffset += lessonPage.limit) {
        const page = await api<Inspection>(`documents/${docId}/inspection?run_id=${encodeURIComponent(runId)}&kind=lessons&offset=${pageOffset}&limit=${lessonPage.limit}`);
        lessons.push(...page.items);
      }
      const lessonByConcept = new Map(lessons.map((lesson) => [String(lesson.conceptId || ""), {
        id: String(lesson.id || ""),
        title: String(lesson.title || "Untitled lesson"),
        objective: String(lesson.objective || ""),
      }]));
      const result: ConceptMapData = {
        documentId: docId,
        runId,
        nodes: items.map((item) => ({
          id: String(item.id || ""),
          title: String(item.title || "Untitled concept"),
          summary: String(item.summary || ""),
          sourceChunkIds: Array.isArray(item.sourceChunkIds) ? item.sourceChunkIds.filter((value): value is string => typeof value === "string") : [],
          lessonCount: Number(item.lessonCount || 0),
          questionCount: Number(item.questionCount || 0),
          lesson: lessonByConcept.get(String(item.id || "")) || null,
        })),
      };
      if (requestId !== graphRequestRef.current) return;
      conceptMapRef.current = result;
      setConceptMap(result);
    } catch (cause) {
      if (requestId === graphRequestRef.current) setGraphError((cause as Error).message || "Could not load the concept map.");
    } finally {
      if (requestId === graphRequestRef.current) setGraphLoading(false);
    }
  }, []);

  const refreshInspection = useCallback(async () => {
    const requestId = ++inspectionRequestRef.current;
    if (startingRuns) return;
    if (!activeDocumentId || !currentRun) {
      setInspection(null);
      setRunDetail(null);
      setInspectionError("");
      setGraphError("");
      ++graphRequestRef.current;
      conceptMapRef.current = null;
      setConceptMap(null);
      return;
    }
    try {
      const record = await api<Inspection>(`documents/${activeDocumentId}/inspection?run_id=${encodeURIComponent(currentRun.id)}&kind=${kind}&offset=${offset}&limit=20`);
      if (record.runId !== currentRun.id) throw new Error("The API server needs to be restarted to support run snapshots.");
      if (requestId !== inspectionRequestRef.current) return;
      setInspection(record);
      setSelectedRowId((current) => record.items.some((item) => item.id === current) ? current : String(record.items[0]?.id || ""));
      setInspectionError("");
    } catch (cause) {
      if (requestId !== inspectionRequestRef.current) return;
      setInspection(null);
      setInspectionError((cause as Error).message);
    }
    if (inspectorView === "graph" && currentRun) await loadConceptMap(activeDocumentId, currentRun.id);
    if (currentRun) {
      try {
        const detail = await api<RunDetail>(`agent-activity/runs/${currentRun.id}`);
        if (requestId === inspectionRequestRef.current) setRunDetail(detail);
      } catch { if (requestId === inspectionRequestRef.current) setRunDetail(null); }
    } else setRunDetail(null);
  }, [activeDocumentId, currentRun, inspectorView, kind, loadConceptMap, offset, startingRuns]);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      setNow(Date.now());
      await refreshInspection();
      if (active) timer = setTimeout(poll, 3500);
    };
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [refreshInspection]);

  useEffect(() => {
    const node = activityLogRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [runDetail?.events?.length, showAllActivity]);

  useEffect(() => {
    const refreshTemplates = async () => {
      const templates = (await loadSharedTemplates()).filter((template) => template.agent === "expert");
      setRunTemplates(templates);
      setSelectedTemplateId((current) => templates.some((template) => template.id === current) ? current : "");
    };
    refreshTemplates();
    window.addEventListener("storage", refreshTemplates);
    window.addEventListener("learnloop-expert-templates-updated", refreshTemplates);
    return () => {
      window.removeEventListener("storage", refreshTemplates);
      window.removeEventListener("learnloop-expert-templates-updated", refreshTemplates);
    };
  }, []);

  function chooseRunTemplate(id: string) {
    setSelectedTemplateId(id);
  }

  async function stopCurrentRun() {
    if (!currentRun || stoppingRunId) return;
    setStoppingRunId(currentRun.id);
    setError("");
    try {
      const result = await api<{ status: string }>(`agent-activity/runs/${encodeURIComponent(currentRun.id)}/stop`, {});
      setMessage(result.status === "stopped" ? "Run stopped. Saved work is retained." : "Stopping the run after current requests finish. Saved work is retained.");
      await ws.refresh();
      await refreshInspection();
    } catch (cause) { setError(`Could not stop the run: ${(cause as Error).message}`); }
    finally { setStoppingRunId(""); }
  }

  function selectSession(runId: string) {
    const run = relatedRuns.find((item) => item.id === runId && (!selectedMaterialId || (item.documentIds || [item.documentId]).includes(selectedMaterialId)));
    setPseudoRunId("");
    setDocumentId(selectedMaterialId || run?.documentId || "");
    setRequestedRunId(run?.id || "new");
    setPendingRunId("");
    setPendingRunDocumentId("");
    setSelectedTemplateId("");
    setHierarchyMode("new");
    setReanalyze(false);
    setHierarchySourceId("");
    setFiles([]);

    setMaterialSourceTab("upload");
    setOffset(0);
    setQuery("");
    setKind("source_chunks");
    setInspectorView("records");
    setRelationshipOpen(false);
    setError("");
    setMessage("");
  }

  function selectPseudoSession(runId: string) {
    setPseudoRunId(runId);
    setRequestedRunId("new");
    setPendingRunId("");
    setPendingRunDocumentId("");
    setInspection(null);
    setRunDetail(null);
    setInspectionError("");
    setGraphError("");
    setSelectedRowId("");
    setOffset(0);
    setQuery("");
    setInspectorView("records");
    setError("");
    setMessage("");
  }

  async function runSelectedMaterials() {
    if (!runnableTargets.length || runnableTargets.length !== runTargets.length || (hierarchyMode === "continue" && !hierarchySourceId)) return;
    setStartingRuns(true);
    ++inspectionRequestRef.current;
    ++graphRequestRef.current;
    setInspection(null);
    setInspectionError("");
    setSelectedRowId("");
    setOffset(0);
    setQuery("");
    setRelationshipOpen(false);
    setRelationship(null);
    conceptMapRef.current = null;
    setConceptMap(null);
    setError("");
    setMessage("");
    try {
      const receipt = await api<RunReceipt>(`courses/${ws.courseId}/hierarchy-runs`, {
          documentIds: runnableTargets.map(doc => doc.id),
          parentRunId: hierarchyMode === "continue" ? hierarchySourceId : null,
          reanalyze: hierarchyMode === "continue" && reanalyze,
          promptTemplate: selectedRunTemplate ? {
            id: selectedRunTemplate.id,
            agent: selectedRunTemplate.agent,
            name: selectedRunTemplate.name,
            prompts: selectedRunTemplate.prompts,
            enabledTools: selectedRunTemplate.enabledTools,
            model: selectedRunTemplate.model,
            temperature: selectedRunTemplate.temperature,
            basePrompts: selectedRunTemplate.basePrompts ?? "v2",
            organizationVariant: selectedRunTemplate.organizationVariant ?? "baseline",
          } : null,
        });
      setRequestedRunId(receipt.runId);
      setPendingRunDocumentId(activeDocumentId);
      setPendingRunId(receipt.runId);
      await ws.refresh();
      setMessage(`Queued one hierarchy run for ${runnableTargets.map(doc => doc.filename).join(", ")}.`);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setStartingRuns(false);
    }
  }

  async function uploadMaterials() {
    if (!ws.courseId || files.length === 0) return;
    setBusy(true);
    setError("");
    setMessage("");
    let uploaded = 0;
    try {
      for (const file of files) {
        const receipt = await uploadCourseFile(ws.courseId, file);
        setDocumentId(receipt.documentId);
        setRequestedRunId("");
        setKind("source_chunks");
        setOffset(0);
        setMessage(receipt.duplicate ? `${file.name} is already in this course. Select a template and run it when ready.` : `${file.name} uploaded. Select a template and click Run when ready.`);
        uploaded += 1;
        await ws.refresh();
      }
      setFiles([]);

      await ws.refresh();
      setMaterialSourceTab("existing");
    } catch (cause) {
      setError((cause as Error).message);
      if (uploaded) await ws.refresh();
    } finally {
      setBusy(false);
    }
  }

  function selectKind(next: InspectionKind) {
    setKind(next);
    setOffset(0);
    setQuery("");
  }

  async function openRelationship(recordId: string, recordKind: InspectionKind) {
    if (!activeDocumentId || !currentRun || !inspection) return;
    setSelectedRowId(recordId);
    setRelationshipOpen(true);
    setRelationshipBusy(true);
    setRelationship(null);
    setRelationshipError("");
    try {
      const result = await api<Inspection>(`documents/${activeDocumentId}/inspection?run_id=${encodeURIComponent(currentRun.id)}&kind=${recordKind}&record_id=${encodeURIComponent(recordId)}&limit=1`);
      setRelationship(result.relationship || null);
      if (!result.relationship) setRelationshipError("No relationship data is available for this record.");
    } catch (cause) {
      setRelationshipError((cause as Error).message);
    } finally {
      setRelationshipBusy(false);
    }
  }

  const counts = inspection?.counts;
  const savedCounts = inspection?.savedCounts || (inspection?.inspectionScope !== "changes" ? counts : undefined);
  const chunks = savedCounts?.source_chunks || 0;
  const embedded = savedCounts?.embeddings || 0;
  const documentStatus = currentRun ? inspection?.document.status || selectedDocument?.status || "" : "";
  const extractDone = chunks > 0 || (Boolean(currentRun) && Boolean(selectedDocument?.pages)) || ["extracted", "indexed", "prepared", "published", "needs_review"].includes(documentStatus);
  const embeddingDone = chunks > 0 && embedded >= chunks;
  const runStatus = runDetail?.status || currentRun?.status || documentStatus;
  const active = isWorking(runStatus);
  const latestStep = runDetail?.agents?.expert;
  const analysisComplete = inspection?.document.analysisComplete === true || (savedCounts?.concepts || 0) > 0;
  const resourceCount = (savedCounts?.lessons || 0) + (savedCounts?.questions || 0);
  const preparedDocument = ["prepared", "published"].includes(documentStatus);
  const needsReview = documentStatus === "needs_review" || runStatus === "needs_review";
  const warningCount = inspection?.sourceWarningCount || 0;
  const hasWarnings = warningCount > 0 || (runStatus === "completed" && /warnings/i.test(runDetail?.summary || currentRun?.summary || ""));
  const runLabel = runStatus === "completed" && hasWarnings ? "completed with warnings" : readable(runStatus || "waiting");
  const recentActivityText = [
    latestStep?.task || "",
    latestStep?.detail || "",
    ...(runDetail?.events || []).slice(-4).flatMap((event) => [eventTitle(event), eventDescription(event)]),
  ].join(" ").toLowerCase();
  const liveStepLabel = latestStep?.task || (runDetail?.events?.length ? eventTitle(runDetail.events[runDetail.events.length - 1]) : "In progress");
  const latestRunningActivity = runStatus === "running" && runDetail?.events?.length
    ? [...runDetail.events].reverse().find((event) => eventText(event, "status") === "running") || runDetail.events[runDetail.events.length - 1]
    : null;
  const elapsedSeconds = useMemo(() => {
    if (!currentRun) return null;
    const events = runDetail?.events || [];
    const start = currentRun.startedAt ? new Date(currentRun.startedAt).getTime() : events[0]?.at ? new Date(events[0].at).getTime() : null;
    if (!start) return null;
    const end = !active && terminalStatuses.has(runStatus) && events.length ? new Date(events[events.length - 1].at).getTime() : now;
    return Math.max(0, Math.floor((end - start) / 1000));
  }, [active, currentRun, now, runDetail, runStatus]);

  const stageState = (stage: "upload" | "extract" | "chunk" | "embedding" | "concepts" | "curriculum" | "resources" | "publish"): "done" | "running" | "pending" | "attention" => {
    if (stage === "upload") return currentRun && selectedDocument ? "done" : "pending";
    if (stage === "extract") return extractDone ? "done" : active ? "running" : "pending";
    if (stage === "chunk") return chunks > 0 ? "done" : active && ["queued", "running"].includes(documentStatus) ? "running" : "pending";
    if (stage === "embedding") return embeddingDone ? "done" : chunks > 0 && active ? "running" : "pending";
    if (stage === "concepts") {
      if (analysisComplete) return "done";
      if (needsReview) return "attention";
      return active && (embeddingDone || /concept|analysis|passage|review/.test(recentActivityText)) ? "running" : "pending";
    }
    if (stage === "curriculum") {
      if (active && /merge|organ|curriculum|prerequisite|repeated goal/.test(recentActivityText)) return "running";
      if (resourceCount > 0 || preparedDocument) return "done";
      if (needsReview) return "attention";
      return active && analysisComplete ? "running" : "pending";
    }
    if (stage === "resources") {
      if (active && /lesson|question|test|material|resource/.test(recentActivityText)) return "running";
      if (inspection?.document.lessonsReady === true) return "done";
      if (needsReview || hasWarnings) return "attention";
      if (runStatus === "completed" && resourceCount > 0) return "done";
      if (documentStatus === "published" && !active) return "done";
      return active && analysisComplete ? "running" : "pending";
    }
    if (needsReview || hasWarnings) return "attention";
    if (hierarchySources.find(source => source.runId === currentRun?.id)?.ready || hierarchySources.find(source => source.runId === currentRun?.id)?.published) return "done";
    if (documentStatus === "published" && !active) return "done";
    return active && /publish|validation|save|complete/.test(recentActivityText) ? "running" : "pending";
  };

  const pageRows = inspection?.items || [];
  const filteredRows = pageRows.filter((row) => JSON.stringify(row).toLowerCase().includes(query.trim().toLowerCase()));
  const pageEnd = Math.min(offset + (inspection?.limit || 20), inspection?.total || 0);
  const allConceptNodes = conceptMap?.documentId === activeDocumentId && conceptMap.runId === currentRun?.id ? conceptMap.nodes : [];
  const matchingConceptNodes = allConceptNodes.filter((node) => !query.trim() || `${node.title} ${node.summary}`.toLowerCase().includes(query.trim().toLowerCase()));
  const graphNodes = matchingConceptNodes.slice(0, 120);
  const conceptMapLayout = useMemo(() => {
    const width = 960;
    const height = 660;
    const positions = graphNodes.map((node, index) => {
      const angle = index * 2.399963229728653 - Math.PI / 2;
      const radius = graphNodes.length <= 1 ? 0 : Math.sqrt((index + 0.5) / graphNodes.length);
      return { node, x: width / 2 + Math.cos(angle) * radius * 390, y: height / 2 + Math.sin(angle) * radius * 220 };
    });
    const edges: { from: string; to: string; weight: number }[] = [];
    const sourceSets = graphNodes.map((node) => new Set(node.sourceChunkIds));
    for (let left = 0; left < graphNodes.length; left += 1) {
      for (let right = left + 1; right < graphNodes.length; right += 1) {
        let weight = 0;
        for (const id of sourceSets[left]) if (sourceSets[right].has(id)) weight += 1;
        if (weight) edges.push({ from: graphNodes[left].id, to: graphNodes[right].id, weight });
      }
    }
    edges.sort((a, b) => b.weight - a.weight);
    return { positions, edges: edges.slice(0, 360), totalEdges: edges.length, lessonCount: graphNodes.filter((node) => node.lesson).length };
  }, [graphNodes]);

  const formatElapsed = (seconds: number | null) => seconds == null ? "—" : `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  const itemText = (row: InspectionRow, key: string) => typeof row[key] === "string" ? row[key] as string : "";
  const runButtonLabel = startingRuns ? "Starting…" : !runTargets.length ? "Select a material to run" : !runnableTargets.length ? "Already running" : materialSelection !== "all" ? "Run selected material" : `Run ${runnableTargets.length} ${runnableTargets.length === 1 ? "material" : "materials"}`;
  const railContent = <>
    <section className="expert-run-template-list" aria-label="Choose a prompt template for the next run">
      <h2>Run with template</h2>
      <label className={`expert-run-template-option ${!selectedTemplateId ? "selected" : ""}`}>
        <input type="radio" name="expert-run-template" checked={!selectedTemplateId} onChange={() => chooseRunTemplate("")} />
        <span><strong>Agent default</strong><small>Use the shared default, or configured settings if none is set</small></span>
      </label>
      {runTemplates.map((template) => <label key={template.id} className={`expert-run-template-option ${selectedTemplateId === template.id ? "selected" : ""}`}>
        <input type="radio" name="expert-run-template" checked={selectedTemplateId === template.id} onChange={() => chooseRunTemplate(template.id)} />
        <span><strong>{template.name}</strong><small>{template.model} · {formatTemplateTemperature(template.temperature)}</small></span>
      </label>)}
      {!runTemplates.length && <p className="expert-run-template-empty">Save an Expert template in Edit agent to run it here.</p>}
    </section>
    <section className="expert-run-rail-summary" aria-label="Selected material run status">
      <h2>Current run</h2>
      {currentRun && selectedDocument ? <>
        <strong title={selectedDocument.filename}>{selectedDocument.filename}</strong>
        <span className={`expert-status-tag ${hasWarnings && runStatus === "completed" ? "needs_review" : runStatus || "queued"}`}>{runLabel}</span>
        <div className="expert-run-rail-metrics"><span>{savedCounts ? chunks : "—"} chunks</span><span>{savedCounts ? embedded : "—"} embeddings</span></div>
        <small>{formatElapsed(elapsedSeconds)} elapsed</small>
      </> : <p>Start a run or load a previous session.</p>}
    </section>
  </>;

  return <ExpertWorkbenchShell activePage="run" railContent={railContent}>
      <div className="expert-page-heading">
        <div><p className="expert-eyebrow">EXPERT AGENT · RUN</p><h1>Run · Material ingestion</h1></div>
      </div>

      <div className="expert-inspector-run-select"><label htmlFor="expert-session-select">Run session</label><select id="expert-session-select" value={currentRun?.id || ""} onChange={(event) => selectSession(event.target.value)} disabled={startingRuns}><option value="">New session</option>{relatedRuns.filter((run) => documents.some((doc) => doc.id === run.documentId) && (!selectedMaterialId || (run.documentIds || [run.documentId]).includes(selectedMaterialId))).map((run) => <option key={run.id} value={run.id}>{documents.filter(doc => (run.documentIds || [run.documentId]).includes(doc.id)).map(doc => doc.filename).join(", ")} · {run.startedAt ? new Date(run.startedAt).toLocaleString() : "Run"} · {readable(run.status)} · {run.id.slice(0, 8)}</option>)}</select></div>

      {ws.error && <p className="expert-alert" role="alert">{ws.error}</p>}
      {error && <p className="expert-alert" role="alert">{error}</p>}
      {message && <p className="expert-message" role="status">{message}</p>}

      {!ws.courseId ? <section className="expert-empty"><h2>Choose or create a course</h2><p>Upload course materials to let the Expert extract passages, build embeddings, and prepare learning resources.</p><Link href="/materials" className="expert-button primary">Open Materials</Link></section> : <div className="expert-columns">
        <section className="expert-left-column" aria-label="Material ingestion">
          <section className="expert-card expert-upload-card">
            <div className="expert-card-heading"><div><h2>Add course materials</h2><p>Upload a source file for the Expert Agent to process.</p></div><span className="expert-course-pill">{ws.courses.find((course) => course.id === ws.courseId)?.title || "Selected course"}</span></div>
            <CourseMaterialPicker
              documents={documents} selection={materialSelection} lockedSelection={selectedMaterialId}
              tab={materialSourceTab} onTabChange={setMaterialSourceTab} files={files}
              onFilesChange={(next) => { setFiles(next); setError(""); setMessage(""); }}
              disabled={busy}
              uploadAction={<button type="button" className="expert-button primary" disabled={busy} onClick={() => void uploadMaterials()}>{busy ? "Uploading…" : `Upload ${files.length === 1 ? "material" : `${files.length} materials`}`}</button>}
              onSelect={(id) => {
                setDocumentId(id);
                setRequestedRunId("");
                setPendingRunId("");
                if (id !== "all") { setOffset(0); setKind("source_chunks"); }
              }}
            />
              <fieldset className="expert-hierarchy-mode"><legend>Hierarchy for the next run</legend>
                <label><input type="radio" name="hierarchy-mode" checked={hierarchyMode === "new"} onChange={() => setHierarchyMode("new")} />Generate a new hierarchy</label>
                <label><input type="radio" name="hierarchy-mode" checked={hierarchyMode === "continue"} onChange={() => setHierarchyMode("continue")} />Continue from a previous run</label>
                {hierarchyMode === "new" ? <p>Build a hierarchy from the selected materials only.</p> : <>
                  <label>Previous run<select value={hierarchySourceId} onChange={event => setHierarchySourceId(event.target.value)}><option value="">Choose a saved hierarchy</option>{hierarchySources.map(source => <option key={source.runId} value={source.runId}>{source.filenames.join(", ") || "Published course hierarchy"} · {source.createdAt ? new Date(source.createdAt).toLocaleString() : ""} · {source.runId.slice(0, 8)}</option>)}</select></label>
                  <p>Keep this run’s topics and concepts. Process newly selected materials.</p>
                  <label><input type="checkbox" checked={reanalyze} onChange={event => setReanalyze(event.target.checked)} />Reanalyze selected materials already in the previous run</label>
                </>}
                {hierarchySourcesError && <p role="alert">{hierarchySourcesError}</p>}
              </fieldset>
            <div className="expert-run-actions">
              <div><strong>{selectedRunTemplate?.name || "Agent default"}</strong><span>{materialSelection === "all" ? `${runTargets.length} materials · all course materials` : selectedDocument?.filename || "No material selected"}</span><small>The selected template applies to the next Expert run. The hierarchy is saved with the run.</small></div>

              <button type="button" className="expert-button primary" disabled={!runnableTargets.length || startingRuns || busy || (hierarchyMode === "continue" && !hierarchySourceId) || runnableTargets.length !== runTargets.length} onClick={() => void runSelectedMaterials()}>{runButtonLabel}</button>
            </div>
            {runTargets.length > runnableTargets.length && <p className="expert-help-note">A selected material already has an active run.</p>}
          </section>

          <section className="expert-card expert-pipeline-card" aria-labelledby="expert-pipeline-title">
            <div className="expert-card-heading"><div><h2 id="expert-pipeline-title">{selectedPseudoRun ? "Pseudo-student test progress" : "Ingestion pipeline"}</h2><p>{selectedPseudoRun ? `${selectedPseudoRun.material} · ${readable(selectedPseudoRun.status)} · ${selectedPseudoRun.phase || "Preparing"}` : currentRun && selectedDocument ? `${selectedDocument.filename} · ${readable(currentRun.status)}` : "Start a run or load a previous session to see its progress."}</p></div><div>{currentRun && isWorking(currentRun.status) && <button type="button" className="expert-button secondary danger" disabled={currentRun.stopSupported === false || stoppingRunId === currentRun.id || currentRun.summary?.startsWith("Stopping after")} onClick={() => void stopCurrentRun()}>{stoppingRunId === currentRun.id || currentRun.summary?.startsWith("Stopping after") ? "Stopping…" : "Stop agent"}</button>} <button type="button" className="expert-text-button" onClick={() => { void ws.refresh(); void refreshInspection(); void refreshPseudoRuns(); }}>Refresh</button></div></div>
            {selectedPseudoRun ? <div className="expert-pseudo-session-progress" role="status">
              <p><strong>Current phase:</strong> {selectedPseudoRun.phase || selectedPseudoRun.message || readable(selectedPseudoRun.status)}</p>
              {selectedPseudoRun.message && <p>{selectedPseudoRun.message}</p>}
              <p>Workbench generation {selectedPseudoRun.workbenchRunId?.slice(0, 8) || selectedPseudoRun.id.slice(0, 8)} · test {selectedPseudoRun.id.slice(0, 8)}</p>
              <div className="expert-metrics">
                <div><span>Test status</span><strong>{readable(selectedPseudoRun.status)}</strong></div>
                <div><span>Episodes completed</span><strong>{selectedPseudoRun.report ? `${selectedPseudoRun.report.completed} / ${selectedPseudoRun.report.completed + selectedPseudoRun.report.failedOrStopped}` : "In progress"}</strong></div>
                <div><span>Preparation calls</span><strong>{selectedPseudoRun.report?.preparationUsage.calls ?? "In progress"}</strong></div>
                <div><span>Preparation cost</span><strong>{selectedPseudoRun.report?.preparationUsage.costUsd == null ? "Pending" : formatCost(selectedPseudoRun.report.preparationUsage.costUsd)}</strong></div>
              </div>
              <h3>Learner episodes</h3>
              {selectedPseudoRun.progress.length ? <ul>{selectedPseudoRun.progress.map((episode, index) => <li key={`${episode.learnerName}-${episode.condition}-${index}`}><strong>{episode.learnerName}</strong> · {readable(episode.condition)} · {readable(episode.status)} · {episode.activitiesCompleted} / {episode.activityLimit} activities</li>)}</ul> : <p>Episode progress will appear after the test materials are prepared.</p>}
              <Link href="/workbench/evaluation" className="expert-text-button">Open pseudo-student test results</Link>
            </div> : <>
            {currentRun && isWorking(currentRun.status) && currentRun.stopSupported === false && <p className="expert-help-note">This run started on an older worker and cannot be stopped safely. Restart the worker after it finishes to enable stopping future runs.</p>}
            <ol className="expert-pipeline">
              {([
                ["upload", "Upload", "File saved"],
                ["extract", "Text extraction", "Read pages"],
                ["chunk", "Chunk passages", chunks ? `${chunks} passages` : "Split the text"],
                ["embedding", "Embed passages", embedded ? `${embedded} vectors` : "Index passages"],
                ["concepts", "Analyze concepts", `${savedCounts?.concepts ?? 0} concepts`],
                ["curriculum", "Plan curriculum", "Order goals and prerequisites"],
                ["resources", "Lessons & questions", `${savedCounts?.lessons ?? 0} lessons · ${savedCounts?.questions ?? 0} questions`],
                ["publish", "Save generated materials", "Ready for Tutor and tests"],
              ] as ["upload" | "extract" | "chunk" | "embedding" | "concepts" | "curriculum" | "resources" | "publish", string, string][]).map(([stage, label, detail], index) => {
                const state = stageState(stage);
                return <li key={stage} className={`expert-pipeline-stage ${state}`}>
                  <span className="expert-stage-marker">{state === "done" ? "✓" : state === "running" ? <span className="expert-spinner" /> : state === "attention" ? "!" : index + 1}</span>
                  <strong>{label}</strong><small>{!inspection && index >= 2 ? "Snapshot unavailable" : state === "running" ? liveStepLabel : state === "attention" ? stage === "publish" && hasWarnings ? "Not published" : stage === "resources" && warningCount ? `${warningCount} need review` : "Needs review" : state === "pending" ? active ? "Queued" : "Not completed" : detail}</small>
                </li>;
              })}
            </ol>
            <div className="expert-metrics">
              <div><span>Elapsed</span><strong>{formatElapsed(elapsedSeconds)}</strong></div>
              <div><span>Chunks saved</span><strong>{savedCounts ? chunks : "—"}</strong></div>
              <div><span>Embeddings saved</span><strong>{savedCounts ? embedded : "—"}{chunks ? ` / ${chunks}` : ""}</strong></div>
              <div><span>Concepts</span><strong>{savedCounts?.concepts ?? "—"}</strong></div>
              <div><span>Completed model API calls</span><strong>{currentRun?.expertUsage ? currentRun.expertUsage.reportedCalls + currentRun.expertUsage.unreportedCalls : "—"}</strong></div>
              <div><span>Reported model cost (USD)</span><strong>{currentRun?.expertUsage && (currentRun.expertUsage.reportedCalls > 0 || (!currentRun.expertUsage.unreportedCalls && !currentRun.expertUsage.priorUsageUnknown)) ? formatCost(currentRun.expertUsage.reportedCostUsd) : "—"}</strong></div>
            </div>
            <p className="expert-usage-note">{!currentRun ? "Select a run to view its provider-reported model cost." : !currentRun.expertUsage ? "Model calls and cost were not recorded for this run." : currentRun.expertUsage.unreportedCalls || currentRun.expertUsage.priorUsageUnknown ? "Partial total: some request costs or earlier attempts were not reported. Local embeddings are excluded." : "Completed model requests and provider-reported cost; in-flight requests are not yet included. Local embeddings are excluded."}</p>
            {latestStep?.detail && active && <p className="expert-current-step" role="status">Current Expert step: {latestStep.detail}</p>}
            </>}
          </section>

          <ExpertTutorHandoffs courseId={ws.courseId} concepts={ws.course?.graph.concepts || []} />

          {ws.course && !selectedPseudoRun && <ExpertHierarchyReview key={ws.courseId + displayedHierarchyId} course={ws.course} runId={displayedHierarchyId} preview={!currentRun} active={Boolean(currentRun && isWorking(currentRun.status))} source={hierarchySources.find(item => item.runId === displayedHierarchyId)} onPublished={async () => { setPublishRevision(value => value + 1); await ws.refresh(); }} />}
          <section className="expert-card expert-activity-panel" aria-labelledby="expert-activity-title">
            <div className="expert-card-heading"><div><h2 id="expert-activity-title">Expert activity log</h2><p>{selectedPseudoRun ? `${selectedPseudoRun.phase || selectedPseudoRun.message || "Pseudo-student preparation"} · see live session progress above.` : currentRun ? runDetail?.summary || currentRun.summary : "Activity from Expert runs will appear here."}</p></div>{selectedPseudoRun ? <span className={`expert-status-tag ${selectedPseudoRun.status}`}>{readable(selectedPseudoRun.status)}</span> : currentRun && <span className={`expert-status-tag ${hasWarnings && runStatus === "completed" ? "needs_review" : runDetail?.status || currentRun.status}`}>{runLabel}</span>}</div>
            {selectedPseudoRun ? <div className="expert-activity-meta"><span>Pseudo test <code>{selectedPseudoRun.id}</code></span><span>Material: {selectedPseudoRun.material}</span><span>Phase: {selectedPseudoRun.phase || readable(selectedPseudoRun.status)}</span></div> : currentRun ? <div className="expert-activity-meta"><span>Run <code>{currentRun.id}</code></span><span>Template: {currentRun.templateName || "Agent default"}</span>{currentRun.model && <span>Model: {currentRun.model}</span>}{currentRun.temperature != null && <span>Temperature: {currentRun.temperature}</span>}{runDetail?.currentAgent && <span>Active agent: {readable(runDetail.currentAgent)}</span>}<span>{runDetail?.events?.length || 0} events</span></div> : <div className="expert-activity-meta"><span>Material: {selectedDocument?.filename || "No material selected"}</span><span>No run record yet</span></div>}
            <div className="expert-activity-log" ref={activityLogRef} aria-live="polite" aria-relevant="additions text">
              {selectedPseudoRun ? <p className="expert-activity-empty" role="status">Pseudo-student preparation is a separate evaluation session. Its current phase and learner progress are shown in the progress panel above.</p> : currentRun && runDetail?.events?.length ? (showAllActivity ? runDetail.events : runDetail.events.slice(-12)).map((event, index) => {
                const status = activityEventStatus(event, runStatus);
                const tone = eventTone(event, status);
                return <article className={`expert-activity-event ${tone}`} key={`${event.sequence ?? index}-${event.type}`}>
                <span className="expert-activity-marker" aria-hidden="true">{event === latestRunningActivity ? <span className="expert-spinner" /> : tone === "complete" ? "✓" : tone === "attention" ? "!" : "·"}</span>
                <time dateTime={event.at}>{eventTime(event.at)}</time>
                <div className="expert-activity-copy"><strong>{eventTitle(event)}</strong>{eventDescription(event) && <p>{eventDescription(event)}</p>}{eventText(event, "tool") && <small>Operation: {readable(eventText(event, "tool"))}</small>}</div>
                {status && <span className={`expert-activity-state ${tone}`}>{readable(status)}</span>}
              </article>}) : <p className="expert-activity-empty" role="status">{!currentRun ? "Run a selected material to start recording Expert activity here." : isWorking(runDetail?.status || currentRun.status) ? "Waiting for the worker to emit its first activity event…" : "No activity events were recorded for this run."}</p>}
            </div>
            {currentRun && (runDetail?.events?.length || 0) > 12 && <button type="button" className="expert-text-button expert-activity-toggle" onClick={() => setShowAllActivity((value) => !value)}>{showAllActivity ? "Show recent events" : `Show all ${runDetail?.events?.length} events`}</button>}
          </section>

        </section>

        <section className="expert-card expert-inspector" aria-labelledby="expert-inspector-title">
          <div className="expert-card-heading"><div><h2 id="expert-inspector-title">Database inspector</h2><p>{inspection?.inspectionMode === "live" ? "Current saved records while this run is active." : "Records saved when the selected run stopped or finished."}</p></div><span className="expert-readonly-tag">Read only</span></div>
          <div className="expert-inspector-run-select"><label htmlFor="expert-inspection-run">Run or test session</label><select id="expert-inspection-run" value={pseudoRunId ? `pseudo:${pseudoRunId}` : currentRun?.id || ""} onChange={(event) => event.target.value.startsWith("pseudo:") ? selectPseudoSession(event.target.value.slice(7)) : selectSession(event.target.value)} disabled={!materialRuns.length && !coursePseudoRuns.length}><option value="">Select a previous run</option>{materialRuns.length > 0 && <optgroup label="Workbench Expert runs">{materialRuns.map((run) => <option value={run.id} key={run.id} title={run.id}>{run.startedAt ? new Date(run.startedAt).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "Run"} · {readable(run.status)} · {run.id.slice(0, 8)}</option>)}</optgroup>}{coursePseudoRuns.length > 0 && <optgroup label="Pseudo-student test sessions">{coursePseudoRuns.map((run) => <option value={`pseudo:${run.id}`} key={`pseudo:${run.id}`} title={run.id}>{new Date(run.createdAt).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} · {run.material} · {run.phase || readable(run.status)} · {run.id.slice(0, 8)}</option>)}</optgroup>}</select></div>
          <div className="expert-inspector-notice"><span aria-hidden="true">ⓘ</span> {selectedPseudoRun ? "Pseudo-test status and learner progress appear in the ingestion panel; the test uses frozen evaluation artifacts rather than Workbench database records." : inspection?.inspectionScope === "changes" ? "Source chunks and embeddings include reused records. Concepts, lessons and questions show changes during this run. Updates load automatically." : inspection?.inspectionMode === "live" ? "Live records may include work retained from earlier runs." : "A snapshot may include work retained from earlier runs."} Vector values are never exposed.</div>
          {inspectionError && <p className="expert-muted" role="status">{inspectionError}</p>}
          <div className="expert-tabs" role="tablist" aria-label="Database record type">
            {tabs.map((tab) => <button type="button" role="tab" aria-selected={inspectorView === "records" && kind === tab.id} key={tab.id} onClick={() => { setInspectorView("records"); selectKind(tab.id); }}>{tab.label}<span>{counts?.[tab.id] ?? "—"}</span></button>)}
            <button type="button" role="tab" aria-selected={inspectorView === "graph"} onClick={() => { setInspectorView("graph"); setQuery(""); setOffset(0); }}>Concept map<span>{counts?.concepts ?? "—"}</span></button>
          </div>
          <div className="expert-inspector-controls"><label className="expert-search"><span aria-hidden="true">⌕</span><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={inspectorView === "graph" ? "Search concepts" : "Search current page"} /></label><button type="button" className="expert-button secondary" onClick={() => { void refreshInspection(); void ws.refresh(); }}>↻ Refresh</button></div>
          {inspectorView === "graph" ? <>
            <div className="expert-map-summary"><strong>{allConceptNodes.length} concepts · {conceptMapLayout.lessonCount} lessons</strong><span>{conceptMapLayout.totalEdges} shared-source links</span><span>Select a concept or lesson to inspect its saved relationships</span></div>
            {graphError ? <p className="expert-alert" role="alert">{graphError}</p> : !activeDocumentId || !currentRun || !inspection ? <p className="expert-muted expert-inspector-empty">{startingRuns || pendingForDocument ? "Starting the new run…" : "Select a run with a saved snapshot to view its concept map."}</p> : graphLoading && (conceptMap?.documentId !== activeDocumentId || conceptMap?.runId !== currentRun.id) ? <p className="expert-muted expert-inspector-empty" role="status">Loading concept map…</p> : !allConceptNodes.length ? <p className="expert-muted expert-inspector-empty">{inspection.inspectionScope === "changes" ? "No new or changed concepts yet." : "No concepts are saved in this snapshot."}</p> : !graphNodes.length ? <p className="expert-muted expert-inspector-empty">No concepts match this search.</p> : <>
              <div className="expert-map-legend"><span><i className="source" /> Concept</span><span><i className="lesson" /> Lesson</span><span><i className="question" /> Has questions</span><span>Lines connect lessons and shared sources</span></div>
              <div className="expert-map-zoom" role="group" aria-label="Concept map zoom">
                <button type="button" aria-label="Zoom out" disabled={mapZoom <= 100} onClick={() => setMapZoom(value => Math.max(100, value - 25))}>−</button>
                <output aria-live="polite" aria-label="Map zoom level">{mapZoom}%</output>
                <button type="button" aria-label="Zoom in" disabled={mapZoom >= 400} onClick={() => setMapZoom(value => Math.min(400, value + 25))}>+</button>
                <button type="button" disabled={mapZoom === 100} onClick={() => setMapZoom(100)}>Reset</button>
                <span>Scroll to zoom · drag to pan</span>
              </div>
              <div ref={mapScrollRef} className={`expert-concept-map-scroll${mapZoom > 100 ? " can-pan" : ""}${mapDragging ? " is-panning" : ""}`} role="region" aria-label="Scrollable concept map" tabIndex={0}
                onPointerDown={event => {
                  if (event.button !== 0 || event.target === event.currentTarget) return;
                  suppressMapClick.current = false;
                  mapDragRef.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, left: event.currentTarget.scrollLeft, top: event.currentTarget.scrollTop, moved: false };
                }}
                onPointerMove={event => {
                  const drag = mapDragRef.current;
                  if (!drag || drag.pointerId !== event.pointerId) return;
                  const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
                  if (!drag.moved && Math.hypot(dx, dy) < 5) return;
                  if (!drag.moved) { drag.moved = true; suppressMapClick.current = true; event.currentTarget.setPointerCapture(event.pointerId); setMapDragging(true); }
                  event.currentTarget.scrollLeft = drag.left - dx;
                  event.currentTarget.scrollTop = drag.top - dy;
                }}
                onPointerUp={event => { if (mapDragRef.current?.pointerId === event.pointerId) { mapDragRef.current = null; setMapDragging(false); } }}
                onPointerCancel={() => { mapDragRef.current = null; setMapDragging(false); }}
                onClickCapture={event => { if (suppressMapClick.current) { event.preventDefault(); event.stopPropagation(); suppressMapClick.current = false; } }}>
                <svg className="expert-concept-map" style={{ width: `${mapZoom}%` }} viewBox="0 0 960 660" role="img" aria-label={`Concept map with ${graphNodes.length} concepts, ${conceptMapLayout.lessonCount} lessons, and ${conceptMapLayout.totalEdges} shared-source links`}>
                  <g className="expert-concept-map-edges">{conceptMapLayout.edges.map((edge) => {
                    const from = conceptMapLayout.positions.find((position) => position.node.id === edge.from);
                    const to = conceptMapLayout.positions.find((position) => position.node.id === edge.to);
                    return from && to ? <line key={`${edge.from}-${edge.to}`} x1={from.x} y1={from.y} x2={to.x} y2={to.y} strokeWidth={Math.min(3, 1 + edge.weight * 0.35)}><title>{edge.weight} shared source passage{edge.weight === 1 ? "" : "s"}</title></line> : null;
                  })}</g>
                  {conceptMapLayout.positions.map(({ node, x, y }) => {
                    const radius = Math.min(22, 10 + Math.sqrt(node.sourceChunkIds.length + node.lessonCount + node.questionCount) * 2);
                    return <g className="expert-concept-map-item" key={node.id}>
                      <g className={`expert-concept-map-node concept ${node.lessonCount ? "has-lesson" : ""} ${node.questionCount ? "has-questions" : ""}`} role="button" tabIndex={0} aria-label={`${node.title} concept. ${node.sourceChunkIds.length} source passages, ${node.lessonCount} lessons, ${node.questionCount} questions.`} onClick={() => void openRelationship(node.id, "concepts")} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); void openRelationship(node.id, "concepts"); } }}>
                      <title>{node.title} concept · {node.sourceChunkIds.length} source passages · {node.lessonCount} lessons · {node.questionCount} questions</title>
                      <circle cx={x} cy={y} r={radius} />
                      <text x={x} y={y + radius + 13} textAnchor="middle">{node.title.length > 22 ? `${node.title.slice(0, 21)}…` : node.title}</text>
                    </g>
                    {node.lesson && <g className="expert-concept-map-lesson">
                      <line className="expert-concept-map-lesson-edge" x1={x} y1={y + 25} x2={x} y2={y + 54} />
                      <g className="expert-concept-map-node lesson" role="button" tabIndex={0} aria-label={`Lesson: ${node.lesson.title}. Objective: ${node.lesson.objective}`} onClick={() => void openRelationship(node.lesson!.id, "lessons")} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); void openRelationship(node.lesson!.id, "lessons"); } }}>
                      <title>{node.lesson.title} · {node.lesson.objective}</title>
                      <rect x={x - 82} y={y + 56} width="164" height="38" rx="7" />
                      <text x={x} y={y + 72} textAnchor="middle">LESSON</text>
                      <text className="expert-concept-map-lesson-title" x={x} y={y + 86} textAnchor="middle">{node.lesson.title.length > 25 ? `${node.lesson.title.slice(0, 24)}…` : node.lesson.title}</text>
                      </g>
                    </g>}
                    </g>;
                  })}
                </svg>
              </div>
              {matchingConceptNodes.length > graphNodes.length && <p className="expert-map-limit">Showing {graphNodes.length} of {matchingConceptNodes.length} matching concepts. Search to narrow the map; use the Concepts table for the full list.</p>}
            </>}
          </> : <>
          <div className="expert-record-table-wrap">
            {!activeDocumentId || !currentRun || !inspection ? <p className="expert-muted expert-inspector-empty">{startingRuns || pendingForDocument ? "Starting the new run…" : "Select a run with a saved snapshot to inspect its records."}</p> : <table className={`expert-record-table ${kind === "source_chunks" ? "expert-chunk-record-table" : ""}`}>
              <thead><tr>{kind === "source_chunks" ? <><th>Page</th><th>Passage preview</th><th>Embedding</th></> : kind === "concepts" ? <><th>Concept</th><th>Summary</th><th>Sources</th></> : kind === "lessons" ? <><th>Lesson</th><th>Objective</th><th>Version</th></> : kind === "questions" ? <><th>Question</th><th>Difficulty</th><th>Format</th></> : <><th>Page</th><th>Model</th><th>Dimensions</th></>}</tr></thead>
              <tbody>{filteredRows.map((row) => {
                const isSelected = String(row.id) === selectedRowId;
                const rowId = String(row.id);
                return <tr key={rowId} className={isSelected ? "selected" : ""} onClick={() => void openRelationship(rowId, kind)}>
                  {kind === "source_chunks" && <><td>{String(row.page)}</td><td className="expert-prompt-cell">{itemText(row, "text")}</td><td><span className={`expert-status-tag ${row.embedding ? "published" : "queued"}`}>{row.embedding ? "Stored" : "Pending"}</span></td></>}
                  {kind === "concepts" && <><td>{itemText(row, "title")}</td><td className="expert-prompt-cell">{itemText(row, "summary")}</td><td>{String(row.sourceCount ?? 0)}</td></>}
                  {kind === "lessons" && <><td>{itemText(row, "title")}</td><td className="expert-prompt-cell">{itemText(row, "objective")}</td><td>{String(row.version ?? "—")}</td></>}
                  {kind === "questions" && <><td className="expert-prompt-cell">{itemText(row, "prompt")}</td><td>{readable(itemText(row, "difficulty"))}</td><td>{readable(itemText(row, "format"))}</td></>}
                  {kind === "embeddings" && <><td>{String(row.page)}</td><td>{itemText(row, "model")}</td><td><span className="expert-status-tag published">{String(row.dimensions)} dim</span></td></>}
                </tr>;
              })}</tbody>
            </table>}
            {inspection && !filteredRows.length && <p className="expert-muted expert-inspector-empty">{query ? "No records on this page match your search." : inspection.inspectionScope === "changes" && kind !== "source_chunks" && kind !== "embeddings" ? "No new or changed records yet." : "No records are stored for this tab in this snapshot."}</p>}
          </div>
          {inspection && <div className="expert-inspector-footer"><span>Showing {inspection.total ? `${offset + 1}–${pageEnd}` : "0"} of {inspection.total} {readable(kind)}</span><div><button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - inspection.limit))} aria-label="Previous records">‹</button><button type="button" disabled={pageEnd >= inspection.total} onClick={() => setOffset(offset + inspection.limit)} aria-label="Next records">›</button></div></div>}
          </>}
          {inspection?.document.coverage && <details className="expert-coverage"><summary>Preparation coverage</summary><p>{inspection.document.coverage.processedPassages ?? 0} of {inspection.document.coverage.totalPassages ?? 0} passages reviewed across {inspection.document.coverage.totalSections ?? 0} sections.</p></details>}
          {Boolean(inspection?.document.missingTextPages?.length) && <p className="expert-alert" role="status">No text was extracted from PDF page{inspection!.document.missingTextPages!.length === 1 ? "" : "s"} {inspection!.document.missingTextPages!.join(", ")}. They may be blank or image-based; image-only content is not included because OCR is not available.</p>}
          {!!inspection?.document.coverage?.mergedConceptCount && <p className="expert-muted">{inspection.document.coverage.mergedConceptCount} concepts from this material were merged with existing concepts in other course materials. Inspect those materials to see their records.</p>}
        </section>
      </div>}
      {relationshipOpen && <dialog ref={relationshipDialog} className={`expert-relationship-dialog ${relationship?.pageContent ? "with-source-page" : ""}`} aria-labelledby="expert-relationship-title" onCancel={() => setRelationshipOpen(false)} onClick={(event) => { if (event.target === event.currentTarget) setRelationshipOpen(false); }}>
        <header className="expert-relationship-header"><div><p className="expert-eyebrow">DATABASE RELATIONSHIPS</p><h2 id="expert-relationship-title">{relationship?.selected.title || "Loading record relationships…"}</h2>{relationship && <p><span className="expert-status-tag indexed">{readable(relationship.selected.kind)}</span><span className="expert-relationship-id">{relationship.selected.id}</span></p>}</div><button type="button" className="expert-dialog-close" aria-label="Close relationship view" onClick={() => setRelationshipOpen(false)}>×</button></header>
        {relationship?.preview && (relationship.selected.kind === "lessons" || relationship.selected.kind === "questions") && <InspectorPreview kind={relationship.selected.kind} content={relationship.preview} />}
        <p className="expert-relationship-intro">Follow the stored provenance from source passages to concepts and the lessons or questions built for each concept. Click a related record to open its relationship view.</p>
        {relationship?.selected.kind === "source_chunks" && relationship.pageContent && <section className="expert-source-page-content" aria-label={`Extracted content from page ${relationship.pageContent.page}`}>
          <header><div><h3>Page content</h3><span>Page {relationship.pageContent.page} · {relationship.pageContent.chunks.length} passage{relationship.pageContent.chunks.length === 1 ? "" : "s"}</span></div><span className="expert-readonly-tag">Read only</span></header>
          <div className="expert-source-page-text">{relationship.pageContent.chunks.map((chunk) => <article key={chunk.id}><small>Passage {chunk.ordinal}</small><p>{chunk.text}</p></article>)}</div>
        </section>}
        {relationshipBusy ? <p className="expert-relationship-loading" role="status">Loading linked records…</p> : relationshipError ? <p className="expert-alert" role="alert">{relationshipError}</p> : relationship && <div className="expert-relationship-flow">
          <section className="expert-relationship-column"><header><span>01</span><div><h3>Source chunks</h3><small>{relationship.sourceChunks.length} connected</small></div></header>
            {relationship.sourceChunks.length ? relationship.sourceChunks.map((chunk) => <button type="button" className={`expert-relationship-node ${relationship.selected.id === chunk.id && ["source_chunks", "embeddings"].includes(relationship.selected.kind) ? "focused" : ""}`} key={chunk.id} onClick={() => void openRelationship(chunk.id, "source_chunks")}><strong>{chunk.id}</strong><span>Page {chunk.page} · passage {chunk.ordinal}{chunk.embedded ? " · embedded" : ""}</span><p>{chunk.text.slice(0, 155)}{chunk.text.length > 155 ? "…" : ""}</p></button>) : <p className="expert-relationship-empty">No source chunk links were saved for this record.</p>}
          </section>
          <div className="expert-relationship-connector"><span>Cited by</span><b aria-hidden="true">→</b></div>
          <section className="expert-relationship-column"><header><span>02</span><div><h3>Concepts</h3><small>{relationship.concepts.length} connected</small></div></header>
            {relationship.concepts.length ? relationship.concepts.map((concept) => <button type="button" className={`expert-relationship-node ${relationship.selected.id === concept.id ? "focused" : ""}`} key={concept.id} onClick={() => void openRelationship(concept.id, "concepts")}><strong>{concept.title}</strong><span>{concept.sourceChunkIds.length} directly cited source{concept.sourceChunkIds.length === 1 ? "" : "s"}</span><p>{concept.summary}</p></button>) : <p className="expert-relationship-empty">No concept cites this source chunk yet.</p>}
          </section>
          <div className="expert-relationship-connector"><span>Produces</span><b aria-hidden="true">→</b></div>
          <section className="expert-relationship-column expert-output-column"><header><span>03</span><div><h3>Learning records</h3><small>{relationship.lessons.length} lessons · {relationship.questions.length} questions</small></div></header>
            {relationship.lessons.map((lesson) => <button type="button" className={`expert-relationship-node asset ${relationship.selected.id === lesson.id ? "focused" : ""}`} key={lesson.id} onClick={() => void openRelationship(lesson.id, "lessons")}><span className="expert-asset-kind">LESSON</span><strong>{lesson.title}</strong><span>Concept: {relationship.concepts.find((concept) => concept.id === lesson.conceptId)?.title || lesson.conceptId}</span><p>{lesson.objective}</p><small>Sources: {lesson.sourceChunkIds.map((id) => id.slice(0, 8)).join(", ") || "none recorded"}</small></button>)}
            {relationship.questions.map((question) => <button type="button" className={`expert-relationship-node asset question ${relationship.selected.id === question.id ? "focused" : ""}`} key={question.id} onClick={() => void openRelationship(question.id, "questions")}><span className="expert-asset-kind">QUESTION · {readable(question.difficulty)}</span><strong>{question.prompt}</strong><span>Concept: {relationship.concepts.find((concept) => concept.id === question.conceptId)?.title || question.conceptId}</span><small>Format: {readable(question.format)} · Sources: {question.sourceChunkIds.map((id) => id.slice(0, 8)).join(", ") || "none recorded"}</small></button>)}
            {!relationship.lessons.length && !relationship.questions.length && <p className="expert-relationship-empty">No lessons or questions are saved for the linked concepts yet.</p>}
          </section>
        </div>}
        <footer className="expert-relationship-footer"><span>Read-only view · source links come from saved citations; learning records belong to their concept.</span><button type="button" className="expert-button secondary" onClick={() => setRelationshipOpen(false)}>Close</button></footer>
      </dialog>}
      <footer className="expert-footer"><span>LearnLoop · Expert developer tools</span><Link href="/materials">Manage course materials →</Link></footer>
  </ExpertWorkbenchShell>;
}
