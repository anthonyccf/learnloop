import type { CourseDetail } from "./backend";

type Graph = CourseDetail["graph"];
export const BUBBLE_RADIUS = 22;
const GAP = 16;
const SEPARATION = BUBBLE_RADIUS * 2 + GAP;
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

export type BubbleNode = Graph["concepts"][number] & { x: number; y: number; radius: number; groupId: string };
export type TopicBubble = { id: string; title: string; summary: string; conceptIds: string[]; cx: number; cy: number; radius: number; x: number; y: number; width: number; height: number };

export function bubbleBounds(nodes: { x: number; y: number; radius: number }[]) {
  if (!nodes.length) return { x: 0, y: 0, width: 360, height: 280 };
  const x = Math.min(...nodes.map(node => node.x - node.radius)) - 24;
  const y = Math.min(...nodes.map(node => node.y - node.radius)) - 24;
  return { x, y, width: Math.max(...nodes.map(node => node.x + node.radius)) + 24 - x, height: Math.max(...nodes.map(node => node.y + node.radius)) + 24 - y };
}

// Published topics are the containers. Unassigned concepts remain explicitly
// ungrouped; there is no generated topic or inferred prerequisite here.
export function layoutBubbleGraph(graph: Graph) {
  const concepts = [...graph.concepts].sort((a, b) => a.id.localeCompare(b.id));
  const byId = new Map(concepts.map(node => [node.id, node]));
  const ids = new Set(byId.keys());
  const edges = graph.prerequisites.filter(edge => edge.prerequisite !== edge.dependent && ids.has(edge.prerequisite) && ids.has(edge.dependent));
  const related = (graph.related || []).filter(edge => edge.first !== edge.second && ids.has(edge.first) && ids.has(edge.second));
  const neighbors = new Map(concepts.map(node => [node.id, new Set<string>()]));
  for (const edge of edges) { neighbors.get(edge.prerequisite)!.add(edge.dependent); neighbors.get(edge.dependent)!.add(edge.prerequisite); }
  for (const edge of related) { neighbors.get(edge.first)!.add(edge.second); neighbors.get(edge.second)!.add(edge.first); }
  const assigned = new Set<string>();
  const topics = (graph.topics || []).map(topic => ({ ...topic, conceptIds: [...new Set(topic.conceptIds)].filter(id => { if (!ids.has(id) || assigned.has(id)) return false; assigned.add(id); return true; }) })).filter(topic => topic.conceptIds.length);
  const remaining = concepts.filter(node => !assigned.has(node.id)).map(node => node.id);
  if (!topics.length && remaining.length) {
    const visited = new Set<string>(), isolated: string[] = [];
    for (const root of remaining) {
      if (visited.has(root)) continue;
      const queue = [root]; visited.add(root);
      for (let index = 0; index < queue.length; index++) for (const id of neighbors.get(queue[index])!) if (!visited.has(id)) { visited.add(id); queue.push(id); }
      if (queue.length > 1) topics.push({ id: `connected:${root}`, title: `Connected concepts ${topics.length + 1}`, summary: "Grouped by published connections.", conceptIds: queue });
      else isolated.push(root);
    }
    if (isolated.length) topics.push({ id: "__ungrouped__", title: topics.length ? "Other concepts" : "Course concepts", summary: "Published concepts without a topic group.", conceptIds: isolated });
  } else if (remaining.length) topics.push({ id: "__ungrouped__", title: "Other concepts", summary: "Published concepts without a topic group.", conceptIds: remaining });

  const local = new Map<string, { x: number; y: number }>();
  const groups = [...topics].sort((a, b) => a.id.localeCompare(b.id)).map((topic, groupIndex) => {
    // Breadth-first ordering places known neighbors in nearby packing slots.
    const members = new Set(topic.conceptIds), visited = new Set<string>(), order: string[] = [];
    const ranked = [...members].sort((a, b) => neighbors.get(b)!.size - neighbors.get(a)!.size || a.localeCompare(b));
    for (const root of ranked) {
      if (visited.has(root)) continue;
      const queue = [root]; visited.add(root);
      for (let index = 0; index < queue.length; index++) {
        const id = queue[index]; order.push(id);
        for (const neighbor of [...neighbors.get(id)!].sort()) if (members.has(neighbor) && !visited.has(neighbor)) { visited.add(neighbor); queue.push(neighbor); }
      }
    }
    const extent = Math.ceil(Math.sqrt(order.length)) + 1;
    const slots: { x: number; y: number }[] = [];
    for (let row = -extent; row <= extent; row++) for (let col = -extent; col <= extent; col++) slots.push({ x: (col + row / 2) * SEPARATION, y: row * SEPARATION * Math.sqrt(3) / 2 });
    slots.sort((a, b) => Math.hypot(a.x, a.y) - Math.hypot(b.x, b.y) || a.y - b.y || a.x - b.x);
    order.forEach((id, index) => local.set(id, { x: slots[index].x, y: slots[index].y + 38 }));
    const radius = Math.max(112, ...order.map(id => { const point = local.get(id)!; return Math.max(Math.hypot(point.x, point.y) + BUBBLE_RADIUS + 18, 96 - point.y + BUBBLE_RADIUS); }));
    const centerRadius = 240 * Math.sqrt(groupIndex);
    return { ...topic, cx: Math.cos(groupIndex * GOLDEN_ANGLE) * centerRadius, cy: Math.sin(groupIndex * GOLDEN_ANGLE) * centerRadius, radius };
  });
  const groupFor = new Map(groups.flatMap(group => group.conceptIds.map(id => [id, group.id] as const)));
  const pairKey = (a: string, b: string) => JSON.stringify([a, b].sort());
  const groupLinks = new Set<string>();
  for (const [a, b] of [...edges.map(edge => [edge.prerequisite, edge.dependent]), ...related.map(edge => [edge.first, edge.second])]) if (groupFor.get(a) !== groupFor.get(b)) groupLinks.add(pairKey(groupFor.get(a)!, groupFor.get(b)!));
  const pairs = groups.flatMap((a, i) => groups.slice(i + 1).map((b, offset) => ({ i, j: i + offset + 1, linked: groupLinks.has(pairKey(a.id, b.id)) })));
  for (let step = 0; step < 300; step++) {
    const forces = groups.map(group => ({ x: -group.cx * .002, y: -group.cy * .002 }));
    for (const pair of pairs) {
      const a = groups[pair.i], b = groups[pair.j];
      const dx = b.cx - a.cx, dy = b.cy - a.cy, distance = Math.max(.01, Math.hypot(dx, dy));
      const separation = a.radius + b.radius + 36;
      const force = (pair.linked ? (distance - separation - 32) * .035 : 0) - 8000 / (distance * distance) - Math.max(0, separation - distance) * .6;
      const x = dx / distance * force, y = dy / distance * force;
      forces[pair.i].x += x; forces[pair.i].y += y; forces[pair.j].x -= x; forces[pair.j].y -= y;
    }
    groups.forEach((group, index) => { const force = forces[index], scale = Math.min(1, 8 / Math.max(.01, Math.hypot(force.x, force.y))); group.cx += force.x * scale; group.cy += force.y * scale; });
  }
  for (let pass = 0; pass < 200; pass++) {
    let overlap = false;
    for (const { i, j } of pairs) {
      const a = groups[i], b = groups[j];
      let dx = b.cx - a.cx, dy = b.cy - a.cy;
      if (!dx && !dy) { dx = Math.cos((i + j) * GOLDEN_ANGLE) * .01; dy = Math.sin((i + j) * GOLDEN_ANGLE) * .01; }
      const distance = Math.hypot(dx, dy), minimum = a.radius + b.radius + 36;
      if (distance >= minimum) continue;
      overlap = true;
      const shift = (minimum - distance + .001) / 2;
      const x = dx / distance * shift, y = dy / distance * shift;
      a.cx -= x; a.cy -= y; b.cx += x; b.cy += y;
    }
    if (!overlap) break;
  }
  const bounds = bubbleBounds(groups.map(group => ({ x: group.cx, y: group.cy, radius: group.radius })));
  for (const group of groups) { group.cx -= bounds.x - 24; group.cy -= bounds.y - 24; }
  const topicBoxes: TopicBubble[] = groups.map(group => ({ ...group, x: group.cx - group.radius, y: group.cy - group.radius, width: group.radius * 2, height: group.radius * 2 }));
  const groupById = new Map(topicBoxes.map(group => [group.id, group]));
  const nodes: BubbleNode[] = concepts.map(node => { const groupId = groupFor.get(node.id)!, group = groupById.get(groupId)!, point = local.get(node.id)!; return { ...node, groupId, radius: BUBBLE_RADIUS, x: group.cx + point.x, y: group.cy + point.y }; });
  return { nodes, edges, related, groups: topicBoxes, topicBoxes, width: bounds.width + 48, height: bounds.height + 48 };
}

export function bubbleLink(from: Pick<BubbleNode, "x" | "y" | "radius">, to: Pick<BubbleNode, "x" | "y" | "radius">, arrow = false) {
  const dx = to.x - from.x, dy = to.y - from.y;
  const distance = Math.max(.01, Math.hypot(dx, dy));
  return { x1: from.x + dx / distance * (from.radius + 3), y1: from.y + dy / distance * (from.radius + 3), x2: to.x - dx / distance * (to.radius + (arrow ? 9 : 3)), y2: to.y - dy / distance * (to.radius + (arrow ? 9 : 3)) };
}
