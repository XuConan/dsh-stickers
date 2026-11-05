"""小红书表情解析单测（不需要网络：用 tests/fixtures/xhs_redmoji.json 当夹具）。"""

import json
import pathlib
import unittest

from app.xhs.parser import MARKET_ID, redmoji_to_items, smiles_to_items, to_candidates

FIXTURE = pathlib.Path(__file__).with_name("fixtures") / "xhs_redmoji.json"


class TestRedmoji(unittest.TestCase):
    def setUp(self):
        raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.emojis = []
        for tab in raw["data"]["emoji"]["tabs"]:
            for col in tab.get("collection") or []:
                self.emojis.extend(col.get("emoji") or [])

    def test_fixture_shape(self):
        self.assertTrue(self.emojis)
        first = self.emojis[0]
        self.assertIn("image_name", first)
        self.assertIn("image", first)

    def test_items_keep_every_emoji(self):
        items = redmoji_to_items(self.emojis)
        self.assertEqual(len(items), len(self.emojis))
        first = self.emojis[0]
        self.assertEqual(items[0].external_id, f"xhs_redmoji_{first['image_name']}")
        self.assertEqual(items[0].desc, first["image_name"])
        self.assertTrue(items[0].url.startswith("https://"))
        self.assertEqual(items[0].category, "小红书表情")

    def test_items_are_static_png(self):
        items = redmoji_to_items(self.emojis)
        for it in items:
            self.assertFalse(it.is_animated)

    def test_skips_missing_url(self):
        items = redmoji_to_items([{"image_name": "[空]"}, {"image_name": "[有]", "image": "https://a/b.png"}])
        self.assertEqual([i.external_id for i in items], ["xhs_redmoji_[有]"])


class TestSmiles(unittest.TestCase):
    def test_prefers_file_name(self):
        items = smiles_to_items([{"fileId": "abc123", "fileName": "https://sns-img.xhscdn.com/a.webp", "width": 240, "height": 240}])
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it.external_id, "xhs_smile_abc123")
        self.assertEqual(it.url, "https://sns-img.xhscdn.com/a.webp")
        self.assertEqual((it.width, it.height), (240, 240))
        self.assertTrue(it.is_animated)          # webp 当动图处理

    def test_falls_back_to_image_url(self):
        items = smiles_to_items([{"fileId": "x1", "imageUrl": "https://sns-img.xhscdn.com/b.png"}])
        self.assertEqual(items[0].url, "https://sns-img.xhscdn.com/b.png")
        self.assertFalse(items[0].is_animated)

    def test_dedupes_and_skips_broken(self):
        raw = [
            {"fileId": "dup", "fileName": "https://a/1.png"},
            {"fileId": "dup", "fileName": "https://a/2.png"},
            {"fileName": "https://a/no-id.png"},
            {"fileId": "no-url"},
            {"fileId": "ok", "fileName": "https://a/3.gif"},
        ]
        items = smiles_to_items(raw)
        self.assertEqual([i.external_id for i in items], ["xhs_smile_dup", "xhs_smile_ok"])
        self.assertTrue(items[-1].is_animated)

    def test_empty_input(self):
        self.assertEqual(smiles_to_items([]), [])
        self.assertEqual(smiles_to_items(None or []), [])


class TestCandidates(unittest.TestCase):
    def test_candidate_columns(self):
        items = smiles_to_items([{"fileId": "k1", "fileName": "https://a/x.png"}])
        cands = to_candidates(items)
        self.assertEqual(len(cands), 1)
        c = cands[0]
        self.assertEqual(c["market"], MARKET_ID)
        self.assertEqual(c["aweme_id"], "xhs_smile_k1")
        self.assertEqual(c["source_type"], "image")
        self.assertEqual(c["url"], "https://a/x.png")

    def test_animated_becomes_sticker(self):
        items = smiles_to_items([{"fileId": "g1", "fileName": "https://a/x.gif"}])
        self.assertEqual(to_candidates(items)[0]["source_type"], "sticker")


if __name__ == "__main__":
    unittest.main()
