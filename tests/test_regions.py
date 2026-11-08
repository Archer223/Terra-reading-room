import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.regions import apply_regions, region_matches
from scripts.archive import ROOT, region_sections, make_epub


class RegionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / "editorial/regions.json").read_text())
        cls.catalog = apply_regions(json.loads((ROOT / "catalog/catalog.json").read_text()), cls.config)

    def group(self, gid):
        return next(g for g in self.catalog["groups"] if g["id"] == gid)

    def test_cities_are_included_in_parent_without_double_counting(self):
        self.assertTrue(region_matches(self.group("act5d0"), "yan", self.catalog["regions"]))
        self.assertTrue(region_matches(self.group("act32side"), "bolivar", self.catalog["regions"]))
        self.assertFalse(region_matches(self.group("act32side"), "columbia", self.catalog["regions"]))
        expected = len({g["id"] for g in self.catalog["groups"] if region_matches(g, "yan", self.catalog["regions"])})
        self.assertEqual(self.catalog["region_stats"]["counts"]["yan"], expected)

    def test_actual_setting_is_not_inferred_from_cast(self):
        self.assertEqual(self.group("act26side")["region_ids"], ["iberia"])
        self.assertEqual(self.group("act50side")["region_ids"], ["special"])
        records = [g for g in self.catalog["groups"] if g["category"] == "record"]
        self.assertTrue(all(g["region_status"] == "unverified" for g in records))

    def test_multi_region_and_pending_are_distinct(self):
        self.assertTrue(region_matches(self.group("act18d0"), "multi", self.catalog["regions"]))
        pending = next(g for g in self.catalog["groups"] if not g["region_ids"])
        self.assertTrue(region_matches(pending, "unknown", self.catalog["regions"]))
        self.assertFalse(region_matches(pending, "multi", self.catalog["regions"]))
        self.assertEqual(self.catalog["region_stats"]["assigned"] + self.catalog["region_stats"]["unknown"], len(self.catalog["groups"]))

    def test_work_labels_do_not_claim_each_story_setting(self):
        sid = self.group("act18d0")["story_ids"][0]
        self.assertNotIn("region_ids", self.catalog["stories"][sid])

    def test_removed_editorial_assignment_clears_derived_label(self):
        config = copy.deepcopy(self.config)
        del config["assignments"]["act5d0"]
        result = apply_regions(self.catalog, config)
        group = next(g for g in result["groups"] if g["id"] == "act5d0")
        self.assertEqual(group["region_ids"], [])

    def test_invalid_or_stale_editorial_evidence_fails_loudly(self):
        for field, value in [("title", "标题已改变"), ("regions", ["missing"]), ("evidence", [])]:
            with self.subTest(field=field):
                config = copy.deepcopy(self.config)
                config["assignments"]["act5d0"][field] = value
                with self.assertRaises(ValueError):
                    apply_regions(self.catalog, config)
        config = copy.deepcopy(self.config)
        config["regions"][0]["parent"] = "lungmen"
        with self.assertRaisesRegex(ValueError, "循环"):
            apply_regions(self.catalog, config)

    def test_region_ebook_preserves_sources_and_pending_section(self):
        sections = region_sections(self.catalog)
        self.assertIn("地区待考证", [title for title, _ in sections])
        self.assertTrue(any("分类依据" in body and "prts.wiki" in body for _, body in sections))
        with tempfile.TemporaryDirectory() as folder:
            result = make_epub(Path(folder) / "regions.epub", "地区目录测试", sections, self.catalog["cutoff"])
            self.assertEqual(result["structural_check"], "passed")
