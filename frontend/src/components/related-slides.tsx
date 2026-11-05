"use client";

import Image from "next/image";
import { useEffect, useState, type ReactNode } from "react";
import { api, Reference } from "@/lib/backend";
import { useWorkspace } from "./workspace-provider";
import { LearningDialog } from "./learning-dialog";

export function SourceLink({ references, context = "question" }: { references: Reference[]; context?: "lesson" | "question" }) {
  const [open, setOpen] = useState(false);
  return <><button className="learning-source-link" onClick={() => setOpen(true)}>{references.length ? `View ${context} sources` : "Browse course materials"} ↗</button>
    {open && <LearningDialog title={`Sources for this ${context}`} onClose={() => setOpen(false)} wide><RelatedSlides references={references} context={context} /></LearningDialog>}
  </>;
}

export function RelatedSlides({ references, context = "question" }: { references: Reference[]; context?: "lesson" | "question" }) {
  const { course } = useWorkspace();
  const cited = references.filter((ref, index) => references.findIndex(r => r.documentId === ref.documentId && r.page === ref.page) === index);
  const options = cited.length ? cited : (course?.documents || []).filter(d => d.pages > 0).map(d => ({ documentId: d.id, label: d.filename, page: 1 }));
  const [selection, setSelection] = useState(0);
  const [revision, setRevision] = useState(0);
  const [viewed, setViewed] = useState<{ documentId: string; page: number } | null>(null);
  const reference = options[selection] || options[0];
  const currentPage = viewed?.documentId === reference?.documentId ? viewed.page : reference?.page || 1;
  const sourceControls = options.length > 0 && <nav className="slide-bubbles" aria-label={cited.length ? "Cited slide pages" : "Course materials"}>{options.map((r, i) => <button type="button" key={`${r.documentId}-${r.page}`} aria-pressed={r.documentId === reference?.documentId && (!cited.length || currentPage === (r.page || 1))} aria-label={cited.length ? `Page ${r.page || 1} from ${r.label}` : r.label} title={r.label} onClick={() => { setSelection(i); setViewed(null); setRevision(value => value + 1); }}>{cited.length ? `p. ${r.page || 1}` : r.label}{cited.length && options.some(other => other.documentId !== r.documentId) && <small>{r.label}</small>}</button>)}</nav>;
  return <aside className="live-card related-slides" aria-label="Related course slides">
    <div className="related-slides-heading"><h2>{cited.length ? "Related slides" : "Course materials"}</h2><p>{cited.length ? `Read the original material for this ${context}.` : `No slide was cited for this ${context}. You can browse your materials here.`}</p></div>
    {reference ? <SlideViewer key={`${reference.documentId}-${reference.page}-${revision}`} reference={reference} sourceControls={sourceControls} onPageChange={page => setViewed({ documentId: reference.documentId, page })} /> : <p>No materials available yet.</p>}
  </aside>;
}

export function SlideViewer({ reference, onPageChange, sourceControls }: { reference: Reference; onPageChange?: (page: number) => void; sourceControls?: ReactNode }) {
  const { course } = useWorkspace();
  const material = course?.documents.find(doc => doc.id === reference.documentId);
  const pageCount = material?.pages || reference.page || 1;
  const [page, setPage] = useState(Math.max(1, Math.min(reference.page || 1, pageCount)));
  const [zoom, setZoom] = useState(100);
  const [attempt, setAttempt] = useState(0);
  const [imageState, setImageState] = useState<"loading" | "ready" | "error">("loading");
  const [textOpen, setTextOpen] = useState(false);
  const textOnly = /\.txt$/i.test(material?.filename || reference.label);
  const imageUrl = `/api/backend/documents/${reference.documentId}/pages/${page}/slide${attempt ? `?retry=${attempt}` : ""}`;
  function navigate(next: number) {
    if (next < 1 || next > pageCount || next === page) return;
    setImageState("loading"); setPage(next); setAttempt(0);
    onPageChange?.(next);
  }
  return <div className="slide-viewer">
    <p className="slide-filename">{material?.filename || reference.label}</p>
    <div className="slide-toolbar">{sourceControls}<nav aria-label="Slide pages"><button className="button secondary" aria-label="Previous slide" disabled={page <= 1} onClick={() => navigate(page - 1)}>←</button><label>Page <input aria-label="Slide page" type="number" min={1} max={pageCount} value={page} onChange={e => { const value = Number(e.target.value); if (Number.isInteger(value)) navigate(value); }} /> of {pageCount}</label><button className="button secondary" aria-label="Next slide" disabled={page >= pageCount} onClick={() => navigate(page + 1)}>→</button></nav>
      {!textOnly && <div className="slide-zoom" role="group" aria-label="Slide zoom">{[100, 150, 200].map(value => <button className="button secondary" aria-pressed={zoom === value} key={value} onClick={() => setZoom(value)}>{value === 100 ? "Fit" : `${value}%`}</button>)}</div>}
    {!textOnly && <button className="button secondary slide-text-toggle" aria-expanded={textOpen} onClick={() => setTextOpen(open => !open)}>{textOpen ? "Hide extracted text" : "Read extracted text"}</button>}
    </div>
    {!textOnly && <div className="slide-canvas" data-fit={zoom === 100} key={`${page}-${attempt}`} aria-busy={imageState === "loading"}>
      {imageState === "loading" && <p className="slide-loading" role="status">Loading slide {page}…</p>}
      {imageState === "error" ? <div className="slide-loading" role="alert"><p>Could not load this slide.</p><button className="button secondary" onClick={() => { setImageState("loading"); setAttempt(a => a + 1); }}>Retry preview</button><button className="button secondary" onClick={() => setTextOpen(true)}>Read extracted text</button></div> : <Image unoptimized loading="eager" src={imageUrl} alt={`Slide ${page} from ${material?.filename || reference.label}`} width={1800} height={1100} style={{ width: `${zoom}%`, height: zoom === 100 ? "100%" : "auto", maxWidth: "none", display: imageState === "ready" ? "block" : "none" }} onLoad={() => setImageState("ready")} onError={() => setImageState("error")} />}
    </div>}
    {(textOnly || textOpen) && <SlideText key={`${reference.documentId}-${page}`} documentId={reference.documentId} page={page} />}
  </div>;
}

function SlideText({ documentId, page }: { documentId: string; page: number }) {
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    api<{ passages: { text: string }[] }>(`documents/${documentId}/pages/${page}`).then(result => { if (active) { setText(result.passages.map(p => p.text).join("\n\n")); setError(""); } }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [documentId, page, attempt]);
  return <div className="live-source">{error ? <><p role="alert">{error}</p><button className="button secondary" onClick={() => setAttempt(a => a + 1)}>Retry text</button></> : text ? <p>{text}</p> : <p role="status">Loading extracted text…</p>}</div>;
}
