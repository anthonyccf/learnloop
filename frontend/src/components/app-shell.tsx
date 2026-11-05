"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon } from "./icons";
import { useWorkspace } from "./workspace-provider";
const navigation = [
  ["/", "Today", "home"],
  ["/learn", "Learn", "book"],
  ["/tutor", "Tutor session", "spark"],
  ["/map", "My understanding", "map"],
  ["/materials", "Materials", "folder"],
  ["/progress", "Progress", "chart"],
  ["/agents", "Agent activity", "spark"],
];
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const activePath = pathname.startsWith("/learn") ? "/learn" : pathname;
  return (
    <div className="app-shell">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <aside className="sidebar">
        <Link href="/" className="brand">
          <span className="brand-mark">
            <Icon name="leaf" size={25} />
          </span>
          learnloop<span className="brand-dot">.</span>
        </Link>
        <CoursePicker id="workspace-course" />
        <p className="nav-caption">YOUR WORKSPACE</p>
        <nav aria-label="Main navigation">
          {navigation.map(([href, title, icon]) => (
            <Link
              key={href}
              href={href}
              className={activePath === href ? "nav-item active" : "nav-item"}
              aria-current={activePath === href ? "page" : undefined}
            >
              <Icon name={icon} />
              <span>{title}</span>
            </Link>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="profile">
            <span className="avatar">YL</span>
            <div>
              <strong>Your learning space</strong>
              <small>Personal learning workspace</small>
            </div>
          </div>
        </div>
      </aside>
      <div className="workspace">
        <header className="mobile-course-header">
          <CoursePicker id="mobile-workspace-course" />
        </header>
        <main id="main" tabIndex={-1}>
          {children}
        </main>
        <footer className="footer">
          Built around your understanding.
          <span>Course materials and progress saved on the server</span>
        </footer>
      </div>
    </div>
  );
}

function CoursePicker({ id }: { id: string }) {
  const { courses, courseId, selectCourse } = useWorkspace();
  return (
    <div className="course-picker">
      <label htmlFor={id}>Your course
        <select id={id} value={courseId} onChange={e => selectCourse(e.target.value)}>
          {!courses.length && <option value="">Create a course in Materials</option>}
          {courses.map(c => <option key={c.id} value={c.id}>{c.title}</option>)}
        </select>
      </label>
    </div>
  );
}
