import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { AssessmentDetails } from "../src/components/assessment-details";

const assessment = { correct: true, uncertain: false, hinted: false, feedback: "Feedback", explanation: "Explanation" };

test("legacy assessments remain readable without invented rubric coverage", () => {
  assert.equal(renderToStaticMarkup(createElement(AssessmentDetails, { assessment })), "");
});

test("partial-credit and contradiction details are visible and response quotes are escaped", () => {
  const html = renderToStaticMarkup(createElement(AssessmentDetails, { assessment: { ...assessment,
    rubricScore: 0.5, partial: true, contradiction: true,
    rubricCoverage: [{ criterionId: "direction", description: "Choose the right direction", score: 0.5, reason: "Some reasoning is missing." }],
    misconceptions: [{ description: "Unsupported assumption", responseQuote: "<script>bad()</script>" }],
  } }));
  assert.match(html, /Rubric coverage · 50%/);
  assert.match(html, /does not count as independent demonstrated evidence/);
  assert.match(html, /needs reassessment/);
  assert.ok(!html.includes("<script>"));
});

test("confirmed weakness and recovery are distinguished from an inconclusive contradiction", () => {
  const detail = { ...assessment, rubricScore: 0, rubricCoverage: [{ criterionId: "direction", description: "Choose the right direction", score: 0, reason: "The direction was reversed." }], contradiction: true, confirmedWeakness: true };
  const confirmed = renderToStaticMarkup(createElement(AssessmentDetails, { assessment: detail }));
  assert.match(confirmed, /Progress is Developing/);
  assert.match(confirmed, /Earlier evidence is retained/);
  assert.doesNotMatch(confirmed, /conflicts with earlier evidence and needs reassessment/);
  const recovery = renderToStaticMarkup(createElement(AssessmentDetails, { assessment: { ...detail, evidenceOutcome: "recovery_progress" } }));
  assert.match(recovery, /One more distinct independent rubric-meeting answer/);
});
