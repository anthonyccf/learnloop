import type { CourseDetail, Difficulty } from "./backend";
export const SPATIAL_READABLE_SCALE=.68;
export const SPATIAL_YAW=-8;
export const SPATIAL_PITCH=28;
export type CurriculumLayer = Difficulty | "unassigned";
export const layerNames: Record<CurriculumLayer, string> = { basic: "Basic", intermediate: "Intermediate", advanced: "Advanced", unassigned: "Unassigned" };
export const layerBadge: Record<CurriculumLayer, string> = { basic: "B", intermediate: "I", advanced: "A", unassigned: "?" };
export const layerOf = (concept: CourseDetail["graph"]["concepts"][number]): CurriculumLayer => concept.curriculum?.layer || "unassigned";
export type CurriculumPoint = { id: string; x: number; y: number; z: number; flatX: number; flatY: number; layer: CurriculumLayer; topic: string; regionId: string; localX: number; localY: number };
export type TopicRegion = { id: string; topicId: string; title: string; layer: CurriculumLayer; conceptIds: string[]; cx: number; cz: number; width: number; depth: number; worldY: number; radius: number; labelLines: string[] };

export function curriculumScene(graph: CourseDetail["graph"]) {
  const topicFor = new Map<string, { id: string; title: string }>();
  for (const topic of graph.topics || []) for (const id of topic.conceptIds) {
    if (!topicFor.has(id)) topicFor.set(id, { id: topic.id, title: topic.title });
  }
  const topicOf = (id: string) => topicFor.get(id) || { id: "__other__", title: "Other concepts" };
  const nodes: CurriculumPoint[] = [];
  const groups: TopicRegion[] = [];
  let top = 40;
  const bands = (["advanced", "intermediate", "basic", "unassigned"] as CurriculumLayer[]).flatMap(layer => {
    const members = graph.concepts.filter(c => layerOf(c) === layer).sort((a,b) => topicOf(a.id).title.localeCompare(topicOf(b.id).title) || topicOf(a.id).id.localeCompare(topicOf(b.id).id) || a.title.localeCompare(b.title) || a.id.localeCompare(b.id));
    if (!members.length) return [];
    // The 2D pyramid keeps its compact, stable reading layout.
    const maxCols = layer === "basic" || layer === "unassigned" ? 18 : layer === "intermediate" ? 14 : 8;
    const cols = Math.min(maxCols, Math.max(1, Math.ceil(Math.sqrt(members.length * 3))));
    const rows = Math.ceil(members.length / cols), height = Math.max(190, rows * 76 + 95);
    const width = Math.max(420, cols * 70 + 110);
    const topicMembers = new Map<string, typeof members>();
    for (const c of members) {
      const id = topicOf(c.id).id;
      topicMembers.set(id, [...(topicMembers.get(id) || []), c]);
    }
    // Circular atlas groups keep a shared topic column on every layer plane.
    const spatial = new Map<string, {x:number;z:number;regionId:string;localX:number;localY:number}>();
    const floorGroups:TopicRegion[]=[];
    for(const [topicId,concepts] of topicMembers) {
      const extent=Math.ceil(Math.sqrt(concepts.length))+2;
      const slots:{x:number;y:number}[]=[];
      for(let row=-extent;row<=extent;row++)for(let col=-extent;col<=extent;col++)slots.push({x:(col+row/2)*72,y:row*72*Math.sqrt(3)/2});
      slots.sort((a,b)=>Math.hypot(a.x,a.y)-Math.hypot(b.x,b.y)||a.y-b.y||a.x-b.x);
      const labelLines=wrapTopicTitle(topicOf(concepts[0].id).title);
      const radius=Math.max(240,labelLines.length*24+160,...slots.slice(0,concepts.length).map(p=>Math.hypot(p.x,p.y+70)+50));
      const regionId=JSON.stringify([layer,topicId]);
      floorGroups.push({id:regionId,topicId,title:topicOf(concepts[0].id).title,layer,conceptIds:concepts.map(c=>c.id),cx:0,cz:0,width:radius*2,depth:radius*2,worldY:0,radius,labelLines});
      concepts.forEach((c,i)=>spatial.set(c.id,{x:slots[i].x,z:slots[i].y+70,localX:slots[i].x,localY:slots[i].y+70,regionId}));
    }
    groups.push(...floorGroups);
    members.forEach((c,index)=>{
      const row=Math.floor(index/cols),col=index%cols,inRow=Math.min(cols,members.length-row*cols),point=spatial.get(c.id)!;
      nodes.push({id:c.id,layer,topic:topicOf(c.id).title,regionId:point.regionId,x:point.x,y:0,z:point.z,localX:point.localX,localY:point.localY,flatX:700+(col-(inRow-1)/2)*70,flatY:top+92+row*76});
    });
    const band={layer,top,height,width,worldY:0,depth:Math.max(180,rows*82+55),spaceWidth:0,spaceDepth:0,count:members.length};
    top+=height+32;
    return [band];
  });
  const activeTopics=new Set(groups.map(g=>g.topicId));
  const topicOrder=[...new Set([...(graph.topics||[]).map(t=>t.id),"__other__"])].filter(id=>activeTopics.has(id));
  const maxRadius=Math.max(240,...groups.map(g=>g.radius));
  const rank:Record<CurriculumLayer,number>={basic:0,intermediate:1,advanced:2,unassigned:-1};
  const topicLinks=new Set<string>();
  for(const edge of [...graph.prerequisites.map(e=>[e.prerequisite,e.dependent] as const),...(graph.related||[]).map(e=>[e.first,e.second] as const)]){
    const from=topicOf(edge[0]).id,to=topicOf(edge[1]).id;
    if(from!==to&&activeTopics.has(from)&&activeTopics.has(to))topicLinks.add(JSON.stringify([from,to].sort()));
  }
  const topicRadius=new Map<string,number>();
  for(const g of groups)topicRadius.set(g.topicId,Math.max(topicRadius.get(g.topicId)||0,g.radius));
  const packed=new Map(packTopicPlane(topicOrder.map(id=>({id,radius:topicRadius.get(id)!})),topicLinks).map(topic=>[topic.id,topic]));
  const zScale=1/Math.sin(18*Math.PI/180),planeSpread=1.75;
  for(const g of groups){const topic=packed.get(g.topicId)!;g.cx=topic.x*planeSpread;g.cz=topic.y*zScale*planeSpread;}
  const halfW=groups.length?Math.max(...groups.map(g=>Math.abs(g.cx)+g.radius)):450;
  const halfD=groups.length?Math.max(...groups.map(g=>Math.abs(g.cz)+g.radius)):450;
  const skirt=Math.max(420,maxRadius*1.2);
  const spaceWidth=Math.max(900,halfW*2+skirt*2),spaceDepth=Math.max(900,halfD*2+skirt*2);
  const shelfPitch=SPATIAL_PITCH*Math.PI/180;
  const layerGap=Math.ceil(spaceDepth*Math.tan(shelfPitch)*.64);
  for(const g of groups)g.worldY=rank[g.layer]*layerGap;
  const regions=new Map(groups.map(g=>[g.id,g]));
  for(const n of nodes){const g=regions.get(n.regionId)!;n.x=g.cx+n.localX;n.y=g.worldY;n.z=g.cz+n.localY;}
  for(const b of bands){b.worldY=rank[b.layer]*layerGap;b.spaceWidth=spaceWidth;b.spaceDepth=spaceDepth;}
  const commonTopics=[...topicOrder].sort((a,b)=>new Set(groups.filter(g=>g.topicId===b).map(g=>g.layer)).size-new Set(groups.filter(g=>g.topicId===a).map(g=>g.layer)).size);
  const anchorTopic=commonTopics.find(id=>groups.some(g=>g.topicId===id&&g.layer==="advanced"))||commonTopics[0];
  const ids=new Set(nodes.map(n=>n.id));
  const yaw=SPATIAL_YAW*Math.PI/180,pitch=shelfPitch;
  const farthest=Math.max(0,...groups.map(g=>{const z=g.cx*Math.sin(yaw)+g.cz*Math.cos(yaw),y=g.worldY-layerGap;return z*Math.cos(pitch)-y*Math.sin(pitch);}));
  const cameraDistance=Math.max(1600,layerGap*3,...bands.map(b=>Math.max(b.spaceWidth,b.spaceDepth)*4),farthest*9);
  return {nodes,bands,groups,anchorTopic,centerY:layerGap,cameraDistance,width:1400,height:Math.max(600,top),edges:graph.prerequisites.filter(e=>e.prerequisite!==e.dependent&&ids.has(e.prerequisite)&&ids.has(e.dependent))};
}
export function learningPath(id:string, edges:{prerequisite:string;dependent:string}[]) {
  const walk = (reverse:boolean) => {
    const found = new Set<string>(), queue = [id];
    const adjacency = new Map<string,string[]>();
    for (const e of edges) { const from=reverse?e.dependent:e.prerequisite, to=reverse?e.prerequisite:e.dependent; adjacency.set(from,[...(adjacency.get(from)||[]),to]); }
    for(let i=0;i<queue.length;i++) for(const next of adjacency.get(queue[i])||[]) if(next!==id && !found.has(next)){found.add(next);queue.push(next);}
    return found;
  };
  const before=walk(true),after=walk(false);
  return {before,after,all:new Set([id,...before,...after])};
}
export function projectPoint(p:{x:number;y:number;z:number}, yaw:number, pitch:number, centerY=320, distance=1600) {
  const a=yaw*Math.PI/180,b=pitch*Math.PI/180;
  const x=p.x*Math.cos(a)-p.z*Math.sin(a), z=p.x*Math.sin(a)+p.z*Math.cos(a);
  const y=p.y-centerY;
  const depth=z*Math.cos(b)-y*Math.sin(b);
  const scale=distance/Math.max(distance*.25,distance+depth);
  return { x:700+x*scale, y:500+(-y*Math.cos(b)-z*Math.sin(b))*scale, depth, scale };
}


export function spatialViewport(scene: ReturnType<typeof curriculumScene>, yaw=-8, pitch=18) {
  const points=scene.bands.flatMap(b=>[-1,1].flatMap(x=>[-1,1].map(z=>projectPoint({x:x*b.spaceWidth/2,y:b.worldY,z:z*b.spaceDepth/2},yaw,pitch,scene.centerY,scene.cameraDistance))));
  for(const g of scene.groups) {
    const p=projectPoint({x:g.cx,y:g.worldY,z:g.cz},yaw,pitch,scene.centerY,scene.cameraDistance);
    points.push({x:p.x-g.radius*p.scale-80,y:p.y-g.radius*p.scale-80,depth:0,scale:1},{x:p.x+g.radius*p.scale+80,y:p.y+g.radius*p.scale+80,depth:0,scale:1});
  }
  if(!points.length)return {x:0,y:0,width:1400,height:1000};
  const x=Math.min(...points.map(p=>p.x))-100,y=Math.min(...points.map(p=>p.y))-100;
  return {x,y,width:Math.max(...points.map(p=>p.x))+100-x,height:Math.max(...points.map(p=>p.y))+100-y};
}

const GOLDEN_ANGLE=Math.PI*(3-Math.sqrt(5));
function packTopicPlane(topics:{id:string;radius:number}[],links:Set<string>){
  const placed=topics.map((topic,index)=>{const ring=240*Math.sqrt(index);return {...topic,x:Math.cos(index*GOLDEN_ANGLE)*ring,y:Math.sin(index*GOLDEN_ANGLE)*ring};});
  const pairs=placed.flatMap((a,i)=>placed.slice(i+1).map((b,offset)=>({i,j:i+offset+1,linked:links.has(JSON.stringify([a.id,b.id].sort()))})));
  for(let step=0;step<300;step++){
    const forces=placed.map(topic=>({x:-topic.x*.002,y:-topic.y*.002}));
    for(const pair of pairs){
      const a=placed[pair.i],b=placed[pair.j],dx=b.x-a.x,dy=b.y-a.y,distance=Math.max(.01,Math.hypot(dx,dy));
      const separation=a.radius+b.radius+160;
      const force=(pair.linked?(distance-separation-32)*.035:0)-8000/(distance*distance)-Math.max(0,separation-distance)*.6;
      const x=dx/distance*force,y=dy/distance*force;
      forces[pair.i].x+=x;forces[pair.i].y+=y;forces[pair.j].x-=x;forces[pair.j].y-=y;
    }
    placed.forEach((topic,index)=>{const force=forces[index],scale=Math.min(1,8/Math.max(.01,Math.hypot(force.x,force.y)));topic.x+=force.x*scale;topic.y+=force.y*scale;});
  }
  for(let pass=0;pass<200;pass++){
    let overlap=false;
    for(const {i,j} of pairs){
      const a=placed[i],b=placed[j];
      let dx=b.x-a.x,dy=b.y-a.y;
      if(!dx&&!dy){dx=Math.cos((i+j)*GOLDEN_ANGLE)*.01;dy=Math.sin((i+j)*GOLDEN_ANGLE)*.01;}
      const distance=Math.hypot(dx,dy),minimum=a.radius+b.radius+160;
      if(distance>=minimum)continue;
      overlap=true;
      const shift=(minimum-distance+.001)/2,x=dx/distance*shift,y=dy/distance*shift;
      a.x-=x;a.y-=y;b.x+=x;b.y+=y;
    }
    if(!overlap)break;
  }
  if(!placed.length)return placed;
  const minX=Math.min(...placed.map(topic=>topic.x-topic.radius)),maxX=Math.max(...placed.map(topic=>topic.x+topic.radius));
  const minY=Math.min(...placed.map(topic=>topic.y-topic.radius)),maxY=Math.max(...placed.map(topic=>topic.y+topic.radius));
  const shiftX=(minX+maxX)/2,shiftY=(minY+maxY)/2;
  for(const topic of placed){topic.x-=shiftX;topic.y-=shiftY;}
  return placed;
}

export function wrapTopicTitle(title:string, width=29) {
  const lines:string[]=[];let line="";
  for(const word of title.split(/\s+/)){
    if(line&&line.length+word.length+1>width){lines.push(line);line="";}
    line+=(line?" ":"")+word;
  }
  if(line)lines.push(line);
  return lines;
}

export function projectAtlasConcept(node:CurriculumPoint,group:TopicRegion,yaw:number,pitch:number,centerY:number,distance:number){
  return projectPoint({x:group.cx+node.localX,y:group.worldY,z:group.cz+node.localY},yaw,pitch,centerY,distance);
}
export function projectDisk(group:TopicRegion,yaw:number,pitch:number,centerY:number,distance:number,yOffset=0,steps=40){
  return Array.from({length:steps},(_,i)=>{
    const t=i/steps*Math.PI*2;
    return projectPoint({x:group.cx+Math.cos(t)*group.radius,y:group.worldY+yOffset,z:group.cz+Math.sin(t)*group.radius},yaw,pitch,centerY,distance);
  });
}
