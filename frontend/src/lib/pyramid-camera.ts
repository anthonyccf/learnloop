export type PyramidCamera = { yaw: number; pitch: number; x: number; y: number };
export const DEFAULT_PYRAMID_CAMERA: PyramidCamera = { yaw: 0, pitch: 60, x: 0, y: 0 };
export const PYRAMID_VIEWS = [
  { name: "Default", pitch: 60 },
  { name: "More overhead", pitch: 72 },
  { name: "Front", pitch: 42 },
] as const;

/** Frame only connection bounds, keeping the current view if they already fit. */
export function fitConnectionView(bounds: { left: number; right: number; top: number; bottom: number }, viewport: { width: number; height: number }, current: { zoom: number; x: number; y: number; scrollTop: number }) {
  const padding = Math.min(viewport.width, viewport.height) * .08;
  const left = 520 + (bounds.left + current.x - 520) * current.zoom;
  const right = 520 + (bounds.right + current.x - 520) * current.zoom;
  const top = (bounds.top + current.y) * current.zoom - current.scrollTop;
  const bottom = (bounds.bottom + current.y) * current.zoom - current.scrollTop;
  if (left >= 520 - viewport.width / 2 + padding && right <= 520 + viewport.width / 2 - padding && top >= padding && bottom <= viewport.height - padding) return current;
  const zoom = Math.max(.35, Math.min(current.zoom,
    (viewport.width - padding * 2) / Math.max(1, bounds.right - bounds.left),
    (viewport.height - padding * 2) / Math.max(1, bounds.bottom - bounds.top)));
  return { zoom, x: 520 - (bounds.left + bounds.right) / 2,
    y: viewport.height / (2 * zoom) - (bounds.top + bounds.bottom) / 2, scrollTop: 0 };
}

/** Orthographic orbit of horizontal terraces at separate world elevations.
 * The default camera exactly preserves the original Option C composition. */
export function pyramidPlane(camera: PyramidCamera, centreY: number, height: number, fixedTiers = false) {
  const yaw = camera.yaw * Math.PI / 180, pitch = camera.pitch * Math.PI / 180;
  const pivot = height / 2, tilt = Math.sin(Math.PI / 3);
  const elevation = (pivot - centreY) / .5;
  const a = Math.cos(yaw), c = -Math.sin(yaw) / tilt;
  const b = Math.sin(yaw) * Math.sin(pitch), d = Math.cos(yaw) * Math.sin(pitch) / tilt;
  const e = 520 + camera.x - a * 520 - c * centreY;
  const f = (fixedTiers ? centreY : pivot - elevation * Math.cos(pitch)) + camera.y - b * 520 - d * centreY;
  return { labelScaleY: 1 / d, transform: `matrix(${a} ${b} ${c} ${d} ${e} ${f})`, point: (p: {x: number; y: number}) => ({ x: a * p.x + c * p.y + e, y: b * p.x + d * p.y + f }) };
}
