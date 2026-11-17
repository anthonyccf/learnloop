import { RichText } from "@/components/rich-text";
type RecordValue = Record<string, unknown>;
const text = (value: unknown) => typeof value === "string" ? value : "";
const object = (value: unknown): RecordValue => value && typeof value === "object" && !Array.isArray(value) ? value as RecordValue : {};
const list = (value: unknown): unknown[] => Array.isArray(value) ? value : [];
function Section({ title, value }: { title: string; value: unknown }) {
  return text(value) ? <section><h4>{title}</h4><RichText>{text(value)}</RichText></section> : null;
}
export function InspectorPreview({ kind, content }: { kind: "lessons" | "questions"; content: RecordValue }) {
  const example = object(content.workedExample);
  const choices = list(content.choices);
  return <details className="expert-learning-preview" open>
    <summary>{kind === "lessons" ? "Lesson preview" : "Question preview"} <span>Read only</span></summary>
    <div className="expert-learning-preview-body">
      {kind === "lessons" ? <>
        <Section title="Objective" value={content.objective} /><Section title="Explanation" value={content.explanation} />
        {list(content.equations).map((entry, index) => { const equation = object(entry); return <section key={index}><h4>Equation</h4><RichText>{`$$\n${text(equation.latex)}\n$$`}</RichText><RichText>{text(equation.explanation)}</RichText></section>; })}
        {text(example.title) && <section><h4>Worked example: {text(example.title)}</h4><ol>{list(example.steps).map((entry, index) => { const step = object(entry); return <li key={index}>{typeof entry === "string" ? <RichText>{entry}</RichText> : <><strong>{text(step.title)}</strong><RichText>{text(step.explanation)}</RichText>{list(step.equations).map((equation, i) => <RichText key={i}>{`$$\n${text(equation)}\n$$`}</RichText>)}</>}</li>; })}</ol><RichText>{text(example.explanation)}</RichText></section>}
        <Section title="Key takeaway" value={content.takeaway} /><Section title="Common mistake" value={content.commonMistake} />
        {list(content.flashcards).length > 0 && <section><h4>Flashcards</h4>{list(content.flashcards).map((entry, index) => { const card = object(entry); return <div key={index}><strong>{text(card.front)}</strong><RichText>{text(card.back)}</RichText></div>; })}</section>}
      </> : <>
        <Section title="Question" value={content.prompt} />
        {choices.length > 0 && <section><h4>Choices</h4><ol className="expert-preview-choices">{choices.map((entry, index) => { const choice = object(entry); return <li key={text(choice.id) || index}><strong>{text(choice.id).toUpperCase()}.</strong> <RichText inline>{text(choice.text)}</RichText>{text(choice.id) === text(content.correctChoiceId) && <span className="expert-preview-correct">Correct answer</span>}</li>; })}</ol></section>}
        <Section title="Reference answer" value={content.referenceAnswer} /><Section title="Explanation" value={content.explanation} /><Section title="Hint" value={content.hint} />
        {list(content.rubric).length > 0 && <section><h4>Rubric</h4>{list(content.rubric).map((entry, index) => { const criterion = object(entry); return <div key={index}><strong>{text(criterion.title) || text(criterion.id)}</strong><RichText>{text(criterion.description)}</RichText></div>; })}</section>}
      </>}
    </div>
  </details>;
}
