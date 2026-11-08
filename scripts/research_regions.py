#!/usr/bin/env python3
"""Read public location metadata only; never collect story bodies or images."""
import argparse
import concurrent.futures
import html
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def research(group):
    title = group["title"]
    url = "https://prts.wiki/w/" + urllib.parse.quote(title, safe="")
    record = {"group_id": group["id"], "title": title, "url": url, "location_fields": []}
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "TerraReadingRoom/0.2 (location metadata only)"})
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(6_000_000).decode("utf-8", errors="replace")
        raw = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", raw, flags=re.S | re.I)
        text = re.sub(r"</?(?:br|p|div|td|th|tr|li|h[1-6]|section)\b[^>]*>", "\n", raw, flags=re.I)
        text = html.unescape(re.sub(r"<[^>]*>", "", text))
        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
        fields = []
        for i, line in enumerate(lines):
            if "作战场地" not in line:
                continue
            value = line[line.index("作战场地"):]
            if value.endswith(("：", ":")) and i + 1 < len(lines):
                value += lines[i+1]
            value = re.split(r"[①②③④]", value)[0].strip()
            if len(value) > 100:
                value = value[:100]
            if value not in fields:
                fields.append(value)
        record["location_fields"] = fields[:3]
        record["status"] = "metadata_found" if fields else "manual_review_needed"
    except Exception as exc:
        record.update(status="fetch_failed", error=type(exc).__name__ + ": " + str(exc)[:100])
    time.sleep(0.35)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="reports/region-location-research.json")
    parser.add_argument("--category", default="main,event,short")
    args = parser.parse_args()
    catalog = json.loads((ROOT / "catalog/catalog.json").read_text(encoding="utf-8"))
    categories = set(args.category.split(","))
    groups = [g for g in catalog["groups"] if g["category"] in categories]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for row in pool.map(research, groups):
            results.append(row)
            print(row["group_id"], row["title"], " | ".join(row["location_fields"]) or row["status"], flush=True)
    target = ROOT / args.output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"note": "PRTS 玩家整理的作战场地元数据，仅作作品主舞台归类线索，非逐段地点核对。", "items": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
