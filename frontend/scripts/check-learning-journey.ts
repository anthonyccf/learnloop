// Validate the actual graph and examples produced by the isolated live journey.
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import katex from "katex";
import { layoutKnowledgeGraph, NODE_HEIGHT, NODE_WIDTH } from "../src/lib/knowledge-layout";
import { WorkedExample } from "../src/components/worked-example";
import type { CourseDetail, LearningMaterials } from "../src/lib/backend";

const graph: CourseDetail["graph"] = JSON.parse(readFileSync("../tmp/journey-graph.json", "utf8"));
const materials: LearningMaterials = JSON.parse(readFileSync("../tmp/journey-materials.json", "utf8"));
const layout = layoutKnowledgeGraph(graph);
assert.equal(layout.nodes.length, graph.concepts.length);
assert.equal(new Set(layout.nodes.map(node => node.id)).size, graph.concepts.length);
for (const node of layout.nodes) {
  assert(node.x >= 0 && node.x + NODE_WIDTH <= layout.width);
  assert(node.y >= 0 && node.y + NODE_HEIGHT <= layout.height);
  for (const other of layout.nodes.filter(other => other.id !== node.id)) {
    assert(node.x + NODE_WIDTH <= other.x || other.x + NODE_WIDTH <= node.x || node.y + NODE_HEIGHT <= other.y || other.y + NODE_HEIGHT <= node.y);
  }
}
assert.deepEqual(materials.materials.map(material => material.conceptId), graph.concepts.map(concept => concept.id));
let equations = 0;
for (const material of materials.materials) {
  const example = material.lesson.workedExample;
  for (const step of example.steps) {
    assert.notEqual(typeof step, "string");
    if (typeof step === "string") continue;
    for (const latex of step.equations) {
      katex.renderToString(latex, { throwOnError: true, strict: "error", trust: false });
      equations++;
    }
  }
  const html = renderToStaticMarkup(createElement(WorkedExample, { example }));
  assert(html.includes("example-steps") && !html.includes("katex-error"));
}
const result = { status: "passed", mapNodes: layout.nodes.length, mapEdges: layout.edges.length, overlappingCards: 0, lessonsRendered: materials.materials.length, formulaLinesRendered: equations, lessonOrderMatchesMap: true };
writeFileSync("../tmp/journey-frontend-report.json", JSON.stringify(result, null, 2));
console.log(JSON.stringify(result));
