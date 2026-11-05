import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { WorkedExample } from "../src/components/worked-example";

test("worked calculations separate instructions and display math with accessible fractions", () => {
  const html = renderToStaticMarkup(createElement(WorkedExample, { example: {
    title: "Hypothetical example", explanation: "The scale controls the spacing between codes.",
    steps: [{ title: "Find the scale", explanation: "Divide the real range by the code range.", equations: [String.raw`s=\frac{b-a}{q_{\max}-q_{\min}}`, String.raw`s=\frac{2-(-1)}{15-0}`, "s=0.2"] },
      { title: "Find the zero-point", explanation: "Locate the code for real zero.", equations: ["z=5"] }],
  } }));
  assert.equal((html.match(/class="katex-display"/g) || []).length, 4);
  assert.match(html, /<mfrac>/);
  assert.match(html, /<msub>/);
  assert.match(html, /<h4>Find the scale<\/h4>/);
  assert.match(html, /<ol class="example-steps">/);
  assert.doesNotMatch(html, /katex-error/);
});

test("legacy and conceptual examples remain readable without invented equations", () => {
  const html = renderToStaticMarkup(createElement(WorkedExample, { example: {
    title: "A simple case", explanation: "The choice depends on the goal.",
    steps: ["Start with **the goal**.", { title: "Compare choices", explanation: "Choose the option that fits the goal.", equations: [] }],
  } }));
  assert.match(html, /<strong>the goal<\/strong>/);
  assert.doesNotMatch(html, /katex-display/);
});
