"""小红书抓取线程 + 来源派发（live 市场）的集成测试，不联网。"""

import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from app import store
from app.events import Bus
from app.markets import registry
from app.xhs import sync as xhs_sync
from app.xhs.api import XhsNeedLogin
from app.xhs.parser import redmoji_to_items


class FakeApi:
    def __init__(self, smiles=None, emojis=None, need_login=False):
        self._smiles = smiles or []
        self._emojis = emojis or []
        self._need = need_login

    def my_smiles(self):
        if self._need:
            raise XhsNeedLogin("无登录信息，或登录信息为空")
        return self._smiles

    def redmoji(self):
        return self._emojis


def fake_cfg(tmpdir):
    return SimpleNamespace(
        xhs_cookie_path=pathlib.Path(tmpdir) / "xhs-cookies.json",
        request_timeout=5.0,
    )


def registry_cfg(tmpdir):
    base = pathlib.Path(tmpdir)
    return SimpleNamespace(
        markets_dir=base / "markets",
        markets_conf_dir=base / "markets.d",
    )


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = registry_cfg(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_xhs_market_shape(self):
        markets = {m.id: m for m in registry.all_markets(self.cfg)}
        self.assertIn("xhs", markets)
        xhs = markets["xhs"]
        self.assertEqual(xhs.kind, "live")
        self.assertTrue(xhs.needs_login)
        self.assertEqual([m["id"] for m in xhs.modes], ["smiles", "redmoji"])

    def test_douyin_modes_exposed(self):
        dy = {m.id: m for m in registry.all_markets(self.cfg)}["douyin"]
        self.assertIn("sticker", [m["id"] for m in dy.modes])


class TestFetch(unittest.TestCase):
    def test_redmoji_rows(self):
        api = FakeApi(emojis=[{"image_name": "[微笑R]", "image": "https://a/1.png"}])
        rows = xhs_sync._fetch("redmoji", api)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["candidate"]["market"], "xhs")
        self.assertEqual(rows[0]["candidate"]["aweme_id"], "xhs_redmoji_[微笑R]")

    def test_smiles_rows(self):
        api = FakeApi(smiles=[{"fileId": "f1", "fileName": "https://a/1.webp"}])
        rows = xhs_sync._fetch("smiles", api)
        self.assertEqual(rows[0]["candidate"]["aweme_id"], "xhs_smile_f1")


class TestRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = pathlib.Path(self.tmp.name) / "t.db"
        store.init(self.db)
        self.cfg = fake_cfg(self.tmp.name)
        self.bus = Bus()

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, mode, api):
        with mock.patch.object(xhs_sync, "XhsApi", return_value=api):
            xhs_sync._run(mode, self.cfg, self.bus, db=self.db)

    def test_redmoji_ingest_writes_market(self):
        emojis = [{"image_name": f"[e{i}]", "image": f"https://a/{i}.png"} for i in range(3)]
        self._run("redmoji", FakeApi(emojis=emojis))
        rows = store.list_candidates(market="xhs", db=self.db)
        self.assertEqual(len(rows), 3)
        self.assertEqual({r["status"] for r in rows}, {"new"})
        self.assertEqual(store.count_candidates(market="xhs", db=self.db), 3)

    def test_second_run_dedupes(self):
        emojis = [{"image_name": "[e1]", "image": "https://a/1.png"}]
        self._run("redmoji", FakeApi(emojis=emojis))
        self._run("redmoji", FakeApi(emojis=emojis))
        self.assertEqual(store.count_candidates(market="xhs", db=self.db), 1)

    def test_need_login_emits_event(self):
        self._run("smiles", FakeApi(need_login=True))
        kinds = [e["type"] for e in self.bus.recent(50)]
        self.assertIn("need_login", kinds)
        self.assertEqual(store.count_candidates(market="xhs", db=self.db), 0)

    def test_running_flag_cleared(self):
        self._run("redmoji", FakeApi(emojis=[]))
        self.assertFalse(xhs_sync.is_running())


class TestRedmojiFixture(unittest.TestCase):
    def test_fixture_parses(self):
        import json
        raw = json.loads((pathlib.Path(__file__).with_name("fixtures") / "xhs_redmoji.json")
                         .read_text(encoding="utf-8"))
        emojis = []
        for tab in raw["data"]["emoji"]["tabs"]:
            for col in tab.get("collection") or []:
                emojis.extend(col.get("emoji") or [])
        self.assertEqual(len(redmoji_to_items(emojis)), len(emojis))


if __name__ == "__main__":
    unittest.main()
