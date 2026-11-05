"use client";
import type { PracticeQuestion as Question } from "@/lib/practice-bank";
import type { ConceptPractice } from "@/lib/practice-session";
import { Icon } from "./icons";

export function PracticeQuestion({
  question,
  record,
  onAnswer,
  onSubmit,
  onHint,
  storageAvailable,
}: {
  question: Question;
  record: ConceptPractice;
  onAnswer: (id: string) => void;
  onSubmit: () => void;
  onHint: () => void;
  storageAvailable: boolean;
}) {
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <div className="question-heading">
        <span className="question-index">
          {String(record.question + 1).padStart(2, "0")}
        </span>
        <p>YOUR TURN</p>
        <span>Question {record.question + 1} of 2</span>
      </div>
      <fieldset
        className="mcq-fieldset"
        disabled={Boolean(record.feedback) || record.ended}
      >
        <legend className="question-label">{question.prompt}</legend>
        <p className="mcq-instruction">Choose one answer.</p>
        <div className="mcq-options">
          {question.choices.map((choice) => {
            const selected = record.answer === choice.id;
            const correct =
              Boolean(record.feedback) && choice.id === question.correctId;
            const wrong = Boolean(record.feedback) && selected && !correct;
            return (
              <label
                key={choice.id}
                className={`mcq-option ${selected ? "is-selected" : ""} ${correct ? "is-correct" : ""} ${wrong ? "is-incorrect" : ""}`}
              >
                <input
                  type="radio"
                  name="answer"
                  value={choice.id}
                  checked={selected}
                  onChange={() => onAnswer(choice.id)}
                  required
                />
                <span className="mcq-letter" aria-hidden="true">
                  {choice.id.toUpperCase()}
                </span>
                <span className="mcq-option-copy">
                  <span>{choice.text}</span>
                  {correct && (
                    <small>
                      <Icon name="check" size={13} />
                      Correct answer
                    </small>
                  )}
                  {wrong && <small>Your answer · not quite</small>}
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>
      <div className="answer-caption">
        <span>
          {storageAvailable
            ? "Selection saved on this device"
            : "Selection available for this visit only"}
        </span>
        <span>Take your time.</span>
      </div>
      {record.hinted && (
        <div className="hint-box">
          <Icon name="hint" size={18} />
          <p>{question.hint}</p>
        </div>
      )}
      {!record.feedback && (
        <>
          <div className="activity-actions">
            <button
              type="button"
              className="hint-button"
              onClick={onHint}
              disabled={record.hinted}
            >
              <Icon name="hint" size={17} />
              {record.hinted ? "Hint used" : "A little hint"}
            </button>
            <button
              className="button dark"
              type="submit"
              disabled={
                !question.choices.some((choice) => choice.id === record.answer)
              }
            >
              Check answer
              <Icon name="arrow" size={17} />
            </button>
          </div>
          <p className="hint-caption">
            Hints support learning. Assisted responses do not add independent
            evidence.
          </p>
        </>
      )}
    </form>
  );
}
