import { test } from "node:test";
import assert from "node:assert/strict";
import { BUBBLE_RADIUS, bubbleLink, layoutBubbleGraph } from "../src/lib/bubble-layout";

const concepts = (count: number) => Array.from({ length: count }, (_, index) => ({ id: `c${String(index).padStart(3, "0")}`, title: `Concept ${index}`, summary: "Published concept", sources: [] }));

test("a 109-concept bubble map keeps equal-size bubbles inside bounds without overlap", () => {
  const items = concepts(109);
  const graph = { concepts: items, prerequisites: items.filter((_, index) => index % 5 !== 0).map(item => ({ prerequisite: items.find(previous => Number(previous.id.slice(1)) === Number(item.id.slice(1)) - 1)!.id, dependent: item.id })),
    topics: Array.from({ length: 23 }, (_, index) => ({ id: `topic-${index}`, title: `Topic ${index}`, summary: "Topic group", conceptIds: items.slice(index * 5, index * 5 + 5).map(item => item.id) })) };
  const before = JSON.stringify(graph);
  const layout = layoutBubbleGraph(graph);
  assert.equal(layout.nodes.length, 109);
  assert.equal(JSON.stringify(graph), before, "layout must not mutate published concepts or relationships");
  for (const node of layout.nodes) {
    assert.equal(node.radius, BUBBLE_RADIUS);
    assert.ok(Number.isFinite(node.x) && Number.isFinite(node.y));
    assert.ok(node.x - node.radius >= 0 && node.y - node.radius >= 0);
    assert.ok(node.x + node.radius <= layout.width && node.y + node.radius <= layout.height);
    for (const other of layout.nodes) if (node.id !== other.id) assert.ok(Math.hypot(node.x - other.x, node.y - other.y) >= node.radius + other.radius + 10, `${node.id} overlaps ${other.id}`);
  }
  const reordered = layoutBubbleGraph({ ...graph, concepts: [...items].reverse(), prerequisites: [...graph.prerequisites].reverse() });
  assert.deepEqual(reordered.nodes, layout.nodes, "refresh/input order must not shuffle the map");
  assert.equal(new Set(layout.groups.flatMap(group => group.conceptIds)).size, 109);
  assert.equal(layout.groups.reduce((sum, group) => sum + group.conceptIds.length, 0), 109, "each concept belongs to exactly one container");
  for (const group of layout.groups) {
    for (const node of layout.nodes.filter(node => node.groupId === group.id)) {
      assert.ok(Math.hypot(node.x - group.cx, node.y - group.cy) + node.radius <= group.radius - 12, `${node.id} escapes ${group.id}`);
      assert.ok(node.y - node.radius >= group.y + 84, `${node.id} overlaps the topic title`);
    }
    for (const other of layout.groups) if (other.id !== group.id) assert.ok(Math.hypot(group.cx - other.cx, group.cy - other.cy) >= group.radius + other.radius + 30, "topic containers overlap");
  }
});

test("published related links pull concepts closer without inventing prerequisite arrows", () => {
  const items = concepts(4);
  const layout = layoutBubbleGraph({ concepts: items, prerequisites: [], related: [{ first: items[0].id, second: items[3].id, rationale: "Published connection" }] });
  const get = (index: number) => layout.nodes.find(node => node.id === items[index].id)!;
  const distance = (a: number, b: number) => Math.hypot(get(a).x - get(b).x, get(a).y - get(b).y);
  assert.ok(distance(0, 3) < distance(0, 1));
  assert.equal(layout.edges.length, 0);
  assert.equal(layout.related.length, 1);
});

test("empty/singleton maps and missing relationship endpoints remain safe", () => {
  assert.equal(layoutBubbleGraph({ concepts: [], prerequisites: [] }).nodes.length, 0);
  const graph = layoutBubbleGraph({ concepts: concepts(1), prerequisites: [{ prerequisite: "missing", dependent: "c000" }], related: [{ first: "c000", second: "missing", rationale: "Invalid" }] });
  assert.equal(graph.nodes.length, 1);
  assert.equal(graph.edges.length, 0);
  assert.equal(graph.related.length, 0);
});

test("duplicate topic memberships and ungrouped concepts retain each concept exactly once", () => {
  const items = concepts(4);
  const result = layoutBubbleGraph({ concepts: items, prerequisites: [], topics: [
    { id: "first", title: "First", summary: "", conceptIds: [items[0].id, items[0].id, items[1].id, "missing"] },
    { id: "second", title: "Second", summary: "", conceptIds: [items[0].id, items[2].id] },
  ] });
  assert.equal(result.groups.flatMap(group => group.conceptIds).length, 4);
  assert.equal(result.nodes.find(node => node.id === items[0].id)?.groupId, "first");
  assert.equal(result.groups.find(group => group.id === "__ungrouped__")?.title, "Other concepts");
});

test("topic groups influence proximity without creating published links", () => {
  const items = concepts(10);
  const result = layoutBubbleGraph({ concepts: items, prerequisites: [], topics: [
    { id: "first", title: "First", summary: "", conceptIds: items.slice(0, 5).map(item => item.id) },
    { id: "second", title: "Second", summary: "", conceptIds: items.slice(5).map(item => item.id) },
  ] });
  const a = result.nodes.slice(0, 5), b = result.nodes.slice(5);
  const distance = (x: typeof a[number], y: typeof a[number]) => Math.hypot(x.x - y.x, x.y - y.y);
  const within = a.flatMap((node, index) => a.slice(index + 1).map(other => distance(node, other)));
  const between = a.flatMap(node => b.map(other => distance(node, other)));
  assert.ok(within.reduce((sum, value) => sum + value, 0) / within.length < between.reduce((sum, value) => sum + value, 0) / between.length);
  assert.equal(result.edges.length, 0);
  assert.equal(result.related.length, 0);
});

test("connection endpoints stop outside both bubbles and preserve prerequisite direction", () => {
  const from = { x: 100, y: 100, radius: BUBBLE_RADIUS }, to = { x: 300, y: 100, radius: BUBBLE_RADIUS };
  const line = bubbleLink(from, to, true);
  assert.ok(line.x1 > from.x + from.radius);
  assert.ok(line.x2 < to.x - to.radius);
  assert.ok(line.x1 < line.x2);
  assert.equal(line.y1, 100);
  assert.equal(line.y2, 100);
});
