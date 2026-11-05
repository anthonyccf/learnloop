"use client";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, Course, CourseDetail, LearnerState, RunSummary, LearningMaterials } from "@/lib/backend";

function useWorkspaceData() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [courseId, setCourseId] = useState("");
  const [course, setCourse] = useState<CourseDetail | null>(null);
  const [learner, setLearner] = useState<LearnerState | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [materials, setMaterials] = useState<LearningMaterials>({ materials: [], expectedCount: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const selected = useRef("");
  const loadedMaterials = useRef("");
  const refreshing = useRef(false);
  const refreshAgain = useRef(false);
  const selectCourse = useCallback((id: string) => {
    selected.current = id; setCourseId(id); setCourse(null); setLearner(null); setRuns([]);
    setMaterials({ materials: [], expectedCount: 0 });
    loadedMaterials.current = "";
    try { localStorage.setItem("learnloop-course-id", id); } catch {}
  }, []);
  const loadCourses = useCallback(async () => {
    const items = await api<Course[]>("courses"); setCourses(items);
    let saved = selected.current;
    try { saved ||= localStorage.getItem("learnloop-course-id") || ""; } catch {}
    const id = items.some(c => c.id === saved) ? saved : items[0]?.id || "";
    if (id !== selected.current) selectCourse(id);
  }, [selectCourse]);
  const refresh = useCallback(async () => {
    if (refreshing.current) { refreshAgain.current = true; return; }
    refreshing.current = true;
    try {
      do {
        refreshAgain.current = false;
        const id = selected.current;
        if (!id) return;
        try {
          const [detail, state, activity] = await Promise.all([api<CourseDetail>(`courses/${id}`), api<LearnerState>(`courses/${id}/learner-state`), api<RunSummary[]>(`courses/${id}/runs`)]);
          if (selected.current !== id) continue;
          setCourse(detail); setLearner(state); setRuns(activity);
          const stamp = `${detail.documents.map(doc => [doc.id, doc.status, doc.lessonCount, doc.postLessonCount ?? "", doc.testCount].join(":")).join("|")}|${detail.graph.concepts.length}`;
          if (stamp !== loadedMaterials.current) {
            const learning = await api<LearningMaterials>(`courses/${id}/materials`);
            if (selected.current !== id) continue;
            if (!Array.isArray(learning.materials)) throw new Error("Course materials were unreadable. Please refresh and retry.");
            setMaterials(learning);
            loadedMaterials.current = stamp;
          }
          if (selected.current === id) setError("");
        } catch (e) { if (selected.current === id) setError((e as Error).message); }
      } while (refreshAgain.current);
    } finally { refreshing.current = false; }
  }, []);
  useEffect(() => { void Promise.resolve().then(loadCourses).catch(e => setError(e.message)).finally(() => setLoading(false)); }, [loadCourses]);
  useEffect(() => { void refresh(); const timer = setInterval(() => void refresh(), 4000); return () => clearInterval(timer); }, [courseId, refresh]);
  return { courses, courseId, course, learner, runs, materials, loading, error, selectCourse, loadCourses, refresh };
}
const Context = createContext<ReturnType<typeof useWorkspaceData> | null>(null);
export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const value = useWorkspaceData(); return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useWorkspace() { const value = useContext(Context); if (!value) throw new Error("Workspace provider required"); return value; }
