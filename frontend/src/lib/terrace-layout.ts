import type { CurriculumLayer } from "./curriculum-map";
import type { GlobeTopic } from "./topic-globe";

const levels: CurriculumLayer[] = ["advanced", "intermediate", "basic", "unassigned"];

/** Size each tier to all its published topics and their concept populations. */
export function terraceLayout(groups: GlobeTopic[], layer: string, pinnedGroups: Set<string> = new Set()) {
  const focused = layer !== "all" && !pinnedGroups.size;
  let top = 60;
  const shelves = levels.flatMap(level => {
    const members = groups.filter(g => g.layer === level);
    if (!members.length || focused && level !== layer) return [];
    const sized = members.map(group => ({ ...group, r: Math.min(260, 52 + Math.sqrt(group.conceptIds.length) * 10) }));
    // Pack rows against the circle's actual horizontal chords, rather than
    // enclosing a narrow rectangular stack in an oversized circle.
    const largest = Math.max(...sized.map(g => g.r));
    const cellWidth = Math.max(180, largest * 2 + 36);
    const cellHeight = largest * 2 + 100 / .62;
    const headerOffset = 55;
    let best: { radius: number; capacities: number[]; rows: number } | undefined;
    const maxRows = Math.min(members.length, Math.ceil(Math.sqrt(members.length) * 2) + 2);
    for (let rows = 1; rows <= maxRows; rows++) {
      const capacities = (radius: number) => Array.from({ length: rows }, (_, i) => {
        const cy = (i - (rows - 1) / 2) * cellHeight + headerOffset;
        const edgeY = Math.abs(cy) + cellHeight / 2;
        return Math.floor(2 * Math.sqrt(Math.max(0, (radius - 24) ** 2 - edgeY ** 2)) / cellWidth);
      });
      let low = rows * cellHeight / 2 + 105;
      let high = low + members.length * cellWidth;
      for (let iteration = 0; iteration < 36; iteration++) {
        const radius = (low + high) / 2, slots = capacities(radius);
        if (slots.every(n => n > 0) && slots.reduce((a, b) => a + b, 0) >= members.length) high = radius;
        else low = radius;
      }
      if (!best || high < best.radius) best = { radius: high, capacities: capacities(high), rows };
    }
    const { radius, capacities, rows } = best!;
    const counts = Array.from({ length: rows }, () => 1);
    for (let remaining = members.length - rows; remaining > 0; remaining--) {
      const candidates = counts.map((count, i) => ({ i, ratio: count / capacities[i] }))
        .filter(({ i }) => counts[i] < capacities[i]).sort((a, b) => a.ratio - b.ratio || a.i - b.i);
      counts[candidates[0].i]++;
    }
    const depth = radius * 2 * .62;
    let index = 0;
    const placed = counts.flatMap((count, row) => {
      const cy = (row - (rows - 1) / 2) * cellHeight + headerOffset;
      const edgeY = Math.abs(cy) + cellHeight / 2;
      const halfChord = Math.sqrt(Math.max(0, (radius - 24) ** 2 - edgeY ** 2));
      const spread = Math.max(0, halfChord - cellWidth / 2);
      return Array.from({ length: count }, (_, column) => {
        const group = sized[index++];
        return { ...group, x: 520 + (count === 1 ? 0 : (column / (count - 1) * 2 - 1) * spread),
          y: top + depth / 2 + cy * .62 - 38, pinned: pinnedGroups.has(group.id) };
      });
    });
    const y = top;
    top += depth + 60;
    return [{ x: 520 - radius, y, width: radius * 2, depth, labelX: 520, labelY: y + 42,
      layer: level, total: members.length, count: members.reduce((n, g) => n + g.conceptIds.length, 0), groups: placed }];
  });
  return { shelves, height: shelves.length ? top + 20 : 0, shown: shelves.reduce((n, s) => n + s.groups.length, 0) };
}

/** Circular platform seen in perspective. */
export function terraceSurface(x: number, y: number, width: number, depth: number) {
  const rx = width / 2, ry = depth / 2, cy = y + ry;
  return `M${x},${cy} A${rx},${ry} 0 1 0 ${x + width},${cy} A${rx},${ry} 0 1 0 ${x},${cy} Z`;
}

/** Screen-facing atlas discs retain every concept, with rotation around their centre. */
export function projectTopicDisc(index: number, count: number, turn: number, radius = 112, tilt = .79) {
  if (count <= 1) return { x: 0, y: 0, depth: 1, scale: 1, front: true };
  const angle = (-90 + index * (count <= 8 ? 360 / count : 137.507764) + turn) * Math.PI / 180;
  const r = count <= 8 ? radius * .9 : radius * Math.sqrt((index + .5) / count);
  return { x: Math.cos(angle) * r, y: Math.sin(angle) * r * tilt, depth: Math.sin(angle), scale: 1, front: true };
}
