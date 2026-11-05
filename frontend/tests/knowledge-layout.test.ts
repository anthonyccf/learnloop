import { test } from "node:test";
import assert from "node:assert/strict";
import { layoutKnowledgeGraph, NODE_HEIGHT, NODE_WIDTH } from "../src/lib/knowledge-layout";

const concepts = (count: number) => Array.from({ length: count }, (_, i) => ({ id: `c${i}`, title: `Concept ${i}`, summary: "Published concept", sources: [] }));

test("live map lays out all 51 concepts without overlapping cards", () => {
  const graph = { concepts: concepts(51), prerequisites: Array.from({ length: 17 }, (_, i) => ({ prerequisite: `c${i}`, dependent: `c${i+1}` })) };
  const layout = layoutKnowledgeGraph(graph);
  assert.equal(layout.nodes.length, 51);
  for (const node of layout.nodes) {
    assert.ok(node.x >= 0 && node.x + NODE_WIDTH <= layout.width);
    assert.ok(node.y >= 0 && node.y + NODE_HEIGHT <= layout.height);
    for (const other of layout.nodes.filter(n => n.id !== node.id)) {
      assert.ok(node.x + NODE_WIDTH <= other.x || other.x + NODE_WIDTH <= node.x || node.y + NODE_HEIGHT <= other.y || other.y + NODE_HEIGHT <= node.y);
    }
  }
  for (const edge of graph.prerequisites) {
    const parent = layout.nodes.find(n => n.id === edge.prerequisite)!;
    const child = layout.nodes.find(n => n.id === edge.dependent)!;
    assert.ok(parent.y + NODE_HEIGHT < child.y);
  }
});

test("wide prerequisite layers wrap and orphan concepts have no invented links", () => {
  const graph = { concepts: concepts(23), prerequisites: Array.from({ length: 12 }, (_, i) => ({ prerequisite: "c0", dependent: `c${i+1}` })) };
  const layout = layoutKnowledgeGraph(graph);
  assert.equal(layout.edges.length, 12);
  assert.deepEqual(layoutKnowledgeGraph(graph), layout);
  assert.equal(layoutKnowledgeGraph({ concepts: [], prerequisites: [] }).nodes.length, 0);
});

test("topic layout covers every concept once, separates boxes, and ranks prerequisites within topics", () => {
  const graph = { concepts: concepts(51), prerequisites: [{ prerequisite: "c0", dependent: "c1" }, { prerequisite: "c1", dependent: "c27" }],
    topics: [{ id: "first", title: "Foundations", summary: "First topic", conceptIds: concepts(26).map(c => c.id) },
      { id: "second", title: "Applications", summary: "Second topic", conceptIds: concepts(25).map((_, i) => `c${i+26}`) }],
    related: [{ first: "c2", second: "c28", rationale: "Related, not prerequisite" }] };
  const layout = layoutKnowledgeGraph(graph);
  assert.equal(new Set(layout.nodes.map(n => n.id)).size, 51);
  assert.equal(layout.edges.length, 2);
  assert.equal(layout.topicBoxes.length, 2);
  assert.ok(layout.topicBoxes[0].y + layout.topicBoxes[0].height < layout.topicBoxes[1].y);
  const parent = layout.nodes.find(n => n.id === "c0")!, child = layout.nodes.find(n => n.id === "c1")!;
  assert.ok(parent.y + NODE_HEIGHT < child.y);
  for (const node of layout.nodes) {
    const topic = layout.topicBoxes.find(t => graph.topics.find(g => g.id === t.id)!.conceptIds.includes(node.id))!;
    assert.ok(node.y >= topic.y + 50 && node.y + NODE_HEIGHT <= topic.y + topic.height);
    for (const other of layout.nodes.filter(n => n.id !== node.id)) assert.ok(node.x + NODE_WIDTH <= other.x || other.x + NODE_WIDTH <= node.x || node.y + NODE_HEIGHT <= other.y || other.y + NODE_HEIGHT <= node.y);
  }
});
