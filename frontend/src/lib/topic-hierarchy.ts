export type HierarchyTopic = { id: string; title: string; summary: string; parentId?: string | null; conceptIds: string[] };

export function hierarchy(topics: HierarchyTopic[], conceptIds: string[]) {
  const valid = new Set(conceptIds);
  const byId = new Map(topics.map(topic => [topic.id, topic]));
  const direct = new Set(topics.flatMap(topic => topic.conceptIds));
  const roots = topics.filter(topic => !topic.parentId || !byId.has(topic.parentId));
  const children = (id: string | null) => id === null ? roots : topics.filter(topic => topic.parentId === id);
  function descendants(id: string) {
    const seen = new Set<string>(), result = new Set<string>(), queue = [id];
    for (let i = 0; i < queue.length; i++) {
      const topic = byId.get(queue[i]);
      if (!topic || seen.has(topic.id)) continue;
      seen.add(topic.id);
      topic.conceptIds.filter(value => valid.has(value)).forEach(value => result.add(value));
      children(topic.id).forEach(child => queue.push(child.id));
    }
    return [...result];
  }
  function path(id: string) {
    const result: HierarchyTopic[] = [], seen = new Set<string>();
    let current = byId.get(id);
    while (current && !seen.has(current.id)) { seen.add(current.id); result.unshift(current); current = current.parentId ? byId.get(current.parentId) : undefined; }
    return result;
  }
  return { byId, children, descendants, path, ungrouped: conceptIds.filter(id => !direct.has(id)) };
}
