import {CATEGORY,DEMO_ID,displayTitle,escapeHTML as e,plain,safeURL,filterGroups,matchesRegion,regionName,normalizeImport,validateStory,nodeXHTML,readableNodes,timeLabels,timeXHTML,buildReadingSections} from "./model.js";
import {createEpub} from "./epub.js";

const $=s=>document.querySelector(s), main=$("#main"), storageKey="terra-reading-room-state-v1";
const initialState={version:1,favorites:[],bookmarks:{},positions:{},completed:[],prefs:{theme:"light",font:19,directives:false},last:null};
let state=structuredClone(initialState),catalog,sources,lists,bodies=new Map(),db=null,routeGeneration=0,observer=null,saveTimer,toastTimer;
let bodyIndex={count:0,items:{}},bodyLoads=new Map();
let category="all",region="all",query="",sort="catalogue",page=1,libraryMode="library",importTarget=null,currentStory=null,currentNode=null;
const pageSize=12, palettes=[["#e1e6da","#3a5144"],["#e8e0d2","#63543a"],["#e3deda","#64514b"],["#dce5e5","#3e5860"],["#e6e3d4","#66613c"],["#dfe0e7","#4d526c"]];
const searchIcon='<svg viewBox="0 0 24 24" fill="none" stroke-width="1.6" aria-hidden="true"><circle cx="10.8" cy="10.8" r="6.3"/><path d="m16 16 4.5 4.5"/></svg>';

try{const saved=JSON.parse(localStorage.getItem(storageKey));if(saved&&saved.version===1)state={...initialState,...saved,prefs:{...initialState.prefs,...saved.prefs}};}catch{}
state.prefs.font=Math.min(28,Math.max(15,Number(state.prefs.font)||19));
document.documentElement.dataset.theme=state.prefs.theme==="dark"?"dark":"light";
document.documentElement.style.setProperty("--reading-size",state.prefs.font+"px");

function notify(text){clearTimeout(toastTimer);const t=$("#toast");t.textContent=text;t.classList.add("visible");toastTimer=setTimeout(()=>t.classList.remove("visible"),4600);}
function persist(){try{localStorage.setItem(storageKey,JSON.stringify(state));}catch{notify("浏览器存储空间不足，请先导出阅读记录备份。");}}
function updateNavigation(active){document.querySelectorAll("[data-nav]").forEach(a=>a.classList.toggle("active",a.dataset.nav===active));$("#saved-count").textContent=state.favorites.length;}
function crumbs(name){$("#breadcrumb").innerHTML=`阅览室 <span>/</span> ${e(name)}`;}
function anchor(kind,id){return `#${kind}/${encodeURIComponent(id)}`;}
function groupById(id){return catalog.groups.find(g=>g.id===id);}
function palette(id){let n=0;for(const c of id)n=(n*31+c.charCodeAt(0))>>>0;return palettes[n%palettes.length];}
function hasBody(id){return bodies.has(id)||!!bodyIndex.items[id];}
function localCount(g){return g.story_ids.filter(hasBody).length;}
async function ensureBody(id){
  if(bodies.has(id))return bodies.get(id);
  const entry=bodyIndex.items[id];if(!entry)return null;
  if(bodyLoads.has(id))return bodyLoads.get(id);
  const pending=(async()=>{const response=await fetch(entry.url);if(!response.ok)throw new Error("本篇正文加载失败，请重试。");const s=validateStory(await response.json());if(s.id!==id)throw new Error("正文编号与篇目不匹配。");bodies.set(id,s);return s;})();
  bodyLoads.set(id,pending);try{return await pending;}finally{bodyLoads.delete(id);}
}
async function ensureBodies(ids){
  const missing=[...new Set(ids)].filter(id=>!bodies.has(id)&&bodyIndex.items[id]);let next=0,done=0;
  if(missing.length)notify(`正在准备正文 0/${missing.length}…`);
  await Promise.all(Array.from({length:Math.min(6,missing.length)},async()=>{while(next<missing.length){const id=missing[next++];await ensureBody(id);done++;if(done%20===0||done===missing.length)notify(`正在准备正文 ${done}/${missing.length}…`);}}));
}
function timeInfo(record){const t=timeLabels(record),release=record?.chronology?.release;return `<section class="time-info" aria-label="剧情时间"><dl><div><dt>事件发生时间 · 泰拉历</dt><dd>${e(t.event)}</dd></div><div><dt>国服开放时间${t.reference?" · 所属作品参考":""}</dt><dd>${e(t.release)}</dd></div></dl>${t.note?`<p>${e(t.note)}</p>`:""}${release?.sources?.length?`<details><summary>时间依据</summary><ul>${release.sources.map(s=>`<li><a href="${safeURL(s.url)}" target="_blank" rel="noopener noreferrer">${e(s.title)} ↗</a></li>`).join("")}</ul></details>`:""}</section>`;}
function finished(g){return g.story_ids.filter(id=>state.completed.includes(id)).length;}
function regionDescription(g){return (g.region_ids||[]).map(id=>regionName(catalog,id)).join(" · ")||"地区待考证";}
function regionTags(g){return `<div class="region-tags" aria-label="作品主要舞台">${g.region_ids?.length?g.region_ids.map(id=>`<a href="${anchor("regions",id)}" title="作品主要舞台：${e(regionName(catalog,id))}">${e(regionName(catalog,id))}</a>`).join(""):'<a class="unverified" href="#regions/unknown">地区待考证</a>'}</div>`;}
function regionSelect(){return `<label class="region-select"><span>地区</span><select id="region-filter" aria-label="按地区筛选"><option value="all">全部地区</option><option value="multi">多地区作品</option><option value="unknown">地区待考证</option>${[["国家与地区",catalog.regions.filter(r=>r.kind==="country")],["城市与其他舞台",catalog.regions.filter(r=>r.kind!=="country")]].map(([label,items])=>`<optgroup label="${label}">${items.map(r=>`<option value="${e(r.id)}">${e(r.name)} · ${catalog.region_stats.counts[r.id]} 部</option>`).join("")}</optgroup>`).join("")}</select></label>`;}
function regionInfo(g){return `<section class="region-info"><div class="eyebrow">SETTING / 作品主要舞台</div>${regionTags(g)}<p>${e(g.region_note)}</p>${g.region_evidence?.length?`<details><summary>查看地区分类依据</summary><ul>${g.region_evidence.map(s=>`<li><a href="${safeURL(s.url)}" target="_blank" rel="noopener noreferrer">${e(s.title)} ↗</a></li>`).join("")}</ul></details>`:""}</section>`;}
function regionShelfHeader(){const r=catalog.regions.find(r=>r.id===region);return `<div class="page-title"><a class="back-link" href="#regions">← 返回地区总览</a><div class="eyebrow">FOLLOW THE STORIES ACROSS TERRA</div><h1>${e(regionName(catalog,region))}</h1><p>${e(r?.description||(region==="multi"?"已记录多个主要舞台的作品。可在任一对应地区找到同一部作品。":region==="unknown"?"这些条目尚未核对主要舞台。故事集、干员密录和漫画将逐篇核对，暂不按角色籍贯推定。":"从不同地区寻找下一篇故事。"))}</p><p>按作品主要舞台初编，尚未逐场景核对；国家筛选包含下属城市。</p><div class="button-row"><button class="button primary" data-action="export-filtered">导出筛选结果 EPUB ↓</button><a class="button" href="downloads/泰拉阅览室-地区剧情集.epub" download>下载地区剧情集 ↓</a></div></div>`;}
function renderRegionIndex(){
  libraryMode="regions";updateNavigation("regions");crumbs("地区书架");const s=catalog.region_stats;
  const cards=items=>`<div class="region-grid">${items.map(r=>{const examples=filterGroups(catalog,{region:r.id}).slice(0,2);return `<a class="region-card" href="${anchor("regions",r.id)}"><span class="region-card-top">${e(r.parent?regionName(catalog,r.parent):r.kind==="country"?"国家与地区":"城市与其他舞台")}<span>${s.counts[r.id]} 部 ↗</span></span><h3>${e(r.name)}</h3><p>${e(r.description)}</p><div class="region-examples">${examples.length?examples.map(g=>e(displayTitle(g))).join(" / "):"尚待补充编目"}</div></a>`;}).join("")}</div>`;
  main.innerHTML=`<div class="page-title"><div class="eyebrow">A READING JOURNEY THROUGH TERRA</div><h1>沿着泰拉，寻找故事。</h1><p>从龙门的街巷，到远方的海岸。选一个地区，翻开发生在那里的故事。</p><div class="button-row"><a class="button primary" href="#regions/all">浏览全部地区篇目 →</a><a class="button" href="downloads/泰拉阅览室-地区剧情集.epub" download>下载地区剧情集 EPUB ↓</a></div></div><div class="coverage-summary"><div><b>${s.assigned}</b><span>部作品已编入主要舞台</span></div><div><b>${s.unknown}</b><span>部作品地区待考证</span></div><div><b>${s.multi}</b><span>部作品记录了多个舞台</span></div></div><p class="page-note">本版是作品级主要舞台初编，分类线索来自 PRTS 社区资料，尚未逐场景核对。国家数量包含下属城市；同一作品可以出现在多个地区，数字不能相加作为收录总数。干员籍贯与阵营不等同于剧情发生地。</p><div class="region-shortcuts"><a class="button" href="#regions/multi">多地区作品 · ${s.multi} →</a><a class="button" href="#regions/unknown">地区待考证 · ${s.unknown} →</a></div><section aria-labelledby="countries-title"><div class="section-heading"><h2 id="countries-title">国家与地区<small>按作品主要舞台寻找</small></h2></div>${cards(catalog.regions.filter(r=>r.kind==="country"))}</section><section aria-labelledby="places-title"><div class="section-heading region-places-heading"><h2 id="places-title">城市与其他舞台<small>具体地点、移动本舰与特殊空间</small></h2></div>${cards(catalog.regions.filter(r=>r.kind!=="country"))}</section><details class="source-info"><summary>编目方法与当前范围</summary><p>${e(catalog.region_method.note)}</p><p>编目复核：${e(catalog.region_method.reviewed_at)}；内容快照截止：${e(catalog.cutoff)}。尚未编入某地区，不代表该地区没有故事；单篇发生地不能由整部作品标签直接推定。每部已编目作品的详情页保留来源与说明。</p><a href="#sources">查看整体收录状态 ↗</a></details>`;
}
function safeState(raw){
  if(!raw||raw.version!==1||!Array.isArray(raw.favorites)||!Array.isArray(raw.completed))throw new Error("这不是有效的阅览室进度备份。");
  const allowed=new Set(Object.keys(catalog.stories).concat(DEMO_ID));
  const clean=structuredClone(initialState);
  clean.favorites=[...new Set(raw.favorites.filter(x=>typeof x==="string"&&groupById(x)))];
  clean.completed=[...new Set(raw.completed.filter(x=>allowed.has(x)))];
  for(const [id,value] of Object.entries(raw.bookmarks||{}))if(allowed.has(id)&&typeof value==="string"&&/^[A-Za-z0-9_-]+$/.test(value))clean.bookmarks[id]=value;
  for(const [id,p] of Object.entries(raw.positions||{}))if(allowed.has(id)&&p&&typeof p.node==="string"&&/^[A-Za-z0-9_-]+$/.test(p.node))clean.positions[id]={node:p.node,percent:Math.min(100,Math.max(0,Number(p.percent)||0))};
  clean.prefs={theme:raw.prefs?.theme==="dark"?"dark":"light",font:Math.min(28,Math.max(15,Number(raw.prefs?.font)||19)),directives:!!raw.prefs?.directives};
  clean.last=allowed.has(raw.last)?raw.last:null;return clean;
}

function openDatabase(){return new Promise((resolve,reject)=>{const req=indexedDB.open("terra-reading-room-v1",1);req.onupgradeneeded=()=>req.result.createObjectStore("bodies",{keyPath:"id"});req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);});}
function allBodies(){return new Promise((resolve,reject)=>{const r=db.transaction("bodies").objectStore("bodies").getAll();r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
function saveBodies(values){return new Promise((resolve,reject)=>{if(!db)return reject(new Error("当前浏览器无法使用本地资料库，请改用本地命令行工具。"));const tx=db.transaction("bodies","readwrite");for(const s of values)tx.objectStore("bodies").put(s);tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error||new Error("导入未完成"));});}

function cover(g){
  const [bg,ink]=palette(g.id),n=g.category==="main"?String(g.id.match(/\d+/)?.[0]||0).padStart(2,"0"):String(g.order+1).padStart(2,"0");
  const top={main:"MAIN THEME",event:"EVENT ARCHIVE",short:"SHORT STORIES",record:"OPERATOR RECORD",comic:"TERRA HISTORICUS"}[g.category];
  return `<div class="book-cover is-${g.category}" style="--cover:${bg};--cover-ink:${ink}"><span class="cover-top">${top}</span><span class="cover-number">${e(n)}</span><strong class="cover-title">${e(g.title)}</strong><span class="cover-bottom">${e(g.operator||"ARKNIGHTS · STORY INDEX")}</span></div>`;
}
function bookCard(g){
  const count=localCount(g),done=finished(g),saved=state.favorites.includes(g.id);
  return `<article class="book-card"><button class="save-book ${saved?"saved":""}" data-action="save" data-id="${e(g.id)}" aria-label="${saved?"取消收藏":"收藏"}《${e(displayTitle(g))}》" aria-pressed="${saved}">${saved?"★":"☆"}</button><a href="${anchor("book",g.id)}" class="cover-link" tabindex="-1" aria-hidden="true">${cover(g)}</a><div class="book-info"><h3><a href="${anchor("book",g.id)}">${e(displayTitle(g))}</a></h3><p><span>${CATEGORY[g.category]}${g.count!=null?` · ${g.count} 篇`:""}</span><span>${g.date?.slice(0,4)||"日期待核验"}</span></p>${regionTags(g)}<div class="mini-status">${g.category==="comic"?"官方原作入口":count?`可读正文 ${count}/${g.count} 篇`:"正文未收录"}</div>${done?`<div class="progress-track" aria-label="已读 ${done} 篇"><span style="width:${Math.round(done/g.count*100)}%"></span></div>`:""}</div></article>`;
}
function hero(){return `<section class="hero"><div><div class="eyebrow">THE STORIES, GATHERED HERE</div><h1>把散落的故事，<br>读成一段旅程。</h1><p>从最初的章节，到远方的只言片语。<br>沿着篇章阅读，也为下一次重逢留一枚书签。</p><div class="button-row"><a class="button primary" href="${anchor("book","main_0")}">从主线开始 <span aria-hidden="true">↗</span></a><a class="button text" href="#demo">试读原创样本 <span aria-hidden="true">→</span></a></div></div><div class="hero-art" aria-hidden="true"><div class="art-cross"></div><div class="art-ring"></div><span class="art-star">✧</span><div class="art-book"><small>ARCHIVE / 01</small><b>故事留存</b><span>TERRA · READING ROOM</span></div><span class="art-label">A PLACE FOR STORIES</span></div></section>`;}
function renderLibrary(mode="library"){
  libraryMode=mode;updateNavigation(mode);crumbs(mode==="regions"?regionName(catalog,region):mode==="shelf"?"我的收藏":"总书架");
  const stats=catalog.stats;
  main.innerHTML=(mode==="regions"?regionShelfHeader():mode==="library"?hero()+`<div class="collection-notes"><span><b>${stats.categories.main}</b>卷主线</span><span><b>${stats.categories.event}</b>部活动</span><span><b>${stats.categories.short}</b>个故事集</span><span><b>${stats.categories.record}</b>份密录</span><span><b>${stats.categories.comic}</b>个官方漫画入口</span><span>目录快照 / 国服简中</span></div>`:`<div class="page-title"><div class="eyebrow">YOUR PERSONAL SHELF</div><h1>故事在这里等你。</h1><p>将想读的作品放进收藏，按自己的节奏继续。收藏与阅读记录保存在当前浏览器，可在下方备份。</p><div class="button-row"><button class="button primary" data-action="export-shelf">导出收藏 EPUB ↓</button><button class="button" data-action="backup-state">备份阅读记录</button><button class="button" data-action="restore-state">恢复阅读记录</button></div></div>`)+
    `<section aria-label="篇目筛选"><div class="section-heading"><h2>${mode==="regions"?"地区篇目":mode==="shelf"?"我的收藏":"全部篇目"}<small>在目录中找到下一篇故事</small></h2><a href="#sources">查看收录范围 ↗</a></div><div class="search-row"><label class="search-box">${searchIcon}<input id="catalog-search" type="search" placeholder="搜索作品、篇目、地区或干员…" aria-label="搜索目录" value="${e(query)}"><span class="search-key">⌘ K</span></label>${regionSelect()}<select id="sort-order" aria-label="篇目排序"><option value="catalogue">官方目录顺序</option><option value="oldest">已知日期：从早到晚</option><option value="newest">已知日期：从晚到早</option></select></div><div class="filter-row">${[["all","全部",stats.groups],...Object.entries(CATEGORY).map(([key,label])=>[key,label,stats.categories[key]||0])].map(([key,label,count])=>`<button class="chip ${category===key?"active":""}" data-action="filter" data-value="${key}" aria-pressed="${category===key}">${label}<small>${count}</small></button>`).join("")}<span class="result-label" id="result-label" aria-live="polite"></span></div></section><section id="library-results" aria-label="目录结果"></section><p class="page-note">游戏正文已从你提供的本地资料接入。地区与时间待考证项保留标记；漫画及站外叙事仍按各自收录状态展示。</p>`;
  $("#sort-order").value=sort;$("#region-filter").value=region;
  renderResults();
  $("#catalog-search").addEventListener("input",ev=>{query=ev.target.value;page=1;renderResults();});
  $("#sort-order").addEventListener("change",ev=>{sort=ev.target.value;page=1;renderResults();});
  $("#region-filter").addEventListener("change",ev=>{region=ev.target.value;page=1;if(mode==="regions"){const hash=anchor("regions",region);if(location.hash===hash)renderLibrary(mode);else location.hash=hash;}else renderResults();});
}
function renderResults(){
  const groups=filterGroups(catalog,{category,region,query,sort,saved:libraryMode==="shelf"?new Set(state.favorites):null}),pages=Math.max(1,Math.ceil(groups.length/pageSize));page=Math.min(page,pages);
  $("#result-label").textContent=`${regionName(catalog,region)} · ${groups.length} 个条目`;
  $("#library-results").innerHTML=groups.length?`<div class="book-grid">${groups.slice((page-1)*pageSize,page*pageSize).map(bookCard).join("")}</div><div class="pagination"><button class="button small" data-action="page" data-delta="-1" ${page===1?"disabled":""}>← 上一页</button><span>${page} / ${pages} <span class="muted">· ${groups.length} 项</span></span><button class="button small" data-action="page" data-delta="1" ${page===pages?"disabled":""}>下一页 →</button></div>`:`<div class="empty"><h2>${libraryMode==="shelf"&&!query?"书架留了一些空位。":"还没找到这篇故事。"}</h2><p>${libraryMode==="shelf"&&!query?"点击作品封面旁的星标，把想读的故事放到这里。":"可以试试作品名、关卡代号或干员名；未列出的官方故事会进入后续查漏。"}</p><a class="button" href="${libraryMode==="shelf"?"#library":"#sources"}">${libraryMode==="shelf"?"去总书架逛逛":"查看收录范围"} ↗</a></div>`;
}
function renderBook(g){
  updateNavigation("library");crumbs(displayTitle(g));const n=localCount(g),saved=state.favorites.includes(g.id);
  main.innerHTML=`<a href="#library" class="back-link">← 返回总书架</a><section class="book-detail-head">${cover(g)}<div><div class="eyebrow">${CATEGORY[g.category]} / STORY ARCHIVE</div><h1>${e(displayTitle(g))}</h1><div class="meta">${g.operator?e(g.operator)+" · ":""}${g.count!=null?g.count+" 个剧情片段":"漫画作品入口"}<br>${g.rerun_date?" · 复刻日期："+g.rerun_date:""}</div><div class="button-row">${g.story_ids.length?`<a class="button primary" href="${anchor("story",g.story_ids.find(id=>!state.completed.includes(id))||g.story_ids[0])}">打开篇章 →</a>`:`<a class="button primary" href="${safeURL(g.source_url)}" target="_blank" rel="noopener noreferrer">前往官方原作 ↗</a>`}<button class="button" data-action="save" data-id="${e(g.id)}">${saved?"★ 已收藏":"☆ 加入收藏"}</button><button class="button" data-action="export-group" data-id="${e(g.id)}">导出 EPUB ↓</button></div></div></section><p class="book-description">${g.category==="comic"?"已登记官方作品入口；集数、发布日期与版本仍待逐项核对。":`按上游目录保留篇章与行动前后顺序。可读正文 ${n}/${g.count} 篇，已读 ${finished(g)} 篇。`}</p>${regionInfo(g)}${timeInfo(g)}${g.story_ids.length?`<div class="section-heading"><h2>篇章目录</h2><span class="pill">${g.count} 篇</span></div><ol class="toc-list">${g.story_ids.map((id,i)=>{const s=catalog.stories[id];return `<li><a class="toc-item" href="${anchor("story",id)}"><span class="toc-index">${String(i+1).padStart(2,"0")}</span><span class="toc-title"><span>${e(s.code)}</span>${e(s.title)}</span><span class="toc-part">${e(s.part||"剧情")}</span><span class="toc-state">${state.completed.includes(id)?"已读 ✓":hasBody(id)?"可阅读":"正文未收录"}</span><span aria-hidden="true">↗</span></a></li>`;}).join("")}</ol>`:""}<details class="source-info"><summary>来源与版本</summary><p>来源：<a href="${safeURL(g.source_url)}" target="_blank" rel="noopener noreferrer">${g.category==="comic"?"官方作品页":"本地导出对应的原始数据"}</a></p><p>收录截止 ${catalog.cutoff}；${g.date?"开放日期的范围与依据见上方时间信息。":"上游未提供可靠日期，本版没有推定首次发布日。"}</p>${g.category!=="comic"?`<p>来源摘要：${catalog.revision}</p>`:""}</details>`;
}
function browserNode(n){
  const text=e(plain(n.text)),id=e(n.id);
  if(n.kind==="dialogue")return `<p id="${id}"><span class="speaker">${e(plain(n.speaker))}</span>${text}</p>`;
  if(["narration","scene","branch"].includes(n.kind))return `<${n.kind==="branch"?"aside":"p"} id="${id}" class="${n.kind}">${text}</${n.kind==="branch"?"aside":"p"}>`;
  if(n.kind==="choice")return `<section id="${id}" class="choice">你想沿哪条路读下去？${n.options.map(o=>o.target?`<button class="option-link" data-action="jump" data-target="${e(o.target)}">${e(plain(o.label))} →</button>`:`<p>${e(plain(o.label))}（跳转待核对）</p>`).join("")}<small>以下保留各条备选分支，分支条件单独标出。</small></section>`;
  return `<details id="${id}" class="directive ${n.kind==="unknown"?"unknown":"known"}"><summary>${n.kind==="unknown"?"未识别段落，待核对":"演出提示"} · ${e(n.command)}</summary><pre>${e(JSON.stringify(n.attributes||{},null,2))}</pre></details>`;
}
function renderStory(id){
  currentStory=id;const story=bodies.get(id),record=catalog.stories[id],g=record&&groupById(record.group_id),demo=id===DEMO_ID;
  if(!record&&!story){renderMissing();return;}
  const title=displayTitle(g,record?.title||story.title);crumbs(title);updateNavigation("library");
  const current=g?.story_ids.indexOf(id)??-1,previous=g?.story_ids[current-1],next=g?.story_ids[current+1];
  main.innerHTML=`<div class="reader-topline"><a class="back-link" href="${g?anchor("book",g.id):"#library"}">← ${e(g?displayTitle(g):"返回书架")}</a><div class="reader-controls">${story?'<button data-action="bookmark" aria-label="在当前位置留书签" title="在当前位置留书签">♧</button>':""}<button data-action="font" data-delta="-1" aria-label="缩小字号">A−</button><button data-action="font" data-delta="1" aria-label="放大字号">A+</button><label><input id="show-directives" type="checkbox" ${state.prefs.directives?"checked":""}>演出提示</label></div></div><header class="reader-head"><div class="eyebrow">${demo?"ORIGINAL READING SAMPLE":e((record?.code||CATEGORY[g?.category]||"PERSONAL")+" / "+(record?.part||"阅读"))}</div><h1>${e(title)}</h1><p>${demo?"原创排版演示 · 非明日方舟官方剧情":`${e(g?displayTitle(g):"个人正文")} · ${story?(story.origin==="user_import"?"本浏览器个人导入":"正文已收录"):"正文未收录"}`}</p>${g?`<p class="reader-region">所属作品主舞台：${e(regionDescription(g))} · 非本篇逐场景地点</p>`:""}</header>${record?`<div class="reader-source">${timeInfo(record)}</div>`:""}`+
    (story?`<article id="reading-body" class="reading-body ${state.prefs.directives?"":"hide-directives"}">${story.nodes.map(browserNode).join("")}</article><div class="reader-bottom"><button class="button small" data-action="bookmark">留一枚书签 ♧</button>${state.bookmarks[id]?`<button class="button small" data-action="jump" data-target="${e(state.bookmarks[id])}">回到书签</button>`:""}<button class="button small" data-action="complete" data-id="${e(id)}">${state.completed.includes(id)?"已读 ✓ · 取消标记":"标记已读 ✓"}</button><button class="button small" data-action="export-story" data-id="${e(id)}">下载本篇 EPUB ↓</button></div>`:
    `<section class="empty" style="margin:32px auto;max-width:760px"><span class="eyebrow">A PLACE RESERVED FOR THE STORY</span><h2>这一页，等你把故事带来。</h2><p>篇目与顺序已经整理好。你可以前往原文阅读器，或将本地正文导入此篇；导入内容只保存在当前浏览器。</p><div class="button-row"><a class="button primary" href="${safeURL(record.reader_url)}" target="_blank" rel="noopener noreferrer">前往原文阅读 ↗</a><button class="button" data-action="import" data-id="${e(id)}">导入本篇正文 ＋</button></div><p class="import-help">支持 ASTR JSON、带段落类型的原生 JSON 与 UTF-8 剧情脚本。<a href="#demo">先看看原创阅读样本 →</a></p></section>`)+
    `<div class="reader-bottom">${previous?`<a class="button" href="${anchor("story",previous)}">← ${e(displayTitle(g,catalog.stories[previous].title))}</a>`:""}${next?`<a class="button" href="${anchor("story",next)}">${e(displayTitle(g,catalog.stories[next].title))} →</a>`:""}</div>${record?`<details class="source-info reader-source"><summary>本篇资料与来源</summary><p>目录条目：${e(record.code)} ${e(record.part)}。原始路径：${e(record.source_path)}。</p>${story?.provided_source?`<p>正文来源：${e(story.provided_source.workbook)} / ${e(story.provided_source.sheet)}。</p>${story.provided_source.recovery_note?`<p>${e(story.provided_source.recovery_note)}</p>`:""}`:""}${story?.warnings?.length?`<p>本篇有 ${story.warnings.length} 项分支或特殊指令待核对，原记录已保留。</p>`:""}<p><a href="${safeURL(record.source_url)}" target="_blank" rel="noopener noreferrer">查看原始数据项目</a></p><button class="button small" data-action="import" data-id="${e(id)}">${story?"重新导入本篇正文":"导入本篇正文"}</button></details>`:`<p class="page-note reader-source">本篇由项目原创，用于验证旁白、对话、分支、书签与 EPUB 排版，不属于官方剧情。</p>`}`;
  $("#show-directives").addEventListener("change",ev=>{state.prefs.directives=ev.target.checked;persist();$("#reading-body")?.classList.toggle("hide-directives",!ev.target.checked);});
  if(story){
    currentNode=state.positions[id]?.node||story.nodes[0].id;state.last=id;persist();
    const elements=[...main.querySelectorAll("#reading-body [id]")];
    observer=new IntersectionObserver(entries=>{
      const visible=entries.filter(x=>x.isIntersecting).sort((a,b)=>a.boundingClientRect.top-b.boundingClientRect.top);
      if(visible.length){currentNode=visible[0].target.id;const idx=story.nodes.findIndex(n=>n.id===currentNode);state.positions[id]={node:currentNode,percent:Math.round((idx+1)/story.nodes.length*100)};clearTimeout(saveTimer);saveTimer=setTimeout(persist,450);}
    },{rootMargin:"-12% 0px -60% 0px",threshold:0});elements.forEach(el=>observer.observe(el));
    const last=state.positions[id]?.node;if(last)requestAnimationFrame(()=>document.getElementById(last)?.scrollIntoView({block:"center"}));
  }
}
function renderLists(){
  updateNavigation("lists");crumbs("阅读书单");
  main.innerHTML=`<div class="page-title"><div class="eyebrow">READ AT YOUR OWN PACE</div><h1>选一条路，慢慢读。</h1><p>书单是不同的入口。首版提供按篇章与上游日期整理的基础书单；人物关系、前置剧情与故事内时间线仍待人工校订。</p></div>${lists.map(l=>`<section class="list-card"><div class="eyebrow">${e(l.eyebrow)}</div><h2>${e(l.title)}</h2><p>${e(l.description)}</p><div class="list-members">${l.group_ids.map(id=>groupById(id)).filter(Boolean).map(g=>`<a class="list-member" href="${anchor("book",g.id)}">${e(displayTitle(g))}</a>`).join("")}</div><div class="button-row"><a class="button primary small" href="${anchor("book",l.group_ids[0])}">从第一部开始 →</a><button class="button small" data-action="save-list" data-id="${e(l.id)}">加入我的收藏 ＋</button><button class="button small" data-action="export-list" data-id="${e(l.id)}">导出书单 EPUB ↓</button></div></section>`).join("")}<div class="tools-panel"><h2>带上自己的阅读节奏</h2><p>在总书架收藏作品，即可组成自己的书单。导出时，有本地正文的篇目会包含正文，其余篇目保留目录与原文入口。</p><a class="button" href="#shelf">查看我的收藏 →</a></div>`;
}
function renderSources(){
  updateNavigation("sources");crumbs("来源与收录");const imported=bodyIndex.count;
  main.innerHTML=`<div class="page-title"><div class="eyebrow">EVERY STORY HAS A SOURCE</div><h1>每一篇故事，都有来处。</h1><p>这里记录已经整理的部分，也保留尚未补齐的空位。本版接入你提供的游戏剧情正文；漫画、档案、模组与站外材料按实际收录状态展示。</p><span class="pill">收录截止 ${catalog.cutoff} · 国服简体中文</span></div><div class="coverage-summary"><div><b>${catalog.stats.stories.toLocaleString()}</b><span>游戏剧情片段索引</span></div><div><b>${catalog.stats.categories.comic}</b><span>官方漫画作品入口</span></div><div><b>${imported}</b><span>已接入的本地游戏正文 · 原创样本另计</span></div></div><p class="page-note">目录包含 ${catalog.stats.game_groups} 个游戏条目组；${catalog.stats.unknown_dates} 个条目组的日期待核验。档案、模组、玩法事件、站外小故事与出版物仍需独立盘点，不计入已完成范围。</p><div class="source-table-wrap"><table><thead><tr><th>资料入口</th><th>当前状态</th><th>下一步核对</th></tr></thead><tbody>${sources.map(s=>`<tr><td>${s.url?`<a href="${safeURL(s.url)}" target="_blank" rel="noopener noreferrer">${e(s.title)} ↗</a>`:e(s.title)}<small>${e(s.kind)} · ${e(s.scope)}</small></td><td>${e(s.status)}</td><td>${e(s.next)}</td></tr>`).join("")}</tbody></table></div><div class="source-info"><p>本地目录来源摘要：<a href="${safeURL(catalog.source_url)}" target="_blank" rel="noopener noreferrer">${catalog.revision}</a></p><p>目录统计以本次本地数据快照及已登记漫画作品为范围。上游没有可靠日期的条目保留“日期待核验”；本版没有强行推定年代或展示整个 IP 的覆盖率。</p></div><section class="tools-panel"><h2>补充自己的正文与阅读记录。</h2><p>本次提供的导出正文已接入这个私人站点。额外通过下方导入的个人文件保存在当前浏览器。建议定期备份正文与阅读记录；更换浏览器、站点地址或清理网站数据后，需要重新导入。</p><div class="button-row"><button class="button" data-action="import">导入本地正文 ＋</button><button class="button" data-action="backup-bodies">备份已导入正文</button><button class="button" data-action="backup-state">备份阅读记录</button><button class="button" data-action="restore-state">恢复阅读记录</button></div></section><div class="tools-panel"><h2>离线阅读</h2><p>地区剧情集包含本次已接入的游戏正文；目录版仅含篇目与来源。收藏和地区筛选结果也可以导出为 EPUB。</p><div class="button-row"><a class="button primary" href="downloads/泰拉阅览室-地区剧情集.epub" download>下载地区剧情集 EPUB ↓</a><a class="button" href="downloads/泰拉阅览室-剧情目录.epub" download>下载剧情目录 EPUB ↓</a><a class="button" href="downloads/泰拉阅览室-原创阅读样本.epub" download>下载原创样本 EPUB ↓</a></div></div>`;
}
function renderMissing(){main.innerHTML='<div class="empty"><h2>这张目录卡还没有归档。</h2><p>可以从总书架重新查找，或检查链接是否完整。</p><a class="button" href="#library">回到总书架 →</a></div>';crumbs("未找到篇目");}
async function renderRoute(preserveScroll=false){
  const generation=++routeGeneration,oldY=window.scrollY;observer?.disconnect();observer=null;currentStory=null;
  const [name,rawId]=location.hash.slice(1).split("/");let id;try{id=decodeURIComponent(rawId||"");}catch{renderMissing();return;}
  if(name==="book"){const g=groupById(id);g?renderBook(g):renderMissing();}
  else if(name==="story"){
    if(!bodies.has(id)&&bodyIndex.items[id]){
      main.innerHTML='<div class="loading-state" role="status">正在打开正文…</div>';
      try{await ensureBody(id);}catch(error){if(generation!==routeGeneration)return;main.innerHTML=`<div class="empty"><h2>正文暂时没有加载成功。</h2><p>${e(error.message)}</p><button class="button" data-action="retry-body">重新加载本篇</button></div>`;return;}
      if(generation!==routeGeneration)return;
    }
    renderStory(id);
  }
  else if(name==="demo")renderStory(DEMO_ID);
  else if(name==="regions"){
    if(!id)renderRegionIndex();
    else if(["all","unknown","multi",...catalog.regions.map(r=>r.id)].includes(id)){
      if(!preserveScroll&&region!==id){category="all";query="";page=1;}region=id;renderLibrary("regions");
    }else renderMissing();
  }
  else if(name==="lists")renderLists();
  else if(name==="sources")renderSources();
  else if(name==="shelf")renderLibrary("shelf");
  else renderLibrary();
  if(generation!==routeGeneration)return;
  if(preserveScroll)window.scrollTo({top:oldY,behavior:"instant"});else if(!currentStory||!state.positions[currentStory])window.scrollTo({top:0,behavior:"instant"});
  document.title=(currentStory?displayTitle(groupById(catalog.stories[currentStory]?.group_id),catalog.stories[currentStory]?.title||bodies.get(currentStory)?.title):name==="book"?displayTitle(groupById(id)):name==="regions"?(id?regionName(catalog,id):"地区书架"):null)||"故事留在这里";document.title+=" · 泰拉阅览室";
}
function download(data,filename,type="application/json"){
  const blob=data instanceof Blob?data:new Blob([data],{type}),url=URL.createObjectURL(blob),link=document.createElement("a");link.href=url;link.download=filename;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
}
async function exportStory(id){
  await ensureBody(id);
  const s=bodies.get(id);if(!s)return notify("请先导入这篇正文。");
  const title=displayTitle(groupById(catalog.stories[id]?.group_id),s.title);
  const sections=[{title:"使用说明",body:`<h1>${e(title)}</h1><p>${id===DEMO_ID?"本篇为原创阅读样本，非官方剧情。":"个人导入正文；以下保留全部分支与来源记录。"}</p>`},{title,body:`<h1>${e(title)}</h1>${timeXHTML(catalog.stories[id])}${readableNodes(s).map(nodeXHTML).join("")}`}];
  download(createEpub({title,sections,cutoff:catalog.cutoff,identifier:encodeURIComponent(id)}),title.replace(/[\\/:*?"<>|]/g,"-")+".epub","application/epub+zip");notify("本篇 EPUB 已生成，包含分支与段落跳转。");
}
async function exportGroups(ids,title){
  const groups=[...new Set(ids)].map(groupById).filter(Boolean);if(!groups.length)return notify("当前没有可导出的作品。");
  const personal=[...bodies.values()].some(s=>s.origin==="user_import");
  if(groups.length===catalog.groups.length&&bodyIndex.count&&!personal){
    const link=document.createElement("a");link.href="downloads/泰拉阅览室-地区剧情集.epub";link.download="泰拉阅览室-地区剧情集.epub";document.body.append(link);link.click();link.remove();notify("已开始下载按地区编排的剧情集 EPUB。");return;
  }
  const selected=groups.flatMap(g=>g.story_ids);await ensureBodies(selected);
  const imported=selected.filter(id=>bodies.has(id)).length;
  const sections=buildReadingSections(catalog,groups,bodies,title);
  const suffix=imported?"阅读版":"目录版";
  download(createEpub({title:title+" · "+suffix,sections,cutoff:catalog.cutoff,identifier:"list-"+Date.now(),source:catalog.source_url}),title.replace(/[\\/:*?"<>|]/g,"-")+"-"+suffix+".epub","application/epub+zip");
  notify(imported?`已生成 EPUB，包含 ${imported} 篇正文，按地区编排。`:"已生成目录版 EPUB；所选作品暂无正文。");
}

main.addEventListener("click",async event=>{
  const button=event.target.closest("[data-action]");if(!button)return;const {action,id,value,target,delta}=button.dataset;
  try{
    if(action==="retry-body")await renderRoute();
    else if(action==="filter"){category=value;page=1;document.querySelectorAll(".chip").forEach(c=>{const active=c.dataset.value===value;c.classList.toggle("active",active);c.setAttribute("aria-pressed",active);});renderResults();}
    else if(action==="page"){page+=Number(delta);renderResults();$("#library-results").scrollIntoView({block:"start"});}
    else if(action==="save"){const i=state.favorites.indexOf(id);i<0?state.favorites.push(id):state.favorites.splice(i,1);persist();updateNavigation(libraryMode);if($("#library-results"))renderResults();else renderRoute(true);notify(i<0?"已放入我的收藏。":"已从收藏移除。");}
    else if(action==="save-list"){const l=lists.find(x=>x.id===id);state.favorites=[...new Set([...state.favorites,...l.group_ids.filter(groupById)])];persist();updateNavigation("lists");notify("整份书单已加入收藏。");}
    else if(action==="font"){state.prefs.font=Math.max(15,Math.min(28,state.prefs.font+Number(delta)));document.documentElement.style.setProperty("--reading-size",state.prefs.font+"px");persist();}
    else if(action==="jump"){document.getElementById(target)?.scrollIntoView({block:"center"});currentNode=target;}
    else if(action==="bookmark"){state.bookmarks[currentStory]=currentNode||bodies.get(currentStory).nodes[0].id;persist();const row=main.querySelector(".reader-bottom");let back=row.querySelector('[data-action="jump"]');if(!back){back=document.createElement("button");back.className="button small";back.dataset.action="jump";back.textContent="回到书签";row.prepend(back);}back.dataset.target=state.bookmarks[currentStory];notify("书签已留在这一页，可从阅读记录恢复。");}
    else if(action==="complete"){const i=state.completed.indexOf(id);i<0?state.completed.push(id):state.completed.splice(i,1);persist();button.textContent=i<0?"已读 ✓ · 取消标记":"标记已读 ✓";notify(i<0?"这一篇已读完。":"已取消已读标记。");}
    else if(action==="import"){importTarget=id||null;$("#body-file").click();}
    else if(action==="backup-state")download(JSON.stringify({...state,format:"terra-reading-room-state"},null,2),"泰拉阅览室-阅读记录.json");
    else if(action==="restore-state")$("#state-file").click();
    else if(action==="backup-bodies"){const stories=[...bodies.values()].filter(s=>s.origin==="user_import");if(!stories.length)return notify("当前还没有导入个人正文。");download(JSON.stringify({format:"terra-reading-room-bodies",version:1,stories},null,2),"泰拉阅览室-个人正文备份.json");}
    else if(action==="export-filtered"){const selected=filterGroups(catalog,{category,region,query,sort});if(!selected.length)return notify("当前筛选没有作品，请调整条件。");await exportGroups(selected.map(g=>g.id),"泰拉阅览室-"+regionName(catalog,region)+(category!=="all"?"-"+CATEGORY[category]:"")+(query?"-搜索结果":""));}
    else if(action==="export-group")await exportGroups([id],displayTitle(groupById(id)));
    else if(action==="export-list"){const l=lists.find(x=>x.id===id);await exportGroups(l.group_ids,l.title);}
    else if(action==="export-shelf")await exportGroups(state.favorites,"泰拉阅览室-我的收藏");
    else if(action==="export-story")await exportStory(id);
  }catch(error){notify(error.message||"操作未完成，请重试。");}
});
$("#theme-button").addEventListener("click",()=>{state.prefs.theme=state.prefs.theme==="dark"?"light":"dark";document.documentElement.dataset.theme=state.prefs.theme;persist();});
$("#body-file").addEventListener("change",async event=>{
  const files=[...event.target.files];event.target.value="";if(!files.length)return;
  try{
    const imported=[],seen=new Set();
    for(const file of files){
      if(file.size>32*1024*1024)throw new Error("单文件超过 32 MB，请使用本地命令行导入。");
      const text=await file.text(),raw=file.name.toLowerCase().endsWith(".json")?JSON.parse(text):text;
      const values=raw?.format==="terra-reading-room-bodies"?raw.stories:Array.isArray(raw)&&raw[0]?.nodes?raw:[raw];
      if(!Array.isArray(values))throw new Error("正文备份缺少 stories 数组。");
      for(const value of values){
        const sourcePath=typeof value==="object"?(value.storyTxt||value.source_path):null;
        const filename=file.name.replace(/\.(json|txt)$/i,"").toLowerCase();
        const matches=Object.values(catalog.stories).filter(s=>sourcePath?s.source_path.toLowerCase()===sourcePath.replace(/^zh_CN\/gamedata\/story\//,"").replace(/\.(json|txt)$/i,"").toLowerCase():s.source_path.toLowerCase().split("/").at(-1)===filename);
        const record=importTarget?catalog.stories[importTarget]:matches.length===1?matches[0]:null;
        const story=normalizeImport(value,record);
        if(!catalog.stories[story.id])throw new Error("正文编号没有匹配当前目录，请从对应篇目页导入。");
        if(importTarget&&story.id!==importTarget)throw new Error("正文编号与当前篇目不一致，已停止导入。");
        if(seen.has(story.id))throw new Error("本批次有重复篇目，未导入任何文件。");seen.add(story.id);imported.push(story);
      }
    }
    await saveBodies(imported);for(const story of imported)bodies.set(story.id,story);
    await renderRoute(true);const warnings=imported.reduce((n,s)=>n+(s.warnings?.length||0),0);notify(`已在本浏览器导入 ${imported.length} 篇正文${warnings?`，${warnings} 项待核对`:""}。`);
  }catch(error){notify("未导入："+(error.message||"文件格式无法识别"));}
  importTarget=null;
});
$("#state-file").addEventListener("change",async event=>{
  const file=event.target.files[0];event.target.value="";if(!file)return;
  try{if(file.size>5*1024*1024)throw new Error("进度文件过大。");state=safeState(JSON.parse(await file.text()));persist();document.documentElement.dataset.theme=state.prefs.theme;document.documentElement.style.setProperty("--reading-size",state.prefs.font+"px");await renderRoute(true);notify("阅读记录已恢复；本地正文保留。");}catch(error){notify("恢复失败："+error.message);}
});
window.addEventListener("hashchange",()=>{if(catalog)renderRoute();});
document.addEventListener("keydown",event=>{if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==="k"){event.preventDefault();if(!$("#catalog-search")){location.hash="library";setTimeout(()=>$("#catalog-search")?.focus(),0);}else $("#catalog-search").focus();}});
window.addEventListener("pagehide",()=>{clearTimeout(saveTimer);persist();});

async function init(){
  try{
    const load=async path=>{const r=await fetch(path);if(!r.ok)throw new Error("目录文件未能加载，请通过本地服务或站点地址打开。");return r.json();};
    const data=await Promise.all([load("data/catalog.json"),load("data/sources.json"),load("data/lists.json"),load("data/demo.json"),load("data/build.json"),load("data/bodies.json")]);
    [catalog,sources,lists]=data;bodyIndex=data[5];for(const s of data[3])bodies.set(s.id,validateStory(s));
    if(data[4].include_local)for(const s of await load("data/local-bodies.json"))bodies.set(s.id,validateStory(s));
    try{db=await openDatabase();for(const s of await allBodies())if(catalog.stories[s.id])bodies.set(s.id,validateStory(s));}catch{notify("当前环境无法打开本地资料库；站内已收录正文仍可阅读。");}
    try{state=safeState(state);}catch{state=structuredClone(initialState);persist();}$("#nav-total").textContent=catalog.stats.groups;$("#cutoff-label").textContent="收录截止 "+catalog.cutoff.replaceAll("-",".");
    await renderRoute();
  }catch(error){main.innerHTML=`<div class="empty"><h2>阅览室暂时没有打开。</h2><p>${e(error.message)}</p><button class="button" id="retry-init">重新加载</button></div>`;$("#retry-init").addEventListener("click",init);}
}
init();
