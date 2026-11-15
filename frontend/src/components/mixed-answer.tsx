"use client";

import { useRef, useState } from "react";
import { api, type SavedMixedAnswer, type StudySession } from "@/lib/backend";

export function MixedAnswer({ activity, courseId, saved, disabled, onSubmit, workbench }: {
  activity: NonNullable<StudySession["activity"]>;
  courseId: string;
  saved?: SavedMixedAnswer;
  disabled: boolean;
  onSubmit: (submit: () => Promise<void>) => void;
  workbench?: { memoryId: string; version: number; onResult: (result: unknown) => void };
}) {
  const [choices, setChoices] = useState<string[]>([]);
  const [blanks, setBlanks] = useState(() => new Map<string, string>());
  const [answerText, setAnswerText] = useState("");
  const operation = useRef<{ key: string; id: string; version: number } | null>(null);
  const blankIds = activity.blankIds || [];
  const ready = activity.format === "multiple_answer" ? choices.length > 0
    : activity.format === "fill_in" ? blankIds.length > 0 && blankIds.every(id => blanks.get(id)?.trim())
    : Boolean(answerText.trim());

  async function submit() {
    const answer = activity.format === "multiple_answer" ? { choiceIds: [...choices].sort() }
      : activity.format === "fill_in" ? { blanks: blankIds.map(id => ({ id, text: blanks.get(id)?.trim() || "" })) }
      : { answerText: answerText.trim() };
    const key = JSON.stringify(answer);
    if (operation.current?.key !== key) {
      const { version } = workbench || await api<{ version: number }>(`courses/${courseId}/learner-state`);
      operation.current = { key, id: crypto.randomUUID(), version };
    }
    const op = operation.current;
    const result = await api(workbench ? `workbench/memories/${workbench.memoryId}/answer` : `activities/${activity.id}/responses`, {
      operationId: op.id, expectedLearnerVersion: op.version, ...answer,
    });
    if (workbench) workbench.onResult(result);
  }

  return <fieldset disabled={disabled}>
    {activity.format === "multiple_answer" ? <>
      <legend>Select all that apply</legend>
      {activity.choices.map(option => <label className="live-choice" key={option.id}>
        <input type="checkbox" checked={(saved?.choiceIds ?? choices).includes(option.id)} onChange={event => {
          const checked = event.target.checked;
          setChoices(previous => checked ? [...previous, option.id] : previous.filter(id => id !== option.id));
        }} />{option.text}
      </label>)}
    </> : activity.format === "fill_in" ? <>
      <legend>Fill in each named blank</legend>
      {blankIds.map(id => <label key={id} className="answer-reasoning">Blank: {id}
        <input maxLength={400} value={saved?.blanks && Object.hasOwn(saved.blanks, id) ? saved.blanks[id] : blanks.get(id) ?? ""} onChange={event => {
          const text = event.target.value;
          setBlanks(previous => new Map(previous).set(id, text));
        }} />
      </label>)}
    </> : <>
      <legend>Explain your answer</legend>
      <label className="answer-reasoning">Your response<textarea rows={4} maxLength={4000}
        value={saved?.answerText ?? answerText} onChange={event => setAnswerText(event.target.value)} />
      </label>
    </>}
    {activity.status === "pending" && <button type="button" className="button dark" disabled={!ready} onClick={() => onSubmit(submit)}>Submit answer</button>}
  </fieldset>;
}
