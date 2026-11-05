"""目录型市场（GitHub 图库）单测：全部离线，用假缓存。"""
from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from app.markets import GithubRepoMarket, pretty_name, registry
from app.markets.base import ext_of, is_animated_path
from app.markets.github_repo import ALL_CATEGORY, category_number


def _market(tmp: Path) -> GithubRepoMarket:
    files = [
        {"path": "001Funny_滑稽大佬😏BQB/a.gif", "size": 100},
        {"path": "001Funny_滑稽大佬😏BQB/b.PNG", "size": 200},
        {"path": "002Cute_可爱BQB/c.jpg", "size": 300},
        {"path": "002Cute_可爱BQB/readme.md", "size": 10},
        {"path": "site/index.tsx", "size": 10},
        {"path": "README.md", "size": 10},
    ]
    cache = tmp / "fake.json"
    cache.write_text(json.dumps({
        "fetched_at": time.time(), "repo": "x/y", "branch": "master",
        "files": files,
    }), encoding="utf-8")
    return GithubRepoMarket(
        market_id="chinesebqb", name="中文表情包库", repo="x/y",
        branch="master", cache_path=cache,
        exclude_dirs=("site", ".github"))


class TestHelpers(unittest.TestCase):
    def test_ext(self):
        self.assertEqual(ext_of("a/B.GIF"), "gif")
        self.assertEqual(ext_of("noext"), "")
        self.assertTrue(is_animated_path("a/b.GIF"))
        self.assertTrue(is_animated_path("a/b.webp"))
        self.assertFalse(is_animated_path("a/b.png"))

    def test_pretty_name(self):
        self.assertEqual(pretty_name("001Funny_滑稽大佬😏BQB"), "滑稽大佬😏")
        self.assertEqual(pretty_name("斗图之王BQB"), "斗图之王")
        # 英文前缀 / 尾随下划线都要剥掉，只留人话那一段
        self.assertEqual(pretty_name("110_AI_人工智能_BQB"), "人工智能")
        self.assertEqual(pretty_name("111_TheBoys_黑袍纠察队_BQB"), "黑袍纠察队")
        self.assertEqual(pretty_name("112PhantomBladeZero_影之刃零_BQB"), "影之刃零")
        self.assertEqual(pretty_name("000Contribution_贡献🇨🇳BQB"), "贡献🇨🇳")
        self.assertEqual(
            pretty_name("微信网友贡献表情包_暂存_有时间慢慢整理BQB"), "微信网友贡献表情包")

    def test_category_number(self):
        self.assertEqual(category_number("112PhantomBladeZero_影之刃零_BQB"), "112")
        self.assertEqual(category_number("斗图之王BQB"), "")


class TestGithubRepoMarket(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="market-test-"))
        self.m = _market(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_only_images_and_excluded_dirs(self):
        items = self.m.items()
        self.assertEqual(len(items), 3)          # a.gif / b.PNG / c.jpg
        self.assertFalse(any("site/" in i.external_id for i in items))

    def test_categories(self):
        cats = {c["id"]: c for c in self.m.categories()}
        self.assertIn(ALL_CATEGORY, cats)                    # 第一条是「全部表情包」
        self.assertEqual(cats[ALL_CATEGORY]["count"], 3)
        real = set(cats) - {ALL_CATEGORY}
        self.assertEqual(real, {"001Funny_滑稽大佬😏BQB", "002Cute_可爱BQB"})
        self.assertEqual(cats["001Funny_滑稽大佬😏BQB"]["count"], 2)
        self.assertEqual(cats["001Funny_滑稽大佬😏BQB"]["number"], "001")
        self.assertEqual(cats["002Cute_可爱BQB"]["name"], "可爱")

    def test_items_by_category(self):
        items = self.m.items(category="002Cute_可爱BQB")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].category, "可爱")      # 展示名（去掉编号和 BQB 后缀）

    def test_items_query(self):
        self.assertEqual(len(self.m.items(query="cute")), 1)
        self.assertEqual(len(self.m.items(query="nothing-here")), 0)

    def test_items_all_category(self):
        self.assertEqual(len(self.m.items(category=ALL_CATEGORY)), 3)

    def test_item_fields(self):
        it = self.m.items(category="001Funny_滑稽大佬😏BQB")[0]
        self.assertTrue(it.external_id.startswith("chinesebqb:"))
        self.assertTrue(it.url.startswith("https://raw.githubusercontent.com/x/y/master/"))
        self.assertIn("%E6%BB%91", it.url)          # 中文被百分号编码
        self.assertTrue(it.is_animated)             # gif → 动图
        cand = it.to_candidate("chinesebqb")
        self.assertEqual(cand["market"], "chinesebqb")
        self.assertEqual(cand["source_type"], "sticker")
        self.assertEqual(cand["aweme_id"], it.external_id)

    def test_manifest_cached(self):
        self.assertTrue(self.m.has_manifest())
        self.assertTrue(self.m.is_fresh())
        self.assertEqual(len(self.m._files()), 3)     # 读取时也会过滤非图片/排除目录


class TestRegistry(unittest.TestCase):
    def test_builtin_markets(self):
        ids = [m.id for m in registry.all_markets()]
        self.assertIn("douyin", ids)
        self.assertIn("chinesebqb", ids)

    def test_get(self):
        self.assertIsNotNone(registry.get("chinesebqb"))
        self.assertIsNone(registry.get("nope"))


if __name__ == "__main__":
    unittest.main()
