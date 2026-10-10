import {useEffect, useMemo, useRef, useState} from 'react';
import ForceGraph3D from 'react-force-graph-3d';
import {Vector2} from 'three';
import {UnrealBloomPass} from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import {Maximize2, ZoomIn, ZoomOut} from 'lucide-react';

export type Node={id:string;label:string;kind:string;organization:string;x:number;y:number;size:number;color:string;evidence_id?:string;amount_minor?:number;background?:boolean};
export type Edge={id:string;source:string;target:string;kind:string;label?:string};
export type GraphData={nodes:Node[];edges:Edge[]};
type Obj={id:string;d:Node;x?:number;y?:number;z?:number;fx?:number;fy?:number;fz?:number};
type Link={id:string;kind:string;source:string|Obj;target:string|Obj};

const S=40; // server layout units -> scene units
const HOME={x:0,y:90,z:1050}, CLOSE={x:0,y:60,z:640};
const still=matchMedia('(prefers-reduced-motion: reduce)').matches;
const webgl=!!document.createElement('canvas').getContext('webgl2');
// The post-processing chain brightens the clear colour, so this near-black lands on the panel colour.
const BG='#010101';
const LINK:Record<string,string>={request:'#b7a0dc',evidence:'#c1ed9b'};
// History sits behind the three organizations so the investigation reads in front of it.
const depth=(id:string)=>{let h=0;for(const c of id)h=(h*31+c.charCodeAt(0))|0;return -260+(h%140)/2;};

export function MoneyGraph({data,focused,onSelect,selected}:{data:GraphData;focused:boolean;onSelect:(id:string)=>void;selected:string|null}){
  const stage=useRef<HTMLDivElement>(null), labels=useRef<HTMLDivElement>(null);
  const fg=useRef<any>(undefined);
  const objs=useRef(new Map<string,Obj>()), links=useRef(new Map<string,Link>());
  const [size,setSize]=useState({w:0,h:0});

  useEffect(()=>{
    const el=stage.current!;
    const ro=new ResizeObserver(()=>setSize({w:el.clientWidth,h:el.clientHeight}));
    ro.observe(el);
    return()=>ro.disconnect();
  },[]);

  // Reuse node/link objects across updates: the simulation keeps their positions,
  // so only genuinely new evidence enters the scene instead of the graph rebuilding.
  const sig=data.nodes.map(n=>n.id).join()+'|'+data.edges.map(e=>e.id).join();
  const graphData=useMemo(()=>{
    const nextN=new Map<string,Obj>(), nextL=new Map<string,Link>();
    for(const n of data.nodes){
      let o=objs.current.get(n.id);
      if(o)o.d=n;
      else if(n.background||n.kind==='organization')o={id:n.id,d:n,fx:n.x*S,fy:n.y*S,fz:n.background?depth(n.id):0};
      else{const org=nextN.get('org:'+n.organization);const j=()=>Math.random()*6-3;o={id:n.id,d:n,x:(org?.fx??0)+j(),y:(org?.fy??0)+j(),z:j()};}
      nextN.set(n.id,o);
    }
    for(const e of data.edges)if(nextN.has(e.source)&&nextN.has(e.target))nextL.set(e.id,links.current.get(e.id)??{id:e.id,kind:e.kind,source:e.source,target:e.target});
    objs.current=nextN;links.current=nextL;
    return{nodes:[...nextN.values()],links:[...nextL.values()]};
  },[sig]);

  const ready=webgl&&size.w>0;
  useEffect(()=>{
    const g=fg.current;if(!g)return;
    const bloom=new UnrealBloomPass(new Vector2(size.w,size.h),.7,.6,.2);
    g.postProcessingComposer().addPass(bloom);
    g.d3Force('link').distance((l:Link)=>l.kind==='evidence'?75:30);
    g.d3Force('charge').strength(-140).distanceMax(170);
    g.d3Force('center',null); // most nodes are pinned; centering would push the free ones away forever
    const c=g.controls();c.autoRotate=!still;c.autoRotateSpeed=.3;
    return()=>{g.postProcessingComposer().removePass(bloom);};
  },[ready]);

  useEffect(()=>{fg.current?.cameraPosition(focused?CLOSE:HOME,{x:0,y:0,z:focused?0:-120},still?0:900);},[focused,ready]);

  // Labels are real buttons positioned over the canvas: crisp text, and keyboard access to the nodes.
  useEffect(()=>{
    let raf=0;
    const tick=()=>{
      const g=fg.current,el=labels.current;
      if(g&&el)for(const b of el.children as HTMLCollectionOf<HTMLElement>){
        const o=objs.current.get(b.dataset.id!);
        if(o?.x===undefined)continue;
        const p=g.graph2ScreenCoords(o.x,o.y,o.z);
        b.style.transform=`translate(${p.x}px,${p.y}px) translate(-50%,${b.className==='org'?-44:14}px)`;
        b.style.visibility='visible';
      }
      raf=requestAnimationFrame(tick);
    };
    tick();
    return()=>cancelAnimationFrame(raf);
  },[]);

  const spin=(on:boolean)=>{const c=fg.current?.controls();if(c)c.autoRotate=on&&!still;};
  const hover={onPointerOver:()=>spin(false),onPointerOut:()=>spin(true),onFocus:()=>spin(false),onBlur:()=>spin(true)};
  const zoom=(f:number)=>{const g=fg.current;if(!g)return;const p=g.camera().position;g.cameraPosition({x:p.x*f,y:p.y*f,z:p.z*f},undefined,250);};
  return <>
    <div className="graph-canvas" ref={stage} {...hover}>
      {ready&&<ForceGraph3D ref={fg} graphData={graphData} width={size.w} height={size.h} backgroundColor={BG}
        controlType="orbit" showNavInfo={false} enableNodeDrag={false}
        nodeLabel={(o:Obj)=>o.d.label} nodeRelSize={4} nodeResolution={10} nodeOpacity={.95}
        nodeVal={(o:Obj)=>o.d.kind==='organization'?30:o.d.kind==='transaction'?.3:o.d.background?1.5:6}
        nodeColor={(o:Obj)=>o.id===selected?'#ffffff':o.d.background?(focused?'#2b4336':'#4f7758'):o.d.color||'#b8f18b'}
        onNodeClick={(o:Obj)=>onSelect(o.id)}
        linkColor={(l:Link)=>LINK[l.kind]??'#3d5c46'} linkOpacity={.4} linkWidth={(l:Link)=>l.kind==='request'?1.2:l.kind==='evidence'?.8:0}
        linkDirectionalParticles={(l:Link)=>still?0:l.kind==='request'?4:l.kind==='evidence'?2:0}
        linkDirectionalParticleWidth={2.6} linkDirectionalParticleSpeed={.008}/>}
    </div>
    <div className="graph-labels" ref={labels} {...hover}>{data.nodes.filter(n=>!n.background).map(n=><button key={n.id} data-id={n.id} className={n.kind==='organization'?'org':n.id===selected?'on':''} onClick={()=>onSelect(n.id)}>{n.label}</button>)}</div>
    {!webgl&&<div className="graph-empty">WebGL is unavailable in this browser. Evidence remains available in the case panel.</div>}
    <div className="graph-controls"><button aria-label="Zoom in" onClick={()=>zoom(.75)}><ZoomIn size={17}/></button><button aria-label="Zoom out" onClick={()=>zoom(1.33)}><ZoomOut size={17}/></button><button aria-label="Reset graph view" onClick={()=>fg.current?.cameraPosition(focused?CLOSE:HOME,{x:0,y:0,z:focused?0:-120},400)}><Maximize2 size={16}/></button></div>
  </>;
}
