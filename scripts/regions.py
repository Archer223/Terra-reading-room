"""Curated work-level settings. Never derive a location from an operator's origin."""
from __future__ import annotations

import copy
import re


def region_matches(group, region_id, regions):
    ids = group.get("region_ids", [])
    if region_id == "all":
        return True
    if region_id == "unknown":
        return not ids
    if region_id == "multi":
        return len(ids) > 1
    by_id = {r["id"]: r for r in regions}
    if region_id not in by_id:
        return False
    for assigned in ids:
        visited = set()
        while assigned and assigned not in visited:
            if assigned == region_id:
                return True
            visited.add(assigned)
            assigned = by_id.get(assigned, {}).get("parent")
    return False


def apply_regions(catalog, config):
    """Return a fresh enriched catalogue; reject stale or unsupported assignments."""
    result = copy.deepcopy(catalog)
    regions = config["regions"]
    by_id = {r["id"]: r for r in regions}
    if len(by_id) != len(regions) or any(not re.fullmatch(r"[a-z][a-z0-9_]*", x) or x in {"all", "multi", "unknown"} for x in by_id):
        raise ValueError("地区 ID 重复或无效")
    for region in regions:
        current, seen = region, set()
        while current:
            if current["id"] in seen:
                raise ValueError("地区层级存在循环")
            seen.add(current["id"])
            parent = current.get("parent")
            if parent and parent not in by_id:
                raise ValueError("地区父级不存在：" + parent)
            current = by_id.get(parent)
    groups = {g["id"]: g for g in result["groups"]}
    # Rebuild derived fields each time, so deleting an editorial entry clears it.
    for group in groups.values():
        group.update(region_ids=[], region_status="unverified", region_scope="work",
                     region_note="尚未核对作品的主要舞台；不按干员出身或阵营推定。", region_evidence=[])
    for gid, assignment in config["assignments"].items():
        if gid not in groups or groups[gid]["title"] != assignment["title"]:
            raise ValueError("地区编目与目录 ID／标题不匹配：" + gid)
        ids = assignment["regions"]
        if not ids or len(ids) != len(set(ids)) or any(r not in by_id for r in ids):
            raise ValueError("地区编目包含空白、重复或不存在的地区：" + gid)
        evidence = assignment.get("evidence", [])
        if not assignment.get("note") or not evidence or any(not e.get("title") or not re.match(r"^https?://", e.get("url", "")) for e in evidence):
            raise ValueError("地区编目缺少说明或可追溯来源：" + gid)
        groups[gid].update(region_ids=ids[:], region_status="assigned",
                           region_note=assignment["note"], region_evidence=copy.deepcopy(evidence))
    result["regions"] = copy.deepcopy(regions)
    result["region_method"] = {"reviewed_at": config["reviewed_at"], "note": config["method"]}
    counts = {r["id"]: sum(region_matches(g, r["id"], regions) for g in groups.values()) for r in regions}
    assigned = sum(bool(g["region_ids"]) for g in groups.values())
    result["region_stats"] = {"assigned": assigned, "unknown": len(groups)-assigned,
                              "multi": sum(len(g["region_ids"]) > 1 for g in groups.values()),
                              "counts": counts}
    return result
