import { test } from "node:test";
import assert from "node:assert/strict";
import { placeMapPreview } from "../src/lib/map-preview";

test("a concept preview stays in the map at each edge and on a phone", () => {
  for (const frame of [{ width: 640, height: 480 }, { width: 335, height: 440 }]) {
    for (const [left, top] of [[0, 0], [frame.width - 44, 0], [0, frame.height - 44], [frame.width - 44, frame.height - 44]]) {
      const box = placeMapPreview({ left, top, width: 44, height: 44 }, frame);
      assert.ok(box.left >= 12 && box.top >= 12);
      assert.ok(box.left + box.width <= frame.width - 12);
      assert.ok(box.top + box.maxHeight <= frame.height - 12);
    }
  }
});

test("the preview flips away from the right edge without shrinking on desktop", () => {
  const box = placeMapPreview({ left: 550, top: 200, width: 44, height: 44 }, { width: 640, height: 480 });
  assert.equal(box.width, 280);
  assert.ok(box.left + box.width < 550);
});
