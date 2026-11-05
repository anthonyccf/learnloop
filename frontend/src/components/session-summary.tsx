"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { concepts } from "@/lib/demo-data";
import { describeAttempt } from "@/lib/learner-evidence";
import {
  isConcept,
  recommendedConcept,
  sessionAttempts,
  sessionIndependent,
} from "@/lib/practice-session";
import { useDemo } from "./demo-provider";
import { PageHeading, StateBadge } from "./ui";
import { Icon } from "./icons";

export function SessionSummary() {
  const { state, dispatch } = useDemo();
  const params = useSearchParams();
  const id = params.get("concept") || state.conceptId;
  if (!state.loaded) return <p role="status">Loading your saved session…</p>;
  if (!isConcept(id))
    return (
      <>
        <h1>Choose a concept from your course.</h1>
        <Link href="/map" className="button dark">
          Explore My understanding
        </Link>
      </>
    );
  const concept = concepts.find((item) => item.id === id)!;
  const record = state.records[id];
  if (!record)
    return (
      <>
        <PageHeading
          eyebrow="NO SESSION YET"
          title={concept.title}
          description="Start a practice session to build evidence for this concept."
        />
        <Link href={`/learn?concept=${id}`} className="button dark">
          Start MC practice
          <Icon name="arrow" size={16} />
        </Link>
      </>
    );
  const attempts = sessionAttempts(record);
  const next = recommendedConcept(id, state.records);
  const changed = record.sessionBefore !== record.status;
  return (
    <>
      <PageHeading
        eyebrow={record.ended ? "SESSION SAVED" : "SESSION SO FAR"}
        title="A little progress, made visible."
        description={`Here’s what your ${concept.title.toLowerCase()} practice shows.`}
      />
      <div className="summary-grid">
        <div className="main-stack">
          <section className="panel summary-change">
            <p className="eyebrow">WHAT CHANGED ON YOUR GRAPH</p>
            <h2>{concept.title}</h2>
            <div className="state-transition">
              <div>
                <small>At the start</small>
                <StateBadge state={record.sessionBefore} />
              </div>
              <Icon name="arrow" />
              <div>
                <small>Now · Intermediate target</small>
                <StateBadge state={record.status} />
              </div>
            </div>
            <p>
              {!attempts.length
                ? "No new answers were submitted in this session. Your existing evidence is unchanged."
                : changed
                  ? record.status === "demonstrated"
                    ? "Evidence from saved practice now supports two distinct independent checks in this demo."
                    : record.status === "review_due"
                      ? "An incorrect response calls for reassessment. Earlier evidence is retained."
                      : "Your answers provide diagnostic evidence; more independent practice is needed."
                  : "Your state is unchanged. Every submitted answer is still retained as evidence."}
            </p>
            <Link className="text-link" href={`/map?concept=${id}`}>
              See this change on My understanding
              <Icon name="map" size={16} />
            </Link>
          </section>
          <div className="summary-metrics">
            <div className="panel">
              <strong>{attempts.length}</strong>
              <span>submitted answers</span>
            </div>
            <div className="panel">
              <strong>{sessionIndependent(record)}</strong>
              <span>distinct independent checks</span>
            </div>
            <div className="panel">
              <strong>
                {attempts.filter((attempt) => attempt.hinted).length}
              </strong>
              <span>hint-assisted attempts</span>
            </div>
          </div>
          <section className="panel summary-attempts">
            <h2>Your session evidence</h2>
            <p className="micro-copy">
              Incorrect and assisted answers remain in your history. Repeating a
              question does not add a distinct check.
            </p>
            {attempts.length ? (
              <ol>
                {attempts.map((attempt) => {
                  const detail = describeAttempt(attempt);
                  return (
                    <li key={attempt.id}>
                      <span
                        className={`attempt-pill ${attempt.correct ? "correct" : "incorrect"}`}
                      >
                        {attempt.correct ? "Correct" : "Needs practice"}
                        {attempt.hinted ? " · hint used" : ""}
                      </span>
                      <h3>{detail.question}</h3>
                      <p>Your selection: {detail.answer}</p>
                      <small>{detail.explanation}</small>
                    </li>
                  );
                })}
              </ol>
            ) : (
              <p className="empty-session">
                No answers submitted yet. You can continue your saved question
                whenever you’re ready.
              </p>
            )}
          </section>
        </div>
        <aside className="right-stack">
          <section className="panel summary-next">
            <span className="small-icon lavender">
              <Icon name="spark" />
            </span>
            <p className="eyebrow">YOUR NEXT USEFUL STEP</p>
            <h2>{next ? next.title : "Explore your course"}</h2>
            <p>
              {!next
                ? "All currently eligible concepts are demonstrated. Explore the graph or revisit a source."
                : next.id === id
                  ? "Keep working with this idea. Review the explanation and try another independent check."
                  : next.prerequisites.includes(id)
                    ? "This concept builds on the understanding you just demonstrated. Its prerequisites are ready."
                    : "This concept is ready for practice or reassessment at its target difficulty."}
            </p>
            {next ? (
              <Link
                href={`/learn?concept=${next.id}`}
                className="button dark"
                onClick={() => {
                  dispatch({ type: "activate", conceptId: next.id });
                  if (state.records[next.id]?.ended)
                    dispatch({ type: "restart" });
                }}
              >
                Continue with {next.title}
                <Icon name="arrow" size={16} />
              </Link>
            ) : (
              <Link href="/map" className="button dark">
                Explore the graph
                <Icon name="arrow" size={16} />
              </Link>
            )}
            <Link href={`/learn?concept=${id}`} className="text-link">
              Return to this concept
              <Icon name="chevron" size={14} />
            </Link>
          </section>
          <div className="notice inline">
            <Icon name="source" size={18} />
            <p>
              Frontend demo. Question content, sources and progress rules are
              illustrative; no backend assessment is performed.
            </p>
          </div>
        </aside>
      </div>
    </>
  );
}
