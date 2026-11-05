"""解析与工具函数单测（stdlib unittest，无需 pytest）。"""
from __future__ import annotations

import unittest

from app.douyin import parser


class TestExtractSecUid(unittest.TestCase):
    def test_from_profile_url(self):
        url = "https://www.douyin.com/user/MS4wLjABAAAAxyz-123_abc"
        self.assertEqual(parser.extract_sec_uid(url), "MS4wLjABAAAAxyz-123_abc")

    def test_from_share_text(self):
        text = "3.14 复制打开抖音，看看 https://www.douyin.com/user/MS4wLjABAAAAtest_1 的作品"
        self.assertEqual(parser.extract_sec_uid(text), "MS4wLjABAAAAtest_1")

    def test_bare_sec_uid(self):
        self.assertEqual(parser.extract_sec_uid("MS4wLjABAAAAqqq"), "MS4wLjABAAAAqqq")

    def test_garbage(self):
        self.assertIsNone(parser.extract_sec_uid("随便一句话"))
        self.assertIsNone(parser.extract_sec_uid(""))


class TestParsePayload(unittest.TestCase):
    def test_image_post_makes_one_candidate_per_image(self):
        payload = {
            "search_list": [{
                "aweme_info": {
                    "aweme_id": "7001",
                    "desc": "猫咪表情包",
                    "author": {"nickname": "喵星人"},
                    "images": [
                        {"url_list": ["https://p3/x-s.jpeg", "https://p3/x-l.jpeg"],
                         "width": 300, "height": 300},
                        {"url_list": ["https://p3/y.jpeg"], "width": 240, "height": 240},
                    ],
                }
            }]
        }
        out = parser.parse_payload(payload)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["aweme_id"], "7001")
        self.assertEqual(out[1]["aweme_id"], "7001_1")
        self.assertEqual(out[0]["url"], "https://p3/x-l.jpeg")  # 取最大的最后一张
        self.assertEqual(out[0]["source_type"], "image")
        self.assertEqual(out[0]["author"], "喵星人")
        self.assertEqual(out[0]["width"], 300)

    def test_video_post(self):
        payload = {"aweme_detail": {
            "aweme_id": "7002",
            "desc": "会动的表情",
            "video": {
                "play_addr": {"url_list": ["https://v/a.mp4"]},
                "cover": {"url_list": ["https://c/c1.jpeg", "https://c/c2.jpeg"]},
                "width": 720, "height": 1280,
            },
        }}
        out = parser.parse_payload(payload)
        self.assertEqual(len(out), 1)
        c = out[0]
        self.assertEqual(c["source_type"], "video")
        self.assertEqual(c["url"], "https://c/c2.jpeg")
        self.assertEqual(c["video_url"], "https://v/a.mp4")
        self.assertTrue(c["is_animated"])

    def test_image_post_info_nested(self):
        payload = {"data": {"image_post_info": {"images": [
            {"url_list": ["https://p3/z.gif"], "image_width": 200, "image_height": 200}
        ]}, "aweme_id": "7003", "desc": "gif"}}
        out = parser.parse_payload(payload)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["url"], "https://p3/z.gif")
        self.assertTrue(out[0]["is_animated"])

    def test_dedupe_by_aweme_id(self):
        item = {"aweme_id": "7004",
                "images": [{"url_list": ["https://p3/a.jpeg"]}]}
        payload = {"list": [item, item]}
        self.assertEqual(len(parser.parse_payload(payload)), 1)

    def test_empty_payload(self):
        self.assertEqual(parser.parse_payload({}), [])
        self.assertEqual(parser.parse_payload(None), [])

    def test_item_without_media_ignored(self):
        payload = {"a": {"aweme_id": "7005", "desc": "纯文本"}}
        self.assertEqual(parser.parse_payload(payload), [])


class TestParseStickerPage(unittest.TestCase):
    def _payload(self):
        return {"status_code": 0, "custom_sticker_page_list": {
            "is_completed": False, "next_cursor": 50, "resources": [{
                "display_name": "我的表情",
                "stickers": [{
                    "animate_type": "webp",
                    "animate_url": {"uri": "tos-cn-o-0812/abc123",
                                    "url_list": ["https://p3/a.awebp?x=1"]},
                }, {
                    "static_url": {"uri": "tos-cn-o-0812/def456",
                                   "url_list": ["https://p3/b.png"]},
                }, {}],
            }],
        }}

    def test_stickers_become_candidates(self):
        items, cursor, done = parser.parse_sticker_page(self._payload())
        self.assertEqual(len(items), 2)          # 第三个啥都没有，跳过
        self.assertEqual(cursor, 50)
        self.assertFalse(done)
        self.assertEqual(items[0]["url"], "https://p3/a.awebp?x=1")
        self.assertTrue(items[0]["is_animated"])
        self.assertEqual(items[0]["source_type"], "sticker")
        self.assertEqual(items[0]["aweme_id"], "sticker_abc123")
        self.assertFalse(items[1]["is_animated"])

    def test_next_cursor_and_done(self):
        payload = self._payload()
        payload["custom_sticker_page_list"]["is_completed"] = True
        payload["custom_sticker_page_list"]["next_cursor"] = 0
        items, cursor, done = parser.parse_sticker_page(payload)
        self.assertTrue(done)
        self.assertEqual(cursor, 0)
        self.assertEqual(len(items), 2)

    def test_empty_page(self):
        self.assertEqual(parser.parse_sticker_page({}), ([], 0, False))
        self.assertEqual(parser.parse_sticker_page(None), ([], 0, False))


if __name__ == "__main__":
    unittest.main()
