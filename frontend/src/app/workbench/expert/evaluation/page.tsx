"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ExpertWorkbenchShell } from "@/components/expert-workbench-shell";
import { api } from "@/lib/backend";
import { useWorkspace } from "@/components/workspace-provider";
import { promptStagesByAgent, readExpertTemplates, workbenchAgents, type AgentPromptTemplate, type WorkbenchAgent } from "@/lib/expert-templates";

type Evaluation = { runId: string; snapshotAvailable: boolean; elapsedSeconds: number | null; retriesUsed: number | null; concepts: number | null; conceptsWithSourceLinks: number | null; processedPassages: number | null; totalPassages: number | null; reviewPassRate: null; cost: null };

export default function ExpertEvaluationPage() {
  const workspace = useWorkspace();
  const [templates, setTemplates] = useState<AgentPromptTemplate[]>([]);
  const [agent, setAgent] = useState<WorkbenchAgent>("expert");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [runIds, setRunIds] = useState<string[]>([]);
  const [evaluations, setEvaluations] = useState<Record<string, Evaluation>>({});
  const [evaluationError, setEvaluationError] = useState("");
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState("");

  useEffect(() => {
    const refresh = () => {
      const next = readExpertTemplates();
      setTemplates(next);
      setSelectedIds((current) => current.filter((id) => next.some((template) => template.id === id)));
    };
    refresh();
    window.addEventListener("storage", refresh);
    window.addEventListener("learnloop-expert-templates-updated", refresh);
    return () => {
      window.removeEventListener("storage", refresh);
      window.removeEventListener("learnloop-expert-templates-updated", refresh);
    };
  }, []);

  const materials = workspace.course?.documents || [];
  const agentConfig = workbenchAgents.find((item) => item.id === agent)!;
  const agentTemplates = useMemo(() => templates.filter((template) => template.agent === agent), [agent, templates]);
  const selectedTemplates = useMemo(() => agentTemplates.filter((template) => selectedIds.includes(template.id)), [agentTemplates, selectedIds]);
  const selectedMaterial = materials.find((material) => material.id === workspace.materialId) || null;

  const availableRuns = useMemo(() => agent === "expert" ? workspace.runs.filter((run) => run.workflow === "course_preparation" && (!workspace.materialId || run.documentId === workspace.materialId)).sort((a, b) => (b.startedAt || "").localeCompare(a.startedAt || "")) : [], [agent, workspace.runs, workspace.materialId]);
  const selectedRuns = availableRuns.filter((run) => runIds.includes(run.id));
  const materialName = (id?: string | null) => materials.find((item) => item.id === id)?.filename || "Unknown material";
  const modelUsedLabel = (run: (typeof selectedRuns)[number]) => {
    if (!run.modelsUsed?.length) return "Not recorded for this run";
    return run.modelsUsed.join(", ");
  };
  const modelSettingLabel = (run: (typeof selectedRuns)[number]) => {
    if (run.model === undefined) return "Not recorded";
    return !run.model || run.model === "configured" ? "Backend default" : run.model;
  };
  const temperatureLabel = (run: (typeof selectedRuns)[number]) => {
    if (run.temperature === undefined) return "Not recorded";
    return run.temperature === null ? "Provider default" : run.temperature.toFixed(1);
  };
  const runKey = selectedRuns.map((run) => run.id).join(",");
  useEffect(() => {
    let cancelled = false;
    if (!runKey) return;
    Promise.all(runKey.split(",").map((id) => api<Evaluation>(`agent-activity/runs/${encodeURIComponent(id)}/evaluation`)))
      .then((results) => { if (!cancelled) { setEvaluations(Object.fromEntries(results.map((item) => [item.runId, item]))); setEvaluationError(""); } })
      .catch((error: Error) => { if (!cancelled) { setEvaluations({}); setEvaluationError(error.message); } });
    return () => { cancelled = true; };
  }, [runKey]);
  function toggleRun(id: string) {
    setRunIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...selectedRuns.map((run) => run.id), id].slice(0, 3));
  }

  function toggleTemplate(id: string) {
    setSelectedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : current.length < 3 ? [...current, id] : current);
  }

  async function copyComparisonSetup() {
    const setup = {
      course: workspace.course?.title || null,
      material: selectedMaterial?.filename || "All course materials",
      templates: selectedTemplates.map(({ id, name, model, temperature, prompts }) => ({ id, name, model, temperature, prompts })),
    };
    try {
      await navigator.clipboard.writeText(JSON.stringify(setup, null, 2));
      setCopied(true);
      setCopyError("");
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
      setCopyError("Clipboard access is unavailable in this browser.");
    }
  }

  const railContent = <><section className="expert-run-template-list" aria-labelledby="evaluation-runs-title">
    <h2 id="evaluation-runs-title">Choose run records</h2><p className="expert-run-template-empty">{selectedRuns.length} of 3 selected</p>
    {agent !== "expert" ? <p className="expert-run-template-empty">Run comparison is available for Expert runs.</p> : availableRuns.length ? availableRuns.map((run) => <label key={run.id} className={`expert-run-template-option ${runIds.includes(run.id) ? "selected" : ""}`}>
      <input type="checkbox" checked={runIds.includes(run.id)} disabled={!runIds.includes(run.id) && selectedRuns.length >= 3} onChange={() => toggleRun(run.id)} />
      <span><strong title={materialName(run.documentId)}>{materialName(run.documentId)}</strong><small>{run.templateName === undefined ? "Template unavailable" : run.templateName || "Backend defaults"} · {run.status.replaceAll("_", " ")}<br />{run.startedAt ? new Date(run.startedAt).toLocaleString() : "Date unavailable"} · {run.id.slice(0, 8)}</small></span>
    </label>) : <p className="expert-run-template-empty">{workspace.error || (workspace.loading ? "Loading runs…" : "No runs for this selection. Start a run from the Run page.")}</p>}
  </section><section className="expert-run-template-list" aria-labelledby="expert-template-picker-title">
    <h2 id="expert-template-picker-title">Choose templates</h2>
    <p className="expert-run-template-empty">{selectedTemplates.length} of 3 selected · {agentConfig.label}</p>
    {agentTemplates.map((template) => <label key={template.id} className={`expert-run-template-option ${selectedIds.includes(template.id) ? "selected" : ""}`}>
      <input type="checkbox" checked={selectedIds.includes(template.id)} disabled={!selectedIds.includes(template.id) && selectedIds.length >= 3} onChange={() => toggleTemplate(template.id)} />
      <span><strong title={template.name}>{template.name}</strong><small>{template.model} · temp {template.temperature.toFixed(1)}</small></span>
    </label>)}
    {!agentTemplates.length && <p className="expert-run-template-empty">No {agentConfig.label} templates saved. <Link href={`/workbench/expert/edit?agent=${agent}`}>Open Edit agent</Link> to create one.</p>}
  </section></>;

  return <ExpertWorkbenchShell activePage="evaluation" activeAgent={agent} onAgentChange={(next) => { setAgent(next); setSelectedIds([]); }} railContent={railContent}>
    <div className="expert-page-heading expert-editor-heading">
      <div><p className="expert-eyebrow">{agentConfig.label.toUpperCase()} AGENT · BENCHMARKS</p><h1>{agentConfig.label} evaluation</h1><p className="expert-page-description">Select saved runs to compare their recorded status and summaries, or compare prompt templates.</p></div>
    </div>

    <div className="expert-local-notice"><strong>Run records</strong><span>Provider-reported model IDs are saved for new Expert runs. Older runs may not include the exact model used.</span></div>

    <div className="expert-evaluation-layout">
      <section className="expert-card expert-config-comparison" aria-labelledby="run-comparison-title">
        <div className="expert-card-heading"><div><h2 id="run-comparison-title">Run comparison</h2><p>Select up to three run records from the sidebar.</p></div></div>
        {selectedRuns.length ? <div className="expert-config-table-wrap"><table className="expert-config-table"><thead><tr><th>Run</th>{selectedRuns.map((run) => <th key={run.id}>{run.id.slice(0, 8)}</th>)}</tr></thead><tbody>
          <tr><th>Material</th>{selectedRuns.map((run) => <td key={run.id}>{materialName(run.documentId)}</td>)}</tr>
          <tr><th>Template</th>{selectedRuns.map((run) => <td key={run.id}>{run.templateName === undefined ? "Template unavailable" : run.templateName || "Backend defaults"}</td>)}</tr>
          <tr><th>Model used</th>{selectedRuns.map((run) => <td key={run.id}>{modelUsedLabel(run)}</td>)}</tr>
          <tr><th>Model setting</th>{selectedRuns.map((run) => <td key={run.id}>{modelSettingLabel(run)}</td>)}</tr>
          <tr><th>Temperature</th>{selectedRuns.map((run) => <td key={run.id}>{temperatureLabel(run)}</td>)}</tr>
          <tr><th>Started</th>{selectedRuns.map((run) => <td key={run.id}>{run.startedAt ? new Date(run.startedAt).toLocaleString() : "Unavailable"}</td>)}</tr>
          <tr><th>Status</th>{selectedRuns.map((run) => <td key={run.id}>{run.status.replaceAll("_", " ")}</td>)}</tr>
          <tr><th>Summary</th>{selectedRuns.map((run) => <td key={run.id}>{run.summary}</td>)}</tr>
        </tbody></table></div> : <p className="expert-muted">Choose run records to inspect their saved details here.</p>}
      </section>
      <section className="expert-card expert-outcomes-card" aria-labelledby="expert-outcomes-title">
        <div className="expert-card-heading"><div><h2 id="expert-outcomes-title">Measured outcomes</h2><p>{selectedMaterial ? selectedMaterial.filename : "Selected material: all course materials"}</p></div><span className="expert-readonly-tag">Saved run data</span></div>
        {evaluationError && <p className="expert-alert" role="alert">{evaluationError}</p>}
        {!selectedRuns.length ? <p className="expert-muted">Select run records to see their saved measurements.</p> : <div className="expert-config-table-wrap"><table className="expert-config-table"><thead><tr><th>Measurement</th>{selectedRuns.map((run) => <th key={run.id}>{run.templateName || "Run"} · {run.id.slice(0, 8)}</th>)}</tr></thead><tbody>
          <tr><th>Concepts with source links</th>{selectedRuns.map((run) => { const m = evaluations[run.id]; return <td key={run.id}>{!m ? (evaluationError ? "Unavailable" : "Loading…") : m.concepts == null ? "Snapshot unavailable" : `${m.conceptsWithSourceLinks} / ${m.concepts}`}</td>; })}</tr>
          <tr><th>Passages processed</th>{selectedRuns.map((run) => { const m = evaluations[run.id]; return <td key={run.id}>{!m ? (evaluationError ? "Unavailable" : "Loading…") : m.processedPassages == null || m.totalPassages == null ? "Not recorded" : `${m.processedPassages} / ${m.totalPassages}`}</td>; })}</tr>
          <tr><th>Elapsed time</th>{selectedRuns.map((run) => { const m = evaluations[run.id]; return <td key={run.id}>{!m ? (evaluationError ? "Unavailable" : "Loading…") : m.elapsedSeconds == null ? "Not recorded" : `${Math.round(m.elapsedSeconds)} s`}</td>; })}</tr>
          <tr><th>Retries used</th>{selectedRuns.map((run) => { const m = evaluations[run.id]; return <td key={run.id}>{!m ? (evaluationError ? "Unavailable" : "Loading…") : m.retriesUsed == null ? "Not recorded" : m.retriesUsed}</td>; })}</tr>
          <tr><th>Review pass rate</th>{selectedRuns.map((run) => <td key={run.id}>Not recorded</td>)}</tr>
          <tr><th>Model cost</th>{selectedRuns.map((run) => <td key={run.id}>Not recorded</td>)}</tr>
        </tbody></table></div>}
        <p className="expert-muted">Source links count concepts referencing a saved passage; they do not measure whether claims are supported. Passage counts describe processing, not concept coverage. Snapshot counts may include records from earlier runs.</p>
        <div className="expert-editor-actions expert-evaluation-actions"><span>{copyError || (selectedTemplates.length < 2 ? "Select at least two templates for a comparison." : "Comparison is ready to export as a run setup.")}</span><button type="button" className="expert-button secondary" disabled={selectedTemplates.length < 2} onClick={() => void copyComparisonSetup()}>{copied ? "Copied setup" : "Copy comparison setup"}</button></div>
      </section>

      {selectedTemplates.length > 0 && <section className="expert-card expert-config-comparison" aria-labelledby="expert-config-comparison-title">
        <div className="expert-card-heading"><div><h2 id="expert-config-comparison-title">Configuration comparison</h2><p>Inspect the selected prompt and model settings side by side.</p></div></div>
        <div className="expert-config-table-wrap"><table className="expert-config-table"><thead><tr><th>Setting</th>{selectedTemplates.map((template) => <th key={template.id}>{template.name}</th>)}</tr></thead><tbody>
          <tr><th>Model</th>{selectedTemplates.map((template) => <td key={template.id}>{template.model}</td>)}</tr>
          <tr><th>Temperature</th>{selectedTemplates.map((template) => <td key={template.id}>{template.temperature.toFixed(1)}</td>)}</tr>
          {promptStagesByAgent[agent].map((stage) => <tr key={stage.id}><th>{stage.label}</th>{selectedTemplates.map((template) => <td key={template.id} className="expert-config-prompt">{template.prompts[stage.id]}</td>)}</tr>)}
        </tbody></table></div>
      </section>}
    </div>
  </ExpertWorkbenchShell>;
}
