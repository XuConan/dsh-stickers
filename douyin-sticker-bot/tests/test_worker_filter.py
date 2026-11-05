"""采集线程的接口过滤单测：收藏模式只认 listcollection，不能混进 post / favorite。"""
from __future__ import annotations

import unittest

try:
    from app.config import Config
    from app.douyin.worker import MODE_ENDPOINTS, Collector
    from app.events import Bus
except ImportError:  # 系统 python 没装 playwright 时跳过
    Collector = None


def _post(aid: str, desc: str = "表情包") -> dict:
    return {
        "aweme_id": aid,
        "desc": desc,
        "author": {"nickname": "某人"},
        "images": [{"url_list": [f"https://p3/{aid}.jpeg"], "width": 240, "height": 240}],
    }


class _FakeResp:
    def __init__(self, url: str, data: dict):
        self.url = url
        self._data = data

    def json(self) -> dict:
        return self._data


@unittest.skipUnless(Collector, "playwright 未安装，跳过采集线程单测")
class TestResponseFilter(unittest.TestCase):
    def setUp(self):
        self.col = Collector(Config(), Bus())
        self.col._collecting = True

    def test_collection_mode_only_takes_listcollection(self):
        self.col._mode_filter = MODE_ENDPOINTS["collection"]
        self.col._on_response(_FakeResp(
            "https://www.douyin.com/aweme/v1/web/aweme/post/?cursor=0",
            {"aweme_list": [_post("post1")]}))
        self.col._on_response(_FakeResp(
            "https://www.douyin.com/aweme/v1/web/aweme/favorite/?cursor=0",
            {"aweme_list": [_post("fav1")]}))
        self.col._on_response(_FakeResp(
            "https://www.douyin.com/aweme/v1/web/aweme/listcollection/?cursor=0",
            {"aweme_list": [_post("col1")]}))
        self.assertEqual(list(self.col._captured), ["col1"])

    def test_like_mode_only_takes_favorite(self):
        self.col._mode_filter = MODE_ENDPOINTS["like"]
        self.col._on_response(_FakeResp(
            "https://www.douyin.com/aweme/v1/web/aweme/listcollection/",
            {"aweme_list": [_post("col1")]}))
        self.col._on_response(_FakeResp(
            "https://www.douyin.com/aweme/v1/web/aweme/favorite/",
            {"aweme_list": [_post("fav1")]}))
        self.assertEqual(list(self.col._captured), ["fav1"])

    def test_ignores_non_aweme_endpoints(self):
        self.col._mode_filter = MODE_ENDPOINTS["keyword"]
        self.col._on_response(_FakeResp(
            "https://www.douyin.com/aweme/v1/web/user/profile/self/",
            {"user": {"nickname": "x"}}))
        self.assertEqual(self.col._captured, {})

    def test_not_collecting_means_ignored(self):
        self.col._collecting = False
        self.col._mode_filter = MODE_ENDPOINTS["collection"]
        self.col._on_response(_FakeResp(
            "https://www.douyin.com/aweme/v1/web/aweme/listcollection/",
            {"aweme_list": [_post("col1")]}))
        self.assertEqual(self.col._captured, {})


if __name__ == "__main__":
    unittest.main()
