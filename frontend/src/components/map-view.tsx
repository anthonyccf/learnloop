"use client";
import Link from "next/link";
import { useEffect, useReducer, useState } from "react";
import { concepts, labels } from "@/lib/demo-data";
import {
  conceptSources,
  describeAttempt,
  difficulties,
  difficultyLabels,
  getConceptEvidence,
  getLearnerConcepts,
  relatedConnections,
  type Difficulty,
  type SourceReference,
} from "@/lib/learner-evidence";
import { useDemo } from "./demo-provider";
import { Icon } from "./icons";
import { PageHeading, SourceDrawer, StateBadge } from "./ui";

type Selection = { id: string; mode: "learner" | "course"; level: Difficulty };
export function MapView() {
  const { state } = useDemo();
  const [selection, setSelection] = useReducer(
    (_: Selection, next: Selection) => next,
    { id: "descent", mode: "learner", level: "intermediate" },
  );
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [lecture, setLecture] = useState("all");
  const [zoom, setZoom] = useState(1);
  const [source, setSource] = useState<SourceReference | null>(null);
  useEffect(() => {
    const sync = () => {
      const params = new URLSearchParams(window.location.search);
      setSelection({
        id: concepts.some((c) => c.id === params.get("concept"))
          ? params.get("concept")!
          : "descent",
        mode: params.get("view") === "course" ? "course" : "learner",
        level: difficulties.includes(params.get("level") as Difficulty)
          ? (params.get("level") as Difficulty)
          : "intermediate",
      });
    };
    sync();
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);
  function select(next: Partial<Selection>) {
    const value = { ...selection, ...next };
    setSelection(value);
    const params = new URLSearchParams({
      concept: value.id,
      view: value.mode === "course" ? "course" : "understanding",
      level: value.level,
    });
    window.history.replaceState(null, "", `/map?${params}`);
  }
  const personal = selection.mode === "learner";
  const rows = getLearnerConcepts(state);
  const current = rows.find((c) => c.id === selection.id)!;
  const evidence = getConceptEvidence(current, state);
  const currentState = evidence.levels[selection.level];
  const stateAt = (id: string) =>
    getConceptEvidence(
      rows.find((c) => c.id === id)!,
      state,
    ).levels[selection.level].state;
  const shown = rows.filter(
    (c) =>
      c.title.toLowerCase().includes(query.toLowerCase()) &&
      (lecture === "all" || conceptSources[c.id].lecture === lecture) &&
      (!personal || filter === "all" || stateAt(c.id) === filter),
  );
  const matches = new Set(shown.map((c) => c.id));
  const unmet = current.prerequisites.filter(
    (id) => rows.find((c) => c.id === id)?.state !== "demonstrated",
  );
  const ready = unmet.length === 0;
  const nearby = new Set([
    current.id,
    ...current.prerequisites,
    ...rows
      .filter((c) => c.prerequisites.includes(current.id))
      .map((c) => c.id),
  ]);
  const links = relatedConnections.filter(
    (link) => link.from === current.id || link.to === current.id,
  );
  const edgeCount = concepts.reduce(
    (count, c) => count + c.prerequisites.length,
    0,
  );
  return (
    <>
      <PageHeading
        eyebrow="YOUR COURSE, CONNECTED"
        title="My understanding"
        description="See how the ideas fit together — and where your understanding stands."
      />
      <section className="map-overview panel">
        <div className="map-overview-top">
          <div className="map-mode-switch" role="group" aria-label="Map view">
            <button
              aria-pressed={personal}
              onClick={() => select({ mode: "learner" })}
            >
              <Icon name="chart" size={16} />
              My understanding
            </button>
            <button
              aria-pressed={!personal}
              onClick={() => select({ mode: "course" })}
            >
              <Icon name="map" size={16} />
              Course structure
            </button>
          </div>
          <span className="tag">COMP7608B · 12 concepts · Sample course</span>
        </div>
        {personal ? (
          <>
            <div className="map-level-row">
              <div>
                <h2>Evidence at each difficulty</h2>
                <p>Readiness always follows the Intermediate target.</p>
              </div>
              <div
                className="difficulty-switch"
                role="group"
                aria-label="Evidence difficulty"
              >
                {difficulties.map((level) => (
                  <button
                    key={level}
                    aria-pressed={selection.level === level}
                    onClick={() => select({ level })}
                  >
                    {difficultyLabels[level]}
                  </button>
                ))}
              </div>
            </div>
            <div className="map-state-counts">
              {Object.entries(labels).map(([status, label]) => (
                <button
                  key={status}
                  aria-pressed={filter === status}
                  onClick={() => setFilter(filter === status ? "all" : status)}
                >
                  <StateBadge state={status as keyof typeof labels} />
                  <strong>
                    {rows.filter((c) => stateAt(c.id) === status).length}
                  </strong>
                  <span className="sr-only">
                    {label} concepts across the whole unit
                  </span>
                </button>
              ))}
            </div>
          </>
        ) : (
          <div className="structure-intro">
            <Icon name="map" size={27} />
            <div>
              <h2>The course’s shared concept graph</h2>
              <p>
                {edgeCount} prerequisite connections and{" "}
                {relatedConnections.length} related-topic links across two
                sample lectures. This view shows course organization without
                personal progress colors.
              </p>
            </div>
          </div>
        )}
        <p className="map-data-note">
          {personal
            ? `${difficultyLabels[selection.level]} evidence across the whole unit. `
            : ""}
          Source locations and earlier learner history are illustrative. New
          practice attempts come from this browser’s demo session.
        </p>
      </section>
      <div className="map-layout understanding-layout">
        <section
          className="panel map-panel"
          aria-label={
            personal ? "Personal knowledge graph" : "Course knowledge graph"
          }
        >
          <div className="map-toolbar">
            <label className="search-field">
              <Icon name="search" size={16} />
              <input
                aria-label="Find a concept"
                placeholder="Find a concept…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <select
              aria-label="Filter course material"
              value={lecture}
              onChange={(e) => setLecture(e.target.value)}
            >
              <option value="all">All materials</option>
              <option value="2">Lecture 2 · Foundations</option>
              <option value="3">Lecture 3 · Training</option>
            </select>
            {personal && (
              <select
                aria-label="Filter concept state"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              >
                <option value="all">All states</option>
                {Object.entries(labels).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            )}
          </div>
          <div className="graph-context">
            <span>
              {shown.length} of {rows.length} concepts match ·{" "}
              {personal
                ? `${difficultyLabels[selection.level]} evidence`
                : "Shared course structure"}
            </span>
            <a href="#concept-details">
              Selected: {current.title}
              <Icon name="chevron" size={12} />
            </a>
          </div>
          <div
            className="graph-scroll"
            tabIndex={0}
            role="region"
            aria-label="Scrollable concept graph; use the concept list below as an alternative"
          >
            <div
              className="graph-canvas"
              style={{ width: 780 * zoom, height: 640 * zoom }}
            >
              <svg viewBox="0 0 780 640" aria-hidden="true">
                <defs>
                  <marker
                    id="arrowhead"
                    markerWidth="7"
                    markerHeight="7"
                    refX="6"
                    refY="3.5"
                    orient="auto"
                  >
                    <path d="M0 0 7 3.5 0 7" fill="none" stroke="#879e80" />
                  </marker>
                </defs>
                {relatedConnections.map((link) => {
                  const from = rows.find((c) => c.id === link.from)!;
                  const to = rows.find((c) => c.id === link.to)!;
                  return (
                    <path
                      key={`${link.from}-related-${link.to}`}
                      d={`M${from.x} ${from.y + 32} Q${(from.x + to.x) / 2} ${Math.max(from.y, to.y) + 65} ${to.x} ${to.y + 32}`}
                      fill="none"
                      stroke="#ab9bbd"
                      strokeWidth="1.5"
                      strokeDasharray="5 5"
                    />
                  );
                })}
                {rows.flatMap((c) =>
                  c.prerequisites.map((id) => {
                    const parent = rows.find((p) => p.id === id)!;
                    const highlighted =
                      c.id === current.id || id === current.id;
                    return (
                      <path
                        key={`${id}-${c.id}`}
                        d={`M${parent.x} ${parent.y + 28} C${parent.x} ${parent.y + 65},${c.x} ${c.y - 65},${c.x} ${c.y - 31}`}
                        fill="none"
                        stroke={highlighted ? "#78976c" : "#c3cebc"}
                        strokeWidth={highlighted ? "2" : "1.2"}
                        markerEnd="url(#arrowhead)"
                      />
                    );
                  }),
                )}
              </svg>
              {rows.map((c) => {
                const status = stateAt(c.id);
                const locked = c.prerequisites.some(
                  (id) =>
                    rows.find((p) => p.id === id)?.state !== "demonstrated",
                );
                return (
                  <button
                    key={c.id}
                    style={{
                      left: `${(c.x / 780) * 100}%`,
                      top: `${(c.y / 640) * 100}%`,
                    }}
                    className={`concept-node ${personal ? status : "course-node"} ${c.id === current.id ? "selected" : ""} ${matches.has(c.id) ? "" : "dimmed"} ${nearby.has(c.id) ? "connected" : ""}`}
                    onClick={() => select({ id: c.id })}
                    aria-pressed={c.id === current.id}
                    aria-label={`${c.title}: ${personal ? `${labels[status]} at ${difficultyLabels[selection.level]}${locked ? "; prerequisites need attention" : ""}` : `Lecture ${conceptSources[c.id].lecture}`}`}
                  >
                    <span className="node-symbol">
                      <Icon
                        name={
                          !personal
                            ? "book"
                            : status === "demonstrated"
                              ? "check"
                              : status === "review_due"
                                ? "clock"
                                : status === "developing"
                                  ? "chart"
                                  : "book"
                        }
                        size={15}
                      />
                    </span>
                    <span className="node-copy">
                      <strong>{c.title}</strong>
                      <small>
                        {personal
                          ? labels[status]
                          : `Lecture ${conceptSources[c.id].lecture}`}
                        {personal && locked && <Icon name="lock" size={10} />}
                      </small>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
          <div className="map-bottom">
            <span>Explore connections · select a concept for evidence</span>
            <div className="zoom-controls">
              <button
                aria-label="Zoom out"
                disabled={zoom <= 0.8}
                onClick={() => setZoom((z) => Math.max(0.8, z - 0.2))}
              >
                −
              </button>
              <button onClick={() => setZoom(1)}>Reset</button>
              <button
                aria-label="Zoom in"
                disabled={zoom >= 1.6}
                onClick={() => setZoom((z) => Math.min(1.6, z + 0.2))}
              >
                +
              </button>
            </div>
          </div>
          <div className="relationship-legend">
            <span>
              <i className="prerequisite-line" />
              Prerequisite → next concept
            </span>
            <span>
              <i className="related-line" />
              Related topic · no required order
            </span>
          </div>
        </section>
        <aside
          id="concept-details"
          className="panel concept-details"
          tabIndex={-1}
        >
          <div className="concept-detail-title" aria-live="polite">
            <p className="eyebrow">
              {personal ? "YOUR CONCEPT EVIDENCE" : "COURSE CONCEPT"}
            </p>
            <h2>{current.title}</h2>
            {personal && (
              <>
                <StateBadge state={currentState.state} />
                <span className="detail-difficulty">
                  At {difficultyLabels[selection.level]}
                </span>
              </>
            )}
          </div>
          <p>{current.summary}</p>
          {personal && (
            <>
              <p className="evidence-reason">
                {evidence.reason(selection.level)}
              </p>
              <section className="concept-levels">
                <h3>Evidence by difficulty</h3>
                {difficulties.map((level) => (
                  <button
                    key={level}
                    aria-pressed={selection.level === level}
                    onClick={() => select({ level })}
                  >
                    <span>
                      <strong>{difficultyLabels[level]}</strong>
                      <small>
                        {evidence.levels[level].independent} independent ·{" "}
                        {evidence.levels[level].assisted} assisted
                        {level === "intermediate" ? " · target" : ""}
                      </small>
                    </span>
                    <StateBadge state={evidence.levels[level].state} />
                  </button>
                ))}
              </section>
              {evidence.misconception && (
                <div className="concept-gap">
                  <Icon name="hint" size={17} />
                  <div>
                    <h3>Idea to revisit</h3>
                    <p>{evidence.misconception}</p>
                  </div>
                </div>
              )}
              <div className="review-dates">
                <span>
                  Last assessed at target
                  <strong>{evidence.lastAssessed}</strong>
                </span>
                <span>
                  Target-level review<strong>{evidence.review}</strong>
                </span>
              </div>
            </>
          )}
          <div className="detail-divider" />
          <h3>Before this concept</h3>
          {current.prerequisites.length ? (
            current.prerequisites.map((id) => (
              <button
                key={id}
                className="prereq-item"
                onClick={() => select({ id })}
              >
                <Icon
                  name={
                    personal
                      ? rows.find((c) => c.id === id)?.state === "demonstrated"
                        ? "check"
                        : "clock"
                      : "book"
                  }
                  size={15}
                />
                <span>
                  {rows.find((c) => c.id === id)?.title}
                  {personal && (
                    <small>
                      {rows.find((c) => c.id === id)?.state === "demonstrated"
                        ? "Ready at target"
                        : "Needs target-level evidence"}
                    </small>
                  )}
                </span>
                <Icon name="chevron" size={13} />
              </button>
            ))
          ) : (
            <p className="micro-copy">A starting concept. No prerequisites.</p>
          )}
          {links.length > 0 && (
            <>
              <h3 className="related-title">Related ideas</h3>
              {links.map((link) => {
                const id = link.from === current.id ? link.to : link.from;
                return (
                  <button
                    className="prereq-item"
                    key={id}
                    onClick={() => select({ id })}
                  >
                    <span>
                      {rows.find((c) => c.id === id)?.title}
                      <small>{link.label} · no required order</small>
                    </span>
                    <Icon name="chevron" size={13} />
                  </button>
                );
              })}
            </>
          )}
          <div className="detail-divider" />
          <h3>In your course materials</h3>
          <button
            className="concept-source"
            onClick={() => setSource(evidence.source)}
          >
            <span className="small-icon lavender">
              <Icon name="source" size={17} />
            </span>
            <span>
              <strong>{evidence.source.title}</strong>
              <small>
                Lecture {evidence.source.lecture} · Slide {evidence.source.page}{" "}
                · Sample
              </small>
            </span>
            <Icon name="chevron" size={14} />
          </button>
          {personal && (
            <>
              <div className="detail-divider" />
              <details
                className="attempt-history"
                open={evidence.history.length > 0}
              >
                <summary>
                  Recent assessment history{" "}
                  <span>
                    {evidence.history.length
                      ? `${evidence.history.length} new`
                      : "Sample history"}
                  </span>
                </summary>
                {evidence.history.length ? (
                  <ol>
                    {[...evidence.history]
                      .reverse()
                      .slice(0, 5)
                      .map((record) => {
                        const detail = describeAttempt(record);
                        return (
                          <li key={record.id}>
                            <div className="attempt-result">
                              <Icon
                                name={record.correct ? "check" : "hint"}
                                size={14}
                              />
                              <strong>
                                {record.correct ? "Correct" : "Needs practice"}
                                {record.hinted
                                  ? " · hint used"
                                  : " · independent attempt"}
                              </strong>
                            </div>
                            <small>
                              Intermediate ·{" "}
                              <time dateTime={record.at}>
                                {new Intl.DateTimeFormat("en-SG", {
                                  timeZone: "Asia/Singapore",
                                  day: "numeric",
                                  month: "short",
                                  hour: "2-digit",
                                  minute: "2-digit",
                                }).format(new Date(record.at))}
                              </time>{" "}
                              SGT
                            </small>
                            <p>{detail.question}</p>
                            <blockquote>{detail.answer}</blockquote>
                            <small>
                              {record.correct && !record.hinted
                                ? "Qualifying response; a repeated question counts once."
                                : "Retained as diagnostic evidence."}
                            </small>
                          </li>
                        );
                      })}
                  </ol>
                ) : (
                  <p className="history-placeholder">
                    {current.state === "unassessed"
                      ? "No assessment recorded at the target yet."
                      : current.state === "review_due"
                        ? "Two earlier independent target-level responses are retained in this sample. Reassessment is due."
                        : current.state === "demonstrated"
                          ? "This sample history includes two distinct independent target-level responses."
                          : "The sample snapshot records developing evidence at the target. Complete MC practice to see your actual demo selections here."}
                  </p>
                )}
                {(state.records[current.id]?.attempts || 0) >
                  evidence.history.length && (
                  <p className="micro-copy">
                    Earlier saved demo attempts have summary counts only.
                  </p>
                )}
              </details>
              <div className="next-learning-step">
                <p className="eyebrow">A USEFUL NEXT STEP</p>
                <p>
                  {!ready
                    ? "Build the prerequisite evidence before starting this concept."
                    : current.state === "review_due"
                      ? "Revisit the source before reassessing this concept."
                      : current.state !== "demonstrated"
                        ? "Try a short MC check and connect the update rule to its meaning."
                        : current.state === "demonstrated"
                          ? "Explore the next connected concept, or revisit your source."
                          : "Begin with the source and a quick concept check."}
                </p>
                {!ready ? (
                  <button
                    className="button secondary"
                    onClick={() => select({ id: unmet[0] })}
                  >
                    Revisit {rows.find((c) => c.id === unmet[0])?.title}
                    <Icon name="arrow" size={15} />
                  </button>
                ) : (
                  <Link
                    className="button dark"
                    href={`/learn?concept=${current.id}`}
                  >
                    {current.state === "demonstrated"
                      ? "View MC practice"
                      : "Practice with MC questions"}
                    <Icon name="arrow" size={15} />
                  </Link>
                )}
                <small>
                  Two authored MC questions per concept · frontend demo.
                </small>
              </div>
            </>
          )}
        </aside>
      </div>
      <details className="panel concept-list" open>
        <summary>Browse concepts without the graph ({shown.length})</summary>
        <div>
          {shown.length ? (
            shown.map((c) => (
              <button
                key={c.id}
                onClick={() => select({ id: c.id })}
                aria-pressed={current.id === c.id}
              >
                <span>
                  {c.title}
                  <small>Lecture {conceptSources[c.id].lecture}</small>
                </span>
                {personal ? (
                  <StateBadge state={stateAt(c.id)} />
                ) : (
                  <Icon name="chevron" size={14} />
                )}
              </button>
            ))
          ) : (
            <p>No matching concepts. Try another search, material, or state.</p>
          )}
        </div>
      </details>
      {source && (
        <SourceDrawer source={source} onClose={() => setSource(null)} />
      )}
    </>
  );
}
