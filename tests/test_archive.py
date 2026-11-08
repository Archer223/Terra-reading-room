import copy
import tempfile
import unittest
import zipfile
from pathlib import Path
from scripts.archive import compile_catalog, normalize_story, parse_script, make_epub, check_epub, node_html, validate_catalog, retain_removed_history


class CatalogTests(unittest.TestCase):
    def make_group(self, date, path="obt/test/story", category="ACTIVITY"):
        return {"name":"测试篇目", "entryType":category, "startTime":date,
                "infoUnlockDatas":[{"storyTxt":path,"storyName":"一段路","storySort":1,"storyCode":"T-1"}]}

    def test_unknown_dates_are_not_invented_and_future_is_excluded(self):
        review={"unknown":self.make_group(0),"future":self.make_group(1893456000,"future")}
        catalog,_,issues=compile_catalog(review,{},"a"*40,"2026-10-29")
        self.assertEqual([g["id"] for g in catalog["groups"]],["unknown"])
        self.assertIsNone(catalog["groups"][0]["date"])
        self.assertEqual(catalog["stats"]["excluded_future"],1)
        self.assertTrue(validate_catalog(catalog))

    def test_repeated_story_path_keeps_two_references_one_body(self):
        catalog,_,issues=compile_catalog({"a":self.make_group(0),"b":self.make_group(0)}, {}, "a"*40,"2026-10-29")
        self.assertEqual(len(catalog["stories"]),1)
        self.assertEqual(len(catalog["groups"]),2)
        self.assertTrue(issues["warnings"])

    def test_operator_records_resolve_full_game_ids_and_legacy_short_ids(self):
        review={"story_kroos_set_1":self.make_group(0,"obt/memory/story_kroos_1_1","NONE")}
        for key in ("char_124_kroos", "kroos"):
            with self.subTest(key=key):
                catalog,_,_=compile_catalog(review,{key:{"name":"克洛丝"}},"a"*40,"2026-10-29")
                self.assertEqual(catalog["groups"][0]["operator"],"克洛丝")
                self.assertEqual(catalog["stories"]["cn:obt/memory/story_kroos_1_1"]["operator"],"克洛丝")

    def test_comics_use_titles_and_urls_not_descriptions(self):
        page='<a href="/terra-historicus/comic/0123"><img alt="作品甲"/><p>不应收集的介绍</p></a>'
        c,_,_=compile_catalog({}, {}, "a"*40,"2026-10-29",page)
        self.assertEqual(c["groups"][0]["title"],"作品甲")
        self.assertNotIn("不应收集",str(c))

    def test_repeated_updates_preserve_prior_missing_versions(self):
        previous={"revision":"revision-2","stories":{"same":{"id":"same","title":"第二版"}}}
        existing={"older":{"id":"older","versions":{"revision-1":{"id":"older"}}},"same":{"id":"same","versions":{"revision-1":{"id":"same","title":"第一版"}}}}
        retained=retain_removed_history(existing,previous,["same"])
        self.assertIn("older",retained)
        self.assertEqual(set(retained["same"]["versions"]),{"revision-1","revision-2"})
        self.assertEqual(retained["same"]["versions"]["revision-1"]["title"],"第一版")


class ImportTests(unittest.TestCase):
    def fixture(self):
        return {"storyList":[
            {"id":1,"prop":"Name","attributes":{"name":"编目员","content":"原创测试"}},
            {"id":2,"prop":"Decision","attributes":{"options":"左;右","values":"1;2"}},
            {"id":3,"prop":"Predicate","attributes":{"references":"1"}},
            {"id":4,"prop":"Name","attributes":{"content":"原创分支一"}},
            {"id":5,"prop":"Predicate","attributes":{"references":"2"}},
            {"id":6,"prop":"NewDirective","attributes":{"content":"保留记录"}}]}

    def test_branch_targets_resolved_without_flattening(self):
        story=normalize_story(self.fixture(),"test/story")
        self.assertEqual([x["target"] for x in story["nodes"][1]["options"]],["l3","l5"])
        self.assertEqual(story["nodes"][2]["kind"],"branch")
        self.assertEqual(len(story["nodes"]),6)

    def test_unknown_directive_is_preserved_and_reported(self):
        story=normalize_story(self.fixture(),"test/story")
        self.assertEqual(story["nodes"][-1]["kind"],"unknown")
        self.assertEqual(story["nodes"][-1]["attributes"]["content"],"保留记录")
        self.assertTrue(story["warnings"])

    def test_quoted_commas_and_original_line_ids(self):
        value=parse_script('\n[name="甲, 乙"] 测试正文\n\n[NewEffect(x="1,2")]')
        self.assertEqual(value["storyList"][0]["id"],2)
        self.assertEqual(value["storyList"][0]["attributes"]["name"],"甲, 乙")
        self.assertEqual(value["storyList"][1]["attributes"]["x"],"1,2")

    def test_bad_jump_rejected_instead_of_silently_losing_branch(self):
        value=self.fixture();value["storyList"][1]["targetLine"]={"option1":999,"option2":5}
        with self.assertRaises(ValueError):normalize_story(value,"test/story")

    def test_duplicate_line_ids_rejected(self):
        value=self.fixture();value["storyList"][1]["id"]=1
        with self.assertRaises(ValueError):normalize_story(value,"test/story")

    def test_imported_html_is_escaped(self):
        output=node_html({"id":"l1","kind":"narration","text":"<script>alert(1)</script>"})
        self.assertNotIn("<script>",output)
        self.assertIn("&lt;script&gt;",output)


class EpubTests(unittest.TestCase):
    def test_unicode_and_choice_anchors_survive_zip(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/"test.epub"
            content='<h1>中文测试</h1><p id="l1"><a href="#l2">选择 →</a></p><p id="l2">原创新段落</p>'
            report=make_epub(out,"原创测试",[("第一篇",content)],"2026-10-29")
            self.assertEqual(report["structural_check"],"passed")
            with zipfile.ZipFile(out) as z:
                self.assertEqual(z.namelist()[0],"mimetype")
                self.assertEqual(z.getinfo("mimetype").compress_type,zipfile.ZIP_STORED)
                self.assertIn("中文测试",z.read("EPUB/section-0000.xhtml").decode())
            first=out.read_bytes();make_epub(out,"原创测试",[("第一篇",content)],"2026-10-29")
            self.assertEqual(first,out.read_bytes())

    def test_missing_internal_target_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,"锚点不存在"):
                make_epub(Path(folder)/"broken.epub","错误测试",[("测试",'<a href="#missing">跳转</a>')],"2026-10-29")


if __name__=="__main__":unittest.main()
