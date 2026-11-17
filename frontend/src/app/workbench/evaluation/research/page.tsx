"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/backend";

type Readiness = { ready: boolean; blockers: string[]; reviews: Record<string, string>; modelChecked: boolean };
type Bundle = { id: string; title: string; readiness: Readiness };
type Settings = { bundle: string; expert: string; tutor: string; assessor: string; repeats: number; activities: number; maxCalls: number; maxTokens: number; baselines: boolean };
type Mean = { preScore: number | null; postScore: number | null; gain: number | null; latencyMs: number | null; costUsd: number | null };
type Run = { id: string; createdAt: string; status: string; message?: string; settings: Settings; model: string; episodesFinished: number; summary: null | { completed: number; failedOrStopped: number; configurationMeans: Record<string, Mean> } };

const profiles = ["Novice", "Intermediate", "Misconception-prone", "Hint-dependent"];
const initial: Settings = { bundle: "comp7608b-inference-v2-draft", expert: "grounded", tutor: "utility", assessor: "weighted", repeats: 2, activities: 6, maxCalls: 256, maxTokens: 150000, baselines: false };
const display = (n: number | null, digits = 2) => n == null ? "Not reported" : n.toFixed(digits);

export default function ControlledEvaluationPage() {
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [form, setForm] = useState(initial);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [selected, setSelected] = useState("");
  const refresh = useCallback(async () => {
    try {
      const [bundles, history] = await Promise.all([api<Bundle[]>("evaluations/bundles"), api<Run[]>("evaluations/runs")]);
      setBundle(bundles[0] || null);
      setRuns(history.sort((a, b) => b.createdAt.localeCompare(a.createdAt)));
      setError("");
    } catch (err) { setError(err instanceof Error ? err.message : "Could not load evaluation data."); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { const initialLoad = window.setTimeout(() => void refresh(), 0); const timer = window.setInterval(() => void refresh(), 10000); return () => { window.clearTimeout(initialLoad); window.clearInterval(timer); }; }, [refresh]);
  const active = runs.find((run) => run.id === selected) || runs[0];
  const episodes = 4 * form.repeats * (form.baselines ? 3 : 1);
  const valid = Number.isInteger(form.repeats) && form.repeats >= 1 && form.repeats <= 10 && Number.isInteger(form.activities) && form.activities >= 2 && form.activities <= 100 && Number.isInteger(form.maxCalls) && form.maxCalls >= 1 && form.maxCalls <= 10000 && Number.isInteger(form.maxTokens) && form.maxTokens >= 1000 && form.maxTokens <= 10000000;
  async function start(event: React.FormEvent) {
    event.preventDefault();
    if (!bundle?.readiness.ready || !valid || starting) return;
    setStarting(true);
    try { const run = await api<Run>("evaluations/runs", form); setSelected(run.id); await refresh(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not start evaluation."); }
    finally { setStarting(false); }
  }
  return <div className="expert-workbench pseudo-evaluation">
    <header className="expert-topbar">
      <Link href="/workbench/expert" className="expert-brand"><span className="expert-brand-mark" aria-hidden="true">◈</span> LearnLoop Agent Workbench</Link>
      <nav aria-label="Workbench navigation" className="expert-topnav">
        <Link href="/workbench/expert">Workbench</Link>
        <Link href="/workbench/evaluation" className="active">Pseudo-student tests</Link>
        <Link href="/agents">Run history</Link>
        <Link href="/learn">Learning</Link>
      </nav>
      <span className="expert-env">Local workspace</span>
    </header>
    <main className="pseudo-evaluation-main">
    <div className="expert-page-heading"><div><p className="expert-eyebrow">WORKBENCH · CONTROLLED EXPERIMENTS</p><h1>Prepared research bundle</h1><p className="expert-page-description">Compare predefined prompt variants with simulated learners in a controlled course unit.</p></div><Link href="/workbench/evaluation" className="expert-button secondary">Your test setups</Link></div>
    {error && <p className="expert-alert" role="alert">{error}</p>}
    <div className="eval-grid">
      <form className="expert-card eval-form" onSubmit={start}>
        <section><h2>Course unit</h2><label>Prepared evaluation bundle<select value={form.bundle} onChange={(e) => setForm({ ...form, bundle: e.target.value })}><option value={initial.bundle}>{bundle?.title || "COMP7608B — Inference"}</option></select></label><p>Frozen evaluation material; separate from the selected Workbench course.</p></section>
        <section><div className="eval-section-heading"><h2>Evaluation readiness</h2><button className="expert-button secondary" type="button" onClick={() => void refresh()}>Refresh</button></div>
          {loading ? <p>Checking readiness…</p> : <div className={bundle?.readiness.ready ? "eval-ready" : "eval-warning"}><strong>{!bundle ? "Readiness unavailable" : bundle.readiness.ready ? "Ready for a research run" : "Review or preparation required"}</strong><p>{!bundle ? "Check the backend connection and refresh." : bundle.readiness.ready ? "The bundle passed its readiness checks." : "Resolve the following blockers before starting a paid evaluation."}</p>
            {bundle?.readiness.blockers.length ? <details><summary>{bundle.readiness.blockers.length} readiness blockers</summary><ul>{bundle.readiness.blockers.map((item) => <li key={item}>{item}</li>)}</ul></details> : null}
          </div>}
          <p>Human review is recorded using the evaluation harness. See <code>backend/docs/evaluation-harness.md</code> and the bundle’s review packet for the materials and commands.</p>
        </section>
        <section><h2>Prompt variants under test</h2><p>These are predefined harness variants, not saved Workbench templates.</p><div className="eval-fields-three">
          <label>Expert<select value={form.expert} onChange={(e) => setForm({ ...form, expert: e.target.value })}><option value="structural">Structural</option><option value="grounded">Grounded</option><option value="verified">Verified</option></select></label>
          <label>Tutor<select value={form.tutor} onChange={(e) => setForm({ ...form, tutor: e.target.value })}><option value="state">State</option><option value="graph">Graph</option><option value="utility">Utility</option></select></label>
          <label>Assessor<select value={form.assessor} onChange={(e) => setForm({ ...form, assessor: e.target.value })}><option value="correctness">Correctness</option><option value="weighted">Evidence-weighted</option><option value="conservative">Conservative</option></select></label>
        </div></section>
        <section><h2>Compare other teaching approaches</h2><label className="eval-check"><input type="checkbox" checked={form.baselines} onChange={(e) => setForm({ ...form, baselines: e.target.checked })} /> Include two additional comparisons</label><p><strong>Fixed sequence:</strong> topics follow a preset order instead of adapting to progress. <strong>Without Tutor memory:</strong> the Tutor loses its learner record between sessions, while the simulated learner keeps what it learned. Including both runs three times as many episodes.</p></section>
        <section><h2>Simulated learners</h2><div className="eval-chips">{profiles.map((profile) => <span key={profile}>{profile}</span>)}</div><p>All four profiles are included in every configuration.</p><label>Repeats per profile<input type="number" min="1" max="10" value={form.repeats} onChange={(e) => setForm({ ...form, repeats: Number(e.target.value) })} /></label></section>
        <section><h2>Run limits</h2><div className="eval-fields-three"><label>Activities per episode<input type="number" min="2" max="100" value={form.activities} onChange={(e) => setForm({ ...form, activities: Number(e.target.value) })} /></label><label>Maximum calls per episode<input type="number" min="1" max="10000" value={form.maxCalls} onChange={(e) => setForm({ ...form, maxCalls: Number(e.target.value) })} /></label><label>Maximum tokens per episode<input type="number" min="1000" max="10000000" value={form.maxTokens} onChange={(e) => setForm({ ...form, maxTokens: Number(e.target.value) })} /></label></div><p>Limits apply per episode; preparation costs are separate. Model calls may incur charges.</p></section>
        <button type="submit" className="expert-button primary eval-start" disabled={!bundle?.readiness.ready || !valid || starting}>{starting ? "Starting…" : "Start evaluation"}</button>
        {!valid && <p role="alert">Enter values within the displayed limits.</p>}
      </form>
      <div className="eval-side"><section className="expert-card eval-panel"><h2>Run summary</h2><dl><div><dt>Episodes</dt><dd>{episodes} total</dd></div><div><dt>Profiles × repeats</dt><dd>4 × {form.repeats}</dd></div><div><dt>Conditions</dt><dd>{form.baselines ? "Adaptive + 2 baselines" : "Adaptive"}</dd></div><div><dt>Activities</dt><dd>{form.activities} per episode</dd></div></dl><div className="eval-note">Simulation results do not establish human learning outcomes.</div></section>
        <section className="expert-card eval-panel"><div className="eval-section-heading"><h2>Run history</h2><button type="button" className="expert-button secondary" onClick={() => void refresh()}>Refresh</button></div>{runs.length ? <label>Choose a run<select value={active?.id || ""} onChange={(e) => setSelected(e.target.value)}>{runs.map((run) => <option key={run.id} value={run.id}>{new Date(run.createdAt).toLocaleString()} · {run.status} · {run.id.slice(0, 8)}</option>)}</select></label> : <p>No evaluations started from this page yet.</p>}
          {active && <div className="eval-run"><p><strong>{active.status.replaceAll("_", " ")}</strong> · {active.episodesFinished} / {4 * active.settings.repeats * (active.settings.baselines ? 3 : 1)} episode results recorded</p><p>{active.settings.expert} / {active.settings.tutor} / {active.settings.assessor} · {active.model}</p>{active.message && <p role="alert">{active.message}</p>}{active.summary && <><p>{active.summary.completed} completed; {active.summary.failedOrStopped} failed or stopped. Score means exclude unsuccessful episodes.</p><div className="expert-config-table-wrap"><table className="expert-config-table"><thead><tr><th>Condition</th><th>Pre</th><th>Post</th><th>Gain</th><th>Cost / episode</th></tr></thead><tbody>{Object.entries(active.summary.configurationMeans).map(([key, mean]) => <tr key={key}><th>{key}</th><td>{display(mean.preScore)}</td><td>{display(mean.postScore)}</td><td>{display(mean.gain)}</td><td>{mean.costUsd == null ? "Unknown" : `$${display(mean.costUsd, 4)}`}</td></tr>)}</tbody></table></div></>}</div>}
        </section></div>
    </div>
    </main>
  </div>;
}
