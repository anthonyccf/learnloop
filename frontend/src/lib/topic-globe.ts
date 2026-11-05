import type { CourseDetail } from "./backend";
import { layerOf, type CurriculumLayer } from "./curriculum-map";

export type GlobeTopic = { id: string; topicId: string; title: string; layer: CurriculumLayer; conceptIds: string[] };

/** Share the published topic membership without running the old shelf force layout. */
export function topicExplorerGraph(graph: CourseDetail["graph"]) {
  const homes = new Map<string, { id: string; title: string }>();
  for (const topic of graph.topics || []) for (const id of topic.conceptIds) if (!homes.has(id)) homes.set(id, topic);
  const groups = new Map<string, GlobeTopic>();
  const nodes = [...graph.concepts].sort((a, b) => a.title.localeCompare(b.title) || a.id.localeCompare(b.id)).map(c => {
    const topic = homes.get(c.id) || { id: "__other__", title: "Other concepts" }, layer = layerOf(c);
    const regionId = JSON.stringify([layer, topic.id]);
    if (!groups.has(regionId)) groups.set(regionId, { id: regionId, topicId: topic.id, title: topic.title, layer, conceptIds: [] });
    groups.get(regionId)!.conceptIds.push(c.id);
    return { id: c.id, layer, regionId };
  });
  const ids = new Set(nodes.map(n => n.id));
  const bands = (["advanced", "intermediate", "basic", "unassigned"] as CurriculumLayer[]).flatMap(layer => {
    const count = nodes.filter(n => n.layer === layer).length;
    return count ? [{ layer, count }] : [];
  });
  return { groups: [...groups.values()].sort((a, b) => a.title.localeCompare(b.title) || a.id.localeCompare(b.id)), nodes, bands, edges: graph.prerequisites.filter(e => e.prerequisite !== e.dependent && ids.has(e.prerequisite) && ids.has(e.dependent)) };
}

/** Stable sphere positions keep a concept in the same place as a topic rotates. */
export type GlobeVector = { x: number; y: number; z: number };
export type GlobePose = { yaw: number; pitch: number };
export const DEFAULT_GLOBE_POSE: GlobePose = { yaw: -18, pitch: 12 };

export function globePoints(count: number): GlobeVector[] {
  if (count < 1) return [];
  if (count === 1) return [{ x: 0, y: 0, z: 1 }];
  const angle = Math.PI * (3 - Math.sqrt(5));
  return Array.from({ length: count }, (_, i) => {
    const y = 1 - 2 * (i + .5) / count;
    const r = Math.sqrt(1 - y * y), theta = angle * i;
    return { x: Math.sin(theta) * r, y, z: Math.cos(theta) * r };
  });
}

export function rotateGlobe(point: GlobeVector, pose: GlobePose) {
  const yaw = pose.yaw * Math.PI / 180, pitch = pose.pitch * Math.PI / 180;
  const x = point.x * Math.cos(yaw) + point.z * Math.sin(yaw);
  const z = -point.x * Math.sin(yaw) + point.z * Math.cos(yaw);
  return { x, y: point.y * Math.cos(pitch) - z * Math.sin(pitch), z: point.y * Math.sin(pitch) + z * Math.cos(pitch) };
}

/** Bring a search result exactly to the front, including points near the poles. */
export function faceGlobePoint(point: GlobeVector): GlobePose {
  return { yaw: Math.atan2(-point.x, point.z) * 180 / Math.PI, pitch: Math.atan2(point.y, Math.hypot(point.x, point.z)) * 180 / Math.PI };
}

export function projectGlobe(point: GlobeVector, pose: GlobePose, radius = 126) {
  const p = rotateGlobe(point, pose), perspective = 1 + p.z * .1;
  return { x: p.x * radius * perspective, y: -p.y * radius * perspective, depth: p.z, scale: .77 + (p.z + 1) * .15, front: p.z >= -.03 };
}
