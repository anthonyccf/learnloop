"use client";

import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";

const DialogTitle = createContext<(title: string | null) => void>(() => {});
export const useLearningDialogTitle = () => useContext(DialogTitle);

export function LearningDialog({ title, onClose, children, wide = false }: {
  title: string; onClose: () => void; children: ReactNode; wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [contentTitle, setContentTitle] = useState<string | null>(null);
  const displayedTitle = contentTitle || title;
  useEffect(() => {
    const dialog = ref.current;
    const previous = document.activeElement as HTMLElement | null;
    dialog?.showModal();
    return () => { dialog?.close(); previous?.focus({ preventScroll: true }); };
  }, []);
  return <dialog ref={ref} className={`learning-dialog${wide ? " learning-dialog-wide" : ""}`} aria-label={displayedTitle} onCancel={event => { event.preventDefault(); onClose(); }} onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="learning-dialog-heading"><h2>{displayedTitle}</h2><button type="button" onClick={onClose} aria-label={`Close ${displayedTitle.toLowerCase()}`}>Close <span aria-hidden="true">×</span></button></div>
    <DialogTitle.Provider value={setContentTitle}>{children}</DialogTitle.Provider>
  </dialog>;
}
