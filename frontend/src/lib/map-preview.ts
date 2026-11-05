type Rect = { left: number; top: number; width: number; height: number };

// Place an unscaled preview inside the visible map, rather than in world space.
export function placeMapPreview(anchor: Rect, frame: { width: number; height: number }) {
  const padding = 12, gap = 12;
  const width = Math.min(280, Math.max(0, frame.width - padding * 2));
  const height = Math.min(228, Math.max(0, frame.height - padding * 2));
  let left = anchor.left + anchor.width + gap;
  if (left + width > frame.width - padding) left = anchor.left - width - gap;
  left = Math.max(padding, Math.min(left, frame.width - width - padding));
  const top = Math.max(padding, Math.min(anchor.top + anchor.height / 2 - height / 2, frame.height - height - padding));
  return { left, top, width, maxHeight: height };
}
