export const CATEGORY = {main:"主线", event:"活动", short:"故事集", record:"干员密录", comic:"官方漫画"};
export const DEMO_ID = "demo:catalogue-night";
export const escapeHTML = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
export const plain = value => String(value ?? "").replace(/<\/?(?:b|i|u|color|size|strong|em)(?:=[^>]*)?>/gi, "").replace(/<@[\w.]+>|<\/>/g, "");
export const safeURL = value => /^https?:\/\//i.test(String(value ?? "")) ? escapeHTML(value) : "#sources";

export function displayTitle(group,title=group?.title||"") {
  return group?.category==="record"&&group.operator ? `${group.operator} · ${title}` : title;
}

export function regionTrail(catalog, id) {
  const byId=new Map((catalog.regions||[]).map(r=>[r.id,r])), trail=[],seen=new Set();
  while(byId.has(id)&&!seen.has(id)){seen.add(id);const r=byId.get(id);trail.push(r);id=r.parent;}
  return trail;
}
export function matchesRegion(catalog, group, region="all") {
  const ids=group.region_ids||[];
  if(region==="all")return true;
  if(region==="unknown")return !ids.length;
  if(region==="multi")return ids.length>1;
  return ids.some(id=>regionTrail(catalog,id).some(r=>r.id===region));
}
export function regionName(catalog,id) {
  return ({all:"全部地区",unknown:"地区待考证",multi:"多地区作品"})[id]||(catalog.regions||[]).find(r=>r.id===id)?.name||"未知地区";
}
export function filterGroups(catalog, {category="all", region="all", query="", saved=null, sort="catalogue"}={}) {
  const q = query.trim().toLocaleLowerCase();
  const rank = {main:0,event:1,short:2,record:3,comic:4};
  return catalog.groups.filter(g => (category === "all" || g.category === category) && (!saved || saved.has(g.id)))
    .filter(g => matchesRegion(catalog,g,region))
    .filter(g => !q || [g.title,g.operator,...g.tags,...(g.region_ids||[]).flatMap(id=>regionTrail(catalog,id).flatMap(r=>[r.name,...(r.aliases||[])])),...g.story_ids.flatMap(id=>{const s=catalog.stories[id];return [s.title,s.code];})].filter(Boolean).some(v=>v.toLocaleLowerCase().includes(q)))
    .sort((a,b)=> sort === "newest" ? ((b.date || "0000").localeCompare(a.date || "0000") || a.order-b.order)
      : sort === "oldest" ? ((a.date || "9999").localeCompare(b.date || "9999") || a.order-b.order)
      : (rank[a.category]-rank[b.category] || a.order-b.order));
}

export function validateStory(story) {
  if (!story || typeof story.id!=="string" || !story.id || typeof story.title!=="string" || !Array.isArray(story.nodes) || !story.nodes.length || story.nodes.length>200000) throw new Error("正文格式不完整：需要 id、title 和非空 nodes。");
  const ids = new Set();
  for (const n of story.nodes) {
    if (!n || typeof n.id!=="string" || !/^[A-Za-z0-9_-]+$/.test(n.id) || ids.has(n.id)) throw new Error("段落编号重复、缺失或含无效字符。");
    ids.add(n.id);
    if (!["dialogue","narration","scene","choice","branch","directive","unknown"].includes(n.kind)) throw new Error("段落类型无法识别。");
    if (n.kind==="choice" && !Array.isArray(n.options)) throw new Error("选项列表应为数组。");
    if ((n.text!==undefined && typeof n.text!=="string") || (n.speaker!==undefined && typeof n.speaker!=="string")) throw new Error("正文和说话人必须是文字。");
  }
  for (const n of story.nodes) for (const o of n.options || []) {
    if (typeof o.label!=="string" || (o.target!=null && !ids.has(o.target))) throw new Error("选项缺少文字或跳转目标不存在。");
  }
  return story;
}

function splitAttributes(raw) {
  const parts=[]; let start=0, quote=null, escaped=false;
  for(let i=0;i<raw.length;i++) {
    const c=raw[i];
    if(escaped) escaped=false;
    else if(c==="\\") escaped=true;
    else if(quote) { if(c===quote) quote=null; }
    else if(c==='"'||c==="'") quote=c;
    else if(c===",") {parts.push(raw.slice(start,i));start=i+1;}
  }
  parts.push(raw.slice(start));
  return Object.fromEntries(parts.filter(x=>x.includes("=")).map(x=>{
    const at=x.indexOf("=");let v=x.slice(at+1).trim();
    if(v.length>=2&&v[0]===v.at(-1)&&['"',"'"].includes(v[0]))v=v.slice(1,-1);
    return [x.slice(0,at).trim().toLowerCase(),v];
  }));
}

export function parseScript(text) {
  return {storyList:text.split(/\r?\n/).flatMap((raw,i)=>{
    const line=raw.trim();if(!line)return [];
    if(!line.startsWith("[")||!line.includes("]"))return [{id:i+1,prop:"name",attributes:{name:"",content:line}}];
    const end=line.indexOf("]"),tag=line.slice(1,end),content=line.slice(end+1).trim();let prop,attributes;
    if(/^name=/i.test(tag)){prop="name";attributes=splitAttributes(tag);}
    else if(tag.includes("(")&&tag.endsWith(")")){const at=tag.indexOf("(");prop=tag.slice(0,at);attributes=splitAttributes(tag.slice(at+1,-1));}
    else {prop=tag;attributes={};}
    if(content)attributes.content=content;
    return [{id:i+1,prop,attributes}];
  })};
}

export function normalizeImport(raw, record) {
  if(typeof raw==="string") raw=parseScript(raw);
  if(Array.isArray(raw))raw={storyList:raw};
  if(!raw || typeof raw!=="object")throw new Error("请选择有效的 JSON 或 UTF-8 剧情脚本。");
  if(raw.nodes) {
    const story=structuredClone(raw);
    // Imported data cannot claim the bundled original-demo identity.
    if(story.id===DEMO_ID)throw new Error("原创演示 ID 为保留编号，请为个人正文使用自己的 ID。");
    story.origin="user_import";return validateStory(story);
  }
  if(!record)throw new Error("无法定位篇目。请从对应篇目的阅读页选择“导入本篇正文”。");
  if(!Array.isArray(raw.storyList)||!raw.storyList.length)throw new Error("没有找到非空 storyList。");
  const effects=new Set(["background","image","scene","character","charslot","charer","dialog","blocker","playmusic","stopmusic","playaudio","stopaudio","delay","cameraeffect","camerashake","cameramove","camerarotate","curtain","mask","musicvolume","soundvolume","bgeffect","imagecut","characteraction","characterfocus","fadeout","fadein","focus","video","multiline","cgitem","showitem","hideitem"]);
  const story={schema_version:1,id:record.id,title:record.title,source_path:record.source_path,source_url:record.source_url,origin:"user_import",warnings:[],nodes:raw.storyList.map((r,i)=>{
    const command=String(r.prop||"").toLowerCase(),a=Object.fromEntries(Object.entries(r.attributes||{}).map(([k,v])=>[k.toLowerCase(),v]));
    const n={id:"l"+String(r.id??i+1),kind:"directive",command,attributes:a};
    if(["name","multiline"].includes(command))Object.assign(n,{kind:String(a.content||"").trim()?(a.name?"dialogue":"narration"):"directive",speaker:String(a.name||""),text:String(a.content||"")});
    else if(["subtitle","animtext","sticker"].includes(command))Object.assign(n,{kind:"narration",text:String(a.text||a.content||"")});
    else if(command==="decision") {
      const values=String(a.values||"").split(";");n.kind="choice";
      n.options=String(a.options||"").split(";").map((label,i)=>{const value=values[Math.min(i,values.length-1)],raw=r.targetLine?.["option"+value];let target=null;if(raw!=null&&raw!==""){const match=String(raw).match(/^(?:line|l)?(\d+)$/);if(!match)throw new Error("无法识别的分支跳转编号。");target="l"+match[1];}return {label,value,target};});
    } else if(["predicate","label","goto"].includes(command))Object.assign(n,{kind:"branch",text:"分支条件："+String(a.references||a.label||a.target||"汇合／条件见原始记录")});
    else if(!effects.has(command))n.kind="unknown";
    return n;
  })};
  for(let i=0;i<story.nodes.length;i++) {
    const n=story.nodes[i];if(n.kind==="unknown")story.warnings.push({line:n.id,issue:"未识别指令已保留"});
    if(n.kind==="choice")for(const option of n.options) {
      if(option.target==null)for(const c of story.nodes.slice(i+1)) {
        if(c.kind==="choice")break;
        if(c.command==="predicate"&&String(c.attributes.references||"").split(";").includes(option.value)){option.target=c.id;break;}
      }
      if(option.target==null)story.warnings.push({line:n.id,issue:"选项跳转待核对"});
    }
  }
  return validateStory(story);
}

export function readableNodes(story) {
  const targets=new Set(story.nodes.flatMap(n=>(n.options||[]).map(o=>o.target)));
  return story.nodes.filter(n=>n.kind!=="directive"||targets.has(n.id));
}
export function timeLabels(record) {
  const times=record?.chronology||{};
  return {event:times.event?.label||"待考证",release:times.release?.label||"待考证",reference:times.release?.scope==="work_reference",note:[times.event?.note,times.release?.note].filter(Boolean).join(" ")};
}
export function timeXHTML(record) {
  const t=timeLabels(record);
  return `<p class="meta">事件发生时间（泰拉历）：${escapeHTML(t.event)}</p><p class="meta">国服开放时间${t.reference?"（所属作品参考）":""}：${escapeHTML(t.release)}</p>${t.note?`<p class="meta">${escapeHTML(t.note)}</p>`:""}`;
}

export function buildReadingSections(catalog,groups,bodies,title) {
  const e=escapeHTML,sections=[{title:"使用说明",level:0,body:`<h1>${e(title)}</h1><p>正文来自用户提供的本地资料。按主要舞台归类，作品在本卷中只出现一次；待考证地区单列。事件发生时间与现实开放时间分别标注，未知时间不推定。保留备选分支及条件，演出指令不混入阅读正文。</p>`}];
  const roots=(catalog.regions||[]).filter(r=>!r.parent),regionMap=new Map((catalog.regions||[]).map(r=>[r.id,r]));
  const primary=g=>{let id=g.region_ids?.[0]||"unknown";const seen=new Set();while(regionMap.get(id)?.parent&&!seen.has(id)){seen.add(id);id=regionMap.get(id).parent;}return id;};
  for(const region of [...roots,{id:"unknown",name:"地区待考证"}]){
    const members=groups.filter(g=>primary(g)===region.id);if(!members.length)continue;
    sections.push({title:region.name,level:0,body:`<h1>${e(region.name)}</h1><p>${e(region.description||"主要舞台尚未核对。")}</p>`});
    for(const group of members){
      const index=sections.length,present=group.story_ids.filter(id=>bodies.has(id)),targets=new Map(present.map((id,i)=>[id,index+1+i]));
      const sourceLinks=(group.region_evidence||[]).map(s=>`<p class="meta"><a href="${safeURL(s.url)}">${e(s.title)}</a></p>`).join("");
      const settings=(group.region_ids||[]).map(id=>regionName(catalog,id)).join(" · ")||"地区待考证";
      sections.push({title:displayTitle(group),level:1,body:`<h1>${e(displayTitle(group))}</h1><p class="meta">${CATEGORY[group.category]} · 作品主要舞台：${e(settings)}</p><p class="meta">${e(group.region_note||"")}</p>${timeXHTML(group)}${sourceLinks}${group.story_ids.length?`<ol>${group.story_ids.map(id=>{const r=catalog.stories[id],label=e(displayTitle(group,[r.code,r.title,r.part].filter(Boolean).join(" · ")));return `<li>${targets.has(id)?`<a href="section-${String(targets.get(id)).padStart(4,"0")}.xhtml">${label}</a>`:`${label}（正文未收录）<a href="${safeURL(r.reader_url)}">原文入口</a>`}${timeXHTML(r)}</li>`;}).join("")}</ol>`:`<p><a href="${safeURL(group.source_url)}">官方作品入口</a></p>`}`});
      for(const id of present){const r=catalog.stories[id],s=bodies.get(id),source=s.provided_source;sections.push({title:displayTitle(group,[r.code,r.title,r.part].filter(Boolean).join(" · ")),level:2,body:`<h1>${e(displayTitle(group,r.title))}</h1><p class="meta">${e(displayTitle(group))} · ${e(r.code)} ${e(r.part)}</p>${timeXHTML(r)}${source?`<p class="meta">用户提供资料：${e(source.workbook)} / ${e(source.sheet)}</p>`:""}${readableNodes(s).map(nodeXHTML).join("")}<p><a href="section-${String(index).padStart(4,"0")}.xhtml">返回作品目录</a></p>`});}
    }
  }
  return sections;
}

export function nodeXHTML(n) {
  const id=escapeHTML(n.id), text=escapeHTML(plain(n.text));
  if(n.kind==="dialogue")return `<p id="${id}" class="dialogue"><strong>${escapeHTML(plain(n.speaker))}</strong><br/>${text}</p>`;
  if(["narration","scene","branch"].includes(n.kind))return `<p id="${id}" class="${n.kind}">${text}</p>`;
  if(n.kind==="choice")return `<section id="${id}" class="choice"><p>选择一条分支：</p><ol>${n.options.map(o=>`<li>${o.target?`<a href="#${escapeHTML(o.target)}">${escapeHTML(plain(o.label))}</a>`:escapeHTML(plain(o.label))+"（跳转待核对）"}</li>`).join("")}</ol><p>以下保留备选分支，不代表连续发生的情节。</p></section>`;
  return `<p id="${id}" class="directive">${n.kind==="unknown"?"未识别段落，待校对":"演出提示"}：${escapeHTML(n.command)} ${escapeHTML(JSON.stringify(n.attributes||{}))}</p>`;
}
