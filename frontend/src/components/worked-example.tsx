import katex from "katex";
import type { LearningMaterial } from "@/lib/backend";
import { RichText } from "./rich-text";

export function WorkedExample({ example, mathExpressions = [] }: {
  example: LearningMaterial["lesson"]["workedExample"];
  mathExpressions?: string[];
}) {
  return <section className="lesson-example">
    <p className="example-eyebrow">LET’S WORK THROUGH IT</p>
    <h3>{example.title}</h3>
    <ol className="example-steps">{example.steps.map((step, index) => <li key={index}>
      <span className="example-step-number" aria-hidden="true">{index + 1}</span>
      <div className="example-step-content">{typeof step === "string"
        ? <RichText mathExpressions={mathExpressions}>{step}</RichText>
        : <><h4>{step.title}</h4><RichText mathExpressions={mathExpressions}>{step.explanation}</RichText>
          {step.equations.map((latex, line) => <div className="example-calculation" key={line}
            dangerouslySetInnerHTML={{ __html: katex.renderToString(latex, { displayMode: true, throwOnError: false, trust: false, strict: "ignore", maxExpand: 500, maxSize: 20 }) }} />)}
        </>}
      </div>
    </li>)}</ol>
    <div className="example-meaning"><RichText mathExpressions={mathExpressions}>{example.explanation}</RichText></div>
  </section>;
}
