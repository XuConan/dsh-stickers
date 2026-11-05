"""本地文件管理：导出夹读取/删除/清空，文件名穿越防护。"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.web.server import App


class _Bus:
    def __init__(self):
        self.events = []

    def emit(self, kind, **data):
        self.events.append((kind, data))


def _app(tmp: Path) -> SimpleNamespace:
    cfg = SimpleNamespace(outbox_dir=tmp / "outbox",
                          stickers_dir=tmp / "stickers")
    cfg.outbox_dir.mkdir()
    cfg.stickers_dir.mkdir()
    return SimpleNamespace(cfg=cfg, bus=_Bus())


class TestLocalFiles(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.app = _app(self.tmp)
        (self.app.cfg.outbox_dir / "001.png").write_bytes(
            b"\x89PNG\r\n\x1a\n" + b"0" * 10)
        (self.app.cfg.outbox_dir / "002.png").write_bytes(b"\xff\xd8" + b"0" * 5)

    def tearDown(self):
        self._td.cleanup()

    def test_info_lists_outbox(self):
        info = App.local_info(self.app)["outbox"]
        self.assertEqual(info["count"], 2)
        self.assertIn("001.png", [f["name"] for f in info["files"]])
        self.assertGreater(info["bytes"], 0)

    def test_file_served_with_mime(self):
        got = App.local_file(self.app, "001.png")
        self.assertIsNotNone(got)
        data, ctype = got
        self.assertEqual(ctype, "image/png")
        self.assertTrue(data.startswith(b"\x89PNG"))

    def test_path_traversal_is_blocked(self):
        # 传目录穿越也只取文件名部分
        self.assertIsNone(App.local_file(self.app, "../../secret.png"))
        self.assertIsNone(App.local_file(self.app, "..\\..\\secret.png"))

    def test_delete_one(self):
        r = App.local_delete(self.app, "001.png")
        self.assertTrue(r["ok"])
        self.assertFalse((self.app.cfg.outbox_dir / "001.png").exists())
        self.assertTrue((self.app.cfg.outbox_dir / "002.png").exists())
        self.assertFalse(App.local_delete(self.app, "001.png")["ok"])

    def test_clear_outbox(self):
        r = App.local_clear(self.app)
        self.assertEqual(r["removed"], 2)
        self.assertEqual(list(self.app.cfg.outbox_dir.iterdir()), [])
        self.assertTrue(any(k == "local_changed" for k, _ in self.app.bus.events))

    def test_purge_garbage_scope_rejected(self):
        r = App.local_purge(self.app, "nonsense")
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main()
