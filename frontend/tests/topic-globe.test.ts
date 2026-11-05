import { test } from "node:test";
import assert from "node:assert/strict";
import { globePoints, faceGlobePoint, rotateGlobe, projectGlobe, topicExplorerGraph } from "../src/lib/topic-globe";
import type { CourseDetail, Difficulty } from "../src/lib/backend";

test("each searchable concept can be brought exactly to the front, even near the poles", () => {
  for (const count of [1, 2, 24, 200, 1000]) for (const point of globePoints(count)) {
    const p = rotateGlobe(point, faceGlobePoint(point));
    assert.ok(Math.abs(p.x) < 1e-10 && Math.abs(p.y) < 1e-10 && Math.abs(p.z - 1) < 1e-10);
    assert.equal(projectGlobe(point, faceGlobePoint(point)).front, true);
  }
  assert.deepEqual(globePoints(0), []);
});

test("rotation preserves a unique stable sphere position and separates front from rear", () => {
  const points = globePoints(200);
  assert.deepEqual(globePoints(200), points);
  assert.equal(new Set(points.map(p => JSON.stringify(p))).size, 200);
  for (const yaw of [-720, -50, 0, 310]) for (const pitch of [-89, 0, 89]) for (const point of points) {
    const p = projectGlobe(point, { yaw, pitch });
    assert.ok(Number.isFinite(p.x) && Number.isFinite(p.y) && p.scale > 0);
    assert.ok(Math.hypot(p.x, p.y) < 147);
  }
  assert.equal(projectGlobe({ x: 0, y: 0, z: -1 }, { yaw: 0, pitch: 0 }).front, false);
});

test("large explorer keeps every concept in one published topic and its actual layer", () => {
  const concepts: CourseDetail["graph"]["concepts"] = Array.from({ length: 900 }, (_, i) => {
    const layer: Difficulty = i < 450 ? "basic" : i < 780 ? "intermediate" : "advanced";
    return { id: `c${i}`, title: `Concept ${i}`, summary: "Distinct goal", sources: [], curriculum: { conceptId: `c${i}`, layer, teaches: "A goal", assumes: [], adds: "A capability" } };
  });
  const graph: CourseDetail["graph"] = { concepts, topics: Array.from({ length: 30 }, (_, i) => ({ id: `t${i}`, title: `Topic ${i}`, summary: "", conceptIds: concepts.filter((_, j) => j % 30 === i).map(c => c.id) })), prerequisites: [{ prerequisite: "c0", dependent: "c451" }, { prerequisite: "missing", dependent: "c1" }] };
  graph.topics!.push({ id: "duplicate", title: "Overlapping topic", summary: "", conceptIds: ["c0"] });
  const scene = topicExplorerGraph(graph);
  assert.equal(scene.groups.length, 90);
  assert.equal(scene.groups.flatMap(g => g.conceptIds).length, 900);
  assert.equal(new Set(scene.groups.flatMap(g => g.conceptIds)).size, 900);
  assert.ok(scene.groups.every(g => g.conceptIds.every(id => concepts.find(c => c.id === id)!.curriculum!.layer === g.layer)));
  assert.equal(scene.groups.find(g => g.conceptIds.includes("c0"))!.topicId, "t0");
  assert.equal(scene.edges.length, 1);
  assert.deepEqual(scene.bands.map(b => b.count), [120, 330, 450]);
  assert.equal(topicExplorerGraph({ concepts: [{ id: "old", title: "Old", summary: "", sources: [] }], prerequisites: [] }).groups[0].layer, "unassigned");
  assert.equal(topicExplorerGraph({ concepts: [], prerequisites: [] }).groups.length, 0);
});
