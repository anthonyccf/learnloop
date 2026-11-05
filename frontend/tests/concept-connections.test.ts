import { test } from "node:test";
import assert from "node:assert/strict";
import { conceptConnections, overviewConceptIds, overviewConceptPoint, conceptConnectionPath } from "../src/lib/concept-connections";
import { terraceLayout } from "../src/lib/terrace-layout";
import type { CourseDetail } from "../src/lib/backend";
import type { GlobeTopic } from "../src/lib/topic-globe";

test("direct concept connections retain direction and related links without invented or dangling endpoints", () => {
  const graph: CourseDetail["graph"] = { concepts: ["a", "b", "c", "d", "e", "unrelated"].map(id => ({ id, title: id, summary: "", sources: [] })), prerequisites: [{ prerequisite: "a", dependent: "b" }, { prerequisite: "b", dependent: "c" }, { prerequisite: "b", dependent: "d" }, { prerequisite: "b", dependent: "d" }, { prerequisite: "missing", dependent: "b" }, { prerequisite: "b", dependent: "b" }], related: [{ first: "e", second: "b", rationale: "Published relationship" }, { first: "b", second: "e", rationale: "Duplicate" }, { first: "e", second: "unrelated", rationale: "Another branch" }] };
  const result = conceptConnections(graph, "b");
  assert.equal(result.edges.length, 4);
  assert.deepEqual([...result.ids].sort(), ["a", "b", "c", "d", "e"]);
  assert.ok(result.edges.some(e => e.from === "a" && e.to === "b" && e.kind === "prerequisite"));
  assert.ok(result.edges.some(e => e.kind === "related"));
  assert.equal(conceptConnections(graph, "missing").ids.size, 0);
});

test("connected topics survive layer focus without duplication or changing their real layer", () => {
  const groups: GlobeTopic[] = (["basic", "intermediate", "advanced"] as const).flatMap(layer => Array.from({ length: 30 }, (_, i) => ({ id: `${layer}-${i}`, topicId: `t${i}`, title: `Topic ${i}`, layer, conceptIds: [`${layer}-concept-${i}`] })));
  const pins = new Set(["basic-29", "intermediate-27", "advanced-25", "advanced-28", "advanced-29"]);
  for (const layer of ["all", "basic", "intermediate"]) {
    const layout = terraceLayout(groups, layer, pins);
    const placed = layout.shelves.flatMap(s => s.groups);
    assert.equal(new Set(placed.map(g => g.id)).size, placed.length);
    assert.ok([...pins].every(id => placed.some(g => g.id === id && g.layer === groups.find(item => item.id === id)!.layer)));
    assert.equal(layout.shelves.length, 3);
    assert.ok(placed.every(g => g.y + g.r < layout.height));
  }
});

test("all concepts remain visible in unselected topic circles at stable positions", () => {
  const group: GlobeTopic & { x: number; y: number; r: number } = { id: "topic", topicId: "t", title: "Published topic", layer: "basic", conceptIds: Array.from({ length: 24 }, (_, i) => `c${i}`), x: 250, y: 400, r: 65 };
  const ids = overviewConceptIds(group);
  assert.ok(ids.includes("c23"));
  assert.equal(ids.length, 24);
  assert.equal(overviewConceptIds(group).length, 24);
  const a = overviewConceptPoint(group, "c23", 0)!;
  assert.deepEqual(overviewConceptPoint(group, "c23", 0), a);
  assert.notDeepEqual(overviewConceptPoint(group, "c23", 90), a);
});

test("arrows terminate at small concept boundaries and follow rotation within the same topic", () => {
  const group: GlobeTopic & { x: number; y: number; r: number } = { id: "topic", topicId: "t", title: "Topic", layer: "intermediate", conceptIds: ["a", "b", "c"], x: 500, y: 450, r: 65 };
  const a = overviewConceptPoint(group, "a", 0)!, b = overviewConceptPoint(group, "b", 0)!;
  const curve = conceptConnectionPath(a, b)!;
  assert.ok(Math.abs(Math.hypot(curve.x1 - a.x, curve.y1 - a.y) - a.radius - 2) < 1e-9);
  assert.ok(Math.abs(Math.hypot(curve.x2 - b.x, curve.y2 - b.y) - b.radius - 5) < 1e-9);
  assert.notEqual(curve.d, conceptConnectionPath(overviewConceptPoint(group, "a", 60)!, overviewConceptPoint(group, "b", 60)!)!.d);
  assert.ok(conceptConnectionPath(a, { ...a, x: a.x + 3 })); // Dense neighbors still get a curved link.
  assert.equal(conceptConnectionPath(a, a), null);
});
