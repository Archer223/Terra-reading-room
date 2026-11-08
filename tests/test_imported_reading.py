import copy
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.archive import ROOT, normalize_story, make_epub, region_sections, reading_nodes, EpubSection
from scripts.chronology import apply_chronology, caption_markers
from scripts.import_exports import reconcile_sheet


class FakeSheet:
    def __init__(self, rows): self.rows = rows
    def iter_rows(self, **kwargs): return iter(self.rows)


class ImportedReadingTests(unittest.TestCase):
    def test_astr_line_prefix_targets_keep_actual_branch_links(self):
        value = {"storyList": [
            {"id": 0, "prop": "Decision", "attributes": {"options": "甲;乙", "values": "1;2"}, "targetLine": {"option1": "line1", "option2": "line3"}},
            {"id": 1, "prop": "Predicate", "attributes": {"references": "1"}},
            {"id": 2, "prop": "Name", "attributes": {"content": "原创分支甲"}},
            {"id": 3, "prop": "Predicate", "attributes": {"references": "2"}},
        ]}
        story = normalize_story(value, "test/branches")
        self.assertEqual([o["target"] for o in story["nodes"][0]["options"]], ["l1", "l3"])

    def test_multiline_and_sticker_text_are_readable_not_effect_metadata(self):
        story = normalize_story({"storyList": [
            {"id": 0, "prop": "multiline", "attributes": {"name": "编目员", "content": "原创连续文字"}},
            {"id": 1, "prop": "sticker", "attributes": {"text": "原创字幕"}},
            {"id": 2, "prop": "playsound", "attributes": {"key": "demo"}},
        ]}, "test/multiline")
        self.assertEqual([n["text"] for n in reading_nodes(story)], ["原创连续文字", "原创字幕"])
        self.assertEqual(len(story["nodes"]), 3)

    def test_xlsx_reconciliation_detects_wrong_body_and_recovers_excel_cell_limit(self):
        rows = [{"id": 4, "prop": "name", "attributes": {"content": "原创测试"}}]
        self.assertEqual(reconcile_sheet(FakeSheet([(4, "编目员", "原创测试")]), rows)["checked_cells"], 1)
        with self.assertRaisesRegex(ValueError, "不一致"):
            reconcile_sheet(FakeSheet([(4, "编目员", "错误的文件")]), rows)
        value = "甲" * 32768
        result = reconcile_sheet(FakeSheet([(4, None, value[:32767])]), [{"id": 4, "attributes": {"content": value}}])
        self.assertEqual(result["excel_truncations_recovered"], 1)

    def test_dialogue_dates_are_not_promoted_to_event_dates(self):
        story = {"nodes": [
            {"id": "l1", "command": "name", "text": "回想1097年1月1日"},
            {"id": "l2", "command": "sticker", "text": "<b>1098年夏</b>"},
        ]}
        self.assertEqual(caption_markers(story), [{"label": "1098年夏", "node": "l2"}])

    def test_release_reference_remains_distinct_from_single_story_unlock(self):
        catalog = {"groups": [{"id": "g", "title": "原创作品", "date": "2020-01-01", "category": "event", "source_url": "https://example.com", "story_ids": ["s"]}], "stories": {"s": {"id": "s"}}, "stats": {}}
        result = apply_chronology(catalog)
        self.assertEqual(result["stories"]["s"]["chronology"]["event"]["status"], "unverified")
        release = result["stories"]["s"]["chronology"]["release"]
        self.assertEqual(release["scope"], "work_reference")
        self.assertIn("分阶段", release["note"])

    def test_region_ebook_contains_each_body_once_and_related_region_links_work(self):
        original = json.loads((ROOT / "catalog/catalog.json").read_text())
        group = copy.deepcopy(next(g for g in original["groups"] if g["id"] == "act18d0"))
        sid = group["story_ids"][0]
        group["story_ids"] = [sid]
        catalog = {**original, "groups": [group], "stories": {sid: original["stories"][sid]}}
        bodies = {sid: {"id": sid, "title": "原创测试", "nodes": [{"id": "l1", "kind": "narration", "text": "原创正文仅出现一次"}]}}
        sections = region_sections(catalog, bodies)
        self.assertEqual(sum(body.count("原创正文仅出现一次") for _, body in sections), 1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "reading.epub"
            self.assertEqual(make_epub(path, "测试", sections, catalog["cutoff"])["structural_check"], "passed")
            with zipfile.ZipFile(path) as z:
                nav = z.read("EPUB/nav.xhtml").decode()
                self.assertGreater(nav.count("<ol>"), 1)


if __name__ == "__main__": unittest.main()
