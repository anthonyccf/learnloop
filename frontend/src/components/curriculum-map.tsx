"use client";
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CourseDetail } from "@/lib/backend";
import { curriculumScene, layerBadge, layerNames, learningPath, projectPoint, projectAtlasConcept, projectDisk, spatialViewport, SPATIAL_PITCH, SPATIAL_READABLE_SCALE, SPATIAL_YAW, type TopicRegion } from "@/lib/curriculum-map";
import { placeMapPreview } from "@/lib/map-preview";

const stateNames:Record<string,string>={unassessed:"Not assessed",developing:"Developing",demonstrated:"Demonstrated",review_due:"Review due",neutral:"Course concept"};
const INITIAL_CAMERA={yaw:SPATIAL_YAW,pitch:SPATIAL_PITCH,zoom:1,x:0,y:0};
const YAW_LIMIT=60,PITCH_MIN=16,PITCH_MAX=50;
const READABLE_SCALE=SPATIAL_READABLE_SCALE;
type Preview={id:string;pinned:boolean;left:number;top:number;width:number;maxHeight:number};

export function CurriculumMap({graph, space, matches, stateAt, onOpen, selectedId="", onClear}:{graph:CourseDetail["graph"];space:boolean;matches:Set<string>;stateAt:(id:string)=>string;onOpen:(id:string)=>void;selectedId?:string;onClear?:()=>void}) {
  const graphKey=JSON.stringify(graph);
  const scene=useMemo(()=>curriculumScene(JSON.parse(graphKey) as CourseDetail["graph"]),[graphKey]);
  const groups=useMemo(()=>new Map(scene.groups.map(g=>[g.id,g])),[scene]);
  const frameRef=useRef<HTMLDivElement>(null);
  const canvasRef=useRef<HTMLDivElement>(null);
  const previewRef=useRef<HTMLDivElement>(null);
  const previewAnchor=useRef<SVGGElement|null>(null);
  const closeTimer=useRef<number|null>(null);
  const suppressFocus=useRef(false);
  const pointerType=useRef("mouse");
  const initializedScene=useRef("");
  const [canvasSize,setCanvasSize]=useState({width:900,height:820});
  const [camera,setCamera]=useState(INITIAL_CAMERA);
  const cameraRef=useRef(camera);
  useEffect(()=>{cameraRef.current=camera;},[camera]);
  const bounds=useMemo(()=>spatialViewport(scene,camera.yaw,camera.pitch),[scene,camera.yaw,camera.pitch]);
  const previousBounds=useRef<{x:number;y:number;key:string}|null>(null);
  const [localFocus,setLocalFocus]=useState({id:selectedId,from:selectedId});
  const [groupFocus,setGroupFocus]=useState("");
  const [preview,setPreview]=useState<Preview|null>(null);
  const [showGroupLabels,setShowGroupLabels]=useState(true);
  const focus=localFocus.from===selectedId?localFocus.id:selectedId;
  const setFocus=(id:string)=>setLocalFocus({id,from:selectedId});
  const drag=useRef<{x:number;y:number;left:number;top:number;orbit:boolean;camera:typeof camera}|null>(null);
  const arrow=useId().replaceAll(":","");
  const activeId=preview?.id||focus;
  const path=useMemo(()=>learningPath(activeId,scene.edges),[activeId,scene.edges]);
  const activeGroup=space&&!focus?scene.groups.find(g=>g.id===groupFocus&&g.conceptIds.some(id=>matches.has(id))):undefined;
  const project=(p:{x:number;y:number;z:number},pose=camera)=>projectPoint(p,pose.yaw,pose.pitch,scene.centerY,scene.cameraDistance);
  const projected=scene.nodes.map(n=>({...n,...(space?projectAtlasConcept(n,groups.get(n.regionId)!,camera.yaw,camera.pitch,scene.centerY,scene.cameraDistance):{x:n.flatX,y:n.flatY,depth:0,scale:1})})).sort((a,b)=>b.depth-a.depth);
  const positions=new Map(projected.map(n=>[n.id,n]));
  const current=graph.concepts.find(c=>c.id===focus);
  const currentPoint=positions.get(focus);
  const previewNode=graph.concepts.find(c=>c.id===preview?.id);
  const previewPoint=positions.get(preview?.id||"");
  const pixelScale=READABLE_SCALE*camera.zoom;
  const title=(id:string)=>graph.concepts.find(c=>c.id===id)?.title||id;
  const cancelClose=()=>{if(closeTimer.current!==null){window.clearTimeout(closeTimer.current);closeTimer.current=null;}};
  function closePreview(restore=false){
    cancelClose();setPreview(null);
    if(restore){suppressFocus.current=true;previewAnchor.current?.focus({preventScroll:true});queueMicrotask(()=>{suppressFocus.current=false;});}
  }
  function scheduleClose(){cancelClose();closeTimer.current=window.setTimeout(()=>setPreview(p=>p?.pinned||previewRef.current?.contains(document.activeElement)?p:null),220);}
  function openPreview(id:string,anchor:SVGGElement,pinned=false){
    if(suppressFocus.current||drag.current||!frameRef.current)return;
    cancelClose();previewAnchor.current=anchor;
    const frame=frameRef.current.getBoundingClientRect(),rect=anchor.getBoundingClientRect();
    const placement=placeMapPreview({left:rect.left-frame.left,top:rect.top-frame.top,width:rect.width,height:rect.height},frame);
    const visibleTop=Math.max(12,12-frame.top),visibleBottom=Math.min(frame.height-12,window.innerHeight-frame.top-12);
    const maxHeight=Math.min(228,Math.max(120,visibleBottom-visibleTop));
    setPreview({id,pinned,...placement,maxHeight,top:Math.max(visibleTop,Math.min(placement.top,visibleBottom-maxHeight))});
  }
  function openConcept(id:string){
    suppressFocus.current=true;closePreview();setGroupFocus("");setFocus(id);onOpen(id);
    requestAnimationFrame(()=>{suppressFocus.current=false;});
  }
  function frameLineage(id:string){
    const route=learningPath(id,scene.edges);
    const placed=scene.nodes.filter(n=>n.id===id||route.all.has(n.id)).flatMap(n=>{const group=groups.get(n.regionId);return group?[projectAtlasConcept(n,group,camera.yaw,camera.pitch,scene.centerY,scene.cameraDistance)]:[];});
    const box=canvasRef.current;
    if(!placed.length||!box)return;
    const pad=140,minX=Math.min(...placed.map(p=>p.x))-pad,maxX=Math.max(...placed.map(p=>p.x))+pad,minY=Math.min(...placed.map(p=>p.y))-pad,maxY=Math.max(...placed.map(p=>p.y))+pad;
    const zoom=Math.max(.35,Math.min(2,box.clientWidth/((maxX-minX)*READABLE_SCALE),box.clientHeight/((maxY-minY)*READABLE_SCALE)));
    setCamera(c=>({...c,zoom}));
    const scale=READABLE_SCALE*zoom;
    requestAnimationFrame(()=>box.scrollTo({left:Math.max(0,((minX+maxX)/2-bounds.x)*scale-box.clientWidth/2),top:Math.max(0,((minY+maxY)/2-bounds.y)*scale-box.clientHeight/2),behavior:"instant"}));
  }
  function showLineage(id:string){
    suppressFocus.current=true;closePreview();setGroupFocus("");setLocalFocus({id,from:""});onClear?.();
    if(space)frameLineage(id);
    requestAnimationFrame(()=>{suppressFocus.current=false;});
  }
  function stageOrigin(zoom:number,viewport:{width:number;height:number}){
    const box=canvasRef.current,scale=READABLE_SCALE*zoom,svgW=viewport.width*scale,svgH=viewport.height*scale;
    return {scale,x:Math.max(0,((box?.clientWidth||0)-svgW)/2),y:Math.max(0,((box?.clientHeight||0)-svgH)/2)};
  }
  function scrollToPoint(p:{x:number;y:number},zoom=camera.zoom,viewport=bounds){
    const box=canvasRef.current;if(!box)return;
    const origin=stageOrigin(zoom,viewport);
    requestAnimationFrame(()=>box.scrollTo({left:Math.max(0,origin.x+(p.x-viewport.x)*origin.scale-box.clientWidth/2),top:Math.max(0,origin.y+(p.y-viewport.y)*origin.scale-box.clientHeight/2),behavior:"instant"}));
  }
  function frameStack(pose=INITIAL_CAMERA){
    const box=canvasRef.current;
    if(!box||!scene.groups.length)return;
    const samples=scene.groups.flatMap(group=>{
      const p=projectPoint({x:group.cx,y:group.worldY,z:group.cz},pose.yaw,pose.pitch,scene.centerY,scene.cameraDistance);
      const rx=group.radius*p.scale,ry=Math.max(40,group.radius*p.scale*Math.sin(pose.pitch*Math.PI/180));
      return [{x:p.x-rx,y:p.y-ry},{x:p.x+rx,y:p.y+ry}];
    });
    const minX=Math.min(...samples.map(p=>p.x)),maxX=Math.max(...samples.map(p=>p.x)),minY=Math.min(...samples.map(p=>p.y)),maxY=Math.max(...samples.map(p=>p.y));
    const viewport=spatialViewport(scene,pose.yaw,pose.pitch);
    const zoom=Math.max(.12,Math.min(1.7,box.clientWidth/((maxX-minX)*READABLE_SCALE)*.92,box.clientHeight/((maxY-minY)*READABLE_SCALE)*.92));
    setCamera({...pose,zoom});
    scrollToPoint({x:(minX+maxX)/2,y:(minY+maxY)/2},zoom,viewport);
  }
  function reset(){
    closePreview();setGroupFocus("");
    if(space)frameStack(INITIAL_CAMERA);else setCamera(INITIAL_CAMERA);
  }
  function chooseGroup(group:TopicRegion){
    if(!group.conceptIds.some(id=>matches.has(id)))return;
    closePreview();setFocus("");setGroupFocus(group.id);onClear?.();
    const p=project({x:group.cx,y:group.worldY,z:group.cz});
    const diameter=group.radius*2*p.scale*READABLE_SCALE;
    const zoom=Math.max(.5,Math.min(3,canvasSize.width/diameter*.8,canvasSize.height/diameter*.75));
    setCamera(c=>({...c,zoom}));scrollToPoint(p,zoom);
  }
  function changeZoom(delta:number){
    closePreview();const zoom=Math.max(.08,Math.min(6,camera.zoom+delta));
    const box=canvasRef.current;
    const origin=stageOrigin(camera.zoom,bounds);
    const p=box?{x:bounds.x+(box.scrollLeft+box.clientWidth/2-origin.x)/pixelScale,y:bounds.y+(box.scrollTop+box.clientHeight/2-origin.y)/pixelScale}:undefined;
    setCamera(c=>({...c,zoom}));if(space&&p)scrollToPoint(p,zoom);
  }
  function fitAll(){
    closePreview();setGroupFocus("");const zoom=Math.min(canvasSize.width/bounds.width,canvasSize.height/bounds.height)/READABLE_SCALE*.94;
    setCamera(c=>({...c,zoom}));scrollToPoint({x:bounds.x+bounds.width/2,y:bounds.y+bounds.height/2},zoom);
  }
  function jumpToLayer(layer:string){
    const topic=activeGroup?.topicId||scene.anchorTopic;
    const group=scene.groups.find(g=>g.layer===layer&&g.topicId===topic)||scene.groups.find(g=>g.layer===layer&&g.conceptIds.some(id=>matches.has(id)));
    if(group){closePreview();scrollToPoint(project({x:group.cx,y:group.worldY,z:group.cz}));}
  }
  useEffect(()=>{
    if(!canvasRef.current)return;
    const observer=new ResizeObserver(([entry])=>{if(entry.contentRect.width&&entry.contentRect.height)setCanvasSize({width:entry.contentRect.width,height:entry.contentRect.height});setPreview(null);});
    observer.observe(canvasRef.current);return()=>observer.disconnect();
  },[]);
  useLayoutEffect(()=>{
    const previous=previousBounds.current;
    previousBounds.current={x:bounds.x,y:bounds.y,key:graphKey};
    if(space&&previous?.key===graphKey&&canvasRef.current){
      canvasRef.current.scrollLeft+=(previous.x-bounds.x)*pixelScale;
      canvasRef.current.scrollTop+=(previous.y-bounds.y)*pixelScale;
    }
  },[space,bounds,graphKey,pixelScale]);
  useLayoutEffect(()=>{
    if(!space||initializedScene.current===graphKey)return;
    initializedScene.current=graphKey;
    frameStack(INITIAL_CAMERA);
    // A saved graph refresh must not override a learner's manual pan.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[space,scene,graphKey]);
  useEffect(()=>{
    if(!preview)return;
    const escape=(e:KeyboardEvent)=>{if(e.key==="Escape"){e.preventDefault();closePreview(true);}};
    const outside=(e:PointerEvent)=>{const target=e.target as Node;if(!previewRef.current?.contains(target)&&!previewAnchor.current?.contains(target))closePreview();};
    document.addEventListener("keydown",escape);document.addEventListener("pointerdown",outside);
    return()=>{document.removeEventListener("keydown",escape);document.removeEventListener("pointerdown",outside);};
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[preview?.id]);
  useEffect(()=>()=>{if(closeTimer.current!==null)window.clearTimeout(closeTimer.current);},[]);
  useEffect(()=>{
    const element=canvasRef.current;
    if(!space||!element)return;
    const onWheel=(event:WheelEvent)=>{
      event.preventDefault();
      closePreview();
      const rect=element.getBoundingClientRect(),pointX=event.clientX-rect.left,pointY=event.clientY-rect.top;
      const wheelAmount=event.shiftKey&&event.deltaX?event.deltaX:event.deltaY||event.deltaX;
      const delta=wheelAmount*(event.deltaMode===WheelEvent.DOM_DELTA_LINE?16:event.deltaMode===WheelEvent.DOM_DELTA_PAGE?element.clientHeight:1);
      const before=cameraRef.current.zoom,next=Math.max(.08,Math.min(6,before*Math.exp(-delta*.0012)));
      if(next===before)return;
      const left=(element.scrollLeft+pointX)*(next/before)-pointX,top=(element.scrollTop+pointY)*(next/before)-pointY;
      setCamera(c=>({...c,zoom:next}));
      requestAnimationFrame(()=>element.scrollTo({left,top,behavior:"instant"}));
    };
    element.addEventListener("wheel",onWheel,{passive:false});
    return()=>element.removeEventListener("wheel",onWheel);
    // Camera is read through a ref; preview dismissal uses only refs and a stable setter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[space]);
  const showAllTitles=camera.zoom>=1.45;
  const diskOf=(group:TopicRegion,yOffset=0)=>projectDisk(group,camera.yaw,camera.pitch,scene.centerY,scene.cameraDistance,yOffset);
  function shelfGrid(band:(typeof scene.bands)[number]){
    const step=720,x0=-band.spaceWidth/2,x1=band.spaceWidth/2,z0=-band.spaceDepth/2,z1=band.spaceDepth/2,parts:string[]=[];
    for(let x=Math.ceil(x0/step)*step;x<=x1;x+=step){if(Math.abs(x-x0)<1||Math.abs(x-x1)<1)continue;const a=project({x,y:band.worldY,z:z0}),b=project({x,y:band.worldY,z:z1});parts.push(`M${a.x} ${a.y} L${b.x} ${b.y}`);}
    for(let z=Math.ceil(z0/step)*step;z<=z1;z+=step){if(Math.abs(z-z0)<1||Math.abs(z-z1)<1)continue;const a=project({x:x0,y:band.worldY,z}),b=project({x:x1,y:band.worldY,z});parts.push(`M${a.x} ${a.y} L${b.x} ${b.y}`);}
    return parts.join(" ");
  }
  const spatialGroups=[...scene.groups].map((group,index)=>({group,index,depth:project({x:group.cx,y:group.worldY,z:group.cz}).depth})).sort((a,b)=>b.depth-a.depth);
  const columns=[...scene.groups.reduce((stacks,group)=>{const stack=stacks.get(group.topicId)||[];stack.push(group);stacks.set(group.topicId,stack);return stacks;},new Map<string,TopicRegion[]>()).values()].map(stack=>stack.sort((a,b)=>a.worldY-b.worldY)).filter(stack=>stack.length>1);
  function conceptMark(n:(typeof projected)[number]){
    const concept=graph.concepts.find(c=>c.id===n.id)!;
    const dim=(!matches.has(n.id)&&!path.all.has(n.id))||!!activeId&&!path.all.has(n.id)||!!activeGroup&&n.regionId!==activeGroup.id;
    const named=focus===n.id||path.all.has(n.id)||(showAllTitles&&!dim)||(!!activeGroup&&n.regionId===activeGroup.id);
    const short=concept.title.length>28?`${concept.title.slice(0,26)}...`:concept.title;
    return <g key={n.id} transform={`translate(${n.x} ${n.y})`} role="button" tabIndex={matches.has(n.id)&&(!activeGroup||n.regionId===activeGroup.id)||path.all.has(n.id)?0:-1} aria-label={`${concept.title} · ${layerNames[n.layer]} · ${stateNames[stateAt(n.id)]||stateAt(n.id)}`} aria-pressed={focus===n.id} aria-haspopup="dialog" aria-expanded={preview?.id===n.id} className={`curriculum-dot ${stateAt(n.id)} ${dim?"is-dimmed":""} ${focus===n.id?"is-selected":""}`}
      onPointerEnter={e=>{if(e.pointerType!=="touch")openPreview(n.id,e.currentTarget);}} onPointerLeave={scheduleClose} onPointerDown={e=>{pointerType.current=e.pointerType;}}
      onFocus={e=>{if(suppressFocus.current)return;const target=e.currentTarget;target.scrollIntoView({block:"nearest",inline:"nearest"});requestAnimationFrame(()=>{if(target.isConnected)openPreview(n.id,target);});}} onBlur={e=>{if(!previewRef.current?.contains(e.relatedTarget as Node))scheduleClose();}}
      onClick={e=>{if(e.detail===0||pointerType.current!=="touch"||preview?.id===n.id&&preview.pinned){e.currentTarget.focus({preventScroll:true});showLineage(n.id);}else openPreview(n.id,e.currentTarget,true);}}
      onKeyDown={e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();showLineage(n.id);}if(e.key==="Escape"){e.preventDefault();closePreview(true);}}}>
      <title>{concept.title} — {n.topic}</title><circle className="curriculum-dot-hit" r={31*n.scale}/><circle r={22*n.scale}/><text textAnchor="middle" dy={5*n.scale} style={{fontSize:15*n.scale}} className="curriculum-dot-badge">{layerBadge[n.layer]}</text>
      {named&&<text className="curriculum-dot-title" textAnchor="middle" y={-30*n.scale} style={{fontSize:13*n.scale}}>{short}</text>}
    </g>;
  }
  return <section className={`curriculum-explorer ${space?"is-spatial":"is-flat"}`} aria-label={space?"3D learning landscape":"2D learning pyramid"}>
    <div className="curriculum-explorer-heading"><div><strong>{space?"Your knowledge landscape":"From foundations to integration"}</strong><p>{space?"Drag to look around the shelves. Click a concept to trace its lineage; View details opens the lesson.":"Click a concept to trace what it builds on and what it leads to."}</p></div><div className="curriculum-view-actions">{space&&<button onClick={fitAll}>Fit all</button>}<button onClick={reset}>Reset {space?"camera":"view"}</button></div></div>
    <div ref={frameRef} className="curriculum-explorer-frame">
      <div ref={canvasRef} className="curriculum-explorer-canvas" onScroll={()=>closePreview()}>
        <div className={space?"curriculum-stage":undefined} style={space?{width:`max(100%, ${bounds.width*pixelScale}px)`,height:`max(100%, ${bounds.height*pixelScale}px)`}:undefined}>
        <svg viewBox={space?`${bounds.x} ${bounds.y} ${bounds.width} ${bounds.height}`:`0 0 1400 ${scene.height}`} style={space?{width:bounds.width*pixelScale,height:bounds.height*pixelScale}:undefined} role="group" aria-label={space?"3D learning shelves. Drag to look around, scroll to zoom, right-drag to pan. Hover a concept to preview; click to trace its lineage.":"Select a concept to trace its lineage. Drag the background to pan."}
          onPointerDown={e=>{if((e.button!==0&&e.button!==2)||(e.target as Element).closest('[role="button"]'))return;if(e.button===2)e.preventDefault();closePreview();const box=canvasRef.current!,pan=!space||e.button===2||e.altKey||e.shiftKey;drag.current={x:e.clientX,y:e.clientY,left:box.scrollLeft,top:box.scrollTop,orbit:space&&!pan,camera};e.currentTarget.setPointerCapture(e.pointerId);}}
          onPointerMove={e=>{const d=drag.current;if(!d)return;const dx=e.clientX-d.x,dy=e.clientY-d.y;if(d.orbit)setCamera({...d.camera,yaw:Math.max(-YAW_LIMIT,Math.min(YAW_LIMIT,d.camera.yaw+dx*.12)),pitch:Math.max(PITCH_MIN,Math.min(PITCH_MAX,d.camera.pitch+dy*.1))});else if(space){canvasRef.current!.scrollLeft=d.left-dx;canvasRef.current!.scrollTop=d.top-dy;}else {const ratio=1400/e.currentTarget.clientWidth;setCamera({...d.camera,x:d.camera.x+dx*ratio,y:d.camera.y+dy*ratio});}}}
          onPointerUp={e=>{drag.current=null;if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);}} onPointerCancel={()=>{drag.current=null;}} onContextMenu={e=>{if(space)e.preventDefault();}}>
          <defs><marker id={arrow} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" fill="#3b7159"/></marker></defs>
          <g transform={space?undefined:`translate(${700+camera.x} ${scene.height/2+camera.y}) scale(${camera.zoom}) translate(-700 ${-scene.height/2})`}>
            {scene.bands.map(b=>{
              const corners=space?[[-b.spaceWidth/2,-b.spaceDepth/2],[b.spaceWidth/2,-b.spaceDepth/2],[b.spaceWidth/2,b.spaceDepth/2],[-b.spaceWidth/2,b.spaceDepth/2]].map(([x,z])=>project({x,y:b.worldY,z})):[];
              const shelfLabel=space?project({x:0,y:b.worldY,z:-b.spaceDepth/2+120}):null;
              return <g key={b.layer} className={`curriculum-band band-${b.layer}`}>{space?<polygon points={corners.map(p=>`${p.x},${p.y}`).join(" ")}/>:<rect x={700-b.width/2} y={b.top} width={b.width} height={b.height} rx="22"/>}{space&&<path d={shelfGrid(b)} className="curriculum-shelf-grid"/>}{shelfLabel&&<text x={shelfLabel.x} y={shelfLabel.y} textAnchor="middle" className="curriculum-shelf-label" style={{fontSize:Math.max(18,42*shelfLabel.scale)}}>{layerNames[b.layer]}</text>}{!space&&<text x={700-b.width/2+24} y={b.top+32} className="curriculum-band-label">{layerNames[b.layer]} · {b.count}</text>}</g>;
            })}
            {space&&columns.map(stack=>stack.slice(1).map((group,index)=>{
              const below=stack[index],a=project({x:below.cx,y:below.worldY,z:below.cz}),b=project({x:group.cx,y:group.worldY,z:group.cz});
              return <line key={`${below.id}:${group.id}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="curriculum-column"/>;
            }))}
            {space&&spatialGroups.map(({group,index})=>{
              const relevant=group.conceptIds.some(id=>matches.has(id));
              const onPath=!!activeId&&group.conceptIds.some(id=>path.all.has(id));
              const dim=!relevant&&!onPath||!!activeId&&!onPath||!!activeGroup&&activeGroup.id!==group.id;
              const nameAt=project({x:group.cx,y:group.worldY,z:group.cz+group.radius+36});
              const lines=group.labelLines.length,font=18*nameAt.scale;
              return <g key={group.id} className={`curriculum-topic-region circle-topic topic-tone-${index%4} ${activeGroup?.id===group.id||onPath?"is-active":""}`}>
                <polygon points={diskOf(group,-18).map(p=>`${p.x},${p.y}`).join(" ")} className="curriculum-topic-lip"/>
                <polygon points={diskOf(group).map(p=>`${p.x},${p.y}`).join(" ")} className={`curriculum-topic-circle ${dim?"is-dimmed":""}`}/>
                {showGroupLabels&&<g transform={`translate(${nameAt.x} ${nameAt.y})`} role="button" tabIndex={relevant?0:-1} aria-label={`${layerNames[group.layer]} topic: ${group.title} · ${group.conceptIds.length} ${group.conceptIds.length===1?"concept":"concepts"}`} aria-disabled={!relevant} aria-pressed={activeGroup?.id===group.id} className={`curriculum-topic-label ${dim?"is-dimmed":""}`} onClick={()=>chooseGroup(group)} onKeyDown={e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();chooseGroup(group);}}}>
                  <title>{group.title}</title><rect x={-170*nameAt.scale} y={-(lines-1)*22*nameAt.scale-font} width={340*nameAt.scale} height={lines*22*nameAt.scale+font+8} fill="transparent"/><text textAnchor="middle" style={{fontSize:font}} className="curriculum-topic-full-title">{group.labelLines.map((line,i)=><tspan x="0" y={-(lines-1-i)*22*nameAt.scale} key={i}>{line}</tspan>)}</text>
                  <text textAnchor="middle" y={16*nameAt.scale} style={{fontSize:14*nameAt.scale}} className="curriculum-topic-count">{group.conceptIds.length} {group.conceptIds.length===1?"concept":"concepts"}</text>
                </g>}
                {projected.filter(n=>n.regionId===group.id).map(conceptMark)}
              </g>;
            })}
            {scene.edges.filter(e=>activeId?(path.before.has(e.dependent)||e.dependent===activeId)&&(path.before.has(e.prerequisite)||e.prerequisite===activeId)||(path.after.has(e.prerequisite)||e.prerequisite===activeId)&&(path.after.has(e.dependent)||e.dependent===activeId):activeGroup?activeGroup.conceptIds.includes(e.prerequisite)&&activeGroup.conceptIds.includes(e.dependent):false).map(e=>{
              const a=positions.get(e.prerequisite)!,b=positions.get(e.dependent)!;const dx=b.x-a.x,dy=b.y-a.y,len=Math.max(1,Math.hypot(dx,dy)),pad=22;
              const x1=a.x+dx/len*pad,y1=a.y+dy/len*pad,x2=b.x-dx/len*pad,y2=b.y-dy/len*pad;
              const lift=space?Math.min(180,Math.abs(y2-y1)*.4+28):0,cx=(x1+x2)/2,cy=Math.min(y1,y2)-lift;
              return <path key={`${a.id}:${b.id}`} d={space?`M${x1} ${y1} Q${cx} ${cy} ${x2} ${y2}`:`M${x1} ${y1} L${x2} ${y2}`} className={`curriculum-edge ${activeId?"is-path":""}`} markerEnd={activeId?`url(#${arrow})`:undefined}/>;
            })}
            {!space&&projected.map(conceptMark)}
          </g>
        </svg>
        </div>
      </div>
      {space&&<div className="curriculum-layer-jumps" aria-label="Jump to a layer">{scene.bands.map(b=><button key={b.layer} aria-label={`Go to ${layerNames[b.layer]} layer`} onClick={()=>jumpToLayer(b.layer)}>{layerNames[b.layer]} <b>{b.count}</b></button>)}</div>}
      {space&&<div className="curriculum-compass" aria-hidden="true"><span style={{transform:`rotate(${-camera.yaw}deg)`}}>▲</span><small>{Math.round(camera.yaw)}°</small></div>}
      <div className="curriculum-camera" aria-label="Map navigation"><button aria-label="Zoom in" disabled={camera.zoom>=6} onClick={()=>changeZoom(.2)}>+</button><span>{Math.round(camera.zoom*100)}%</span><button aria-label="Zoom out" disabled={camera.zoom<=.08} onClick={()=>changeZoom(-.2)}>−</button></div>
      {!matches.size&&<p className="curriculum-empty" role="status">No concepts match. Clear your filters to explore the course.</p>}
      {preview&&previewNode&&previewPoint&&<div ref={previewRef} className="map-concept-preview curriculum-hover-preview" role="dialog" aria-label="Concept preview" style={{left:preview.left,top:preview.top,width:preview.width,maxHeight:preview.maxHeight}} onPointerEnter={cancelClose} onPointerLeave={scheduleClose}>
        <button className="map-preview-close" aria-label="Close concept preview" onClick={()=>closePreview(true)}>×</button><p className="map-preview-topic">{previewPoint.topic}</p><h3>{previewNode.title}</h3><p>{layerNames[previewPoint.layer]} curriculum layer</p>{stateAt(previewNode.id)!=="neutral"&&<p className="map-preview-state"><i className={stateAt(previewNode.id)}/>{stateNames[stateAt(previewNode.id)]}</p>}<button className="map-preview-details" onClick={()=>{previewAnchor.current?.focus({preventScroll:true});openConcept(previewNode.id);}}>View details →</button>
      </div>}
    </div>
    {space&&<div className="curriculum-orbit"><label>Rotate <input aria-label="Rotate landscape" type="range" min={-YAW_LIMIT} max={YAW_LIMIT} value={camera.yaw} onChange={e=>{closePreview();setCamera(c=>({...c,yaw:Number(e.target.value)}));}}/></label><label>Tilt <input aria-label="Tilt landscape" type="range" min={PITCH_MIN} max={PITCH_MAX} value={camera.pitch} onChange={e=>{closePreview();setCamera(c=>({...c,pitch:Number(e.target.value)}));}}/></label><label className="curriculum-topic-label-toggle"><input type="checkbox" checked={showGroupLabels} onChange={e=>setShowGroupLabels(e.target.checked)}/>Topic labels</label><span>{scene.groups.length} topic disks · drag to look around · scroll to zoom · right-drag to pan</span></div>}
    {space&&<details className="curriculum-topic-index"><summary>Browse topic groups ({scene.groups.length})</summary>{scene.bands.map(b=><div key={b.layer}><h3>{layerNames[b.layer]}</h3><div>{scene.groups.filter(g=>g.layer===b.layer).map(group=><button key={group.id} aria-pressed={activeGroup?.id===group.id} disabled={!group.conceptIds.some(id=>matches.has(id))} onClick={()=>chooseGroup(group)}>{group.title}<b>{group.conceptIds.length}</b></button>)}</div></div>)}</details>}
    <div className="curriculum-map-legend"><span><b>B</b> Basic</span><span><b>I</b> Intermediate</span><span><b>A</b> Advanced</span>{Object.entries(stateNames).filter(([s])=>s!=="neutral"&&stateAt(scene.nodes[0]?.id||"")!=="neutral").map(([s,label])=><span key={s}><i className={s}/>{label}</span>)}</div>
    <p className="curriculum-explorer-hint">Hover or focus a small circle for a preview. Click or press Enter to trace its lineage across prerequisites. View details opens the lesson. {space&&"Drag to look around, scroll to zoom, and right-drag to move across a shelf."}</p>
    <div className="curriculum-focus-card" aria-live="polite">
      {activeGroup?<><div><p className="eyebrow">{layerNames[activeGroup.layer]} · Topic group</p><h3>{activeGroup.title}</h3><p>{activeGroup.conceptIds.filter(id=>matches.has(id)).length} of {activeGroup.conceptIds.length} concepts match your filters.</p></div><div className="curriculum-focus-actions"><button onClick={reset}>Show all topics</button></div><ul className="curriculum-group-concepts">{activeGroup.conceptIds.filter(id=>matches.has(id)).map(id=><li key={id}><button onClick={()=>showLineage(id)}>{title(id)}<small>{stateNames[stateAt(id)]||stateAt(id)}</small></button></li>)}</ul></>:current&&currentPoint?<><div><p className="eyebrow">Lineage · {layerNames[currentPoint.layer]} · {currentPoint.topic}</p><h3>{current.title}</h3><p>{current.curriculum?.adds||current.summary}</p></div><div className="curriculum-focus-actions"><button className="button dark" onClick={()=>openConcept(current.id)}>View details & lesson →</button><button onClick={()=>{setLocalFocus({id:"",from:""});onClear?.();closePreview();}}>Clear path</button></div></>:<p>Explore a topic circle, then hover or click one of its smaller concept circles.</p>}
      {current&&<div className="curriculum-path-links"><div><strong>Builds on</strong>{scene.edges.filter(e=>e.dependent===focus).length?scene.edges.filter(e=>e.dependent===focus).map(e=><button key={e.prerequisite} onClick={()=>showLineage(e.prerequisite)}>{title(e.prerequisite)}</button>):<span>No required prerequisites</span>}</div><div><strong>Prepares you for</strong>{scene.edges.filter(e=>e.prerequisite===focus).length?scene.edges.filter(e=>e.prerequisite===focus).map(e=><button key={e.dependent} onClick={()=>showLineage(e.dependent)}>{title(e.dependent)}</button>):<span>No further required connections</span>}</div></div>}
    </div>
  </section>;
}
