import type { CourseDetail } from "./backend";

export const NODE_WIDTH = 180;
export const NODE_HEIGHT = 88;
type Graph = CourseDetail["graph"];
export type MapNode = Graph["concepts"][number] & { x: number; y: number };
export type TopicBox = { id: string; title: string; summary: string; x: number; y: number; width: number; height: number };

export function layoutKnowledgeGraph(graph: Graph) {
  const ids = new Set(graph.concepts.map(c => c.id));
  const edges = graph.prerequisites.filter(e => ids.has(e.prerequisite) && ids.has(e.dependent));
  if (graph.topics?.length) {
    const nodes: MapNode[] = [], topicBoxes: TopicBox[] = [], placed = new Set<string>();
    const byId = new Map(graph.concepts.map(c => [c.id, c]));
    let y = 16;
    const topics = [...graph.topics];
    const grouped = new Set(topics.flatMap(t => t.conceptIds));
    const remaining = graph.concepts.filter(c => !grouped.has(c.id)).map(c => c.id);
    if (remaining.length) topics.push({ id: "ungrouped", title: "Other published concepts", summary: "Awaiting course organization", conceptIds: remaining });
    for (const topic of topics) {
      const members = topic.conceptIds.filter(id => ids.has(id) && !placed.has(id));
      if (!members.length) continue;
      const memberSet = new Set(members), depth = new Map(members.map(id => [id, 0]));
      const incoming = new Map(members.map(id => [id, 0]));
      const children = new Map(members.map(id => [id, [] as string[]]));
      for (const edge of edges.filter(e => memberSet.has(e.prerequisite) && memberSet.has(e.dependent))) {
        children.get(edge.prerequisite)!.push(edge.dependent);
        incoming.set(edge.dependent, incoming.get(edge.dependent)! + 1);
      }
      const ready = members.filter(id => !incoming.get(id));
      for (let i = 0; i < ready.length; i++) for (const child of children.get(ready[i])!) {
        depth.set(child, Math.max(depth.get(child)!, depth.get(ready[i])! + 1));
        incoming.set(child, incoming.get(child)! - 1);
        if (!incoming.get(child)) ready.push(child);
      }
      let top = y + 58;
      for (const rank of [...new Set(depth.values())].sort((a, b) => a - b)) {
        const level = members.filter(id => depth.get(id) === rank);
        level.forEach((id, i) => { nodes.push({ ...byId.get(id)!, x: 36 + i % 4 * 204, y: top + Math.floor(i / 4) * 136 }); placed.add(id); });
        top += Math.ceil(level.length / 4) * 136;
      }
      const height = top - y - 24;
      topicBoxes.push({ ...topic, x: 16, y, width: 852, height });
      y += height + 32;
    }
    return { nodes, edges, topicBoxes, width: 900, height: Math.max(360, y) };
  }
  const neighbors = new Map([...ids].map(id => [id, new Set<string>()]));
  for (const edge of edges) {
    neighbors.get(edge.prerequisite)!.add(edge.dependent);
    neighbors.get(edge.dependent)!.add(edge.prerequisite);
  }
  const seen = new Set<string>();
  const groups: Set<string>[] = [];
  for (const concept of graph.concepts) {
    if (seen.has(concept.id)) continue;
    const group = new Set<string>(), queue = [concept.id];
    while (queue.length) {
      const id = queue.pop()!;
      if (seen.has(id)) continue;
      seen.add(id); group.add(id);
      queue.push(...neighbors.get(id)!);
    }
    groups.push(group);
  }
  groups.sort((a, b) => b.size - a.size);
  const nodes: MapNode[] = [];
  let x = 24, y = 24, rowHeight = 0;
  for (const group of groups) {
    const members = graph.concepts.filter(c => group.has(c.id));
    const outgoing = new Map(members.map(c => [c.id, [] as string[]]));
    const incoming = new Map(members.map(c => [c.id, 0]));
    const depth = new Map(members.map(c => [c.id, 0]));
    for (const edge of edges.filter(e => group.has(e.prerequisite))) {
      outgoing.get(edge.prerequisite)!.push(edge.dependent);
      incoming.set(edge.dependent, incoming.get(edge.dependent)! + 1);
    }
    const ready = members.filter(c => !incoming.get(c.id)).map(c => c.id);
    for (let i = 0; i < ready.length; i++) {
      for (const child of outgoing.get(ready[i])!) {
        depth.set(child, Math.max(depth.get(child)!, depth.get(ready[i])! + 1));
        incoming.set(child, incoming.get(child)! - 1);
        if (!incoming.get(child)) ready.push(child);
      }
    }
    const levels = new Map<number, typeof members>();
    for (const concept of members) {
      const rank = depth.get(concept.id)!;
      levels.set(rank, [...(levels.get(rank) || []), concept]);
    }
    const width = Math.max(...[...levels.values()].map(level => Math.min(level.length, 4))) * 204 - 24;
    const height = [...levels.values()].reduce((sum, level) => sum + Math.ceil(level.length / 4) * 136, 0) - 48;
    if (x + width > 876) { x = 24; y += rowHeight + 40; rowHeight = 0; }
    let top = 0;
    for (const [, level] of [...levels].sort(([a], [b]) => a - b)) {
      level.forEach((concept, index) => nodes.push({ ...concept, x: x + index % 4 * 204, y: y + top + Math.floor(index / 4) * 136 }));
      top += Math.ceil(level.length / 4) * 136;
    }
    x += width + 24;
    rowHeight = Math.max(rowHeight, height);
  }
  return { nodes, edges, topicBoxes: [] as TopicBox[], width: 900, height: Math.max(360, y + rowHeight + 24) };
}
