import { useRef, useState, type ReactNode } from "react";
import type { CourseDetail } from "@/lib/backend";

export type MaterialTab = "upload" | "existing";

type Props = {
  documents: CourseDetail["documents"];
  selection: string;
  onSelect: (id: string) => void;
  lockedSelection?: string;
  tab: MaterialTab;
  onTabChange: (tab: MaterialTab) => void;
  files: File[];
  onFilesChange: (files: File[]) => void;
  disabled?: boolean;
  uploadAction?: ReactNode;
};

export function CourseMaterialPicker({
  documents, selection, onSelect, lockedSelection, tab, onTabChange,
  files, onFilesChange, disabled, uploadAction,
}: Props) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const selectedDocument = documents.find((doc) => doc.id === selection);
  return <>
    <div className="expert-material-source-tabs" role="tablist" aria-label="Course material source">
      <button type="button" role="tab" disabled={disabled} aria-selected={tab === "upload"} onClick={() => onTabChange("upload")}>Upload files{files.length > 0 && <span>{files.length}</span>}</button>
      <button type="button" role="tab" disabled={disabled} aria-selected={tab === "existing"} onClick={() => onTabChange("existing")}>Select existing<span>{documents.length}</span></button>
    </div>
    {tab === "upload" ? <div
      className={`expert-dropzone ${dragging ? "dragging" : ""} ${files.length ? "has-files" : ""}`}
      onDragOver={(event) => { event.preventDefault(); if (!disabled) setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        if (!disabled) onFilesChange(Array.from(event.dataTransfer.files).filter((file) => /\.(pdf|txt)$/i.test(file.name)));
      }}
    >
      <span className="expert-upload-icon" aria-hidden="true">⇧</span>
      <strong>Drag and drop files here</strong><span>or</span>
      <button type="button" className="expert-button primary" disabled={disabled} onClick={() => fileInput.current?.click()}>Choose files</button>
      <input ref={fileInput} type="file" aria-label="Course files" disabled={disabled} accept=".pdf,.txt,application/pdf,text/plain" multiple hidden onChange={(event) => {
        onFilesChange(Array.from(event.target.files || []));
        event.target.value = "";
      }} />
      {files.length > 0 && <>
        <ul className="expert-pending-files">{files.map((file, index) => <li key={`${file.name}-${index}`}>
          <span className="expert-file-type">{file.name.split(".").pop()?.toUpperCase()}</span>
          <span className="expert-file-name">{file.name}<small>{(file.size / (1024 * 1024)).toFixed(1)} MiB · ready to upload</small></span>
        </li>)}</ul>
        <div className="expert-dropzone-actions"><span>{files.length} file{files.length === 1 ? "" : "s"} selected</span>{uploadAction}</div>
      </>}
      <small>PDF or UTF-8 TXT · up to 20 MiB per file</small>
    </div> : <div className="expert-selected-materials">
      <h3>Select a course material <span>{documents.length}</span></h3>
      {documents.length > 0 && <p className="expert-muted">{selection === "all" ? "Selected: all course materials" : selectedDocument ? `Selected: ${selectedDocument.filename}` : "Choose a material for this run."}{lockedSelection && " Change the workspace Material filter to choose another."}</p>}
      {documents.length === 0 ? <p className="expert-muted">No materials in this course yet. Use Upload files to add one.</p> : <ul className="expert-material-list">
        <li className={selection === "all" ? "active" : ""}><button type="button" disabled={disabled || !!lockedSelection} aria-pressed={selection === "all"} onClick={() => onSelect("all")}>All course materials</button></li>
        {documents.map((doc) => <li key={doc.id} className={selection === doc.id ? "active" : ""}>
          <button type="button" disabled={disabled || (!!lockedSelection && doc.id !== lockedSelection)} aria-pressed={selection === doc.id} onClick={() => onSelect(doc.id)}>
            <span className="expert-file-type">{doc.filename.split(".").pop()?.toUpperCase()}</span>
            <span className="expert-file-name">{doc.filename}<small>{doc.pages ? `${doc.pages} pages` : "Page count pending"}</small></span>
            <span className={`expert-status-tag ${doc.status}`}>{doc.status.replaceAll("_", " ")}</span>
          </button>
        </li>)}
      </ul>}
    </div>}
  </>;
}
