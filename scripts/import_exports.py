#!/usr/bin/env python3
"""Read user-supplied XLSX exports and reconcile their text with local scripts.

No network or subprocess access. The user's matching ASTR parser is imported as
a module (its command-line updater is never executed). The source XLSX files
remain unchanged. Raw scripts retain branches/media commands not shown in XLSX.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import hashlib
import importlib.util
import io
import json
import re
import sys
from pathlib import Path

from openpyxl import load_workbook

try:
    from .archive import ROOT, compile_catalog, normalize_story, write_json, read_json, digest, snapshot_current
    from .regions import apply_regions
except ImportError:
    from archive import ROOT, compile_catalog, normalize_story, write_json, read_json, digest, snapshot_current
    from regions import apply_regions


def read_menus(path):
    workbook = load_workbook(path, read_only=True, data_only=False)
    if "Menu" not in workbook.sheetnames:
        workbook.close()
        raise ValueError("缺少 Menu 目录：" + path.name)
    entries = []
    for row in workbook["Menu"].iter_rows(min_row=4, values_only=True):
        if len(row) < 4 or not row[3]:
            continue
        stem = str(row[3])
        actual = stem if stem in workbook.sheetnames else stem[:31] if stem[:31] in workbook.sheetnames else None
        entries.append({"sheet": stem, "actual_sheet": actual, "title": row[1], "part": row[2]})
    return workbook, entries


def reconcile_sheet(sheet, ast_rows):
    """Every exported text/option cell must be present in the local source AST."""
    by_id = {r["id"]: r for r in ast_rows}
    checked, recovered = 0, 0
    for row in sheet.iter_rows(values_only=True):
        if len(row) < 3 or not isinstance(row[0], int) or row[2] is None:
            continue
        index, label, text = row[:3]
        label, text = str(label or ""), str(text)
        if label == "----" or label.startswith("--"):
            continue
        if index not in by_id:
            raise ValueError(f"导出行号 {index} 不在原始脚本中")
        record = by_id[index]
        attrs = record.get("attributes", {})
        if label.startswith("Option_"):
            expected = str(attrs.get("options", "")).split(";")
        else:
            expected = [str(attrs.get(k, "")) for k in ("content", "text")]
        if not any(text == candidate or text.strip() == candidate.strip() for candidate in expected):
            if len(text) == 32767 and any(candidate.startswith(text) for candidate in expected):
                recovered += 1
            else:
                raise ValueError(f"导出内容与原始脚本不一致：行 {index}")
        checked += 1
    return {"checked_cells": checked, "excel_truncations_recovered": recovered}


def load_parser(folder):
    # Importing jsonconvert does not run its __main__ updater or Git commands.
    sys.path.insert(0, str(folder))
    spec = importlib.util.spec_from_file_location("user_astr_jsonconvert", folder / "jsonconvert.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.reader


def run(args):
    exports, data, parser_dir = Path(args.exports), Path(args.data), Path(args.parser)
    table_path = data / "zh_CN/gamedata/excel/story_review_table.json"
    table = read_json(table_path)
    characters = read_json(data / "zh_CN/gamedata/excel/character_table.json")
    old = read_json(ROOT / "catalog/catalog.json")
    source_hash = digest(table_path.read_bytes())
    catalog, snapshot, issues = compile_catalog(table, characters, "user-sha256:" + source_hash, args.cutoff, local_source=True)
    comics = [g for g in old["groups"] if g["category"] == "comic"]
    catalog["groups"].extend(comics)
    catalog["stats"].update(groups=len(catalog["groups"]), unknown_dates=sum(g["date"] is None for g in catalog["groups"]))
    catalog["stats"]["categories"]["comic"] = len(comics)
    catalog["scope"] = "用户提供的本地 Excel 与原始脚本；已匹配正文可阅读，漫画保留官方入口"
    catalog["provenance"] = {"kind": "user_provided_exports", "review_table_sha256": source_hash,
                             "previous_catalog_revision": old["revision"], "cutoff": args.cutoff}
    catalog = apply_regions(catalog, read_json(ROOT / "editorial/regions.json"))
    by_stem = collections.defaultdict(list)
    for sid, record in catalog["stories"].items():
        by_stem[Path(record["source_path"]).name].append(sid)
    raw_reader = load_parser(parser_dir)
    destination = ROOT / "corpus/provided"
    destination.mkdir(parents=True, exist_ok=True)
    result = {"source": "user_provided_exports", "cutoff": args.cutoff, "workbooks": [], "bodies": {},
              "errors": [], "excluded": [], "recovered_sheets": [], "checked_cells": 0, "excel_truncations_recovered": 0,
              "parser_sha256": digest((parser_dir / "jsonconvert.py").read_bytes())}
    kinds, commands = collections.Counter(), collections.Counter()
    paths = sorted(exports.rglob("*.xlsx"))
    for number, file in enumerate(paths, 1):
        relative = str(file.relative_to(exports))
        workbook, entries = read_menus(file)
        fingerprint = digest(file.read_bytes())
        file_record = {"file": relative, "sha256": fingerprint, "entries": len(entries), "imported": 0}
        print(f"[{number}/{len(paths)}] {relative}：{len(entries)} 篇", flush=True)
        for entry in entries:
            stem = entry["sheet"]
            matches = by_stem.get(stem, [])
            if len(matches) != 1:
                result["errors"].append({"file": relative, "sheet": stem, "issue": "目录未匹配或存在歧义", "matches": len(matches)})
                continue
            sid = matches[0]
            record = catalog["stories"][sid]
            source = data / "zh_CN/gamedata/story" / (record["source_path"] + ".txt")
            try:
                raw = source.read_text(encoding="utf-8-sig")
                messages = io.StringIO()
                with contextlib.redirect_stdout(messages):
                    parsed = raw_reader(raw)
                if entry["title"] and str(entry["title"]) != record["title"]:
                    raise ValueError("目录标题与原始数据不一致")
                recovery = None
                if entry["actual_sheet"]:
                    try:
                        checks = reconcile_sheet(workbook[entry["actual_sheet"]], parsed["storyList"])
                        if entry["actual_sheet"] != stem:
                            recovery = "Excel 工作表名被截断；已按正文逐行核对原始脚本"
                    except ValueError:
                        if entry["actual_sheet"] == stem:
                            raise
                        checks = {"checked_cells": 0, "excel_truncations_recovered": 0}
                        recovery = "长名称变体的工作表缺失或被合并；按 Excel 目录从用户提供的原始脚本恢复"
                else:
                    checks = {"checked_cells": 0, "excel_truncations_recovered": 0}
                    recovery = "Excel 目录中的工作表缺失；从用户提供的原始脚本恢复"
                story = normalize_story(parsed, record["source_path"], record["title"], record["source_url"])
                story["origin"] = "user_provided_export"
                story["provided_source"] = {"workbook": relative, "sheet": stem, "workbook_sha256": fingerprint,
                                            "raw_sha256": digest(source.read_bytes())}
                if recovery:
                    story["provided_source"]["recovery_note"] = recovery
                    result["recovered_sheets"].append({"file": relative, "sheet": stem, "id": sid, "note": recovery})
                if not parsed.get("OPTIONTRACE", True):
                    story["warnings"].append({"issue": "原导出解析器未能完全追踪分支，已保留条件与待核对标记"})
                if sid in result["bodies"]:
                    # Multiple workbook references do not duplicate a story.
                    result["bodies"][sid].setdefault("additional_sources", []).append(story["provided_source"])
                    continue
                name = digest(sid.encode())[:24] + ".json"
                encoded = json.dumps(story, ensure_ascii=False, separators=(",", ":")).encode()
                (destination / name).write_bytes(encoded)
                result["bodies"][sid] = {"file": name, "sha256": digest(encoded), "nodes": len(story["nodes"]),
                                         "warnings": len(story["warnings"]), "source": story["provided_source"]}
                record["status"] = "body_available"
                result["checked_cells"] += checks["checked_cells"]
                result["excel_truncations_recovered"] += checks["excel_truncations_recovered"]
                kinds.update(n["kind"] for n in story["nodes"])
                commands.update(n.get("command", "") for n in story["nodes"])
                file_record["imported"] += 1
            except Exception as error:
                result["errors"].append({"file": relative, "sheet": stem, "id": sid, "issue": str(error)[:300]})
        workbook.close()
        result["workbooks"].append(file_record)
    available = set(result["bodies"])
    for group in catalog["groups"]:
        group["available_count"] = sum(sid in available for sid in group["story_ids"])
        if group["story_ids"] and group["available_count"] == len(group["story_ids"]):
            group["status"] = "body_available"
    catalog["stats"]["provided_bodies"] = len(available)
    catalog["stats"]["imported_official_bodies"] = len(available)
    result["missing_story_ids"] = sorted(set(catalog["stories"]) - available)
    result["node_kinds"], result["commands"] = dict(kinds), dict(commands)
    result["summary"] = {"workbooks": len(paths), "stories": len(available), "catalog_stories": len(catalog["stories"]),
                         "missing": len(result["missing_story_ids"]), "errors": len(result["errors"]),
                         "checked_cells": result["checked_cells"]}
    # Keep a durable report even if some files require a targeted correction.
    write_json(ROOT / "reports/body-import.json", result)
    if result["errors"]:
        print(json.dumps(result["summary"], ensure_ascii=False))
        raise ValueError("部分正文未通过核对，未替换目录；详见 reports/body-import.json")
    snapshot_current()
    write_json(ROOT / "catalog/catalog.json", catalog)
    write_json(ROOT / "raw/catalog-snapshot.json", snapshot)
    write_json(destination / "manifest.json", {k: v for k, v in result.items() if k not in {"commands", "node_kinds"}})
    print(json.dumps(result["summary"], ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exports", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--parser", required=True)
    parser.add_argument("--cutoff", default="2026-11-03")
    arguments = parser.parse_args()
    try:
        run(arguments)
    except (OSError, ValueError, KeyError) as error:
        print("导入未完成：" + str(error), file=sys.stderr)
        raise SystemExit(1)
