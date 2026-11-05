export type KnowledgeView = {
  id: string; mode: "personal" | "course"; level: string;
  query: string; topic: string; material: string; status: string;
  display: "auto" | "map" | "list";
  layout: "atlas" | "pyramid" | "space"; layer: "all" | "basic" | "intermediate" | "advanced" | "unassigned";
};

export function readKnowledgeView(params: URLSearchParams): KnowledgeView {
  const mode = params.get("view") === "course" ? "course" : "personal";
  return {
    id: params.get("concept") || "", mode,
    level: ["basic", "intermediate", "advanced"].includes(params.get("level") || "") ? params.get("level")! : "intermediate",
    query: params.get("q") || "", topic: params.get("topic") || "all", material: params.get("material") || "all",
    status: mode === "personal" && ["unassessed", "developing", "demonstrated", "review_due"].includes(params.get("state") || "") ? params.get("state")! : "all",
    layout: params.get("layout") === "atlas" ? "atlas" : params.get("layout") === "space" ? "space" : "pyramid",
    layer: ["basic", "intermediate", "advanced", "unassigned"].includes(params.get("layer") || "") ? params.get("layer") as KnowledgeView["layer"] : "all",
    display: params.get("display") === "map" ? "map" : params.get("display") === "list" ? "list" : "auto",
  };
}

export function knowledgeViewUrl(view: KnowledgeView) {
  const params = new URLSearchParams();
  if (view.layout !== "pyramid") params.set("layout", view.layout);
  if (view.layer !== "all") params.set("layer", view.layer);
  if (view.id) params.set("concept", view.id);
  if (view.mode === "course") params.set("view", "course");
  if (view.level !== "intermediate") params.set("level", view.level);
  if (view.query) params.set("q", view.query);
  if (view.topic !== "all") params.set("topic", view.topic);
  if (view.material !== "all") params.set("material", view.material);
  if (view.mode === "personal" && view.status !== "all") params.set("state", view.status);
  if (view.display !== "auto") params.set("display", view.display);
  return `/map${params.size ? `?${params}` : ""}`;
}
