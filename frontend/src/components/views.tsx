"use client";
import Link from "next/link";
import { useState } from "react";
import { concepts, documents, labels } from "@/lib/demo-data";
import { useDemo } from "./demo-provider";
import { Icon } from "./icons";
import { PageHeading, SourceDrawer, StateBadge } from "./ui";
import { getConceptEvidence, getLearnerConcepts } from "@/lib/learner-evidence";
import { recommendedConcept, unmetPrerequisites } from "@/lib/practice-session";
import { AgentContextNotice } from './agent-activity';
export function TodayView() {
  const { state, dispatch } = useDemo();
  const learnerConcepts = getLearnerConcepts(state);
  const demonstrated = learnerConcepts.filter(
    (concept) => concept.state === "demonstrated",
  ).length;
  const active = concepts.find((concept) => concept.id === state.conceptId)!;
  const recommended =
    state.ended || unmetPrerequisites(active.id, state.records).length > 0
      ? recommendedConcept(active.id, state.records) || active
      : active;
  const recommendedRecord = state.records[recommended.id];
  const reviews = learnerConcepts.filter(
    (concept) => concept.state === "review_due",
  );
  return (
    <>
      <PageHeading
        eyebrow="YOUR DAILY LEARNING LOOP"
        title="Make room for a little discovery."
        description="Pick up where you left off. One concept at a time."
        action={
          <span className="quiet-tag">
            <Icon name="book" size={15} />
            Training & optimization
          </span>
        }
      />
      <div className="today-grid">
        <div className="main-stack">
          <section className="hero-card">
            <div className="hero-content">
              <span className="hero-kicker">
                <span className="pulse-dot" />
                YOUR NEXT STEP
              </span>
              <h2>
                A clearer picture of
                <br />
                {recommended.title.toLowerCase()}.
              </h2>
              <p>{recommended.summary}</p>
              <div className="hero-meta">
                <span>
                  <Icon name="clock" size={15} />
                  About 8 minutes
                </span>
                <span>Intermediate</span>
              </div>
              <Link
                href={`/learn?concept=${recommended.id}`}
                className="button dark"
                onClick={() => {
                  dispatch({ type: "activate", conceptId: recommended.id });
                  if (recommendedRecord?.ended) dispatch({ type: "restart" });
                }}
              >
                {recommendedRecord &&
                !recommendedRecord.ended &&
                (recommendedRecord.answer || recommendedRecord.attempts)
                  ? "Resume learning"
                  : "Start learning"}
                <Icon name="arrow" size={18} />
              </Link>
              <small className="hero-footnote">
                Your place is saved as you go.
              </small>
            </div>
            <div className="descent-art" aria-hidden="true">
              <svg viewBox="0 0 300 280">
                <defs>
                  <linearGradient id="terrain" x2="0" y2="1">
                    <stop stopColor="#b9d4c0" stopOpacity=".5" />
                    <stop offset="1" stopColor="#e0eadb" stopOpacity=".1" />
                  </linearGradient>
                </defs>
                <ellipse
                  cx="150"
                  cy="230"
                  rx="125"
                  ry="21"
                  fill="#aac7ac"
                  opacity=".18"
                />
                {[0, 1, 2, 3, 4].map((i) => (
                  <path
                    key={i}
                    d={`M25 ${80 + i * 27} Q135 ${250 + i * 3} 275 ${65 + i * 29}`}
                    fill={i === 4 ? "url(#terrain)" : "none"}
                    stroke="#93b69b"
                    strokeWidth="1.2"
                    opacity={0.35 + i * 0.1}
                  />
                ))}
                <path
                  d="M72 107 Q104 148 138 162T203 157"
                  fill="none"
                  stroke="#315f4b"
                  strokeWidth="2"
                  strokeDasharray="4 6"
                />
                {[
                  [72, 107],
                  [105, 143],
                  [138, 162],
                  [171, 165],
                  [203, 157],
                ].map(([cx, cy], i) => (
                  <circle
                    key={i}
                    cx={cx}
                    cy={cy}
                    r={i === 4 ? 7 : 4}
                    fill={i === 4 ? "#245c46" : "#fff"}
                    stroke="#315f4b"
                    strokeWidth="2"
                  />
                ))}
                <text
                  x="185"
                  y="119"
                  fill="#416c53"
                  fontSize="12"
                  fontFamily="monospace"
                >
                  a step closer.
                </text>
              </svg>
            </div>
          </section>
          <section className="panel recommendation">
            <span className="small-icon lavender">
              <Icon name="spark" />
            </span>
            <div>
              <h3>Why this next?</h3>
              <p>
                {recommended.id === active.id && !state.ended
                  ? "Your current concept and saved question are ready to resume. A short explanation and two independent checks build evidence."
                  : "This concept is eligible at its target difficulty. It builds on demonstrated prerequisites or offers a useful review."}
              </p>
              <Link href={`/map?concept=${recommended.id}`}>
                See where it fits
                <Icon name="arrow" size={15} />
              </Link>
            </div>
          </section>
          <section>
            <div className="section-heading">
              <h2>Your learning path</h2>
              <Link href="/map">
                Explore map
                <Icon name="arrow" size={15} />
              </Link>
            </div>
            <div className="path-list">
              {learnerConcepts
                .filter((c) => ["gradients", "descent", "sgd"].includes(c.id))
                .map((concept, i) => (
                  <Link
                    href={`/map?concept=${concept.id}`}
                    key={concept.id}
                    className="path-row"
                  >
                    <span
                      className={`path-number ${concept.state === "demonstrated" ? "done" : ""}`}
                    >
                      {concept.state === "demonstrated" ? (
                        <Icon name="check" size={16} />
                      ) : (
                        String(i + 1).padStart(2, "0")
                      )}
                    </span>
                    <div>
                      <strong>{concept.title}</strong>
                      <small>
                        {concept.state === "demonstrated"
                          ? "A foundation you can build on"
                          : unmetPrerequisites(concept.id, state.records).length
                            ? "Prerequisite evidence needed"
                            : "Ready to practice · Intermediate"}
                      </small>
                    </div>
                    <Icon name="chevron" size={17} />
                  </Link>
                ))}
            </div>
          </section>
        </div>
        <aside className="right-stack">
          <section className="panel goal-card">
            <p className="eyebrow">THE BIGGER PICTURE</p>
            <h2>
              Understand how
              <br />
              models learn.
            </h2>
            <p>Training & optimization</p>
            <div className="progress-track">
              <span style={{ width: `${(demonstrated / 12) * 100}%` }} />
            </div>
            <div className="progress-caption">
              <strong>{demonstrated} of 12</strong>
              <span>concepts demonstrated</span>
            </div>
            <Link href="/progress" className="text-link">
              View your progress
              <Icon name="arrow" size={15} />
            </Link>
          </section>
          <section className="panel review-card">
            <div className="section-heading">
              <h3>Time for a refresh</h3>
              <span className="count-pill">{reviews.length}</span>
            </div>
            <p>A small revisit helps ideas stick.</p>
            {reviews.map((c) => (
              <Link
                href={`/map?concept=${c.id}`}
                key={c.id}
                className="review-item"
              >
                <span className="small-icon amber">
                  <Icon name="clock" size={17} />
                </span>
                <div>
                  <strong>{c.title}</strong>
                  <small>Review due · Intermediate</small>
                </div>
                <Icon name="chevron" size={16} />
              </Link>
            ))}
          </section>
          <div className="quote-card">
            <Icon name="leaf" size={24} />
            <p>
              Understanding grows
              <br />
              with every good question.
            </p>
            <span>No rush. Just progress.</span>
          </div>
        </aside>
      </div>
    </>
  );
}
export function MaterialsView() {
  const [source, setSource] = useState(false);
  return (
    <>
      <PageHeading
        eyebrow="YOUR COURSE LIBRARY"
        title="Good learning starts at the source."
        description="The materials behind your concepts, explanations, and practice."
      />
      <AgentContextNotice workflow="course_preparation"/>
      <div className="notice inline">
        <Icon name="source" />
        <p>
          Sample library. Uploading and processing documents will be available
          when the backend is connected.
        </p>
      </div>
      <div className="material-grid">
        {documents.map((doc) => (
          <article className="panel material-card" key={doc.title}>
            <div className={`document-art ${doc.color}`}>
              <Icon name="source" size={44} />
              <span>COURSE NOTES</span>
            </div>
            <span className="tag">Sample material</span>
            <h2>{doc.title}</h2>
            <p>{doc.filename}</p>
            <div className="material-meta">
              <span>{doc.pages} pages</span>
              <span>{doc.concepts} concepts</span>
            </div>
            {doc.title === "Training & learning" ? (
              <button
                className="button secondary"
                onClick={() => setSource(true)}
              >
                Preview sample passage
                <Icon name="arrow" size={16} />
              </button>
            ) : (
              <Link
                href="/map?concept=derivatives"
                className="button secondary"
              >
                Explore linked concepts
                <Icon name="arrow" size={16} />
              </Link>
            )}
          </article>
        ))}
      </div>
      {source && <SourceDrawer onClose={() => setSource(false)} />}
    </>
  );
}
export function ProgressView() {
  const { state } = useDemo();
  const rows = getLearnerConcepts(state);
  return (
    <>
      <PageHeading
        eyebrow="EVIDENCE, NOT JUST ACTIVITY"
        title="See your understanding take shape."
        description="Every concept has a story. Here's what your practice shows."
      />
      <div className="stats-grid">
        {Object.entries(labels).map(([status, label]) => (
          <div className="panel stat-card" key={status}>
            <span className="sr-only">{label}</span>
            <StateBadge state={status as keyof typeof labels} />
            <strong>{rows.filter((c) => c.state === status).length}</strong>
            <small>concepts at target difficulty</small>
          </div>
        ))}
      </div>
      <section className="panel table-panel">
        <div className="section-heading">
          <div>
            <h2>Concept evidence</h2>
            <p>Overall status is measured against each concept’s target.</p>
          </div>
          <span className="tag">Target: Intermediate</span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Concept</th>
                <th>Overall state</th>
                <th>Basic</th>
                <th>Intermediate</th>
                <th>Advanced</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id}>
                  <td>
                    <Link href={`/map?concept=${c.id}`}>{c.title}</Link>
                  </td>
                  <td>
                    <StateBadge state={c.state} />
                  </td>
                  <td>
                    {labels[getConceptEvidence(c, state).levels.basic.state]}
                  </td>
                  <td>
                    {
                      labels[
                        getConceptEvidence(c, state).levels.intermediate.state
                      ]
                    }
                  </td>
                  <td>
                    {labels[getConceptEvidence(c, state).levels.advanced.state]}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <div className="panel evidence-note">
        <Icon name="spark" />
        <div>
          <h3>One correct answer is a good start.</h3>
          <p>
            Demonstrated understanding needs two independent rubric-meeting
            answers to distinct questions at the target difficulty, without
            hints or unresolved contradictions.
          </p>
          <p>
            Current demo:{" "}
            {Object.values(state.records).reduce(
              (sum, record) => sum + record.attempts,
              0,
            )}{" "}
            practice attempts across{" "}
            {
              Object.values(state.records).filter(
                (record) => record.attempts > 0,
              ).length
            }{" "}
            concepts. These are local demo outcomes, not backend assessments.
          </p>
        </div>
      </div>
    </>
  );
}
