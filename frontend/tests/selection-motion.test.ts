import { test } from "node:test";
import assert from "node:assert/strict";
import { interpolateSelection, selectionEase, type SelectionFrame } from "../src/lib/selection-motion";
import { conceptConnectionPath } from "../src/lib/concept-connections";

function frames(): [SelectionFrame, SelectionFrame] {
  const from: SelectionFrame = {
    groups: { topic: { x: 100, y: 200, r: 65, turn: 350, opacity: 1 } },
    nodes: { a: { x: 80, y: 200, radius: 7, scale: 1, opacity: 1, groupId: "topic" }, b: { x: 140, y: 230, radius: 7, scale: 1, opacity: 1, groupId: "topic" } },
    panel: { a: { x: -60, y: -30, radius: 18, scale: 1, opacity: 1, groupId: "topic" } },
    shelves: { basic: { y: 520, depth: 280, labelY: 584, opacity: 1 } }, height: 865, zoom: 1,
  };
  const to = structuredClone(from);
  to.groups.topic = { x: 300, y: 450, r: 75, turn: 10, opacity: 1 };
  to.nodes.a = { ...from.nodes.a, x: 280, y: 430, radius: 9 };
  to.nodes.b = { ...from.nodes.b, x: 340, y: 490 };
  to.panel.a = { ...from.panel.a, x: 20, y: 90 };
  to.shelves.basic = { y: 675, depth: 420, labelY: 739, opacity: 1 };
  to.height = 1160; to.zoom = .8;
  return [from, to];
}

test("selection eases camera, terraces and both bubble views to exact final positions without mutating snapshots", () => {
  const [from, to] = frames(), saved = structuredClone([from, to]);
  const start = interpolateSelection(from, to, 0), middle = interpolateSelection(from, to, .4);
  assert.deepEqual(start, from);
  assert.deepEqual(interpolateSelection(from, to, 1), to);
  assert.ok(middle.nodes.a.x > from.nodes.a.x && middle.nodes.a.x < to.nodes.a.x);
  assert.ok(middle.panel.a.y > from.panel.a.y && middle.panel.a.y < to.panel.a.y);
  assert.ok(middle.shelves.basic.y > from.shelves.basic.y && middle.zoom < from.zoom);
  assert.ok(middle.groups.topic.turn > 350 && middle.groups.topic.turn < 370); // Short route across 360°.
  assert.deepEqual([from, to], saved);
  assert.equal(selectionEase(-1), 0); assert.equal(selectionEase(2), 1);
});

test("arrow endpoints follow the moving small bubbles throughout the transition", () => {
  const [from, to] = frames(), paths = new Set<string>();
  for (const progress of [0, .1, .25, .5, .8, 1]) {
    const frame = interpolateSelection(from, to, progress), a = frame.nodes.a, b = frame.nodes.b;
    const path = conceptConnectionPath(a, b)!;
    assert.ok(Math.abs(Math.hypot(path.x1 - a.x, path.y1 - a.y) - a.radius - 2) < 1e-9);
    assert.ok(Math.abs(Math.hypot(path.x2 - b.x, path.y2 - b.y) - b.radius - 5) < 1e-9);
    paths.add(path.d);
  }
  assert.equal(paths.size, 6);
});

test("rapid selections restart from the displayed frame and new connected bubbles enter from their topic", () => {
  const [from, to] = frames(), interrupted = interpolateSelection(from, to, .3);
  const next = structuredClone(to);
  next.nodes.a.x += 100;
  next.nodes.c = { ...next.nodes.b, x: 330, y: 400 };
  const restart = interpolateSelection(interrupted, next, 0);
  assert.deepEqual(restart.nodes.a, interrupted.nodes.a);
  assert.equal(restart.nodes.c.opacity, 0);
  assert.equal(restart.nodes.c.x, interrupted.groups.topic.x);
  const moving = interpolateSelection(interrupted, next, .5);
  assert.ok(moving.nodes.c.opacity > 0 && moving.nodes.c.opacity < 1);
  assert.deepEqual(interpolateSelection(interrupted, next, 1), next);
});
