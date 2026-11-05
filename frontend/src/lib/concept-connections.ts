import type { CourseDetail } from "./backend";
import { projectTopicDisc } from "./terrace-layout";
import type { GlobeTopic } from "./topic-globe";

export type ConceptConnection = { from: string; to: string; kind: "prerequisite" | "related" };

/** Only published, direct relationships; related links never imply a prerequisite. */
export function conceptConnections(graph: CourseDetail["graph"], root: string) {
  const known = new Set(graph.concepts.map(c => c.id)), links = new Map<string, ConceptConnection>();
  if (known.has(root)) {
    for (const e of graph.prerequisites) if (e.prerequisite !== e.dependent && known.has(e.prerequisite) && known.has(e.dependent) && (e.prerequisite === root || e.dependent === root)) {
      links.set(JSON.stringify(["prerequisite", e.prerequisite, e.dependent]), { from: e.prerequisite, to: e.dependent, kind: "prerequisite" });
    }
    for (const e of graph.related || []) if (e.first !== e.second && known.has(e.first) && known.has(e.second) && (e.first === root || e.second === root)) {
      const [from, to] = [e.first, e.second].sort();
      links.set(JSON.stringify(["related", from, to]), { from, to, kind: "related" });
    }
  }
  const edges = [...links.values()];
  return { edges, ids: new Set(known.has(root) ? [root, ...edges.flatMap(e => [e.from, e.to])] : []) };
}

export function overviewConceptIds(group: GlobeTopic) {
  return group.conceptIds;
}

/** Uses the full published membership so endpoints do not jump when detail changes. */
export function overviewConceptPoint(group: GlobeTopic & { x: number; y: number; r: number }, id: string, turn: number) {
  const i = group.conceptIds.indexOf(id);
  if (i < 0) return undefined;
  const p = projectTopicDisc(i, group.conceptIds.length, turn, group.r * .72, .62);
  return { x: group.x + p.x, y: group.y + p.y, radius: group.conceptIds.length <= 4 ? 11 : group.conceptIds.length <= 10 ? 8.5 : 5.5 };
}

/** Stop outside the small bubbles, including connections inside the same topic. */
export function conceptConnectionPath(a: { x: number; y: number; radius: number }, b: { x: number; y: number; radius: number }) {
  const dx = b.x - a.x, dy = b.y - a.y, length = Math.hypot(dx, dy);
  if (length < 1e-6) return null;
  if (length <= a.radius + b.radius + 5) {
    const nx = -dy / length, ny = dx / length;
    const x1 = a.x + nx * (a.radius + 2), y1 = a.y + ny * (a.radius + 2);
    const x2 = b.x + nx * (b.radius + 5), y2 = b.y + ny * (b.radius + 5);
    const lift = Math.max(a.radius, b.radius) * 3 + 20;
    const cx = (a.x + b.x) / 2 + nx * lift, cy = (a.y + b.y) / 2 + ny * lift;
    return { d: `M${x1} ${y1} Q${cx} ${cy} ${x2} ${y2}`, x1, y1, x2, y2, cx, cy };
  }
  const x1 = a.x + dx / length * (a.radius + 2), y1 = a.y + dy / length * (a.radius + 2);
  const x2 = b.x - dx / length * (b.radius + 5), y2 = b.y - dy / length * (b.radius + 5);
  const bend = Math.min(80, Math.max(18, length * .15));
  const cx = (x1 + x2) / 2 - dy / length * bend, cy = (y1 + y2) / 2 + dx / length * bend;
  return { d: `M${x1} ${y1} Q${cx} ${cy} ${x2} ${y2}`, x1, y1, x2, y2, cx, cy };
}
