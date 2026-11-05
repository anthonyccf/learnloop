import { test } from "node:test";
import assert from "node:assert/strict";
import { terraceLayout, projectTopicDisc } from "../src/lib/terrace-layout";
import type { GlobeTopic } from "../src/lib/topic-globe";
import type { CurriculumLayer } from "../src/lib/curriculum-map";

const groups: GlobeTopic[] = (["basic", "intermediate", "advanced"] as CurriculumLayer[]).flatMap(layer => Array.from({ length: 31 }, (_, i) => ({ id: `${layer}-${i}`, topicId: `t${i}`, title: `Published topic ${i}`, layer, conceptIds: Array.from({ length: i + 1 }, (_, n) => `c-${layer}-${i}-${n}`) })));

test("every topic and concept is placed on its actual tier without pagination", () => {
  const layout = terraceLayout(groups, "all");
  assert.equal(layout.shown, groups.length);
  assert.equal(new Set(layout.shelves.flatMap(s => s.groups.map(g => g.id))).size, groups.length);
  for (const shelf of layout.shelves) {
    assert.equal(shelf.count, groups.filter(g => g.layer === shelf.layer).reduce((n, g) => n + g.conceptIds.length, 0));
    assert.ok(Math.abs(shelf.depth / shelf.width - .62) < 1e-9);
    for (const group of shelf.groups) {
      const cx = shelf.x + shelf.width / 2, cy = shelf.y + shelf.depth / 2;
      for (const px of [group.x - group.r, group.x + group.r]) {
        for (const py of [group.y - group.r * .62, group.y + group.r * .62 + 65]) {
          assert.ok(((px - cx) / (shelf.width / 2)) ** 2 + ((py - cy) / (shelf.depth / 2)) ** 2 < 1, "topic and labels fit inside circular platform");
        }
      }
      assert.equal(group.layer, shelf.layer);
      assert.ok(group.x - group.r > shelf.x && group.x + group.r < shelf.x + shelf.width);
      assert.ok(group.y - group.r * .62 > shelf.y);
      assert.ok(group.y + group.r * .62 + 65 < shelf.y + shelf.depth);
    }
  }
  for (let i = 1; i < layout.shelves.length; i++) assert.ok(layout.shelves[i].y > layout.shelves[i - 1].y + layout.shelves[i - 1].depth);
});

test("bases grow and shrink with population and topic discs grow with concept count", () => {
  const small = terraceLayout([groups[0]], "all");
  const large = terraceLayout(groups.filter(g => g.layer === "basic"), "all");
  assert.ok(large.shelves[0].width > small.shelves[0].width);
  assert.ok(large.shelves[0].depth > small.shelves[0].depth);
  assert.ok(large.shelves[0].groups.at(-1)!.r > small.shelves[0].groups[0].r);
  assert.deepEqual(terraceLayout([], "all"), { shelves: [], height: 0, shown: 0 });
});

test("layer focus and connection pins retain all matching topics with stable positions", () => {
  assert.equal(terraceLayout(groups, "basic").shown, 31);
  const pins = new Set(["advanced-30", "basic-30"]);
  const all = terraceLayout(groups, "all");
  const connected = terraceLayout(groups, "basic", pins);
  assert.equal(connected.shown, groups.length);
  for (const shelf of connected.shelves) for (const g of shelf.groups) {
    const original = all.shelves.flatMap(s => s.groups).find(item => item.id === g.id)!;
    assert.deepEqual([g.x, g.y, g.r], [original.x, original.y, original.r]);
    assert.equal(g.pinned, pins.has(g.id));
  }
});

test("topic discs keep every concept finite and within their boundary", () => {
  for (const count of [1, 5, 40, 300]) for (let i = 0; i < count; i++) {
    const p = projectTopicDisc(i, count, 0);
    assert.ok(Number.isFinite(p.x) && Number.isFinite(p.y));
    assert.ok(Math.hypot(p.x, p.y / .79) <= 112);
    assert.equal(p.front, true);
  }
});

test("topic circles fill the platform width with room for their labels", () => {
  for (const count of [5, 17, 19, 31]) {
    const shelf = terraceLayout(groups.filter(g => g.layer === "basic").slice(0, count), "all").shelves[0];
    const left = Math.min(...shelf.groups.map(g => g.x - g.r));
    const right = Math.max(...shelf.groups.map(g => g.x + g.r));
    assert.ok(right - left > shelf.width * .6, "topics should use the sides of the circle");
    for (let i = 0; i < shelf.groups.length; i++) for (let j = i + 1; j < shelf.groups.length; j++) {
      const a = shelf.groups[i], b = shelf.groups[j];
      assert.ok(Math.abs(a.x - b.x) > a.r + b.r + 20 || Math.abs(a.y - b.y) > (a.r + b.r) * .62 + 75, "topic circles and labels must not overlap");
    }
  }
});
