"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useWorkspace } from "./workspace-provider";
const navigation = [["/materials", "Materials"], ["/learn", "Learning"], ["/tutor", "Chat with tutor"]];
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { courses, courseId, selectCourse } = useWorkspace();
  if (pathname.startsWith("/workbench")) return <>{children}</>;
  return <div className="learner-shell">
    <a href="#main" className="skip-link">Skip to content</a>
    <header className="learner-topbar">
      <Link href="/learn" className="learner-brand"><span aria-hidden="true">◈</span> LearnLoop</Link>
      <nav className="learner-nav" aria-label="Main navigation">{navigation.map(([href, label]) => <Link key={href} href={href} className={pathname === href || (href === "/learn" && pathname.startsWith("/learn/")) ? "active" : ""} aria-current={pathname === href || (href === "/learn" && pathname.startsWith("/learn/")) ? "page" : undefined}>{label}</Link>)}</nav>
      <label className="learner-course">Course<select value={courseId} onChange={event => selectCourse(event.target.value)} disabled={!courses.length}>{!courses.length && <option value="">No courses yet</option>}{courses.map(course => <option key={course.id} value={course.id}>{course.title}</option>)}</select></label>
      <Link href="/workbench/expert" className="learner-workbench-link">Agent workbench ↗</Link>
    </header>
    <main id="main" className="learner-main" tabIndex={-1}>{children}</main>
  </div>;
}
