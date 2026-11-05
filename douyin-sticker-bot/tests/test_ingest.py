"""目录型市场入库（ingest）单测：用假市场，不碰网络、不碰真库。"""
from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path

from app import store
from app.events import Bus
from app.markets import ingest
from app.markets.base import MarketItem


class FakeMarket:
    id = "fakemarket"
    name = "假市场"
    kind = "catalog"
    needs_login = False

    def ensure_manifest(self, force: bool = False):
        return {"files": []}

    def items(self, category=None, query=None, limit=500):
        return [
            MarketItem(external_id="fake:1", url="https://x/1.png", desc="一"),
            MarketItem(external_id="fake:2", url="https://x/2.gif", desc="二",
                       is_animated=True),
        ]

    def categories(self):
        return []


class TestIngest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ingest-test-"))
        self.db = self.dir / "t.db"
        store.init(self.db)
        self.bus = Bus()

    def tearDown(self):
        deadline = time.time() + 5
        while ingest.is_running() and time.time() < deadline:
            time.sleep(0.05)
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_ingest_writes_candidates(self):
        ok = ingest.start(FakeMarket(), category="c1", cfg=None,
                          bus=self.bus, db=self.db)
        self.assertTrue(ok)
        deadline = time.time() + 5
        while ingest.is_running() and time.time() < deadline:
            time.sleep(0.05)
        rows = store.list_candidates(db=self.db)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["market"] == "fakemarket" for r in rows))
        self.assertEqual(store.counts(db=self.db)["by_market"],
                         {"fakemarket": 2})
        kinds = {r["aweme_id"]: r["source_type"] for r in rows}
        self.assertEqual(kinds["fake:2"], "sticker")      # 动图 → sticker
        self.assertEqual(kinds["fake:1"], "image")

    def test_ingest_is_idempotent(self):
        for _ in range(2):
            ingest.start(FakeMarket(), category="c1", cfg=None,
                         bus=self.bus, db=self.db)
            deadline = time.time() + 5
            while ingest.is_running() and time.time() < deadline:
                time.sleep(0.05)
        self.assertEqual(len(store.list_candidates(db=self.db)), 2)


if __name__ == "__main__":
    unittest.main()
