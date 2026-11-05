"""缩略图压缩：原图动辄几百 KB，网格里必须是几十 KB 的小图。"""
import io
import unittest

from PIL import Image

try:
    from app.web.server import shrink_thumb
except ImportError as e:                      # 没装 playwright 时跳过
    shrink_thumb = None
    _skip = f"依赖不可用：{e}"
else:
    _skip = None


def _png(w: int, h: int, color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


@unittest.skipUnless(shrink_thumb, _skip or "缺少 shrink_thumb")
class TestShrinkThumb(unittest.TestCase):
    def test_large_static_shrinks(self):
        data = shrink_thumb(_png(1200, 1200))
        with Image.open(io.BytesIO(data)) as im:
            self.assertLessEqual(max(im.size), 360)
            self.assertIn(im.format, ("JPEG", "PNG"))
        self.assertLess(len(data), len(_png(1200, 1200)))

    def test_small_image_still_ok(self):
        data = shrink_thumb(_png(100, 100))
        with Image.open(io.BytesIO(data)) as im:
            self.assertEqual(im.size, (100, 100))

    def test_transparent_png_keeps_alpha(self):
        buf = io.BytesIO()
        Image.new("RGBA", (800, 800), (0, 0, 0, 0)).save(buf, format="PNG")
        data = shrink_thumb(buf.getvalue())
        with Image.open(io.BytesIO(data)) as im:
            self.assertIn(im.mode, ("RGBA", "LA", "P"))

    def test_big_gif_falls_back_to_first_frame(self):
        """大动图只取第一帧（逐帧重编码会卡几十秒）。"""
        import random
        rnd = random.Random(7)
        pics = []
        for _ in range(12):
            im = Image.new("RGB", (500, 500))
            im.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
                        for _ in range(500 * 500)])
            pics.append(im)
        buf = io.BytesIO()
        pics[0].save(buf, format="GIF", save_all=True, append_images=pics[1:],
                     duration=100, loop=0)
        data = buf.getvalue()
        self.assertGreater(len(data), 300_000)          # 走「大动图」那条路
        out = shrink_thumb(data)
        with Image.open(io.BytesIO(out)) as im:
            self.assertEqual(getattr(im, "n_frames", 1), 1)
            self.assertLessEqual(max(im.size), 360)
        self.assertLess(len(out), len(data))

    def test_garbage_returns_input(self):
        self.assertEqual(shrink_thumb(b"not an image"), b"not an image")


if __name__ == "__main__":
    unittest.main()
