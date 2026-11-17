"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/backend";

export type PseudoLearner = { id: string; name: string; model: string; basic: number; intermediate: number; advanced: number; hint: number; gain: number; delaySeconds: number; misconceptions: boolean; builtin: boolean };
type Draft = Omit<PseudoLearner, "id" | "builtin">;
const defaults: Draft = { name: "", model: "configured", basic: 0.25, intermediate: 0.12, advanced: 0.05, hint: 0.2, gain: 0.1, delaySeconds: 45, misconceptions: false };

export function PseudoLearnerDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (learner: PseudoLearner) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [draft, setDraft] = useState<Draft>(defaults);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { const node = dialog.current; if (!node) return; if (open && !node.open) node.showModal(); else if (!open && node.open) node.close(); }, [open]);
  async function create(event: React.FormEvent) {
    event.preventDefault(); setSaving(true); setError("");
    try { const profile = await api<PseudoLearner>("evaluations/learners", draft); setDraft(defaults); onCreated(profile); onClose(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not create learner."); }
    finally { setSaving(false); }
  }
  const percent = (key: "basic" | "intermediate" | "advanced" | "hint", label: string) => <label>{label} (%)<input type="number" min="0" max="100" step="1" required value={Math.round(draft[key] * 100)} onChange={(e) => setDraft({ ...draft, [key]: Number(e.target.value) / 100 })} /></label>;
  return <dialog ref={dialog} className="learner-profile-dialog" aria-labelledby="learner-profile-title" onCancel={(e) => { e.preventDefault(); if (!saving) onClose(); }}><form className="eval-form" onSubmit={create}><div className="eval-section-heading"><div><h2 id="learner-profile-title">Create simulated learner</h2><p>Set starting behavior for a reusable profile. Values are simulation assumptions.</p></div><button type="button" className="expert-button secondary" onClick={onClose} disabled={saving}>Close</button></div>
    <label>Learner name<input required maxLength={100} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="e.g. Needs help with foundations" /></label>
    <label>Response model<input required maxLength={200} value={draft.model} onChange={(e) => setDraft({ ...draft, model: e.target.value })} /></label><p>Use <code>configured</code> for the backend model, or enter a provider model ID.</p>
    <h3>Starting ability</h3><p>Estimated chance of answering independently at each difficulty before learning.</p><div className="eval-fields-three">{percent("basic", "Basic")}{percent("intermediate", "Intermediate")}{percent("advanced", "Advanced")}</div>
    <h3>Learning behavior</h3><div className="eval-fields-three">{percent("hint", "Chance of requesting a hint")}<label>Maximum gain per activity (%)<input type="number" min="0" max="15" step="1" required value={Math.round(draft.gain * 100)} onChange={(e) => setDraft({ ...draft, gain: Number(e.target.value) / 100 })} /></label><label>Response time (seconds)<input type="number" min="1" max="3600" step="1" required value={draft.delaySeconds} onChange={(e) => setDraft({ ...draft, delaySeconds: Number(e.target.value) })} /></label></div>
    <label className="eval-check learner-misconception"><input type="checkbox" checked={draft.misconceptions} onChange={(e) => setDraft({ ...draft, misconceptions: e.target.checked })} /> Starts with misconceptions on some concepts</label>
    {error && <p className="expert-alert" role="alert">{error}</p>}<div className="learner-dialog-actions"><button type="button" className="expert-button secondary" onClick={onClose} disabled={saving}>Cancel</button><button type="submit" className="expert-button primary" disabled={saving}>{saving ? "Creating…" : "Create learner"}</button></div>
  </form></dialog>;
}
