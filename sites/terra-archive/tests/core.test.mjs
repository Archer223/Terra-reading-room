import {test} from "node:test";
import assert from "node:assert/strict";
import {filterGroups,matchesRegion,regionTrail,normalizeImport,parseScript,nodeXHTML,safeURL,validateStory,buildReadingSections,readableNodes,timeLabels} from "../model.js";
import {createEpub} from "../epub.js";

const catalog={groups:[{id:"a",title:"第一本",category:"main",tags:[],story_ids:["s"],order:0,date:null},{id:"b",title:"第二本",category:"event",tags:["编目员"],story_ids:[],order:1,date:"2020-01-01"}],stories:{s:{title:"原创章节",code:"T-1"}}};
const regional={...catalog,regions:[{id:"yan",name:"炎国",aliases:["大炎"]},{id:"lungmen",name:"龙门",parent:"yan"},{id:"ursus",name:"乌萨斯"}],groups:[{...catalog.groups[0],region_ids:["lungmen","ursus"]},{...catalog.groups[1],region_ids:[]}]};
test("region filtering combines hierarchy, query, category and favorites",()=>{
  assert.deepEqual(filterGroups(regional,{region:"yan",category:"main",query:"大炎",saved:new Set(["a"])}).map(g=>g.id),["a"]);
  assert.equal(filterGroups(regional,{region:"yan",category:"event"}).length,0);
  assert.equal(filterGroups(regional,{region:"yan",saved:new Set(["b"])}).length,0);
  assert.equal(filterGroups(regional,{query:"龙门"})[0].id,"a");
});
test("multi-region and unverified works remain separate and never duplicate",()=>{
  assert.deepEqual(filterGroups(regional,{region:"multi"}).map(g=>g.id),["a"]);
  assert.deepEqual(filterGroups(regional,{region:"unknown"}).map(g=>g.id),["b"]);
  assert.equal(filterGroups(regional,{region:"missing"}).length,0);
  assert.equal(matchesRegion(regional,regional.groups[0],"ursus"),true);
  assert.deepEqual(regionTrail(regional,"lungmen").map(r=>r.id),["lungmen","yan"]);
});
test("native ASTR line targets, multiline and sticker text survive import",()=>{
  const story=normalizeImport({storyList:[{id:0,prop:"decision",attributes:{options:"继续",values:"1"},targetLine:{option1:"line1"}},{id:1,prop:"predicate",attributes:{references:"1"}},{id:2,prop:"multiline",attributes:{name:"编目员",content:"原创文字"}},{id:3,prop:"sticker",attributes:{text:"原创字幕"}}]},{id:"cn:demo",title:"测试"});
  assert.equal(story.nodes[0].options[0].target,"l1");assert.equal(story.nodes[2].kind,"dialogue");assert.equal(story.nodes[3].text,"原创字幕");
});
test("reading export keeps branch targets and separates the two times",()=>{
  const record={...catalog.stories.s,id:"s",part:"幕间",chronology:{event:{label:"待考证"},release:{label:"2020-01-01",scope:"work_reference",note:"单篇解锁待核对"}}};
  const c={...regional,stories:{s:record},groups:[{...regional.groups[0],source_url:"https://example.com",region_note:"初编"}]};
  const s={id:"s",title:"测试",nodes:[{id:"l1",kind:"choice",options:[{label:"继续",target:"l2"}]},{id:"l2",kind:"branch",text:"分支一"},{id:"l3",kind:"directive",command:"background",attributes:{image:"demo"}},{id:"l4",kind:"narration",text:"原创完整正文"}]};
  const sections=buildReadingSections(c,c.groups,new Map([["s",s]]),"测试书单");
  assert.equal(sections.filter(x=>x.body.includes("原创完整正文")).length,1);
  assert.ok(sections.some(x=>x.level===2&&x.body.includes('href="#l2"')));
  assert.ok(sections.some(x=>x.body.includes("所属作品参考")&&x.body.includes("单篇解锁待核对")));
  assert.equal(readableNodes(s).some(x=>x.id==="l3"),false);assert.equal(timeLabels(record).event,"待考证");
});
test("search reaches chapter code and operator tags",()=>{assert.equal(filterGroups(catalog,{query:"T-1"})[0].id,"a");assert.equal(filterGroups(catalog,{query:"编目员"})[0].id,"b");assert.equal(filterGroups(catalog,{category:"record"}).length,0);});
test("unknown dates stay at the end of date sorting",()=>{assert.equal(filterGroups(catalog,{sort:"oldest"})[0].id,"b");assert.equal(filterGroups(catalog,{sort:"newest"})[0].id,"b");});
test("favorites restrict results independently of sorting",()=>{assert.deepEqual(filterGroups(catalog,{saved:new Set(["b"])}).map(g=>g.id),["b"]);});
test("ASTR choice targets and unknown commands are preserved",()=>{
  const value={storyList:[{id:1,prop:"Decision",attributes:{options:"左;右",values:"1;2"}},{id:2,prop:"Predicate",attributes:{references:"1"}},{id:3,prop:"Predicate",attributes:{references:"2"}},{id:4,prop:"NewCommand",attributes:{payload:"retain"}}]};
  const s=normalizeImport(value,{id:"cn:test",title:"测试",source_path:"test"});assert.deepEqual(s.nodes[0].options.map(o=>o.target),["l2","l3"]);assert.equal(s.nodes[3].kind,"unknown");assert.equal(s.nodes[3].attributes.payload,"retain");assert.equal(s.warnings.length,1);
});
test("quoted attributes keep commas and source line numbers",()=>{const p=parseScript('\n[name="A, B"] 原创测试');assert.equal(p.storyList[0].attributes.name,"A, B");assert.equal(p.storyList[0].id,2);});
test("missing jump targets reject invalid input",()=>{assert.throws(()=>validateStory({id:"a",title:"b",nodes:[{id:"l1",kind:"choice",options:[{label:"失效",target:"l2"}]}]}),/目标不存在/);});
test("imported HTML cannot become active markup",()=>{assert.ok(!nodeXHTML({id:"l1",kind:"narration",text:'<script>alert(1)</script>'}).includes("<script>"));assert.equal(safeURL("javascript:alert(1)"),"#sources");});
test("browser EPUB has the required uncompressed first mimetype entry",()=>{
  const bytes=createEpub({title:"原创测试",sections:[{title:"第一篇",body:'<h1 id="a">测试</h1>'}]});const view=new DataView(bytes.buffer);assert.equal(view.getUint32(0,true),0x04034b50);assert.equal(view.getUint16(8,true),0);assert.equal(new TextDecoder().decode(bytes.slice(30,38)),"mimetype");assert.equal(new TextDecoder().decode(bytes.slice(38,58)),"application/epub+zip");
});
