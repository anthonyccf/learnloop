"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { concepts } from "@/lib/demo-data";
import { practiceBank } from "@/lib/practice-bank";
import {
  isConcept,
  sessionIndependent,
  unmetPrerequisites,
} from "@/lib/practice-session";
import {
  difficulties,
  difficultyLabels,
  getConceptEvidence,
} from "@/lib/learner-evidence";
import { useDemo } from "./demo-provider";
import { Icon } from "./icons";
import { PracticeQuestion } from "./practice-question";
import { SourceDrawer, StateBadge, PageHeading } from "./ui";
import { AgentContextNotice } from './agent-activity';

export function LearnView() {
  const { state, dispatch, storageAvailable } = useDemo();
  const params = useSearchParams();
  const id = params.get("concept") || state.conceptId;
  const known = isConcept(id);
  const [source, setSource] = useState(false);
  useEffect(() => {
    if (state.loaded && known && state.conceptId !== id)
      dispatch({ type: "activate", conceptId: id });
  }, [state.loaded, state.conceptId, id, known, dispatch]);
  if (!known)
    return (
      <>
        <PageHeading
          eyebrow="CONCEPT NOT FOUND"
          title="Choose a concept from your course."
          description="That practice link does not match the demo course."
        />
        <Link href="/map" className="button dark">
          Explore My understanding
        </Link>
      </>
    );
  if (!state.loaded || state.conceptId !== id)
    return (
      <div className="panel activity-card" role="status">
        Loading your saved practice…
      </div>
    );
  const concept = concepts.find((item) => item.id === id)!;
  const record = state.records[id];
  const evidence = getConceptEvidence(concept, state);
  const question = practiceBank[id][record.question];
  const selected = question.choices.find(
    (choice) => choice.id === record.answer,
  );
  const completed = sessionIndependent(record) >= 2;
  const unmet = unmetPrerequisites(id, state.records);
  const summaryUrl = `/learn/summary?concept=${id}`;
  if (unmet.length)
    return (
      <>
        <PageHeading
          eyebrow="BUILD ON YOUR FOUNDATIONS"
          title={`Before ${concept.title.toLowerCase()}`}
          description="This concept depends on evidence that needs attention first."
        />
        <section className="panel blocked-practice">
          <span className="small-icon amber">
            <Icon name="lock" />
          </span>
          <h2>A useful place to start</h2>
          <p>
            Demonstrated understanding at the Intermediate target is needed for:{" "}
            {unmet
              .map(
                (parent) => concepts.find((item) => item.id === parent)?.title,
              )
              .join(", ")}
            .
          </p>
          {unmet.map((parent) => (
            <Link
              key={parent}
              href={`/learn?concept=${parent}`}
              className="button dark"
            >
              Revisit {concepts.find((item) => item.id === parent)?.title}
              <Icon name="arrow" size={16} />
            </Link>
          ))}
          <button className="button secondary" onClick={() => setSource(true)}>
            Browse this concept’s source
          </button>
          <Link href={`/map?concept=${id}`} className="text-link">
            See prerequisites on the graph
            <Icon name="map" size={16} />
          </Link>
        </section>
        {source && (
          <SourceDrawer
            source={evidence.source}
            onClose={() => setSource(false)}
          />
        )}
      </>
    );
  return (
    <>
      <AgentContextNotice workflow="next_activity"/>
      <PageHeading
        eyebrow="YOUR LEARNING SESSION"
        title="Let’s connect the dots."
        description="Concept-specific MC practice, guided by your course graph."
        action={
          <Link
            href={summaryUrl}
            onClick={() => dispatch({ type: "end" })}
            className="text-link"
          >
            End & summarize
            <Icon name="arrow" size={16} />
          </Link>
        }
      />
      <div className="learn-grid">
        <div className="main-stack">
          <section className="panel activity-card">
            <div className="activity-top">
              <span className="tag">
                {record.ended
                  ? "SESSION SAVED"
                  : record.feedback
                    ? "PRACTICE FEEDBACK"
                    : "CONCEPT PRACTICE"}
              </span>
              <span className="difficulty">
                <span />
                <span />
                <span className="faded" />
                Intermediate
              </span>
            </div>
            <h2>{concept.title}</h2>
            <div className="why-inline">
              <Icon name="spark" size={16} />
              <p>
                {record.status === "review_due"
                  ? "Recheck earlier understanding with fresh independent evidence."
                  : `Build evidence for ${concept.title.toLowerCase()} at its target difficulty.`}
              </p>
            </div>
            {record.ended ? (
              <div className="saved-session">
                <Icon name="check" size={24} />
                <h3>Your session is saved.</h3>
                <p>
                  Your answers and evidence are still here. Review the summary
                  or begin a fresh practice session.
                </p>
                <div className="feedback-actions">
                  <Link href={summaryUrl} className="button dark">
                    View session summary
                    <Icon name="arrow" size={16} />
                  </Link>
                  <button
                    className="button secondary"
                    onClick={() => dispatch({ type: "restart" })}
                  >
                    Start another session
                  </button>
                </div>
              </div>
            ) : (
              <>
                <div className="lesson-copy">
                  <p>{evidence.source.excerpt}</p>
                  {evidence.source.equation && (
                    <div className="formula-card">
                      <span>THE UPDATE RULE</span>
                      <div className="equation">{evidence.source.equation}</div>
                      <p>The learning rate scales the gradient step.</p>
                    </div>
                  )}
                  <button
                    className="source-chip"
                    onClick={() => setSource(true)}
                  >
                    <Icon name="source" size={14} />
                    Lecture {evidence.source.lecture} · Slide{" "}
                    {evidence.source.page}
                    <span>Sample</span>
                    <Icon name="chevron" size={13} />
                  </button>
                </div>
                <PracticeQuestion
                  question={question}
                  record={record}
                  storageAvailable={storageAvailable}
                  onAnswer={(value) => dispatch({ type: "answer", value })}
                  onSubmit={() =>
                    dispatch({ type: "submit", at: new Date().toISOString() })
                  }
                  onHint={() => dispatch({ type: "hint" })}
                />
                {record.feedback && (
                  <section
                    className={`feedback-box ${record.feedback}`}
                    aria-live="polite"
                  >
                    <span className="eyebrow">
                      PRACTICE FEEDBACK · DEMO ONLY
                    </span>
                    <h3>
                      {record.feedback === "success"
                        ? "That’s right."
                        : record.feedback === "assisted"
                          ? "That’s right — with a little help."
                          : "Not quite. Let’s look at why."}
                    </h3>
                    <p>{selected?.explanation}</p>
                    {record.feedback === "practice" && (
                      <p>
                        <strong>
                          Correct answer: {question.correctId.toUpperCase()}.
                        </strong>{" "}
                        {
                          question.choices.find(
                            (choice) => choice.id === question.correctId,
                          )?.text
                        }
                      </p>
                    )}
                    {record.hinted && (
                      <p>
                        This attempt used a hint and does not add independent
                        evidence.
                      </p>
                    )}
                    <strong>
                      {sessionIndependent(record)} of 2 distinct independent
                      checks completed in this session.
                    </strong>
                    <div className="adaptive-followup">
                      <h3>
                        {completed
                          ? "Ready to reflect."
                          : record.feedback === "practice"
                            ? "Revisit the idea, then try another check."
                            : record.feedback === "assisted"
                              ? "Now try an independent check."
                              : "Connect the idea in a second question."}
                      </h3>
                      <p>
                        {completed
                          ? "Your session summary connects these attempts to the graph and recommends what to study next."
                          : record.feedback === "practice"
                            ? "Review the explanation above or open the source. A different question will check the same concept."
                            : record.feedback === "assisted"
                              ? "Hints are useful support. The next question starts without a hint so you can show what you understand."
                              : "Another distinct question gives stronger evidence than repeating the same answer."}
                      </p>
                      {record.feedback === "practice" && (
                        <>
                          <button
                            className="source-chip"
                            onClick={() => setSource(true)}
                          >
                            <Icon name="source" size={14} />
                            Revisit the source
                          </button>
                          {concept.prerequisites.length > 0 && (
                            <div className="prerequisite-review">
                              Optional foundation review:{" "}
                              {concept.prerequisites.map((parent) => (
                                <Link
                                  key={parent}
                                  href={`/learn?concept=${parent}`}
                                >
                                  {
                                    concepts.find((item) => item.id === parent)
                                      ?.title
                                  }
                                </Link>
                              ))}
                            </div>
                          )}
                        </>
                      )}
                    </div>
                    <div className="feedback-actions">
                      {completed ? (
                        <Link
                          className="button dark"
                          href={summaryUrl}
                          onClick={() => dispatch({ type: "end" })}
                        >
                          See session summary
                          <Icon name="arrow" size={16} />
                        </Link>
                      ) : (
                        <button
                          className="button dark"
                          onClick={() => dispatch({ type: "next" })}
                        >
                          {record.feedback === "practice"
                            ? "Try another check"
                            : record.feedback === "assisted"
                              ? "Try without a hint"
                              : "Next question"}
                          <Icon name="arrow" size={16} />
                        </button>
                      )}
                      <Link className="text-link" href={`/map?concept=${id}`}>
                        See concept evidence
                        <Icon name="map" size={15} />
                      </Link>
                    </div>
                  </section>
                )}
              </>
            )}
          </section>
        </div>
        <aside className="right-stack">
          <section className="panel session-plan">
            <p className="eyebrow">THIS SESSION</p>
            <h3>{concept.title}</h3>
            <ol>
              <li className="completed">
                <span>
                  <Icon name="check" size={14} />
                </span>
                <div>
                  <strong>Connect the idea</strong>
                  <small>Read a short explanation</small>
                </div>
              </li>
              <li className={completed ? "completed" : "current"}>
                <span>2</span>
                <div>
                  <strong>Check your understanding</strong>
                  <small>Two distinct MC questions</small>
                </div>
              </li>
              <li className={completed ? "current" : ""}>
                <span>3</span>
                <div>
                  <strong>Reflect & continue</strong>
                  <small>Review your session summary</small>
                </div>
              </li>
            </ol>
          </section>
          <section className="panel evidence-card">
            <div className="section-heading">
              <h3>Your evidence</h3>
              <Icon name="chart" size={17} />
            </div>
            <p>{concept.title}</p>
            {difficulties.map((level) => (
              <div key={level} className="evidence-row">
                <span>{difficultyLabels[level]}</span>
                <StateBadge state={evidence.levels[level].state} />
              </div>
            ))}
            <p className="micro-copy">
              Target: Intermediate. Feedback and progress use local demo rules.
            </p>
            <Link href={`/map?concept=${id}`} className="text-link">
              Open on the graph
              <Icon name="arrow" size={14} />
            </Link>
          </section>
          <div className="support-note">
            <Icon name="lock" size={16} />
            <p>Your answers stay in this browser. No backend or model calls.</p>
          </div>
        </aside>
      </div>
      {source && (
        <SourceDrawer
          source={evidence.source}
          onClose={() => setSource(false)}
        />
      )}
    </>
  );
}
