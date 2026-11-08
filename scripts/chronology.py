"""Keep story-world time and real-world CN availability separate."""
from __future__ import annotations

import copy
import datetime as dt
import re
from zoneinfo import ZoneInfo


def caption_markers(story):
    markers, seen = [], set()
    # Only on-screen captions, never dates mentioned in dialogue or inferred
    # from a character's age. Captions may themselves describe a flashback.
    pattern = re.compile(r"(?<!\d)(?:10\d\d|11\d\d)(?:年(?:\d{1,2}月(?:\d{1,2}日)?)?(?:春|夏|秋|冬)?|[./-]\d{1,2}[./-]\d{1,2})")
    for node in story.get("nodes", []):
        if node.get("command") not in {"subtitle", "sticker"}:
            continue
        text = re.sub(r"<[^>]*>", "", node.get("text", ""))
        for match in pattern.finditer(text):
            if match[0] not in seen:
                markers.append({"label": match[0], "node": node["id"]})
                seen.add(match[0])
    return markers


def apply_chronology(catalog, config=None, bodies=None, snapshot=None):
    config, bodies, snapshot = config or {}, bodies or {}, snapshot or {}
    result = copy.deepcopy(catalog)
    corrections = config.get("groups", {})
    known_groups = {g["id"]: g for g in result["groups"]}
    for gid, entry in corrections.items():
        if gid not in known_groups or entry["title"] != known_groups[gid]["title"]:
            raise ValueError("时间编目与目录 ID／标题不匹配：" + gid)
    for group in result["groups"]:
        correction = corrections.get(group["id"], {})
        event = correction.get("event", {"label": "待考证", "status": "unverified", "note": "尚未确认作品主线及插叙的统一时间范围。", "sources": []})
        if group["category"] == "comic":
            release = {"label": "不适用（官方漫画，发布日期待考证）", "status": "not_applicable", "sources": []}
        elif correction.get("release"):
            release = correction["release"]
        elif group.get("date"):
            stamp = snapshot.get(group["id"], {}).get("startTime")
            label = dt.datetime.fromtimestamp(stamp, ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M") if stamp and stamp > 0 else group["date"]
            release = {"label": label + "（上游记录，待公告复核）", "status": "upstream", "scope": "work", "sources": [{"title": "本地目录 startTime 字段", "url": group["source_url"]}]}
        else:
            release = {"label": "待考证", "status": "unverified", "scope": "work", "note": "目录未提供可靠首次开放时间；未采用回顾入口上线时间替代。", "sources": []}
        group["chronology"] = {"event": event, "release": release}
        if release.get("date"):
            dt.date.fromisoformat(release["date"])
            group.setdefault("upstream_date", group.get("date"))
            group["date"] = release["date"]
            group["date_label"] = "国服首次开放（公告核对）"
        for sid in group["story_ids"]:
            record = result["stories"][sid]
            markers = caption_markers(bodies.get(sid, {}))
            record["chronology"] = {
                "event": {"label": "篇内时间标记：" + "、".join(m["label"] for m in markers) + "（可能含插叙）" if markers else "待考证",
                          "status": "caption_reference" if markers else "unverified", "markers": markers,
                          "note": "时间标记来自本篇画面字幕，不能直接等同于全部事件的发生日期。" if markers else "本篇事件发生时间尚未逐场景考证。"},
                "release": {"label": release["label"], "status": "work_reference" if release["status"] not in {"unverified", "not_applicable"} else release["status"],
                            "scope": "work_reference", "note": "所属作品首次开放时间；本篇分阶段解锁时间待核对。", "sources": release.get("sources", [])},
            }
    result["stats"]["unknown_dates"] = sum(not g.get("date") for g in result["groups"])
    result["time_stats"] = {
        "work_release_with_reference": sum(g["chronology"]["release"]["status"] in {"upstream", "confirmed"} for g in result["groups"]),
        "stories_with_caption_markers": sum(s["chronology"]["event"]["status"] == "caption_reference" for s in result["stories"].values()),
        "stories_event_unverified": sum(s["chronology"]["event"]["status"] == "unverified" for s in result["stories"].values()),
    }
    return result
