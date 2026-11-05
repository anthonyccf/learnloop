import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_PYRAMID_CAMERA, PYRAMID_VIEWS, pyramidPlane, fitConnectionView } from "../src/lib/pyramid-camera";

test("view presets keep tiers fixed and labels upright while changing surface depth", () => {
  const depths = new Set<number>();
  for (const view of PYRAMID_VIEWS) for (const centre of [210, 435, 660]) {
    const plane = pyramidPlane({ ...DEFAULT_PYRAMID_CAMERA, pitch: view.pitch }, centre, 865, true);
    const middle = plane.point({ x: 520, y: centre });
    assert.ok(Math.abs(middle.x - 520) < 1e-9 && Math.abs(middle.y - centre) < 1e-9);
    const below = plane.point({ x: 520, y: centre + 100 });
    assert.ok(Math.abs((below.y - middle.y) / 100 * plane.labelScaleY - 1) < 1e-9);
    depths.add(below.y - middle.y);
  }
  assert.equal(depths.size >= 3, true);
});

test("default camera preserves the terraces and pan moves every layer equally", () => {
  for (const centre of [210, 435, 660]) {
    const point = { x: 170, y: centre + 30 };
    const original = pyramidPlane(DEFAULT_PYRAMID_CAMERA, centre, 865).point(point);
    assert.ok(Math.abs(original.x - point.x) < 1e-9 && Math.abs(original.y - point.y) < 1e-9);
    const moved = pyramidPlane({ ...DEFAULT_PYRAMID_CAMERA, x: 65, y: -35 }, centre, 865).point(point);
    assert.ok(Math.abs(moved.x - point.x - 65) < 1e-9 && Math.abs(moved.y - point.y + 35) < 1e-9);
  }
});

test("orbit projects separate elevations and remains finite through a full turn", () => {
  for (let yaw = -180; yaw <= 180; yaw += 15) for (const pitch of [20, 60, 85]) {
    const camera = { yaw, pitch, x: 0, y: 0 };
    const upper = pyramidPlane(camera, 210, 865).point({ x: 520, y: 210 });
    const lower = pyramidPlane(camera, 660, 865).point({ x: 520, y: 660 });
    assert.ok(Number.isFinite(upper.x) && Number.isFinite(lower.y));
    assert.ok(upper.y < lower.y);
  }
});

test("visible connections preserve zoom, pan and scroll instead of fitting the whole map", () => {
  const current = { zoom: 1.4, x: 30, y: -100, scrollTop: 250 };
  assert.deepEqual(fitConnectionView({ left: 400, right: 600, top: 420, bottom: 610 }, { width: 1040, height: 700 }, current), current);
});

test("offscreen local arrows pan into view without zooming out", () => {
  const bounds = { left: 400, right: 600, top: 2200, bottom: 2450 };
  const view = fitConnectionView(bounds, { width: 1040, height: 700 }, { zoom: 1.2, x: 0, y: 0, scrollTop: 0 });
  assert.equal(view.zoom, 1.2);
  assert.equal(view.scrollTop, 0);
  assert.ok(Math.abs((2325 + view.y) * view.zoom - 350) < 1e-9);
});

test("long connections zoom out only enough for their own bounds", () => {
  const viewport = { width: 1040, height: 700 };
  const bounds = { left: 300, right: 750, top: 1000, bottom: 2200 };
  const view = fitConnectionView(bounds, viewport, { zoom: 1.5, x: 0, y: 0, scrollTop: 0 });
  assert.ok(view.zoom < 1.5 && view.zoom > .45);
  assert.ok((bounds.top + view.y) * view.zoom >= 55);
  assert.ok((bounds.bottom + view.y) * view.zoom <= 645);
});
