"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { CourseMaterialPicker, type MaterialTab } from "@/components/course-material-picker";
import { api, uploadCourseFile, type Course, type CourseDetail } from "@/lib/backend";
import { loadSharedTemplates, type AgentPromptTemplate, type WorkbenchAgent } from "@/lib/expert-templates";
import { PseudoLearnerDialog, type PseudoLearner } from "@/components/pseudo-learner-dialog";
import { PseudoLearnerProgress, type LearnerProgress } from "@/components/pseudo-learner-progress";

type Setup = { id: string; availableSimulators?: string[]; course: { title: string }; material: { id: string; filename: string; documentCount?: number }; release: { id: string; version: number } };
type WorkbenchGeneratedRun = { runId: string; createdAt: string; filenames: string[]; documents: { id: string; filename: string }[]; revision: number; ready: boolean; published: boolean; releaseId?: string | null };
type PseudoRun = {
  id: string;
  setupId: string;
  createdAt: string;
  course: string;
  material: string;
  materialId: string;
  releaseId: string;
  releaseVersion?: number;
  workbenchRevision?: number | null;
  materialSource?: "published" | "workbench_generated" | "combined" | "legacy";
  workbenchRunId?: string | null;
  preparedAvailable: boolean;
  status: string;
  phase?: string;
  message?: string;
  errorType?: string;
  progress: LearnerProgress[];
  config: { concepts: number; activities: number; baselines: boolean; sourceRunId?: string | null; simulator?: "controlled" | "belief" };
  report: null | {
    conceptCount: number;
    completed: number;
    failedOrStopped: number;
    scopeWarnings: string[];
    preparationUsage: { calls: number; costUsd: number | null; usageComplete?: boolean };
    episodes: { learnerName: string; baseline: string; status: string; errorType: string | null; profileControlValid?: boolean; metrics?: { preScore: number; postScore: number; gain: number; calls: number; costUsd: number | null; simulationPolicyAgreement: number | null } }[];
  };
};

const agentRoles: { id: WorkbenchAgent; label: string }[] = [
  { id: "expert", label: "Expert" },
  { id: "tutor", label: "Tutor" },
  { id: "assessing", label: "Assessing" },
];

export default function PseudoStudentPage() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [courseId, setCourseId] = useState("");
  const [course, setCourse] = useState<CourseDetail | null>(null);
  const [workbenchRuns, setWorkbenchRuns] = useState<WorkbenchGeneratedRun[]>([]);
  const [workbenchRunId, setWorkbenchRunId] = useState("");
  const [sourceDocumentId, setSourceDocumentId] = useState("all");
  const [sourceTab, setSourceTab] = useState<MaterialTab>("upload");
  const [files, setFiles] = useState<File[]>([]);
  const [materialMode, setMaterialMode] = useState<"new" | "previous">("new");
  const courseSeenRef = useRef("");
  const workbenchRunIdRef = useRef(workbenchRunId);
  workbenchRunIdRef.current = workbenchRunId;
  const [templates, setTemplates] = useState<AgentPromptTemplate[]>([]);
  const [selected, setSelected] = useState({ expert: "", tutor: "", assessing: "" });
  const [learners, setLearners] = useState<PseudoLearner[]>([]);
  const [selectedLearners, setSelectedLearners] = useState<string[]>(["novice", "intermediate", "misconception_prone", "hint_dependent"]);
  const [learnerDialog, setLearnerDialog] = useState(false);
  const [runs, setRuns] = useState<PseudoRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [sourceRun, setSourceRun] = useState("");
  const [concepts, setConcepts] = useState(1);
  const [activities, setActivities] = useState(2);
  const [simulator, setSimulator] = useState("controlled");
  const [running, setRunning] = useState(false);
  const [retrying, setRetrying] = useState("");
  const [stopping, setStopping] = useState("");
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [courseList, savedTemplates, savedLearners] = await Promise.all([
        api<Course[]>("courses"),
        loadSharedTemplates(),
        api<PseudoLearner[]>("evaluations/learners"),
      ]);
      setLearners(savedLearners);
      setCourses(courseList);
      setTemplates(savedTemplates);
      setCourseId((current) => courseList.some((item) => item.id === current) ? current : courseList[0]?.id || "");
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load your workspace.");
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshRuns = useCallback(async () => {
    try {
      const next = (await api<PseudoRun[]>("evaluations/pseudo-runs")).sort((a, b) => b.createdAt.localeCompare(a.createdAt));
      setRuns(next);
      setSelectedRunId((current) => next.some((run) => run.id === current) ? current : next[0]?.id || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load test runs.");
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(timer);
  }, [refresh]);

  useEffect(() => {
    const initial = window.setTimeout(() => void refreshRuns(), 0);
    const timer = window.setInterval(() => void refreshRuns(), 7000);
    return () => { window.clearTimeout(initial); window.clearInterval(timer); };
  }, [refreshRuns]);

  useEffect(() => {
    if (!courses.some((item) => item.id === courseId)) return;
    let cancelled = false;
    Promise.all([
      api<CourseDetail>(`courses/${encodeURIComponent(courseId)}`),
      api<WorkbenchGeneratedRun[]>(`courses/${encodeURIComponent(courseId)}/hierarchy-runs`),
    ]).then(([item, generatedRuns]) => {
      if (!cancelled) {
        setCourse(item);
        const readyRuns = generatedRuns.filter((run) => run.ready && run.documents.length > 0);
        setWorkbenchRuns(generatedRuns);
        setSourceDocumentId((current) => item.documents.some((doc) => doc.id === current) ? current : "all");
        if (courseSeenRef.current !== courseId) {
          courseSeenRef.current = courseId;
          setMaterialMode(readyRuns.length ? "previous" : "new");
        }
        const kept = readyRuns.find((run) => run.runId === workbenchRunIdRef.current);
        const chosen = kept ?? readyRuns[0];
        setWorkbenchRunId(chosen?.runId ?? "");
        if (!kept) {
          setSourceRun("");
          if (chosen) setConcepts((current) => Math.max(current, Math.min(20, chosen.documents.length)));
        }
      }
    }).catch((err: Error) => {
      if (!cancelled) { setCourse(null); setError(err.message); }
    });
    return () => { cancelled = true; };
  }, [courseId, courses]);

  const availableWorkbenchRuns = workbenchRuns.filter((run) => run.ready && run.documents.length > 0);
  const selectedWorkbenchRun = materialMode === "previous" ? availableWorkbenchRuns.find((run) => run.runId === workbenchRunId) : undefined;
  const sourceMaterials = selectedWorkbenchRun?.documents || [];
  const sourceReleaseId = selectedWorkbenchRun
    ? `workbench:${selectedWorkbenchRun.runId}:${selectedWorkbenchRun.revision}`
    : "";
  const reusableRuns = runs.filter((run) =>
    run.materialSource === "workbench_generated" &&
    run.preparedAvailable && !!sourceReleaseId && run.releaseId === sourceReleaseId &&
    (run.materialId === "__all__" || (sourceMaterials.length === 1 && run.materialId === sourceMaterials[0].id)),
  );
  const preparation = reusableRuns.find((run) => run.id === sourceRun);
  const visibleRun = runs.find((run) => run.id === selectedRunId) ?? runs[0] ?? null;
  const documents = course?.documents ?? [];
  const selectedDocuments = sourceDocumentId === "all" ? documents : documents.filter((doc) => doc.id === sourceDocumentId);
  const newMaterialCount = sourceTab === "upload" ? files.length : selectedDocuments.length;
  const materialCount = materialMode === "new" ? newMaterialCount : sourceMaterials.length;
  const hasMaterial = materialMode === "new" ? !!course && newMaterialCount > 0 : !!selectedWorkbenchRun;
  const validConceptCount = Boolean(preparation) ||
    (Number.isInteger(concepts) && concepts >= Math.max(1, materialCount) && concepts <= 20);
  const effectiveConcepts = preparation?.report?.conceptCount ?? preparation?.config.concepts ?? (Number.isInteger(concepts) ? concepts : 1);
  const episodeCallLimit = Math.max(64, 7 * effectiveConcepts + 12 * (Number.isInteger(activities) ? activities : 2) + 16);

  function chooseMaterialMode(mode: "new" | "previous") {
    setMaterialMode(mode);
    setSourceRun("");
    if (mode === "new") {
      setConcepts((current) => Math.max(current, Math.min(20, newMaterialCount)));
    } else {
      const run = availableWorkbenchRuns.find((item) => item.runId === workbenchRunId);
      if (run) setConcepts((current) => Math.max(current, Math.min(20, run.documents.length)));
    }
  }

  const canStart = hasMaterial && validConceptCount && selectedLearners.length > 0 && selectedLearners.length <= 20 &&
    Number.isInteger(activities) && activities >= 2 && activities <= 12 && !running;

  async function startTest(event: React.FormEvent) {
    event.preventDefault();
    if (!canStart) return;
    setRunning(true);
    setError("");
    setMessage("");
    try {
      const selection = {
        courseId,
        expertTemplateId: selected.expert || null,
        tutorTemplateId: selected.tutor || null,
        assessingTemplateId: selected.assessing || null,
        learnerProfileIds: selectedLearners,
      };
      let started: PseudoRun;
      if (materialMode === "new") {
        const documentIds = sourceTab === "existing" ? selectedDocuments.map((doc) => doc.id) : [];
        if (sourceTab === "upload") {
          for (const file of files) {
            setMessage(`Uploading ${file.name}…`);
            documentIds.push((await uploadCourseFile(courseId, file)).documentId);
          }
        }
        started = await api<PseudoRun>("evaluations/pseudo-runs/from-files", {
          ...selection, documentIds, concepts, activities, simulator,
        });
      } else {
        const setup = await api<Setup>("evaluations/setups", {
          ...selection, documentId: preparation?.materialId ?? "__all__", workbenchRunId,
        });
        if (simulator === "belief" && !setup.availableSimulators?.includes("belief")) {
          throw new Error("Restart the local LearnLoop API to load the belief-based pilot.");
        }
        started = await api<PseudoRun>("evaluations/pseudo-runs", {
          setupId: setup.id, concepts: preparation?.config.concepts ?? concepts,
          activities, simulator, baselines: false, sourceRunId: preparation?.id ?? null,
        });
      }
      setSelectedRunId(started.id);
      await Promise.all([refreshRuns(), refresh()]);
      setMessage("Test started. Progress will appear under Test runs.");
    } catch (err) {
      setMessage("");
      setError(err instanceof Error ? err.message : "Could not start the test.");
    } finally {
      setRunning(false);
    }
  }

  async function stopRun(runId: string) {
    if (stopping) return;
    if (!window.confirm("Stop this test? Learners that have not finished will stop where they are.")) return;
    setStopping(runId);
    setError("");
    setMessage("");
    try {
      await api(`evaluations/pseudo-runs/${encodeURIComponent(runId)}/stop`, {});
      await refreshRuns();
      setMessage("Test stopped. Finished learners are kept.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not stop the test.");
    } finally {
      setStopping("");
    }
  }

  async function retryLearner(runId: string, learnerId: string, condition: string) {
    if (retrying) return;
    setRetrying(`${learnerId}:${condition}`);
    setError("");
    setMessage("");
    try {
      await api(`evaluations/pseudo-runs/${encodeURIComponent(runId)}/retry`, { learnerId, condition });
      await refreshRuns();
      setMessage("Retry started. This learner is restarting from the beginning.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the retry.");
    } finally {
      setRetrying("");
    }
  }

  return <div className="expert-workbench pseudo-evaluation">
    <header className="expert-topbar">
      <Link href="/workbench/expert" className="expert-brand"><span className="expert-brand-mark" aria-hidden="true">◈</span> LearnLoop Agent Workbench</Link>
      <nav aria-label="Workbench navigation" className="expert-topnav">
        <Link href="/workbench/expert">Workbench</Link>
        <Link href="/workbench/evaluation" className="active" aria-current="page">Pseudo-student tests</Link>
        <Link href="/agents">Run history</Link>
        <Link href="/learn">Learning</Link>
      </nav>
      <span className="expert-env">Local workspace</span>
    </header>

    <main className="pseudo-evaluation-main">
      <div className="expert-page-heading">
        <div><p className="expert-eyebrow">WORKBENCH · SIMULATED LEARNERS</p><h1>Pseudo-student tests</h1><p className="expert-page-description">Choose course materials, agents, and learners for your test.</p></div>
        <button type="button" className="expert-button secondary" disabled={running} onClick={() => void refresh()}>Refresh workspace</button>
      </div>
      {error && <p className="expert-alert" role="alert">{error}</p>}
      {message && <p className="eval-ready" role="status">{message}</p>}

      <div className="eval-grid">
        <form className="expert-card eval-form" onSubmit={startTest}>
          <fieldset className="eval-test-fields" disabled={running}>
          <section>
            <h2>Course and material</h2>
            <p>Choose a course, then use new course material or a previous Workbench generation.</p>
            <label>Course<select value={courseId} disabled={loading || !courses.length} onChange={(e) => { setCourseId(e.target.value); setCourse(null); setSourceDocumentId("all"); setSourceTab("upload"); setFiles([]); setSourceRun(""); setWorkbenchRuns([]); setWorkbenchRunId(""); }}>
              <option value="">Select course</option>{courses.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
            </select></label>
            <div className="eval-material-choices" role="radiogroup" aria-label="Course material">
              <label className="eval-material-choice"><input type="radio" name="material-mode" checked={materialMode === "new"} onChange={() => chooseMaterialMode("new")} /><span><strong>New course material</strong><small>Start test generates materials from your files with the selected Expert template.</small></span></label>
              <label className="eval-material-choice"><input type="radio" name="material-mode" checked={materialMode === "previous"} onChange={() => chooseMaterialMode("previous")} /><span><strong>Previous course material</strong><small>Use all materials from a completed Workbench generation.</small></span></label>
            </div>
            {materialMode === "new" ? <>
              <CourseMaterialPicker
                documents={documents} selection={sourceDocumentId} tab={sourceTab} files={files} disabled={!course || running}
                onTabChange={(tab) => {
                  setSourceTab(tab);
                  setConcepts((current) => Math.max(current, Math.min(20, tab === "upload" ? files.length : selectedDocuments.length)));
                }}
                onFilesChange={(next) => {
                  setFiles(next);
                  setConcepts((current) => Math.max(current, Math.min(20, next.length)));
                }}
                onSelect={(id) => {
                  setSourceDocumentId(id);
                  if (id === "all") setConcepts((current) => Math.max(current, Math.min(20, documents.length)));
                }}
              />
            </> : <>
              {availableWorkbenchRuns.length > 0 && <label>Previous generation<select value={workbenchRunId} onChange={(event) => {
                const next = availableWorkbenchRuns.find((run) => run.runId === event.target.value);
                if (!next) return;
                setWorkbenchRunId(next.runId);
                setSourceRun("");
                setConcepts((current) => Math.max(current, Math.min(20, next.documents.length)));
              }}>
                {availableWorkbenchRuns.map((run) => <option key={run.runId} value={run.runId}>{run.filenames.join(", ") || "Workbench materials"} · rev {run.revision} · {run.runId.slice(0, 8)}</option>)}
              </select></label>}
              {course && !availableWorkbenchRuns.length && <p>No previous course material yet. Choose New course material to start a test from source files.</p>}
            </>}
          </section>

          <section>
            <h2>Workbench materials</h2>
            <p>The test loads these materials as the course release and studies them through the Tutor workbench. Each new test also prepares separate pre- and post-exams.</p>
            {reusableRuns.length > 0 && <>
              <label>Test materials<select value={preparation?.id ?? ""} onChange={(e) => setSourceRun(e.target.value)}>
                <option value="">Use the selected Workbench materials and create new exams</option>
                {reusableRuns.map((run) => <option key={run.id} value={run.id}>{new Date(run.createdAt).toLocaleString()} · {run.report?.conceptCount ?? run.config.concepts} concepts · {run.id.slice(0, 8)}</option>)}
              </select></label>
              {preparation
                ? <p>This repeats the practice questions and held-out exams from the selected test.</p>
                : <p>New pre- and post-exams are written from the selected materials. The pre-test finishes before practice activities are counted.</p>}
            </>}
            {!preparation && <>
              <div className="eval-fields-three eval-run-controls">
                <label>Maximum concepts<input type="number" min={Math.max(1, materialCount)} max="20" value={concepts} onChange={(e) => setConcepts(Number(e.target.value))} /></label>
              </div>
              {materialCount > 20 && <p role="alert">A test supports up to 20 materials. {materialMode === "previous" ? "Choose a smaller generation or start from new course material." : "Select fewer source files."}</p>}
            </>}
          </section>

          <section>
            <h2>Expert, Tutor, and Assessing</h2>
            <p>The Expert template is applied when this test asks the Workbench Expert to write a lesson or question, including Backend default. The Tutor template is sent with each activity. The Assessing template is the default for this test's session.</p>
            <div className="eval-fields-three">
              {agentRoles.map((role) => <label key={role.id}>{role.label}<select value={selected[role.id]} onChange={(e) => setSelected({ ...selected, [role.id]: e.target.value })}>
                <option value="">Backend default</option>{templates.filter((template) => template.agent === role.id).map((template) => <option key={template.id} value={template.id}>{template.name}</option>)}
              </select></label>)}
            </div>
            <p>Missing a template? Create it in <Link href="/workbench/expert/edit">Edit agent</Link>, then refresh this page.</p>
          </section>

          <section>
            <div className="eval-section-heading"><h2>Simulated learners</h2><button type="button" className="expert-button secondary" onClick={() => setLearnerDialog(true)}>+ Create learner</button></div>
            <p>Select the learners to include. Create a profile to set its model and behavior.</p>
            <div className="learner-profile-list">
              {learners.map((learner) => <label className="learner-profile-option" key={learner.id}>
                <input type="checkbox" checked={selectedLearners.includes(learner.id)} onChange={(e) => setSelectedLearners((current) => e.target.checked ? [...current, learner.id] : current.filter((id) => id !== learner.id))} />
                <span><strong>{learner.name}</strong><small>{learner.builtin ? "Built-in" : "Custom"} · Model: {learner.model === "configured" ? "Backend default" : learner.model} · Starting ability: {Math.round(learner.basic * 100)}% / {Math.round(learner.intermediate * 100)}% / {Math.round(learner.advanced * 100)}% (basic / intermediate / advanced)</small></span>
              </label>)}
            </div>
            {!selectedLearners.length && <p role="alert">Select at least one learner.</p>}
            {selectedLearners.length > 20 && <p role="alert">Select at most 20 learners per test.</p>}
          </section>

          <section>
            <h2>Test options</h2>
            <div className="eval-fields-three eval-run-controls">
              <label>Student simulator<select value={simulator} onChange={(e) => setSimulator(e.target.value)}>
                <option value="controlled">Controlled answers</option>
                <option value="belief">Belief-based pilot</option>
              </select></label>
              <label>Activities per learner<input type="number" min="2" max="12" value={activities} onChange={(e) => setActivities(Number(e.target.value))} /></label>
            </div>
            <p>{selectedLearners.length} learners, one workbench session each. {!preparation && "Limit: 80 preparation calls per concept. "}Limit: {episodeCallLimit} calls per episode. Model calls may incur charges.</p>
            <p>Counts are simulated learning activities, not mouse clicks. Prerequisites outside the prepared subset are omitted.</p>
            <button type="submit" className="expert-button primary eval-start" disabled={!canStart}>
              {running ? "Starting test…" : "Start test"}
            </button>
          </section>
          </fieldset>
        </form>

        <div className="eval-side">
          <section className="expert-card eval-panel">
            <h2>Test runs</h2>
            {visibleRun ? <>
              <label className="eval-run-picker">Choose a run<select value={visibleRun.id} onChange={(event) => setSelectedRunId(event.target.value)}>
                {runs.map((run) => <option key={run.id} value={run.id}>{new Date(run.createdAt).toLocaleString()} · {run.course} · {run.material} · {run.status.replaceAll("_", " ")} · {run.id.slice(0, 8)}</option>)}
              </select></label>
              <article className="eval-saved" key={visibleRun.id}>
              <strong>{visibleRun.course} · {visibleRun.material}</strong>
              <p>Student simulator · {visibleRun.config.simulator === "belief" ? "Belief-based pilot" : "Controlled answers"}</p>
              {visibleRun.releaseVersion && visibleRun.materialSource === "published" && <p>Published course version {visibleRun.releaseVersion} · Workbench materials</p>}
              {visibleRun.materialSource === "combined" && <p>Published course version {visibleRun.releaseVersion} + Workbench run {visibleRun.workbenchRunId?.slice(0, 8) || "unknown"}{visibleRun.workbenchRevision != null ? ` · revision ${visibleRun.workbenchRevision}` : ""}</p>}
              {visibleRun.materialSource === "workbench_generated" && <p>Workbench generation {visibleRun.workbenchRunId?.slice(0, 8) || "unknown"}{visibleRun.releaseVersion != null && ` · revision ${visibleRun.releaseVersion}`}</p>}
              <p>{new Date(visibleRun.createdAt).toLocaleString()} · {visibleRun.status.replaceAll("_", " ")} {visibleRun.phase ? `· ${visibleRun.phase}` : ""}</p>
              {(visibleRun.status === "starting" || visibleRun.status === "running") && <button type="button" className="expert-button secondary" disabled={stopping === visibleRun.id} onClick={() => void stopRun(visibleRun.id)}>{stopping === visibleRun.id ? "Stopping…" : "Stop test"}</button>}
              {visibleRun.config.sourceRunId && <p>Reused materials from test {visibleRun.config.sourceRunId.slice(0, 8)}; original preparation costs are not included below.</p>}
              {visibleRun.message && <p role="alert">{visibleRun.message} {visibleRun.errorType && `(${visibleRun.errorType})`}</p>}
              <PseudoLearnerProgress episodes={visibleRun.progress || []} retrying={retrying} onRetry={(learnerId, condition) => void retryLearner(visibleRun.id, learnerId, condition)} />
              {visibleRun.report && <>
                {visibleRun.progress?.some((item) => item.attempt > 1) && <p><strong>Original run summary below; retry outcomes are shown above.</strong></p>}
                <p>{visibleRun.report.conceptCount} concepts · {visibleRun.report.completed} completed · {visibleRun.report.failedOrStopped} failed or stopped</p>
                <p>Preparation: {visibleRun.report.preparationUsage.calls} calls · cost {visibleRun.report.preparationUsage.costUsd == null ? "unknown" : `$${visibleRun.report.preparationUsage.costUsd.toFixed(4)}`}</p>
                {visibleRun.report.preparationUsage.usageComplete === false && <p>Provider usage may be incomplete because a model request had to be retried.</p>}
                {visibleRun.report.scopeWarnings.map((warning) => <p key={warning}>{warning}</p>)}
                {visibleRun.report.episodes.map((episode, index) => <div key={index}>
                  <p><strong>{episode.learnerName} · {episode.baseline.replaceAll("_", " ")}:</strong> {episode.status}{episode.metrics ? ` · pre ${(episode.metrics.preScore * 100).toFixed(0)}%, post ${(episode.metrics.postScore * 100).toFixed(0)}% · ${episode.metrics.calls} calls · cost ${episode.metrics.costUsd == null ? "unknown" : `$${episode.metrics.costUsd.toFixed(4)}`}` : episode.errorType ? ` (${episode.errorType})` : ""}</p>
                  {episode.metrics?.simulationPolicyAgreement != null && <p>Simulator followed its configured answer policy {(episode.metrics.simulationPolicyAgreement * 100).toFixed(0)}% of the time.{episode.profileControlValid === false && " This episode did not meet the 75% protocol threshold; interpret its scores with caution."}</p>}
                </div>)}
              </>}
            </article>
            </> : <p>No exploratory tests started yet.</p>}
          </section>
          <div className="eval-note">Exploratory simulated results are not evidence of human learning or research effectiveness.</div>
        </div>
      </div>
    </main>
    <PseudoLearnerDialog open={learnerDialog} onClose={() => setLearnerDialog(false)} onCreated={(learner) => { setLearners((current) => [...current, learner]); setSelectedLearners((current) => [...current, learner.id]); }} />
  </div>;
}
