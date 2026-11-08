#!/usr/bin/env python3
"""Metadata-first story archive, local body import and EPUB 3 export. Python 3.10+."""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import html
import json
import re
import shutil
import sys
import urllib.parse
import urllib.request
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo
try:
    from .regions import apply_regions, region_matches
    from .chronology import apply_chronology
except ImportError:
    from regions import apply_regions, region_matches
    from chronology import apply_chronology

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "sites/terra-archive"
TZ = ZoneInfo("Asia/Shanghai")
REPO = "050644zf/ArknightsStoryJson"
CATEGORIES = {"main": "主线", "event": "活动", "short": "故事集", "record": "干员密录", "comic": "官方漫画"}
DEMO_ID = "demo:catalogue-night"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def iso_day(timestamp):
    return dt.datetime.fromtimestamp(timestamp, TZ).date().isoformat() if timestamp and timestamp > 0 else None


def reader_url(path):
    return "https://astr.pages.dev/#/zh_CN/content?f=" + urllib.parse.quote(path, safe="/")


class ComicParser(HTMLParser):
    """Use cover alt titles only; do not copy summaries or comic panels."""
    def __init__(self):
        super().__init__()
        self.current = None
        self.items = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            href = attrs.get("href", "")
            self.current = href if re.fullmatch(r"/terra-historicus/comic/\d+", href) else None
        if tag == "img" and self.current and attrs.get("alt", "").strip():
            self.items.setdefault(self.current, attrs["alt"].strip())

    def handle_endtag(self, tag):
        if tag == "a":
            self.current = None


def compile_catalog(review, characters, revision, cutoff, comic_html="", *, local_source=False):
    dt.date.fromisoformat(cutoff)
    if not local_source and not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("revision 必须是实际上游提交的完整 SHA")
    if local_source and not re.fullmatch(r"user-sha256:[0-9a-f]{64}", revision):
        raise ValueError("本地来源必须使用实际文件的 SHA-256")
    source = "https://github.com/Kengxxiao/ArknightsGameData" if local_source else f"https://github.com/{REPO}/blob/{revision}/zh_CN/gamedata/excel/story_review_table.json"
    groups, stories, excluded, warnings = [], {}, [], []
    character_names = collections.defaultdict(set)
    for key, character in characters.items():
        name = character.get("name")
        if not name:
            continue
        character_names[key].add(name)
        match = re.fullmatch(r"char_\d+_(.+)", key)
        if match:
            character_names[match[1]].add(name)
    type_map = {"MAINLINE": "main", "ACTIVITY": "event", "MINI_ACTIVITY": "short", "NONE": "record"}
    safe_snapshot = {}
    for position, (gid, group) in enumerate(review.items()):
        date = iso_day(group.get("startTime"))
        if date and date > cutoff:
            excluded.append({"id": gid, "title": group.get("name"), "date": date, "reason": "晚于收录截止日"})
            continue
        raw_type = group.get("entryType")
        if raw_type not in type_map:
            warnings.append({"group": gid, "issue": "未知目录类别", "value": raw_type})
            continue
        category = type_map[raw_type]
        members = []
        operator = None
        safe_rows = []
        ordered = sorted(enumerate(group.get("infoUnlockDatas", [])), key=lambda x: (x[1].get("storySort", 0), x[0]))
        for original_order, item in ordered:
            path = item.get("storyTxt", "").strip()
            if not path:
                warnings.append({"group": gid, "issue": "缺少剧情文件路径", "id": item.get("storyId")})
                continue
            sid = "cn:" + path.casefold()
            if sid in stories:
                warnings.append({"group": gid, "issue": "同路径多次引用，正文合并", "id": sid})
            else:
                if category == "record":
                    match = re.search(r"story_(.+)_\d+_\d+$", path)
                    if match:
                        names = character_names.get(match[1], set())
                        operator = next(iter(names)) if len(names) == 1 else None
                stories[sid] = {
                    "id": sid, "title": item.get("storyName") or group.get("name") or path,
                    "code": item.get("storyCode") or "", "part": item.get("avgTag") or "",
                    "group_id": gid, "source_path": path, "order": len(members),
                    "upstream_story_id": item.get("storyId"), "dependency": item.get("storyDependence"),
                    "reader_url": reader_url(path), "source_url": source,
                    "status": "index_only", "date_status": "upstream_date" if date else "unverified",
                }
            members.append(sid)
            safe_rows.append({key: item.get(key) for key in ("storyId", "storyName", "storyCode", "storySort", "storyTxt", "avgTag", "storyDependence")})
        title = group.get("name") or gid
        if category == "record":
            for sid in members:
                stories[sid]["operator"] = operator
        groups.append({
            "id": gid, "title": title, "category": category, "operator": operator,
            "date": date, "date_label": "上游开始日期" if date else "日期待核验",
            "rerun_date": iso_day(group.get("remakeStartTime")),
            "order": position, "story_ids": members, "count": len(members),
            "source_url": source, "reader_url": reader_url(stories[members[0]]["source_path"]) if members else "https://astr.pages.dev/#/zh_CN/menu",
            "status": "index_only", "tags": [operator] if operator else [],
        })
        safe_snapshot[gid] = {key: group.get(key) for key in ("id", "name", "entryType", "startTime", "remakeStartTime")}
        safe_snapshot[gid]["infoUnlockDatas"] = safe_rows
    parser = ComicParser()
    parser.feed(comic_html)
    for href, title in parser.items.items():
        gid = "comic:" + href.rsplit("/", 1)[-1]
        groups.append({"id": gid, "title": title, "category": "comic", "operator": None,
                       "date": None, "date_label": "日期待核验", "rerun_date": None,
                       "order": len(groups), "story_ids": [], "count": None,
                       "source_url": "https://comic.hypergryph.com" + href,
                       "reader_url": "https://comic.hypergryph.com" + href,
                       "status": "source_link", "tags": []})
    counts = collections.Counter(g["category"] for g in groups)
    stats = {"groups": len(groups), "game_groups": len(groups) - counts["comic"], "stories": len(stories),
             "categories": dict(counts), "unknown_dates": sum(g["date"] is None for g in groups),
             "excluded_future": len(excluded), "imported_official_bodies": 0}
    catalog = {"schema_version": 1, "title": "泰拉阅览室", "cutoff": cutoff, "locale": "zh_CN",
               "revision": revision, "source_url": source, "scope": "目录快照，非完整剧情正文；站外来源持续核对",
               "groups": groups, "stories": stories, "stats": stats}
    return catalog, safe_snapshot, {"excluded_future": excluded, "warnings": warnings}


def fetch_public(url):
    req = urllib.request.Request(url, headers={"User-Agent": "TerraReadingRoom/0.1 (metadata index)"})
    with urllib.request.urlopen(req, timeout=45) as response:
        return response.read()


def retain_removed_history(existing, previous, removed):
    result = dict(existing)
    for sid in removed:
        prior = result.get(sid, {})
        versions = dict(prior.get("versions", {}))
        versions[previous["revision"]] = previous["stories"][sid]
        result[sid] = {"id": sid, "versions": versions}
    return result


def snapshot_current():
    """Keep immutable, metadata-only snapshots even before the next Git commit."""
    if not (ROOT / "catalog/catalog.json").exists():
        return
    catalog = read_json(ROOT / "catalog/catalog.json")
    destination = ROOT / "raw/snapshots" / catalog["revision"]
    for source, filename in ((ROOT / "catalog/catalog.json", "catalog.json"),
                             (ROOT / "raw/catalog-snapshot.json", "game-index.json"),
                             (ROOT / "sources/manifest.json", "manifest.json")):
        target = destination / filename
        if source.exists() and not target.exists():
            write_json(target, read_json(source))


def sync(args):
    snapshot_current()
    if args.refresh:
        commit = json.loads(fetch_public(f"https://api.github.com/repos/{REPO}/commits/main"))
        revision = commit["sha"]
        prefix = f"https://raw.githubusercontent.com/{REPO}/{revision}/zh_CN/"
        review_bytes = fetch_public(prefix + "gamedata/excel/story_review_table.json")
        char_bytes = fetch_public(prefix + "chardict.json")
        comic_bytes = fetch_public("https://comic.hypergryph.com/terra-historicus/")
    else:
        if not args.review_file or not args.char_file or not args.revision:
            raise ValueError("请提供 --review-file、--char-file、--revision，或使用 --refresh")
        revision = args.revision
        review_bytes, char_bytes = Path(args.review_file).read_bytes(), Path(args.char_file).read_bytes()
        comic_bytes = Path(args.comic_file).read_bytes() if args.comic_file else b""
    catalog, snapshot, issues = compile_catalog(json.loads(review_bytes), json.loads(char_bytes), revision, args.cutoff, comic_bytes.decode("utf-8"))
    catalog = apply_regions(catalog, read_json(ROOT / "editorial/regions.json"))
    old = read_json(ROOT / "catalog/catalog.json") if (ROOT / "catalog/catalog.json").exists() else None
    old_ids, new_ids = set(old["stories"]) if old else set(), set(catalog["stories"])
    removed = sorted(old_ids - new_ids)
    # Retain historical records with an explicit inactive state when an upstream entry vanishes.
    if old and removed:
        history_path = ROOT / "catalog/retained-history.json"
        history = read_json(history_path) if history_path.exists() else {}
        write_json(history_path, retain_removed_history(history, old, removed))
    changes = {"new": sorted(new_ids-old_ids), "missing_upstream": removed,
               "changed": sorted(sid for sid in old_ids & new_ids if old["stories"][sid] != catalog["stories"][sid]) if old else []}
    write_json(ROOT / "catalog/catalog.json", catalog)
    write_json(ROOT / "raw/catalog-snapshot.json", snapshot)
    write_json(ROOT / "raw/character-names.json", json.loads(char_bytes))
    write_json(ROOT / "sources/manifest.json", {
        "cutoff": args.cutoff, "retrieved_at": dt.datetime.now(TZ).isoformat(timespec="seconds"),
        "upstream": REPO, "revision": revision,
        "files": [{"path": "zh_CN/gamedata/excel/story_review_table.json", "sha256": digest(review_bytes)},
                  {"path": "zh_CN/chardict.json", "sha256": digest(char_bytes)},
                  {"url": "https://comic.hypergryph.com/terra-historicus/", "sha256": digest(comic_bytes)}],
        "note": "仅保留标题、目录、日期与索引字段；未收集官方剧情正文或漫画图像。"})
    write_json(ROOT / "reports/sync.json", {**issues, "changes": changes, "stats": catalog["stats"]})
    write_reports(catalog, issues)
    snapshot_current()
    print(json.dumps(catalog["stats"], ensure_ascii=False))


def write_reports(catalog, issues):
    s = catalog["stats"]
    text = f"""# 收录状态 · {catalog['cutoff']}

这是可核验的**目录索引首版**，尚未收录官方剧情全文，不能称为全部官方故事全集。

- 上游版本：`{catalog['revision']}`。
- 游戏内条目组：{s['game_groups']}；剧情片段：{s['stories']}。
- 官方漫画门户已发现作品：{s['categories'].get('comic', 0)}；漫画集数尚未盘点。
- 日期待核验的条目组：{s['unknown_dates']}；晚于截止日排除：{s['excluded_future']}。
- 官方剧情正文导入：0；原创演示文本单独统计。

主线章节和密录的上游时间经常是 0 或 -1，本版保留“日期待核验”，不猜测首次发布日期。
上述数字的分母只是选定上游快照中的目录，不是整个 IP 的全部叙事材料。
活动分类暂保留上游类别，Intermezzi 与 SideStory 的细分待官方目录校对。

| 内容范围 | 当前状态 | 下一步 |
| --- | --- | --- |
| 主线、活动、故事集、干员密录 | 标题与篇章顺序已索引；正文待本地导入 | 核对历史日期与版本，导入后抽检 |
| 官方漫画 | 作品名与官方入口已索引 | 逐作品补集数、日期与连续性说明 |
| 干员档案、模组及其他角色文本 | 待盘点 | 建独立目录，不算作已收录正文 |
| 集成战略、生息演算等叙事 | 待盘点 | 保留事件条件、分支与结局关系 |
| 官方社交账号与网页活动 | 仅登记来源 | 核验账号白名单，按年份查漏 |
| 出版物、动画与 PV | 仅登记范围 | 建书目与媒介索引 |

原创样本仅用于检查旁白、说话人、选项、分支跳转及 EPUB 排版，不属于明日方舟官方剧情。
来源登记见 `sources/registry.json`；机器可读差异见 `reports/sync.json`。
"""
    (ROOT / "reports/收录状态.md").write_text(text, encoding="utf-8")


def split_attrs(value):
    """Split commas outside quoted attribute values, retaining unknown keys."""
    result, start, quote, escaped = [], 0, None, False
    for i, char in enumerate(value):
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == ",":
            result.append(value[start:i])
            start = i + 1
    result.append(value[start:])
    attrs = {}
    for item in result:
        if "=" in item:
            key, val = item.split("=", 1)
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            attrs[key.strip().casefold()] = val
    return attrs


def parse_script(text):
    result = []
    for i, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if line.startswith("[") and "]" in line:
            tag, content = line[1:].split("]", 1)
            if tag.casefold().startswith("name="):
                prop, attrs = "name", split_attrs(tag)
            elif "(" in tag and tag.endswith(")"):
                prop, raw = tag.split("(", 1)
                attrs = split_attrs(raw[:-1])
            else:
                prop, attrs = tag, {}
            if content.strip():
                attrs["content"] = content.strip()
        else:
            prop, attrs = "name", {"name": "", "content": line}
        result.append({"id": i, "prop": prop, "attributes": attrs})
    return {"storyList": result}


def normalize_story(payload, source_path=None, title=None, source_url=None):
    if isinstance(payload, str):
        payload = parse_script(payload)
    if isinstance(payload, list):
        payload = {"storyList": payload}
    if not isinstance(payload, dict):
        raise ValueError("正文应为 JSON 对象、ASTR 数组或文本脚本")
    if "nodes" in payload:
        story = dict(payload)
        if title:
            story["title"] = title
        validate_story(story)
        return story
    rows = payload.get("storyList")
    if not isinstance(rows, list) or not rows:
        raise ValueError("没有找到非空 storyList 或 nodes")
    source_path = source_path or payload.get("storyTxt") or payload.get("source_path")
    if not source_path:
        raise ValueError("请使用 --source-path 指定目录中的 storyTxt，或在 JSON 中提供 storyTxt")
    source_path = source_path.removeprefix("zh_CN/gamedata/story/").removesuffix(".json").removesuffix(".txt")
    story = {"schema_version": 1, "id": "cn:" + source_path.casefold(), "title": title or payload.get("storyName") or source_path,
             "source_path": source_path, "source_url": source_url or "", "origin": "user_import", "nodes": [], "warnings": []}
    known_effects = {"background", "image", "scene", "character", "charslot", "charer", "dialog", "blocker", "playmusic", "stopmusic", "playaudio", "stopaudio", "delay", "cameraeffect", "camerashake", "cameramove", "camerarotate", "curtain", "mask", "musicvolume", "soundvolume", "bgeffect", "imagecut", "characteraction", "characterfocus", "fadeout", "fadein", "focus", "video", "multiline", "cgitem", "showitem", "hideitem"}
    known_effects.update({"header", "playsound", "stopsound", "animtextclean", "gridbg", "largebg", "largebgtween", "imagetween", "backgroundtween", "avgdisplay", "theater", "charactercutin", "effect", "focusout", "focusparam", "verticalbg", "interlude", "hidecgitem", "stickertween", "stickerclear", "warp", "imagerotate", "imgeffect", "delau", "comment"})
    for offset, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"第 {offset+1} 个段落不是对象")
        prop = str(row.get("prop", "")).casefold()
        attrs = {str(k).casefold(): v for k, v in row.get("attributes", {}).items()}
        node = {"id": "l" + str(row.get("id", offset+1)), "kind": "directive", "command": prop, "attributes": attrs}
        if prop in {"name", "multiline"}:
            node.update(kind="dialogue" if attrs.get("name") else "narration", text=str(attrs.get("content", "")), speaker=str(attrs.get("name", "")))
            if not node["text"].strip():
                node["kind"] = "directive"
        elif prop in {"subtitle", "animtext", "sticker"}:
            node.update(kind="narration", text=str(attrs.get("text") or attrs.get("content") or ""))
        elif prop == "decision":
            labels = str(attrs.get("options", "")).split(";")
            values = str(attrs.get("values", "")).split(";")
            targets = row.get("targetLine", {})
            node.update(kind="choice", options=[])
            for idx, label in enumerate(labels):
                value = values[min(idx, len(values)-1)]
                target = targets.get("option" + value)
                target = canonical_target(target)
                node["options"].append({"label": label, "value": value, "target": target})
        elif prop in {"predicate", "label", "goto"}:
            node.update(kind="branch", text="分支条件：" + str(attrs.get("references") or attrs.get("label") or attrs.get("target") or "汇合／条件见原始记录"))
        elif prop not in known_effects:
            node["kind"] = "unknown"
            story["warnings"].append({"line": node["id"], "command": prop, "issue": "未识别指令已保留"})
        story["nodes"].append(node)
    # Resolve choices by predicate when the ASTR target map is absent.
    for idx, node in enumerate(story["nodes"]):
        if node["kind"] == "choice":
            for option in node["options"]:
                if option["target"] is None:
                    for candidate in story["nodes"][idx+1:]:
                        if candidate["kind"] == "choice":
                            break
                        refs = str(candidate.get("attributes", {}).get("references", "")).split(";")
                        if candidate.get("command") == "predicate" and option["value"] in refs:
                            option["target"] = candidate["id"]
                            break
                if option["target"] is None:
                    story["warnings"].append({"line": node["id"], "issue": "选项跳转待人工核对", "value": option["value"]})
    validate_story(story)
    return story


def canonical_target(value):
    if value is None or value == "":
        return None
    value = str(value)
    if re.fullmatch(r"(?:line|l)?\d+", value):
        return "l" + re.sub(r"^(?:line|l)", "", value)
    raise ValueError("无法识别的分支跳转编号：" + value)


def validate_story(story):
    if not isinstance(story.get("id"), str) or not story["id"] or not isinstance(story.get("title"), str):
        raise ValueError("正文缺少有效 id 或 title")
    nodes = story.get("nodes")
    if not isinstance(nodes, list) or not nodes or len(nodes) > 200000:
        raise ValueError("nodes 必须是非空数组，且不超过 200000 个段落")
    ids = set()
    for node in nodes:
        nid = node.get("id")
        if not isinstance(nid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", nid) or nid in ids:
            raise ValueError("段落 ID 缺失、重复或含无效字符")
        ids.add(nid)
        if node.get("kind") not in {"dialogue", "narration", "scene", "choice", "branch", "directive", "unknown"}:
            raise ValueError("未知段落类型")
        if node["kind"] == "choice" and not isinstance(node.get("options"), list):
            raise ValueError("选项应为数组")
    for node in nodes:
        for option in node.get("options", []):
            if option.get("target") is not None and option["target"] not in ids:
                raise ValueError("分支跳转目标不存在：" + str(option["target"]))
    return story


def import_body(args):
    file = Path(args.file)
    payload = read_json(file) if file.suffix.lower() == ".json" else file.read_text(encoding="utf-8-sig")
    story = normalize_story(payload, args.source_path, args.title, args.source_url)
    catalog = read_json(ROOT / "catalog/catalog.json")
    if story["id"] not in catalog["stories"]:
        raise ValueError("正文 ID 未匹配目录；请先核对 --source-path，或导入带目录元数据的原生格式")
    record = catalog["stories"][story["id"]]
    story["title"] = args.title or record["title"]
    story["source_url"] = args.source_url or record["source_url"]
    story["origin"] = "user_import"
    story["imported_at"] = dt.datetime.now(TZ).isoformat(timespec="seconds")
    filename = digest(story["id"].encode())[:24] + ".json"
    output = ROOT / "corpus/local" / filename
    write_json(output, story)
    print(f"已导入 {story['title']}：{len(story['nodes'])} 个段落，{len(story.get('warnings', []))} 项待核对；保存到 {output}")


def plain(value):
    # Remove display markup, never interpret imported HTML.
    text = re.sub(r"</?(?:b|i|u|color|size|strong|em)(?:=[^>]*)?>", "", str(value or ""), flags=re.I)
    return re.sub(r"<@[\w.]+>|</>", "", text)


def node_html(node):
    nid, kind = html.escape(node["id"], quote=True), node["kind"]
    content = html.escape(plain(node.get("text", "")))
    if kind == "dialogue":
        return f'<p id="{nid}" class="dialogue"><strong>{html.escape(plain(node.get("speaker", "")))}</strong><br/>{content}</p>'
    if kind in {"narration", "scene", "branch"}:
        tag = "aside" if kind == "branch" else "p"
        return f'<{tag} id="{nid}" class="{kind}">{content}</{tag}>'
    if kind == "choice":
        links = []
        for option in node["options"]:
            label = html.escape(plain(option.get("label", "")))
            links.append(f'<li><a href="#{html.escape(option["target"], quote=True)}">{label}</a></li>' if option.get("target") else f'<li>{label}（跳转待核对）</li>')
        return f'<section id="{nid}" class="choice"><p>选择一条分支：</p><ol>{"".join(links)}</ol><p>以下保留各条备选分支，分支条件在段落前标出。</p></section>'
    label = "未识别段落，待校对" if kind == "unknown" else "演出提示"
    return f'<aside id="{nid}" class="directive">{label}：{html.escape(str(node.get("command", "")))} {html.escape(json.dumps(node.get("attributes", {}), ensure_ascii=False))}</aside>'


EPUB_CSS = """body{font-family:serif;line-height:1.85;margin:5%;color:#242a27}h1,h2{line-height:1.45}a{color:#31564b}p{margin:1em 0}strong{font-family:sans-serif;font-size:.88em}.narration{color:#555}.scene,.branch{padding:.8em;border-left:2px solid #9b9c8c;background:#f1f1e9}.choice{border:1px solid #aaa;padding:1em}.directive{font-size:.75em;color:#666;margin:.7em 0;overflow-wrap:anywhere}.meta{font-family:sans-serif;font-size:.8em;color:#666}li{margin:.6em 0}img{max-width:100%}.cover{text-align:center;padding-top:15%}"""


class EpubSection(tuple):
    def __new__(cls, title, body, level=0):
        value = super().__new__(cls, (title, body))
        value.level = level
        return value


def nested_toc(entries):
    root, stack = [], []
    stack.append((-1, root))
    for label, href, level in entries:
        while len(stack) > 1 and stack[-1][0] >= level:
            stack.pop()
        node = {"label": label, "href": href, "children": []}
        stack[-1][1].append(node)
        stack.append((level, node["children"]))
    def render(nodes):
        return '<ol>' + ''.join(f'<li><a href="{href}">{html.escape(label)}</a>' + (render(children) if children else '') + '</li>' for label, href, children in ((n['label'], n['href'], n['children']) for n in nodes)) + '</ol>'
    return render(root)


def xhtml(title, body):
    return '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="zh-CN" lang="zh-CN"><head><title>' + html.escape(title) + '</title><link rel="stylesheet" type="text/css" href="style.css"/></head><body>' + body + '</body></html>'


def make_epub(output, title, sections, cutoff, identifier="terra-archive", source_url=""):
    """sections is [(title, XHTML body)]. No dependency or network needed."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    files = {"EPUB/style.css": EPUB_CSS}
    items = ['<item id="css" href="style.css" media-type="text/css"/>', '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>']
    spine, nav = [], []
    for i, section in enumerate(sections):
        section_title, body = section
        filename = f"section-{i:04d}.xhtml"
        files["EPUB/" + filename] = xhtml(section_title, body)
        items.append(f'<item id="s{i}" href="{filename}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="s{i}"/>')
        nav.append((section_title, filename, getattr(section, "level", 0)))
    files["EPUB/nav.xhtml"] = xhtml("目录", '<nav epub:type="toc" id="toc"><h1>目录</h1>' + nested_toc(nav) + '</nav>')
    unique_id = "urn:sha256:" + digest((identifier + cutoff).encode())
    # Stable timestamps make repeated builds of unchanged data reproducible.
    modified = cutoff + "T00:00:00Z"
    source_meta = f'<dc:source>{html.escape(source_url)}</dc:source>' if source_url else ""
    files["EPUB/package.opf"] = f'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="uid">{unique_id}</dc:identifier><dc:title>{html.escape(title)}</dc:title><dc:language>zh-CN</dc:language><dc:creator>泰拉阅览室 · 个人整理</dc:creator><dc:date>{cutoff}</dc:date><meta property="dcterms:modified">{modified}</meta>{source_meta}</metadata><manifest>{''.join(items)}</manifest><spine>{''.join(spine)}</spine></package>'''
    container = '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'
    files["META-INF/container.xml"] = container
    with zipfile.ZipFile(output, "w") as archive:
        entry = zipfile.ZipInfo("mimetype", date_time=(2026, 1, 1, 0, 0, 0))
        archive.writestr(entry, "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for name, body in sorted(files.items()):
            entry = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            archive.writestr(entry, body.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
    return check_epub(output)


def check_epub(path):
    with zipfile.ZipFile(path) as z:
        if z.namelist()[0] != "mimetype" or z.getinfo("mimetype").compress_type != zipfile.ZIP_STORED or z.read("mimetype") != b"application/epub+zip":
            raise ValueError("EPUB mimetype 错误")
        ids = {}
        for name in z.namelist():
            if name.endswith((".xhtml", ".opf", ".xml")):
                root = ET.fromstring(z.read(name))
                ids[name] = {n.attrib["id"] for n in root.iter() if "id" in n.attrib}
        from posixpath import dirname, normpath
        for name in ids:
            root = ET.fromstring(z.read(name))
            for node in root.iter():
                href = node.get("href")
                if href is None or urllib.parse.urlsplit(href).scheme:
                    continue
                target, _, anchor = href.partition("#")
                target = normpath(dirname(name) + "/" + target) if target else name
                if target not in z.namelist():
                    raise ValueError(f"EPUB 断链：{name} → {href}")
                if anchor and anchor not in ids.get(target, set()):
                    raise ValueError(f"EPUB 锚点不存在：{name} → {href}")
        return {"path": str(path), "files": len(z.namelist()), "structural_check": "passed", "epubcheck": "not_run"}


def load_bodies(include_local=False, include_provided=True):
    result = {}
    paths = list((ROOT / "corpus/demo").glob("*.json"))
    if include_provided and (ROOT / "corpus/provided/manifest.json").exists():
        manifest = read_json(ROOT / "corpus/provided/manifest.json")
        paths += [ROOT / "corpus/provided" / item["file"] for item in manifest["bodies"].values()]
    if include_local:
        paths += list((ROOT / "corpus/local").glob("*.json"))
    for path in paths:
        story = read_json(path)
        validate_story(story)
        result[story["id"]] = story
    return result


def time_html(record):
    times = record.get("chronology", {})
    event, release = times.get("event", {}), times.get("release", {})
    body = '<p class="meta">事件发生时间（泰拉历）：' + html.escape(event.get("label", "待考证")) + '</p>'
    body += '<p class="meta">国服开放时间' + ('（所属作品参考）' if release.get("scope") == "work_reference" else '') + '：' + html.escape(release.get("label", "待考证")) + '</p>'
    notes = [t["note"] for t in (event, release) if t.get("note")]
    if notes:
        body += '<p class="meta">' + html.escape(' '.join(notes)) + '</p>'
    for source in release.get("sources", []):
        body += f'<p class="meta">时间依据：<a href="{html.escape(source["url"], quote=True)}">{html.escape(source["title"])}</a></p>'
    return body


def reading_nodes(story):
    targets = {o.get("target") for n in story["nodes"] for o in n.get("options", [])}
    return [n for n in story["nodes"] if n["kind"] != "directive" or n["id"] in targets]


def display_title(group, title=None):
    title = group["title"] if title is None else title
    return f'{group["operator"]} · {title}' if group.get("category") == "record" and group.get("operator") else title


def book_sections(catalog, groups, bodies=None, *, offset=0, level=0):
    bodies = bodies or {}
    sections = [EpubSection("使用说明", '<h1>泰拉阅览室</h1><p>收录截止日期：' + catalog["cutoff"] + '</p><p>正文来自用户提供的本地导出，漫画保留官方入口。未收录正文的条目明确标注。事件时间与现实开放时间分列；字幕时间可能含插叙，作品开放时间不等于每一篇的解锁时间。分支条件与备选剧情保留，演出指令不混入正文。</p>')]
    for group in groups:
        group_title = display_title(group)
        body = f'<h1>{html.escape(group_title)}</h1><p class="meta">{CATEGORIES[group["category"]]} · {group["date"] or "日期待核验"}</p>'
        body += region_html(catalog, group)
        body += time_html(group)
        present = [sid for sid in group["story_ids"] if sid in bodies]
        body += f'<p class="meta">本卷正文：{len(present)}/{len(group["story_ids"])} 篇。</p>' if group["story_ids"] else ''
        directory_index = offset + len(sections)
        file_indices = {sid: directory_index + 1 + i for i, sid in enumerate(present)}
        if not group["story_ids"]:
            body += f'<p><a href="{html.escape(group["source_url"], quote=True)}">打开官方作品</a></p>'
        else:
            body += '<ol>'
            for sid in group["story_ids"]:
                item = catalog["stories"][sid]
                label = html.escape(display_title(group, (item["code"] + " " + item["title"] + " · " + item["part"]).strip()))
                if sid in bodies:
                    body += f'<li><a href="section-{file_indices[sid]:04d}.xhtml">{label}</a>{time_html(item)}</li>'
                else:
                    body += f'<li>{label}{time_html(item)}<p class="meta">正文未收录 · <a href="{html.escape(item["reader_url"], quote=True)}">前往原文阅读器</a></p></li>'
            body += '</ol>'
        sections.append(EpubSection(group_title, body, level))
        for sid in present:
            item, story = catalog["stories"][sid], bodies[sid]
            title = display_title(group, (item["code"] + " " + item["title"] + " · " + item["part"]).strip())
            source = story.get("provided_source", {})
            source_note = '用户提供的本地正文' + (' · ' + source["workbook"] + ' / ' + source["sheet"] if source else '')
            text = f'<h1>{html.escape(title)}</h1><p class="meta">{html.escape(group_title)}</p>' + time_html(item) + f'<p class="meta">{html.escape(source_note)}</p>'
            if source.get("recovery_note"):
                text += '<p class="meta">' + html.escape(source["recovery_note"]) + '</p>'
            text += ''.join(node_html(n) for n in reading_nodes(story))
            text += f'<p><a href="section-{directory_index:04d}.xhtml">返回作品目录</a></p>'
            sections.append(EpubSection(title, text, level+1))
    return sections


def region_html(catalog, group):
    names = {r["id"]: r["name"] for r in catalog.get("regions", [])}
    label = "、".join(names[i] for i in group.get("region_ids", [])) or "地区待考证"
    evidence = " · ".join(f'<a href="{html.escape(s["url"], quote=True)}">{html.escape(s["title"])}</a>' for s in group.get("region_evidence", []))
    return f'<p class="meta">作品主要舞台：{html.escape(label)}</p><p class="meta">{html.escape(group.get("region_note", ""))}</p>' + (f'<p class="meta">分类依据：{evidence}</p>' if evidence else "")


def region_sections(catalog, bodies=None):
    sections = [EpubSection("地区分类说明", '<h1>沿着泰拉，寻找故事</h1><p>' + html.escape(catalog["region_method"]["note"]) + '</p><p>本卷按国家与地区编排，作品正文只保存一份；多地区作品在其他关联地区提供跳转。城市入口链接到所属国家中的作品。无法确定主要舞台的作品列入地区待考证。事件时间与国服开放时间分别标注。</p>')]
    region_map = {r["id"]: r for r in catalog["regions"]}
    def primary(group):
        rid = next(iter(group.get("region_ids", [])), "unknown")
        while region_map.get(rid, {}).get("parent"):
            rid = region_map[rid]["parent"]
        return rid
    directory_indices, pending = {}, []
    for region in catalog["regions"] + [{"id": "unknown", "name": "地区待考证", "description": "尚未完成地点编目，不能据此认定为单一地区或多地区。"}]:
        groups = [g for g in catalog["groups"] if region_matches(g, region["id"], catalog["regions"])]
        if not groups:
            continue
        head_index = len(sections)
        sections.append(EpubSection(region["name"], f'<h1>{html.escape(region["name"])}</h1><p>{html.escape(region["description"])}</p><p>本地区关联 {len(groups)} 部作品。</p>'))
        related = []
        for group in groups:
            if primary(group) == region["id"]:
                directory_indices[group["id"]] = len(sections)
                sections.extend(book_sections(catalog, [group], bodies, offset=len(sections)-1, level=1)[1:])
            else:
                related.append(group)
        pending.append((head_index, related))
    for index, groups in pending:
        if groups:
            title, body = sections[index]
            body += '<h2>关联作品</h2><ol>' + ''.join(f'<li><a href="section-{directory_indices[g["id"]]:04d}.xhtml">{html.escape(display_title(g))}</a></li>' for g in groups) + '</ol>'
            sections[index] = EpubSection(title, body)
    return sections


def write_region_report(catalog):
    stats = catalog["region_stats"]
    lines = ["# 地区分类初编", "", f"编目复核日期：{catalog['region_method']['reviewed_at']}；内容快照截止：{catalog['cutoff']}。", "", catalog["region_method"]["note"], "",
             f"现有 {len(catalog['groups'])} 部作品：{stats['assigned']} 部已编入主要舞台，{stats['unknown']} 部地区待考证；{stats['multi']} 部已记录多个舞台。不是逐剧情片段的地点覆盖率。", "", "| 地区 | 作品数（含下属城市、地区内去重） |", "| --- | ---: |"]
    for region in catalog["regions"]:
        lines.append(f"| {region['name']} | {stats['counts'][region['id']]} |")
    lines += ["", "## 待考证条目", "", "| 类别 | 待编目作品数 |", "| --- | ---: |"]
    for key, name in CATEGORIES.items():
        lines.append(f"| {name} | {sum(g['category'] == key and not g['region_ids'] for g in catalog['groups'])} |")
    lines += ["", "编目源文件：`editorial/regions.json`。每项保存稳定 ID、预期标题、舞台标签、说明与来源链接。构建与同步会重新应用该文件；删除编目项会恢复待考证状态。", "", "本轮主要采用 PRTS 社区资料作为线索，不能称为官方确认。场地美术、角色籍贯、政治阵营不直接等同于实际剧情地点；故事集、密录和漫画需要后续逐篇核对。"]
    (ROOT / "reports/地区分类.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build(args):
    catalog = read_json(ROOT / "catalog/catalog.json")
    catalog = apply_regions(catalog, read_json(ROOT / "editorial/regions.json"))
    bodies = load_bodies(args.include_local)
    chronology_path = ROOT / "editorial/chronology.json"
    snapshot_path = ROOT / "raw/catalog-snapshot.json"
    catalog = apply_chronology(catalog, read_json(chronology_path) if chronology_path.exists() else {}, bodies,
                               read_json(snapshot_path) if snapshot_path.exists() else {})
    validate_catalog(catalog)
    write_json(ROOT / "catalog/catalog.json", catalog)
    write_region_report(catalog)
    out = ROOT / "dist/local-site" if args.include_local else SITE / "dist"
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "data/catalog.json", catalog)
    write_json(out / "data/demo.json", list(load_bodies(include_provided=False).values()))
    write_json(out / "data/sources.json", read_json(ROOT / "sources/registry.json"))
    write_json(out / "data/lists.json", read_json(ROOT / "reading-lists/collections.json"))
    provided = {sid: story for sid, story in bodies.items() if story.get("origin") == "user_provided_export" and sid in catalog["stories"]}
    body_index = {"version": 1, "source": "user_provided_exports", "count": len(provided), "items": {}}
    body_directory = out / "bodies"
    body_directory.mkdir(exist_ok=True)
    for sid, story in provided.items():
        payload = json.dumps(story, ensure_ascii=False, separators=(",", ":")).encode()
        fingerprint = digest(payload)
        filename = digest(sid.encode())[:24] + "-" + fingerprint[:12] + ".json"
        (body_directory / filename).write_bytes(payload)
        body_index["items"][sid] = {"url": "bodies/" + filename, "sha256": fingerprint, "nodes": len(story["nodes"])}
    expected_files = {Path(entry["url"]).name for entry in body_index["items"].values()}
    for path in body_directory.glob("*.json"):
        if path.name not in expected_files and re.fullmatch(r"[0-9a-f]{24}-[0-9a-f]{12}\.json", path.name):
            path.unlink()
    write_json(out / "data/bodies.json", body_index)
    write_json(out / "data/build.json", {"include_local": args.include_local, "provided_bodies": len(provided), "version": "0.3.0"})
    if args.include_local:
        write_json(out / "data/local-bodies.json", [b for b in bodies.values() if b.get("origin") == "user_import"])
    else:
        (out / "data/local-bodies.json").unlink(missing_ok=True)
    # Version every dependency so a new deployment cannot mix cached old code
    # with a new catalogue. Source files remain buildless and readable.
    for name in ("styles.css", "model.js"):
        shutil.copy2(SITE / name, out / name)
    model_version = digest((out / "model.js").read_bytes())[:12]
    epub_source = (SITE / "epub.js").read_text(encoding="utf-8").replace('"./model.js"', f'"./model.js?v={model_version}"')
    (out / "epub.js").write_text(epub_source, encoding="utf-8")
    epub_version = digest((out / "epub.js").read_bytes())[:12]
    app_source = (SITE / "app.js").read_text(encoding="utf-8").replace('"./model.js"', f'"./model.js?v={model_version}"').replace('"./epub.js"', f'"./epub.js?v={epub_version}"')
    for data_name in ("catalog", "demo", "sources", "lists", "build", "bodies", "local-bodies"):
        data_file = out / "data" / (data_name + ".json")
        if data_file.exists():
            version = digest(data_file.read_bytes())[:12]
            app_source = app_source.replace(f'"data/{data_name}.json"', f'"data/{data_name}.json?v={version}"')
    (out / "app.js").write_text(app_source, encoding="utf-8")
    index = (SITE / "index.html").read_text(encoding="utf-8").replace('href="styles.css"', 'href="styles.css?v=' + digest((out / "styles.css").read_bytes())[:12] + '"').replace('src="app.js"', 'src="app.js?v=' + digest((out / "app.js").read_bytes())[:12] + '"')
    (out / "index.html").write_text(index, encoding="utf-8")
    reports = []
    reports.append(make_epub(out / "downloads/泰拉阅览室-剧情目录.epub", "泰拉阅览室 · 剧情目录（不含原文）", book_sections(catalog, catalog["groups"]), catalog["cutoff"], "catalog-"+catalog["revision"], catalog["source_url"]))
    reports.append(make_epub(out / "downloads/泰拉阅览室-地区分类目录.epub", "泰拉阅览室 · 地区分类目录（不含原文）", region_sections(catalog), catalog["cutoff"], "regions-"+digest(json.dumps(catalog["region_stats"], sort_keys=True).encode()), catalog["source_url"]))
    if provided:
        sections = region_sections(catalog, bodies)
        reports.append(make_epub(out / "downloads/泰拉阅览室-地区剧情集.epub", "泰拉阅览室 · 地区剧情集", sections, catalog["cutoff"], "provided-regions-" + catalog["revision"], catalog["source_url"]))
        del sections
    demo = bodies[DEMO_ID]
    demo_sections = [("使用说明", '<h1>阅读与分支测试样本</h1><p>本卷为原创排版演示，不属于明日方舟官方剧情。</p>'), (demo["title"], '<h1>' + html.escape(demo["title"]) + '</h1><p class="meta">原创演示 · 非官方剧情</p>' + "".join(node_html(n) for n in demo["nodes"]))]
    reports.append(make_epub(out / "downloads/泰拉阅览室-原创阅读样本.epub", "泰拉阅览室 · 原创阅读样本", demo_sections, catalog["cutoff"], "demo-v1"))
    report = {"catalog_validation": "passed", "distribution_mode": "local_bodies" if args.include_local else "user_provided_bodies" if provided else "metadata_and_original_demo", "stats": catalog["stats"], "region_stats": catalog["region_stats"], "time_stats": catalog["time_stats"], "provided_bodies": len(provided), "epubs": reports}
    write_json(ROOT / "reports/build.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def validate_catalog(catalog):
    gids = [g["id"] for g in catalog["groups"]]
    if len(gids) != len(set(gids)):
        raise ValueError("条目组 ID 重复")
    for group in catalog["groups"]:
        for sid in group["story_ids"]:
            if sid not in catalog["stories"]:
                raise ValueError("目录引用不存在的篇目：" + sid)
        if group["date"] and group["date"] > catalog["cutoff"]:
            raise ValueError("包含截止日之后的内容")
    for sid, story in catalog["stories"].items():
        if sid != story["id"] or not story["title"]:
            raise ValueError("篇目 ID 或标题异常")
    return True


def export(args):
    catalog = apply_regions(read_json(ROOT / "catalog/catalog.json"), read_json(ROOT / "editorial/regions.json"))
    bodies = load_bodies(True)
    catalog = apply_chronology(catalog, read_json(ROOT / "editorial/chronology.json"), bodies, read_json(ROOT / "raw/catalog-snapshot.json"))
    if args.region:
        if args.region not in {r["id"] for r in catalog["regions"]} | {"unknown", "multi", "all"}:
            raise ValueError("未知地区编号：" + args.region)
        groups = [g for g in catalog["groups"] if region_matches(g, args.region, catalog["regions"])]
    else:
        groups = [g for g in catalog["groups"] if g["id"] in args.group]
        if len(groups) != len(set(args.group)):
            raise ValueError("书单中有未找到的条目组")
    if not groups:
        raise ValueError("所选范围没有已编目作品")
    sections = region_sections(catalog, bodies) if args.region == "all" else book_sections(catalog, groups, bodies)
    report = make_epub(args.output, args.title, sections, catalog["cutoff"], args.region or "-".join(args.group), catalog["source_url"])
    print(json.dumps(report, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="泰拉阅览室：目录同步、个人正文导入、网站与 EPUB 生成")
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("sync", help="同步目录元数据，不下载官方剧情正文")
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--review-file")
    p.add_argument("--char-file")
    p.add_argument("--comic-file")
    p.add_argument("--revision")
    p.add_argument("--cutoff", default="2026-10-29")
    p.set_defaults(func=sync)
    p = commands.add_parser("import", help="导入本地 ASTR JSON／剧情脚本")
    p.add_argument("file")
    p.add_argument("--source-path")
    p.add_argument("--title")
    p.add_argument("--source-url")
    p.set_defaults(func=import_body)
    p = commands.add_parser("build", help="生成网站、目录 EPUB 与原创样本 EPUB")
    p.add_argument("--include-local", action="store_true", help="仅供本地构建，将个人导入正文复制到本地网站")
    p.set_defaults(func=build)
    p = commands.add_parser("export", help="将指定条目组与已导入正文导出为 EPUB")
    selection = p.add_mutually_exclusive_group(required=True)
    selection.add_argument("--group", action="append")
    selection.add_argument("--region", help="地区 ID，例如 yan、lungmen、victoria；也支持 multi、unknown")
    p.add_argument("--title", default="泰拉阅览室 · 我的书单")
    p.add_argument("--output", required=True)
    p.set_defaults(func=export)
    p = commands.add_parser("check", help="检查 EPUB 的 XML、资源与内部锚点")
    p.add_argument("file")
    p.set_defaults(func=lambda a: print(json.dumps(check_epub(a.file), ensure_ascii=False)))
    args = parser.parse_args()
    try:
        args.func(args)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print("错误：" + str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
