"""sqlite 存储单测（每个用例用独立临时库）。"""
from __future__ import annotations

import itertools
import shutil
import tempfile
import unittest
from pathlib import Path

from app import store


_seq = itertools.count(1)


def _item(url: str, **kw) -> dict:
    # 每个候选默认给不同的 aweme_id（同 id 会被当成重复，见 add_candidate）
    base = {"aweme_id": f"t{next(_seq)}", "desc": "d", "author": "a",
            "source_type": "image", "url": url, "video_url": "",
            "width": 240, "height": 240, "is_animated": False}
    base.update(kw)
    return base


class TestStore(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="sticker-test-"))
        self.db = self.dir / "t.db"
        store.init(self.db)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_add_and_get(self):
        cid = store.add_candidate(_item("https://x/1.png"), db=self.db)
        self.assertIsNotNone(cid)
        row = store.get_candidate(cid, db=self.db)
        self.assertEqual(row["url"], "https://x/1.png")
        self.assertEqual(row["status"], "new")

    def test_duplicate_url_rejected(self):
        self.assertIsNotNone(store.add_candidate(_item("https://x/1.png"), db=self.db))
        self.assertIsNone(store.add_candidate(_item("https://x/1.png"), db=self.db))

    def test_add_with_skipped_status(self):
        cid = store.add_candidate(_item("https://x/2.png"), status="skipped", db=self.db)
        self.assertEqual(store.get_candidate(cid, db=self.db)["status"], "skipped")

    def test_update_and_counts(self):
        a = store.add_candidate(_item("https://x/1.png"), db=self.db)
        b = store.add_candidate(_item("https://x/2.png"), db=self.db)
        store.update_candidate(a, db=self.db, status="downloaded")
        store.update_candidate(b, db=self.db, status="duplicate")
        c = store.counts(db=self.db)
        self.assertEqual(c["downloaded"], 1)
        self.assertEqual(c["duplicate"], 1)
        self.assertEqual(c["new"], 0)
        self.assertEqual(c["total"], 2)

    def test_list_filters_by_status(self):
        a = store.add_candidate(_item("https://x/1.png"), db=self.db)
        store.add_candidate(_item("https://x/2.png"), db=self.db)
        store.update_candidate(a, db=self.db, status="downloaded")
        got = store.list_candidates(["downloaded"], db=self.db)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["id"], a)
        self.assertEqual(len(store.list_candidates(None, db=self.db)), 2)

    def test_find_similar_exact(self):
        cid = store.add_candidate(_item("https://x/1.png"), db=self.db)
        store.update_candidate(cid, db=self.db, status="downloaded",
                               sha256="abc", dhash="0f0f0f0f0f0f0f0f")
        hit = store.find_similar("abc", None, db=self.db)
        self.assertEqual(hit["id"], cid)

    def test_find_similar_by_dhash(self):
        cid = store.add_candidate(_item("https://x/1.png"), db=self.db)
        store.update_candidate(cid, db=self.db, status="downloaded",
                               sha256="aaa", dhash="0000000000000000")
        hit = store.find_similar("bbb", "0000000000000003", max_hamming=6, db=self.db)
        self.assertEqual(hit["id"], cid)

    def test_find_similar_ignores_new_status(self):
        cid = store.add_candidate(_item("https://x/1.png"), db=self.db)
        store.update_candidate(cid, db=self.db, sha256="abc",
                               dhash="0000000000000000")
        self.assertIsNone(store.find_similar("abc", "0000000000000000", db=self.db))

    def test_settings_roundtrip(self):
        self.assertEqual(store.get_setting("k", "def", db=self.db), "def")
        store.set_setting("k", [1, 2, 3], db=self.db)
        self.assertEqual(store.get_setting("k", None, db=self.db), [1, 2, 3])

    def test_runs(self):
        rid = store.create_run("keyword", "猫咪", db=self.db)
        self.assertIsInstance(rid, int)
        store.finish_run(rid, {"new": 3}, db=self.db)

    def test_path_column_does_not_collide_with_db_path(self):
        """回归：候选表的 path 列不能被当成数据库路径参数。"""
        cid = store.add_candidate(_item("https://x/p.png", path="/tmp/a.png"), db=self.db)
        self.assertEqual(store.get_candidate(cid, db=self.db)["path"], "/tmp/a.png")
        store.update_candidate(cid, db=self.db, path="/tmp/b.gif")
        self.assertEqual(store.get_candidate(cid, db=self.db)["path"], "/tmp/b.gif")


    def test_same_aweme_id_is_deduped_even_if_url_changes(self):
        """回归：表情包链接带签名参数，同一条表情 url 变了也不能重复入库。"""
        first = _item("https://x/s.awebp?x-signature=aaa")
        first["aweme_id"] = "sticker_abc"
        second = _item("https://x/s.awebp?x-signature=bbb")
        second["aweme_id"] = "sticker_abc"
        self.assertIsNotNone(store.add_candidate(first, db=self.db))
        self.assertIsNone(store.add_candidate(second, db=self.db))
        self.assertEqual(store.counts(db=self.db)["total"], 1)


class TestMarketColumn(unittest.TestCase):
    """第二期：candidates.market（来源）列 + 老库迁移。"""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="sticker-market-"))
        self.db = self.dir / "t.db"

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_default_market_is_douyin(self):
        store.init(self.db)
        cid = store.add_candidate(_item("https://x/a.png"), db=self.db)
        self.assertEqual(store.get_candidate(cid, db=self.db)["market"], "douyin")

    def test_market_filter(self):
        store.init(self.db)
        store.add_candidate(_item("https://x/a.png"), db=self.db)
        store.add_candidate(_item("https://x/b.png", market="chinesebqb"), db=self.db)
        self.assertEqual(len(store.list_candidates(db=self.db)), 2)
        self.assertEqual(
            len(store.list_candidates(market="chinesebqb", db=self.db)), 1)
        self.assertEqual(store.counts(db=self.db)["by_market"],
                         {"douyin": 1, "chinesebqb": 1})

    def test_old_db_gets_column(self):
        """老库（没有 market 列）打开时自动补列，历史数据算作抖音。"""
        import sqlite3
        conn = sqlite3.connect(str(self.db))
        conn.executescript(
            "CREATE TABLE candidates(id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " aweme_id TEXT, desc TEXT, author TEXT, source_type TEXT, url TEXT,"
            " video_url TEXT, width INTEGER, height INTEGER, is_animated INTEGER,"
            " sha256 TEXT, dhash TEXT, path TEXT, status TEXT, collected_at REAL,"
            " imported_at REAL);"
            "INSERT INTO candidates(aweme_id, url, status) VALUES('old','https://x/old.png','new');")
        conn.commit()
        conn.close()
        store.init(self.db)                       # 迁移
        rows = store.list_candidates(db=self.db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["market"], "douyin")
        store.init(self.db)                       # 幂等：再来一次不报错
        self.assertEqual(len(store.list_candidates(db=self.db)), 1)

    def test_delete_candidates_scope(self):
        """清空列表按筛选范围删，只删命中的那些。"""
        store.init(self.db)
        store.add_candidate(_item("https://x/a.png"), db=self.db)
        store.add_candidate(_item("https://x/b.png", market="chinesebqb"), db=self.db)
        store.add_candidate(_item("https://x/c.png", market="chinesebqb"), db=self.db)
        store.update_candidate(
            store.list_candidates(market="chinesebqb", db=self.db)[0]["id"],
            status="imported", db=self.db)
        self.assertEqual(
            store.delete_candidates(["new"], market="chinesebqb", db=self.db), 1)
        self.assertEqual(store.count_candidates(["new"], db=self.db), 1)
        self.assertEqual(
            store.count_candidates(market="chinesebqb", db=self.db), 1)
        self.assertEqual(store.delete_candidates(["imported"], db=self.db), 1)
        self.assertEqual(store.count_candidates(db=self.db), 1)
        self.assertEqual(store.delete_candidates(db=self.db), 1)   # 不带条件=全删
        self.assertEqual(store.count_candidates(db=self.db), 0)

    def test_pagination(self):
        store.init(self.db)
        for i in range(7):
            store.add_candidate(_item(f"https://x/{i}.png"), db=self.db)
        self.assertEqual(store.count_candidates(db=self.db), 7)
        p1 = store.list_candidates(limit=3, offset=0, db=self.db)
        p2 = store.list_candidates(limit=3, offset=3, db=self.db)
        p3 = store.list_candidates(limit=3, offset=6, db=self.db)
        self.assertEqual([len(p1), len(p2), len(p3)], [3, 3, 1])
        self.assertFalse({x["id"] for x in p1} & {x["id"] for x in p2})
        # 一次翻完不重不漏
        all_ids = [x["id"] for x in p1 + p2 + p3]
        self.assertEqual(len(all_ids), len(set(all_ids)))
        # 状态筛选也跟着走
        store.update_candidate(p1[0]["id"], status="imported", db=self.db)
        self.assertEqual(store.count_candidates(["new"], db=self.db), 6)
        self.assertEqual(
            store.count_candidates(["imported"], db=self.db), 1)


if __name__ == "__main__":
    unittest.main()
