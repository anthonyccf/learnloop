"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, type Course, type CourseDetail } from "@/lib/backend";
import { loadSharedTemplates, type AgentPromptTemplate, type WorkbenchAgent } from "@/lib/expert-templates";
import { PseudoLearnerDialog, type PseudoLearner } from "@/components/pseudo-learner-dialog";
import { PseudoLearnerProgress, type LearnerProgress } from "@/components/pseudo-learner-progress";

type Setup = { id: string; course: { title: string }; material: { id: string; filename: string; documentCount?: number }; release: { id: string; version: number } };
type RunMode = "existing" | "generate";
type PseudoRun = {
  id: string;
  setupId: string;
  createdAt: string;
  course: string;
  material: string;
  materialId: string;
  releaseId: string;
  preparedAvailable: boolean;
  status: string;
  phase?: string;
  message?: string;
  errorType?: string;
  progress: LearnerProgress[];
  config: { concepts: number; activities: number; baselines: boolean; sourceRunId?: string | null };
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
  { id: "tutor", label: "Tutor" },
  { id: "assessing", label: "Assessing" },
];

export default function PseudoStudentPage() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [courseId, setCourseId] = useState("");
  const [course, setCourse] = useState<CourseDetail | null>(null);
  const [materialId, setMaterialId] = useState("");
  const [templates, setTemplates] = useState<AgentPromptTemplate[]>([]);
  const [selected, setSelected] = useState<Record<WorkbenchAgent, string>>({ expert: "", tutor: "", assessing: "" });
  const [learners, setLearners] = useState<PseudoLearner[]>([]);
  const [selectedLearners, setSelectedLearners] = useState<string[]>(["novice", "intermediate", "misconception_prone", "hint_dependent"]);
  const [learnerDialog, setLearnerDialog] = useState(false);
  const [runs, setRuns] = useState<PseudoRun[]>([]);
  const [runMode, setRunMode] = useState<RunMode>("generate");
  const [sourceRun, setSourceRun] = useState("");
  const [concepts, setConcepts] = useState(1);
  const [activities, setActivities] = useState(2);
  const [baselines, setBaselines] = useState(false);
  const [running, setRunning] = useState(false);
  const [retrying, setRetrying] = useState("");
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
      const next = await api<PseudoRun[]>("evaluations/pseudo-runs");
      setRuns(next.sort((a, b) => b.createdAt.localeCompare(a.createdAt)));
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
    if (!courseId) return;
    let cancelled = false;
    api<CourseDetail>(`courses/${encodeURIComponent(courseId)}`).then((item) => {
      if (!cancelled) {
        setCourse(item);
        setMaterialId(item.documents[0]?.id || "");
        setSourceRun("");
      }
    }).catch((err: Error) => {
      if (!cancelled) { setCourse(null); setError(err.message); }
    });
    return () => { cancelled = true; };
  }, [courseId]);

  const reusableRuns = runs.filter((run) =>
    run.preparedAvailable && run.materialId === materialId && run.releaseId === course?.release?.id,
  );
  const effectiveSource = sourceRun || reusableRuns[0]?.id || "";
  const validSource = reusableRuns.some((run) => run.id === effectiveSource);
  const materialCount = materialId === "__all__" ? course?.documents.length || 0 : 1;

  async function startTest(event: React.FormEvent) {
    event.preventDefault();
    if (!course?.release || !materialId || running) return;
    if (runMode === "existing" && !validSource) return;
    setRunning(true);
    setError("");
    setMessage("");
    try {
      // Freeze the current choices as the run's immutable input, then start it in one action.
      const setup = await api<Setup>("evaluations/setups", {
        courseId,
        documentId: materialId,
        expertTemplateId: runMode === "generate" ? selected.expert || null : null,
        tutorTemplateId: selected.tutor || null,
        assessingTemplateId: selected.assessing || null,
        learnerProfileIds: selectedLearners,
      });
      await api<PseudoRun>("evaluations/pseudo-runs", {
        setupId: setup.id,
        concepts,
        activities,
        baselines,
        sourceRunId: runMode === "existing" ? effectiveSource : null,
      });
      await refreshRuns();
      setMessage("Test started. Progress will appear under Test runs.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the test.");
    } finally {
      setRunning(false);
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
        <div><p className="expert-eyebrow">WORKBENCH · SIMULATED LEARNERS</p><h1>Pseudo-student tests</h1><p className="expert-page-description">Choose course materials and agents, then start a test.</p></div>
        <button type="button" className="expert-button secondary" onClick={() => void refresh()}>Refresh workspace</button>
      </div>
      {error && <p className="expert-alert" role="alert">{error}</p>}
      {message && <p className="eval-ready" role="status">{message}</p>}

      <div className="eval-grid">
        <form className="expert-card eval-form" onSubmit={startTest}>
          <section>
            <h2>Course and material</h2>
            <p>Choose a published course and one or all of its materials.</p>
            <div className="eval-fields-three">
              <label>Course<select value={courseId} disabled={loading || !courses.length} onChange={(e) => { setCourseId(e.target.value); setCourse(null); setMaterialId(""); }}>
                <option value="">Select course</option>{courses.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
              </select></label>
              <label>Material<select value={materialId} disabled={!course?.documents.length} onChange={(e) => { setMaterialId(e.target.value); setSourceRun(""); }}>
                <option value="">Select material</option><option value="__all__">All published materials</option>
                {course?.documents.map((item) => <option key={item.id} value={item.id}>{item.filename}</option>)}
              </select></label>
            </div>
            {course && <p>{course.release ? `Published course version ${course.release.version}` : "Publish this course before starting a test."}</p>}
            {materialId === "__all__" && <p>Concepts are sampled across files. Choose a concept limit at least as large as the number of materials.</p>}
          </section>

          <section>
            <h2>Expert materials</h2>
            <p>Choose whether to reuse an earlier preparation or have Expert create a fresh set for this test.</p>
            <div className="eval-material-choices">
              <label className="eval-material-choice">
                <input type="radio" name="expert-material-mode" checked={runMode === "existing"} onChange={() => { setRunMode("existing"); setSourceRun(""); }} />
                <span><strong>Use existing course materials</strong><small>Reuse lessons, questions and exams from an earlier test for this exact material and published version.</small></span>
              </label>
              <label className="eval-material-choice">
                <input type="radio" name="expert-material-mode" checked={runMode === "generate"} onChange={() => { setRunMode("generate"); setSourceRun(""); }} />
                <span><strong>Generate a new set with Expert</strong><small>Expert creates new lessons, practice questions and held-out exams.</small></span>
              </label>
            </div>
            {runMode === "existing" ? <>
              <label>Prepared materials from<select value={effectiveSource} onChange={(e) => setSourceRun(e.target.value)} disabled={!reusableRuns.length}>
                <option value="">{reusableRuns.length ? "Select an earlier test" : "No matching prepared materials"}</option>
                {reusableRuns.map((run) => <option key={run.id} value={run.id}>{new Date(run.createdAt).toLocaleString()} · {run.report?.conceptCount ?? run.config.concepts} concepts · {run.id.slice(0, 8)}</option>)}
              </select></label>
              {!reusableRuns.length && <p role="status">No earlier test has prepared materials for this exact material and course version. Choose “Generate a new set with Expert” to prepare the first set.</p>}
              {reusableRuns.length > 0 && <p>The most recent matching preparation is selected. Expert generation is skipped; the selected Tutor, Assessing and learner settings use these frozen materials.</p>}
            </> : <>
              <label>Expert template<select value={selected.expert} onChange={(e) => setSelected({ ...selected, expert: e.target.value })}>
                <option value="">Backend default</option>
                {templates.filter((template) => template.agent === "expert").map((template) => <option key={template.id} value={template.id}>{template.name}</option>)}
              </select></label>
              <div className="eval-fields-three eval-run-controls">
                <label>Maximum concepts<input type="number" min={Math.max(1, materialCount)} max="20" value={concepts} onChange={(e) => setConcepts(Number(e.target.value))} /></label>
              </div>
              {materialCount > 20 && <p role="alert">A test supports up to 20 materials at once. Choose an individual material for this course.</p>}
            </>}
          </section>

          <section>
            <h2>Tutor and Assessing</h2>
            <p>Choose saved Workbench templates. Your selections are captured with this run.</p>
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
              <label>Activities per learner<input type="number" min="2" max="12" value={activities} onChange={(e) => setActivities(Number(e.target.value))} /></label>
            </div>
            <label className="eval-check"><input type="checkbox" checked={baselines} onChange={(e) => setBaselines(e.target.checked)} /> Include both comparison approaches</label>
            <p>{selectedLearners.length} learners × {baselines ? 3 : 1} approaches = {selectedLearners.length * (baselines ? 3 : 1)} episodes. {runMode === "generate" && "Limit: 80 preparation calls per concept. "}Limit: 64 calls per episode. Model calls may incur charges.</p>
            <p>Counts are simulated learning activities, not mouse clicks. Prerequisites outside the prepared subset are omitted.</p>
            <button type="submit" className="expert-button primary eval-start" disabled={!course?.release || !materialId || !selectedLearners.length || selectedLearners.length > 20 || running || (runMode === "existing" && !validSource) || (runMode === "generate" && (!Number.isInteger(concepts) || concepts < Math.max(1, materialCount) || concepts > 20)) || !Number.isInteger(activities) || activities < 2 || activities > 12}>
              {running ? "Starting test…" : runMode === "existing" ? "Start test with existing materials" : "Generate materials and start test"}
            </button>
          </section>
        </form>

        <div className="eval-side">
          <section className="expert-card eval-panel">
            <h2>Test runs</h2>
            {runs.length ? runs.map((run) => <article className="eval-saved" key={run.id}>
              <strong>{run.course} · {run.material}</strong>
              <p>{new Date(run.createdAt).toLocaleString()} · {run.status.replaceAll("_", " ")} {run.phase ? `· ${run.phase}` : ""}</p>
              {run.config.sourceRunId && <p>Reused materials from test {run.config.sourceRunId.slice(0, 8)}; original preparation costs are not included below.</p>}
              {run.message && <p role="alert">{run.message} {run.errorType && `(${run.errorType})`}</p>}
              <PseudoLearnerProgress episodes={run.progress || []} retrying={retrying} onRetry={(learnerId, condition) => void retryLearner(run.id, learnerId, condition)} />
              {run.report && <>
                {run.progress?.some((item) => item.attempt > 1) && <p><strong>Original run summary below; retry outcomes are shown above.</strong></p>}
                <p>{run.report.conceptCount} concepts · {run.report.completed} completed · {run.report.failedOrStopped} failed or stopped</p>
                <p>Preparation: {run.report.preparationUsage.calls} calls · cost {run.report.preparationUsage.costUsd == null ? "unknown" : `$${run.report.preparationUsage.costUsd.toFixed(4)}`}</p>
                {run.report.preparationUsage.usageComplete === false && <p>Provider usage may be incomplete because a model request had to be retried.</p>}
                {run.report.scopeWarnings.map((warning) => <p key={warning}>{warning}</p>)}
                {run.report.episodes.map((episode, index) => <div key={index}>
                  <p><strong>{episode.learnerName} · {episode.baseline.replaceAll("_", " ")}:</strong> {episode.status}{episode.metrics ? ` · pre ${(episode.metrics.preScore * 100).toFixed(0)}%, post ${(episode.metrics.postScore * 100).toFixed(0)}% · ${episode.metrics.calls} calls · cost ${episode.metrics.costUsd == null ? "unknown" : `$${episode.metrics.costUsd.toFixed(4)}`}` : episode.errorType ? ` (${episode.errorType})` : ""}</p>
                  {episode.metrics && <p>Simulator followed its configured answer policy {episode.metrics.simulationPolicyAgreement == null ? "an unknown amount" : `${(episode.metrics.simulationPolicyAgreement * 100).toFixed(0)}% of the time`}.{episode.profileControlValid === false && " This episode did not meet the 75% protocol threshold; interpret its scores with caution."}</p>}
                </div>)}
              </>}
            </article>) : <p>No exploratory tests started yet.</p>}
          </section>
          <div className="eval-note">Exploratory simulated results are not evidence of human learning or research effectiveness.</div>
        </div>
      </div>
    </main>
    <PseudoLearnerDialog open={learnerDialog} onClose={() => setLearnerDialog(false)} onCreated={(learner) => { setLearners((current) => [...current, learner]); setSelectedLearners((current) => [...current, learner.id]); }} />
  </div>;
}
