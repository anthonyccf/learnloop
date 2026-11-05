export const SELECTION_MOTION_MS = 620;
export type MotionGroup = { x: number; y: number; r: number; turn: number; opacity: number };
export type MotionNode = { x: number; y: number; radius: number; scale: number; opacity: number; groupId: string };
export type MotionShelf = { y: number; depth: number; labelY: number; opacity: number };
export type SelectionFrame = {
  groups: Record<string, MotionGroup>;
  nodes: Record<string, MotionNode>;
  panel: Record<string, MotionNode>;
  shelves: Record<string, MotionShelf>;
  height: number;
  zoom: number;
};

export function selectionEase(progress: number) {
  return 1 - Math.pow(1 - Math.max(0, Math.min(1, progress)), 3);
}
const mix = (a: number, b: number, t: number) => a + (b - a) * t;
const turn = (a: number, b: number, t: number) => a + (((b - a + 180) % 360 + 360) % 360 - 180) * t;

/** One shared frame drives bubble positions, terrace reflow, zoom and arrow anchors. */
export function interpolateSelection(from: SelectionFrame, to: SelectionFrame, progress: number): SelectionFrame {
  if (progress >= 1) return to;
  const t = selectionEase(progress);
  const groups = Object.fromEntries(Object.entries(to.groups).map(([id, b]) => {
    const a = from.groups[id] || { ...b, r: b.r * .8, opacity: 0 };
    return [id, { x: mix(a.x, b.x, t), y: mix(a.y, b.y, t), r: mix(a.r, b.r, t), turn: turn(a.turn, b.turn, t), opacity: mix(a.opacity, b.opacity, t) }];
  }));
  const nodes = (target: SelectionFrame["nodes"], previous: SelectionFrame["nodes"], panel: boolean) => Object.fromEntries(Object.entries(target).map(([id, b]) => {
    const origin = from.groups[b.groupId] || to.groups[b.groupId];
    const a = previous[id] || { ...b, x: panel ? 0 : origin?.x ?? b.x, y: panel ? 0 : origin?.y ?? b.y, radius: b.radius * .6, opacity: 0 };
    return [id, { ...b, x: mix(a.x, b.x, t), y: mix(a.y, b.y, t), radius: mix(a.radius, b.radius, t), scale: mix(a.scale, b.scale, t), opacity: mix(a.opacity, b.opacity, t) }];
  }));
  const shelves = Object.fromEntries(Object.entries(to.shelves).map(([id, b]) => {
    const a = from.shelves[id] || { ...b, opacity: 0 };
    return [id, { y: mix(a.y, b.y, t), depth: mix(a.depth, b.depth, t), labelY: mix(a.labelY, b.labelY, t), opacity: mix(a.opacity, b.opacity, t) }];
  }));
  return { groups, nodes: nodes(to.nodes, from.nodes, false), panel: nodes(to.panel, from.panel, true), shelves, height: mix(from.height, to.height, t), zoom: mix(from.zoom, to.zoom, t) };
}
