import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { TutorBrainMemory, type BrainGraph, type BrainStates } from "../src/components/tutor-brain-memory";
import { hierarchy } from "../src/lib/topic-hierarchy";

test("brain map shows all published concepts and each level of selected memory", () => {
  const graph: BrainGraph = {
    concepts: Array.from({ length: 128 }, (_, index) => ({ id: `c${index}`, title: `Concept ${index}`, targetDifficulty: "basic" })),
    prerequisites: [{ prerequisite: "c0", dependent: "c1" }],
    related: [{ first: "c0", second: "c2" }],
  };
  const states: BrainStates = { c0: { basic: "developing", intermediate: "demonstrated", advanced: "review_due" } };
  const html = renderToStaticMarkup(createElement(TutorBrainMemory, { graph, states, gaps: {}, currentConceptId: "c0" }));
  assert.equal((html.match(/class="tutor-brain-node"/g) || []).length, 128);
  assert.match(html, /Concept 0, target basic\. basic: Developing, intermediate: Demonstrated, advanced: Review due/);
  assert.match(html, /Concept 1, target basic\. basic: Not assessed, intermediate: Not assessed, advanced: Not assessed/);
  assert.match(html, /marker-end=/);
  assert.match(html, /stroke-dasharray="6 5"/);
});

test("nested topic navigation counts descendants once and finds each concept's path", () => {
  const topics = [
    { id: "root", title: "Attention", summary: "", conceptIds: [] },
    { id: "child", parentId: "root", title: "Efficient attention", summary: "", conceptIds: ["a", "b"] },
    { id: "legacy", title: "Other", summary: "", conceptIds: ["c"] },
  ];
  const tree = hierarchy(topics, ["a", "b", "c", "d"]);
  assert.deepEqual(tree.children(null).map(topic => topic.id), ["root", "legacy"]);
  assert.deepEqual(tree.descendants("root"), ["a", "b"]);
  assert.deepEqual(tree.path("child").map(topic => topic.id), ["root", "child"]);
  assert.deepEqual(tree.ungrouped, ["d"]);
  const graph: BrainGraph = { concepts: ["a", "b", "c", "d"].map(id => ({ id, title: id, targetDifficulty: "basic" })), topics, prerequisites: [], related: [] };
  const html = renderToStaticMarkup(createElement(TutorBrainMemory, { graph, states: {}, gaps: {} }));
  assert.match(html, /Open topic Attention, 2 concepts/);
  assert.match(html, /Open topic Other, 1 concept/);
  assert.doesNotMatch(html, /Open topic Efficient attention/);
  assert.match(html, /d, target basic/);
});

test("topic color and accessible progress reflect demonstrated descendants at their course targets", () => {
  const graph: BrainGraph = {
    concepts: [{ id: "a", title: "A", targetDifficulty: "basic" }, { id: "b", title: "B", targetDifficulty: "intermediate" }],
    topics: [{ id: "root", title: "Topic", summary: "", conceptIds: [] }, { id: "child", parentId: "root", title: "Child", summary: "", conceptIds: ["a", "b"] }],
    prerequisites: [], related: [],
  };
  const states: BrainStates = { a: { basic: "demonstrated", intermediate: "unassessed", advanced: "unassessed" }, b: { basic: "demonstrated", intermediate: "developing", advanced: "unassessed" } };
  const html = renderToStaticMarkup(createElement(TutorBrainMemory, { graph, states, gaps: {} }));
  assert.match(html, /Open topic Topic, 2 concepts, 50% demonstrated at course target, 1 developing · 1 demonstrated/);
  assert.match(html, /fill="rgb\(203, 212, 164\)"/);
  assert.match(html, /Topic progress · demonstrated at course target/);
  const hidden = renderToStaticMarkup(createElement(TutorBrainMemory, { graph, states, gaps: {}, showEvidence: false }));
  assert.doesNotMatch(hidden, /50% demonstrated|Topic progress · demonstrated/);
});
