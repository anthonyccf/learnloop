"use client";

import { useState } from "react";
import { useWorkspace } from "./workspace-provider";
import { LearningDialog } from "./learning-dialog";

export function LessonPicker({ selectedId, onSelect, onPractice, onClose }: {
  selectedId: string; onSelect: (id: string) => void; onPractice: () => void; onClose: () => void;
}) {
  const { course, materials } = useWorkspace();
  const [query, setQuery] = useState("");
  const matches = materials.materials.filter(item => `${item.lesson.title} ${item.filename}`.toLowerCase().includes(query.trim().toLowerCase()));
  const topics = course?.graph.topics || [];
  const grouped = new Set(topics.flatMap(topic => topic.conceptIds));
  const groups = [
    ...topics.map(topic => ({ title: topic.title, lessons: matches.filter(item => topic.conceptIds.includes(item.conceptId)) })),
    { title: topics.length ? "Other lessons" : "Course lessons", lessons: matches.filter(item => !grouped.has(item.conceptId)) },
  ].filter(group => group.lessons.length);
  return <LearningDialog title="Choose a lesson" onClose={onClose}>
    <label className="lesson-picker-search">Search lessons<input type="search" placeholder="Search by lesson or material…" value={query} onChange={event => setQuery(event.target.value)} /></label>
    <div className="lesson-picker-results" aria-label="Available lessons">
      {!matches.length && <p role="status">No lessons match your search.</p>}
      {groups.map(group => <section key={group.title}><h3>{group.title}</h3><ul>{group.lessons.map(item => <li key={item.conceptId}><button aria-current={selectedId === item.conceptId ? "true" : undefined} onClick={() => onSelect(item.conceptId)}>{item.lesson.title}{selectedId === item.conceptId && <span>Current lesson</span>}</button></li>)}</ul></section>)}
    </div>
    <button className="lesson-general-practice" onClick={onPractice}>Practice across course →</button>
  </LearningDialog>;
}
