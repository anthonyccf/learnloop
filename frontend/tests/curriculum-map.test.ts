import { test } from "node:test";
import assert from "node:assert/strict";
import { curriculumScene, learningPath, projectPoint, layerOf, spatialViewport, projectAtlasConcept, projectDisk, SPATIAL_PITCH, SPATIAL_READABLE_SCALE } from "../src/lib/curriculum-map";
import { readKnowledgeView, knowledgeViewUrl } from "../src/lib/knowledge-view";
import type { CourseDetail, Difficulty } from "../src/lib/backend";

const graph = ():CourseDetail["graph"] => ({concepts:Array.from({length:128},(_,i)=>{
 const layer:Difficulty=i<71?"basic":i<122?"intermediate":"advanced";
 return {id:`c${i}`,title:`Concept ${i}`,summary:"Source-supported goal",sources:[],targetDifficulty:"advanced",curriculum:{conceptId:`c${i}`,layer,teaches:"Distinct teaching scope",adds:"A new supported capability",assumes:[]}};
}),prerequisites:[{prerequisite:"c0",dependent:"c71"},{prerequisite:"c71",dependent:"c122"},{prerequisite:"missing",dependent:"c0"}],topics:[]});

test("all 128 concepts occupy their actual curriculum layer without flat overlaps",()=>{
 const g=graph(),scene=curriculumScene(g);
 assert.equal(scene.nodes.length,128);
 assert.deepEqual(scene.bands.map(b=>[b.layer,b.count]),[["advanced",6],["intermediate",51],["basic",71]]);
 for(const n of scene.nodes){const band=scene.bands.find(b=>b.layer===n.layer)!;assert.ok(n.flatY>band.top && n.flatY<band.top+band.height);}
 for(let i=0;i<scene.nodes.length;i++)for(let j=i+1;j<scene.nodes.length;j++)assert.ok(Math.hypot(scene.nodes[i].flatX-scene.nodes[j].flatX,scene.nodes[i].flatY-scene.nodes[j].flatY)>=60);
 assert.equal(scene.edges.length,2);
 assert.ok(scene.nodes.find(n=>n.id==="c122")!.y>scene.nodes.find(n=>n.id==="c0")!.y);
 assert.equal(layerOf(g.concepts[0]),"basic"); // Mastery target is independently advanced.
});

test("unassigned and empty curricula are safe, with no inferred difficulty",()=>{
 const g=graph();g.concepts=[{id:"legacy",title:"Legacy",summary:"No assigned layer",sources:[],targetDifficulty:"advanced"}];
 const s=curriculumScene(g);assert.equal(s.nodes[0].layer,"unassigned");assert.equal(s.edges.length,0);
 assert.equal(curriculumScene({concepts:[],prerequisites:[]}).nodes.length,0);
});

test("selected paths preserve direction, exclude unrelated branches and terminate on cycles",()=>{
 const edges=[{prerequisite:"a",dependent:"b"},{prerequisite:"b",dependent:"c"},{prerequisite:"x",dependent:"y"}];
 const p=learningPath("b",edges);assert.deepEqual([...p.before],["a"]);assert.deepEqual([...p.after],["c"]);assert.ok(!p.all.has("x"));
 assert.equal(learningPath("a",[...edges,{prerequisite:"c",dependent:"a"}]).all.size,3);
});

test("3D projection uses depth, stays finite across camera limits and is deterministic",()=>{
 for(const yaw of [-65,0,65])for(const pitch of [18,34,62])for(const n of curriculumScene(graph()).nodes){
  const p=projectPoint(n,yaw,pitch);assert.ok(Number.isFinite(p.x)&&Number.isFinite(p.y)&&p.scale>0);
 }
 assert.notDeepEqual(projectPoint({x:100,y:0,z:100},-22,34),projectPoint({x:100,y:0,z:100},22,34));
 assert.deepEqual(projectPoint({x:0,y:320,z:0},0,34),{x:700,y:500,depth:0,scale:1});
});

test("layer and 3D deep links persist separately from evidence difficulty",()=>{
 const v=readKnowledgeView(new URLSearchParams("layout=space&layer=basic&level=advanced&q=cache"));
 const restored=readKnowledgeView(new URL(knowledgeViewUrl(v),"http://localhost").searchParams);
 assert.deepEqual(restored,v);assert.equal(v.layer,"basic");assert.equal(v.level,"advanced");
 const fallback=readKnowledgeView(new URLSearchParams("layout=bad&layer=bad"));assert.equal(fallback.layout,"pyramid");assert.equal(fallback.layer,"all");
});


test("3D topics form separate regions within each layer and preserve every concept",()=>{
 const g=graph();
 g.topics=[
  {id:"one",title:"Shared topic",summary:"First topic",conceptIds:g.concepts.filter((_,i)=>i%2===0).map(c=>c.id)},
  {id:"two",title:"Shared topic",summary:"Distinct topic with the same title",conceptIds:g.concepts.filter((_,i)=>i%2===1).map(c=>c.id)},
 ];
 const s=curriculumScene(g);
 assert.equal(s.groups.length,6); // Each published topic occupies three layers.
 assert.equal(new Set(s.groups.flatMap(r=>r.conceptIds)).size,128);
 assert.equal(s.groups.reduce((sum,r)=>sum+r.conceptIds.length,0),128);
 for(const group of s.groups){
  const expected=g.topics.find(t=>t.id===group.topicId)!;
  for(const id of group.conceptIds){
   const n=s.nodes.find(n=>n.id===id)!;
   assert.ok(expected.conceptIds.includes(id));assert.equal(n.layer,group.layer);assert.equal(n.regionId,group.id);
   assert.ok(Math.abs(n.x-group.cx)+22<=group.width/2);
   assert.ok(Math.abs(n.z-group.cz)+22<=group.depth/2);
  }
 }
 for(let i=0;i<s.groups.length;i++)for(let j=i+1;j<s.groups.length;j++){
  const a=s.groups[i],b=s.groups[j];if(a.layer!==b.layer)continue;
  assert.ok(Math.abs(a.cx-b.cx)>(a.width+b.width)/2||Math.abs(a.cz-b.cz)>(a.depth+b.depth)/2);
 }
 const bounds=spatialViewport(s,-22,34);
 for(const group of s.groups)for(const x of [-1,1])for(const z of [-1,1]){
  const p=projectPoint({x:group.cx+x*group.width/2,y:group.worldY,z:group.cz+z*group.depth/2},-22,34,s.centerY,s.cameraDistance);
  assert.ok(p.x>bounds.x&&p.x<bounds.x+bounds.width&&p.y>bounds.y&&p.y<bounds.y+bounds.height);
 }
 assert.deepEqual(curriculumScene({...g,concepts:[...g.concepts].reverse()}),s);
});

test("overlapping topic memberships use their first published home, with an explicit remainder",()=>{
 const g=graph();g.concepts=g.concepts.slice(0,3);
 g.topics=[{id:"a",title:"A",summary:"Topic A",conceptIds:["c0","c1","missing"]},{id:"b",title:"B",summary:"Topic B",conceptIds:["c1"]}];
 const s=curriculumScene(g);
 assert.equal(s.groups.length,2);assert.equal(s.groups.find(r=>r.topicId==="a")!.conceptIds.length,2);
 assert.equal(s.groups.find(r=>r.topicId==="__other__")!.conceptIds[0],"c2");
 assert.equal(s.groups.flatMap(r=>r.conceptIds).length,3);
});


function insidePolygon(point:{x:number;y:number},polygon:{x:number;y:number}[]){
 let crossings=0;
 for(let i=0;i<polygon.length;i++){
  const a=polygon[i],b=polygon[(i+1)%polygon.length];
  if((a.y>point.y)!==(b.y>point.y)){
   const x=(b.x-a.x)*(point.y-a.y)/(b.y-a.y)+a.x;
   if(point.x<x)crossings++;
  }
 }
 return crossings%2===1;
}

test("atlas circles contain their concept bubbles at every supported camera angle",()=>{
 const g=graph();g.topics=Array.from({length:22},(_,i)=>({id:`topic-${i}`,title:`Published topic ${i} with a complete readable name`,summary:"A published topic",conceptIds:g.concepts.filter((_,j)=>j%22===i).map(c=>c.id)}));
 const scene=curriculumScene(g);
 for(const region of scene.groups){
  assert.equal(region.labelLines.join(" "),region.title);
  for(const id of region.conceptIds){
   const node=scene.nodes.find(n=>n.id===id)!;
   assert.ok(Math.hypot(node.localX,node.localY)+22<region.radius);
   const countBaseline=-region.radius+65+region.labelLines.length*24;
   assert.ok(node.localY-22>countBaseline+8);
   for(const yaw of [-60,-8,40])for(const pitch of [16,SPATIAL_PITCH,48]){
    const placed=projectAtlasConcept(node,region,yaw,pitch,scene.centerY,scene.cameraDistance);
    const expected=projectPoint({x:region.cx+node.localX,y:region.worldY,z:region.cz+node.localY},yaw,pitch,scene.centerY,scene.cameraDistance);
    assert.deepEqual(placed,expected);
    const rim=projectDisk(region,yaw,pitch,scene.centerY,scene.cameraDistance,0,48);
    assert.ok(insidePolygon(placed,rim));
   }
  }
 }
});

test("wide layers preserve readable topic sizes instead of shrinking the full course",()=>{
 const g=graph();g.topics=Array.from({length:22},(_,i)=>({id:`topic-${i}`,title:`Topic ${i}`,summary:"Published topic",conceptIds:g.concepts.filter((_,j)=>j%22===i).map(c=>c.id)}));
 const scene=curriculumScene(g);
 const basic=scene.bands.find(b=>b.layer==="basic")!,middle=scene.bands.find(b=>b.layer==="intermediate")!;
 const pitch=SPATIAL_PITCH*Math.PI/180,gap=middle.worldY-basic.worldY,touching=basic.spaceDepth*Math.tan(pitch);
 assert.ok(gap>touching*.5&&gap<touching);
 assert.ok(new Set(scene.groups.map(g=>g.cx)).size>1);
 assert.ok(new Set(scene.groups.map(g=>g.cz)).size>1);
 for(const band of scene.bands)for(const group of scene.groups.filter(g=>g.layer===band.layer)){
  assert.ok(Math.abs(group.cx)+group.radius<band.spaceWidth/2);
  assert.ok(Math.abs(group.cz)+group.radius<band.spaceDepth/2);
 }
 for(const group of scene.groups){
  const p=projectPoint({x:group.cx,y:group.worldY,z:group.cz},-8,SPATIAL_PITCH,scene.centerY,scene.cameraDistance);
  assert.ok(group.radius*2*p.scale*SPATIAL_READABLE_SCALE>=280);
  assert.ok(20*p.scale*SPATIAL_READABLE_SCALE>=12);
 }
 const topics=new Map<string,{cx:number;cz:number}>();
 for(const group of scene.groups){const placed=topics.get(group.topicId);if(placed){assert.equal(group.cx,placed.cx);assert.equal(group.cz,placed.cz);}else topics.set(group.topicId,{cx:group.cx,cz:group.cz});}
});
