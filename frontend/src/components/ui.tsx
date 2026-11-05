"use client";
import { useEffect, useRef, type ReactNode } from "react";
import { labels, type ConceptState } from "@/lib/demo-data";
import { Icon } from "./icons";
import { conceptSources, type SourceReference } from "@/lib/learner-evidence";
export function StateBadge({ state }: { state: ConceptState }) {
  return (
    <span className={`state-badge ${state}`}>
      <span className="status-dot" />
      {labels[state]}
    </span>
  );
}
export function PageHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="subtitle">{description}</p>
      </div>
      {action}
    </div>
  );
}
export function SourceDrawer({
  onClose,
  source = conceptSources.descent,
}: {
  onClose: () => void;
  source?: SourceReference;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = dialog.current;
    node?.showModal();
    return () => node?.close();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="source-dialog"
      onCancel={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      aria-labelledby="source-title"
    >
      <div className="drawer-header">
        <div>
          <p className="eyebrow">COURSE REFERENCE</p>
          <h2 id="source-title">{source.title}</h2>
        </div>
        <button
          className="icon-button"
          onClick={onClose}
          aria-label="Close source"
        >
          <Icon name="close" />
        </button>
      </div>
      <div className="drawer-body">
        <span className="tag">
          Lecture {source.lecture} · Slide {source.page} · Sample reference
        </span>
        <article className="slide-preview">
          <span>
            COMP7608B /{" "}
            {source.lecture === "2" ? "FOUNDATIONS" : "OPTIMIZATION"}
          </span>
          <h3>{source.heading}</h3>
          {source.equation && <div className="equation">{source.equation}</div>}
          <p>{source.excerpt}</p>
        </article>
        <div className="notice">
          <Icon name="source" />
          <p>
            This passage and slide location are illustrative demo data, not a
            rendered page or a verified quotation from your PDF.
          </p>
        </div>
      </div>
    </dialog>
  );
}
