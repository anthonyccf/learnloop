"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type Assessment } from "@/lib/backend";
import { useWorkspace } from "./workspace-provider";
import { PreparationStatus } from "./learning-status";
import { RichText } from "./rich-text";
import { Icon } from "./icons";

type RecentAttempt = {
  id: string;
  conceptId: string;
  at: string;
  difficulty: string;
  assessment: Assessment | null;
};

const stateLabels: Record<string, string> = {
  unassessed: "Not assessed",
  developing: "Developing",
  demonstrated: "Demonstrated",
  review_due: "Review due",
};

export function TodayWorkspace() {
  const { course, courseId, learner, materials } = useWorkspace();
  const [history, setHistory] = useState<RecentAttempt[] | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let active = true;
    api<RecentAttempt[]>(`courses/${courseId}/assessments`).then(items => {
      if (active) { setHistory(items); setError(""); }
    }).catch((reason: Error) => {
      if (active) setError(reason.message);
    });
    return () => { active = false; };
  }, [courseId, learner?.version, retry]);

  if (!course) return null;

  const lessons = materials.materials;
  if (!lessons.length) return <section className="today-start" aria-labelledby="today-start-title">
    <h2 id="today-start-title">{course.documents.length ? "Your lessons are on their way." : "Start with something you want to learn."}</h2>
    <p>{course.documents.length ? "Ready lessons will appear here as your materials are prepared." : "Add your lecture notes or a reading. We’ll turn them into lessons you can work through at your own pace."}</p>
    <Link href="/materials" className="button dark">{course.documents.length ? "View materials" : "Add materials"}<Icon name="arrow" size={17} /></Link>
    <PreparationStatus />
  </section>;

  const ordered = [...(history || [])].sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
  const recent = ordered.filter((item, index, items) =>
    course.graph.concepts.some(concept => concept.id === item.conceptId) &&
    items.findIndex(other => other.conceptId === item.conceptId) === index
  ).slice(0, 3);
  const previousLesson = ordered.map(item => lessons.find(lesson => lesson.conceptId === item.conceptId)).find(Boolean);
  const lesson = previousLesson || lessons[0];
  const href = `/learn?concept=${encodeURIComponent(lesson.conceptId)}`;

  return <div className="today-content">
    <section className="today-next" aria-labelledby="today-next-title">
      <h2 id="today-next-title">{previousLesson ? "Continue learning" : "Start with one idea"}</h2>
      {history === null && !error ? <p role="status">Finding your recent learning…</p> : <>
        <h3>{lesson.lesson.title}</h3>
        <RichText className="today-objective">{lesson.lesson.objective}</RichText>
        <Link className="button dark today-primary" href={href}>{previousLesson ? "Return to lesson" : "Start lesson"}<Icon name="arrow" size={18} /></Link>
        <p className="today-context">{previousLesson ? "A lesson you recently practiced. Take another look, then try a question when you’re ready." : "A starting point from your course materials. Read the idea, then try it for yourself."}</p>
      </>}
    </section>

    <section className="today-recent" aria-labelledby="today-recent-title">
      <div className="today-section-heading"><h2 id="today-recent-title">Recent learning</h2><Link href="/progress">View progress <Icon name="arrow" size={15} /></Link></div>
      {error ? <div className="today-history-error" role="alert"><p>Couldn’t load recent practice. Your lessons are still available.</p><button onClick={() => { setError(""); setRetry(value => value + 1); }}>Try again</button></div> : history === null ? <p className="today-empty" role="status">Loading recent practice…</p> : !recent.length ? <p className="today-empty">Your practiced concepts will appear here. Begin with a lesson above.</p> : <ul className="today-recent-list">
        {recent.map(item => {
          const concept = course.graph.concepts.find(c => c.id === item.conceptId)!;
          const material = lessons.find(entry => entry.conceptId === item.conceptId);
          const state = learner?.concepts[item.conceptId]?.[item.difficulty]?.state || "unassessed";
          return <li key={item.conceptId}>
            <Link className="today-recent-link" href={material ? `/learn?concept=${encodeURIComponent(item.conceptId)}` : `/map?concept=${encodeURIComponent(item.conceptId)}`}>
              <div><h3>{material?.lesson.title || concept.title}</h3><span className="today-level">{item.difficulty}</span></div>
              <span className={`today-evidence today-evidence-${state}`}>{stateLabels[state] || "Not assessed"}</span>
              <Icon name="arrow" size={17} />
            </Link>
          </li>;
        })}
      </ul>}
    </section>
    <PreparationStatus />
  </div>;
}
