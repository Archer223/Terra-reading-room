import {escapeHTML as e} from "./model.js";
const encoder=new TextEncoder();
const crcTable=Uint32Array.from({length:256},(_,i)=>{let c=i;for(let j=0;j<8;j++)c=c&1?0xedb88320^(c>>>1):c>>>1;return c>>>0;});
function crc32(bytes){let c=0xffffffff;for(const b of bytes)c=crcTable[(c^b)&255]^(c>>>8);return (c^0xffffffff)>>>0;}
function chunk(length){const b=new Uint8Array(length),v=new DataView(b.buffer);return {b,u16:(at,n)=>v.setUint16(at,n,true),u32:(at,n)=>v.setUint32(at,n,true)};}

export function zipStore(files) {
  const local=[],central=[];let offset=0,centralSize=0;
  for(const [path,value] of files) {
    const name=encoder.encode(path),data=typeof value==="string"?encoder.encode(value):value;
    const crc=crc32(data),h=chunk(30+name.length);
    h.u32(0,0x04034b50);h.u16(4,20);h.u16(6,0x800);h.u16(8,0);h.u16(12,0x5c21);h.u32(14,crc);h.u32(18,data.length);h.u32(22,data.length);h.u16(26,name.length);h.b.set(name,30);
    local.push(h.b,data);
    const c=chunk(46+name.length);c.u32(0,0x02014b50);c.u16(4,20);c.u16(6,20);c.u16(8,0x800);c.u16(10,0);c.u16(14,0x5c21);c.u32(16,crc);c.u32(20,data.length);c.u32(24,data.length);c.u16(28,name.length);c.u32(42,offset);c.b.set(name,46);
    central.push(c.b);centralSize+=c.b.length;offset+=h.b.length+data.length;
  }
  const end=chunk(22);end.u32(0,0x06054b50);end.u16(8,files.length);end.u16(10,files.length);end.u32(12,centralSize);end.u32(16,offset);
  const all=new Uint8Array(offset+centralSize+22);let at=0;for(const part of [...local,...central,end.b]){all.set(part,at);at+=part.length;}return all;
}

const css=`body{font-family:serif;line-height:1.85;margin:5%;color:#263d32}h1,h2{line-height:1.5}a{color:#355b4c}p{margin:1em 0}strong{font-family:sans-serif;font-size:.85em}.meta,.directive{font-family:sans-serif;font-size:.75em;color:#777;overflow-wrap:anywhere}.scene,.branch{padding:.8em;border-left:2px solid #ac9a70;background:#f0f1e9}.narration{color:#666}.choice{padding:1em;border:1px solid #aaa}li{margin:.6em 0}`;
function xhtml(title,body){return `<?xml version="1.0" encoding="utf-8"?><!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="zh-CN" lang="zh-CN"><head><title>${e(title)}</title><link rel="stylesheet" type="text/css" href="style.css"/></head><body>${body}</body></html>`;}

export function createEpub({title,sections,cutoff="2026-10-29",identifier="personal-reading-list",source=""}) {
  if(!title||!Array.isArray(sections)||!sections.length)throw new Error("电子书需要标题与至少一节内容。");
  const files=[["mimetype","application/epub+zip"],["META-INF/container.xml",`<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/></rootfiles></container>`],["EPUB/style.css",css]];
  const items=['<item id="css" href="style.css" media-type="text/css"/>','<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'],spine=[],toc=[];
  const stack=[{level:-1,children:toc}];
  sections.forEach((s,i)=>{const name=`section-${String(i).padStart(4,"0")}.xhtml`;files.push(["EPUB/"+name,xhtml(s.title,s.body)]);items.push(`<item id="s${i}" href="${name}" media-type="application/xhtml+xml"/>`);spine.push(`<itemref idref="s${i}"/>`);const level=s.level||0;while(stack.length>1&&stack.at(-1).level>=level)stack.pop();const n={title:s.title,name,level,children:[]};stack.at(-1).children.push(n);stack.push(n);});
  const renderToc=nodes=>`<ol>${nodes.map(n=>`<li><a href="${n.name}">${e(n.title)}</a>${n.children.length?renderToc(n.children):""}</li>`).join("")}</ol>`;
  files.push(["EPUB/nav.xhtml",xhtml("目录",`<nav epub:type="toc" id="toc"><h1>目录</h1>${renderToc(toc)}</nav>`)]);
  files.push(["EPUB/package.opf",`<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="uid">urn:terra-reading-room:${e(identifier)}</dc:identifier><dc:title>${e(title)}</dc:title><dc:language>zh-CN</dc:language><dc:creator>泰拉阅览室 · 个人整理</dc:creator><dc:date>${e(cutoff)}</dc:date><meta property="dcterms:modified">${e(cutoff)}T00:00:00Z</meta>${source?`<dc:source>${e(source)}</dc:source>`:""}</metadata><manifest>${items.join("")}</manifest><spine>${spine.join("")}</spine></package>`]);
  return zipStore(files);
}
