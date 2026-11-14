"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useWorkspace } from "@/components/workspace-provider";
import { workbenchAgents, type WorkbenchAgent } from "@/lib/expert-templates";

export type ExpertPage = "edit" | "run" | "evaluation";

const expertPages: { id: ExpertPage; label: string; href: string; detail: string }[] = [
  { id: "edit", label: "Edit agent", href: "/workbench/expert/edit", detail: "Prompts and settings" },
  { id: "run", label: "Run", href: "/workbench/expert", detail: "Ingestion and activity" },
  { id: "evaluation", label: "Evaluation", href: "/workbench/expert/evaluation", detail: "Compare templates" },
];

export function ExpertWorkbenchShell({ activePage, activeAgent = "expert", onAgentChange, railContent, children }: { activePage: ExpertPage; activeAgent?: WorkbenchAgent; onAgentChange?: (agent: WorkbenchAgent) => void; railContent?: ReactNode; children: ReactNode }) {
  const workspace = useWorkspace();
  const materials = workspace.course?.documents || [];
  return <div className={`expert-workbench ${railContent ? "expert-workbench-with-rail-content" : ""}`}>
    <header className="expert-topbar">
      <Link href="/workbench/expert" className="expert-brand"><span className="expert-brand-mark" aria-hidden="true">◈</span> LearnLoop Agent Workbench</Link>
      <nav aria-label="Workbench navigation" className="expert-topnav">
        <Link href="/workbench/expert" className="active" aria-current="page">Workbench</Link>
        <Link href="/agents">Run history</Link>
      </nav>
      <span className="expert-env">Local workspace</span>
    </header>

    <aside className="expert-agent-rail" aria-label="Agent modes">
      <section className="expert-rail-context" aria-label="Shared course and material filters">
        <p className="expert-rail-label">Workspace context</p>
        <label className="expert-course-select">Course
          <select value={workspace.courseId} onChange={(event) => workspace.selectCourse(event.target.value)} disabled={!workspace.courses.length}>
            {!workspace.courses.length && <option value="">No courses</option>}
            {workspace.courses.map((course) => <option key={course.id} value={course.id}>{course.title}</option>)}
          </select>
        </label>
        <label className="expert-course-select">Material
          <select value={workspace.materialId} onChange={(event) => workspace.selectMaterial(event.target.value)} disabled={!materials.length}>
            <option value="">All course materials</option>
            {materials.map((material) => <option key={material.id} value={material.id}>{material.filename}</option>)}
          </select>
        </label>
        <p className="expert-rail-context-note">Shared across agents and pages</p>
      </section>
      <p className="expert-rail-label">Agent modes</p>
      {workbenchAgents.map((agent) => <button key={agent.id} type="button" className={`expert-mode ${activeAgent === agent.id ? "selected" : ""}`} aria-current={activeAgent === agent.id ? "page" : undefined} aria-pressed={onAgentChange ? activeAgent === agent.id : undefined} disabled={!onAgentChange && activeAgent !== agent.id} onClick={() => onAgentChange?.(agent.id)}><span aria-hidden="true">{agent.id === "expert" ? "✦" : agent.id === "tutor" ? "◌" : "▣"}</span> {agent.label}</button>)}
      <button className="expert-mode" disabled title="Full-loop workbench is planned"><span>↔</span> Full learning loop</button>
      {railContent && <div className="expert-rail-custom">{railContent}</div>}
      <div className="expert-rail-bottom"><span className="expert-status-dot" /> Expert agent tools</div>
    </aside>

    <main className="expert-main">
      <nav className="expert-subnav" aria-label="Expert agent pages">
        {expertPages.map((page) => <Link key={page.id} href={page.href} className={activePage === page.id ? "active" : ""} aria-current={activePage === page.id ? "page" : undefined}>
          <strong>{page.label}</strong><span>{page.detail}</span>
        </Link>)}
      </nav>
      {children}
    </main>
  </div>;
}
