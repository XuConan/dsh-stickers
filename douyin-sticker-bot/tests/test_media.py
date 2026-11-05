"""归一化 / 感知哈希单测。"""
from __future__ import annotations

import io
import unittest

from PIL import Image

from app.config import Config
from app.media import dedupe, normalize

CFG = Config()


def _png(size=(500, 500), color=(255, 0, 0, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _gif(size=(200, 200), frames=4) -> bytes:
    imgs = []
    for i in range(frames):
        im = Image.new("RGBA", size, (0, 0, 0, 0))
        for x in range(i * 10, i * 10 + 40):
            if x < size[0]:
                im.putpixel((x, size[1] // 2), (255, 0, 0, 255))
        imgs.append(im)
    buf = io.BytesIO()
    imgs[0].save(buf, format="GIF", save_all=True, append_images=imgs[1:],
                 duration=80, loop=0, disposal=2)
    return buf.getvalue()


class TestNormalizeStatic(unittest.TestCase):
    def test_square_to_target(self):
        r = normalize.normalize(_png(), CFG)
        self.assertEqual(r["ext"], "png")
        self.assertEqual((r["width"], r["height"]), (240, 240))
        self.assertFalse(r["animated"])
        img = Image.open(io.BytesIO(r["data"]))
        self.assertEqual(img.size, (240, 240))

    def test_wide_image_keeps_ratio_inside_canvas(self):
        # 600x300 -> 240x120 居中，上下留透明
        r = normalize.normalize(_png((600, 300)), CFG)
        img = Image.open(io.BytesIO(r["data"]))
        self.assertEqual(img.size, (240, 240))
        alpha = img.convert("RGBA").getchannel("A")
        self.assertEqual(alpha.getpixel((120, 5)), 0)
        self.assertGreater(alpha.getpixel((120, 120)), 200)

    def test_tall_image_leaves_side_margins(self):
        # 300x600 -> 120x240 居中，左右留透明
        r = normalize.normalize(_png((300, 600)), CFG)
        img = Image.open(io.BytesIO(r["data"]))
        self.assertEqual(img.size, (240, 240))
        alpha = img.convert("RGBA").getchannel("A")
        self.assertEqual(alpha.getpixel((5, 120)), 0)
        self.assertGreater(alpha.getpixel((120, 120)), 200)

    def test_bad_bytes_raise(self):
        with self.assertRaises(normalize.NormalizeError):
            normalize.normalize(b"not an image", CFG)


class TestNormalizeAnimated(unittest.TestCase):
    def test_gif_becomes_240_animated(self):
        r = normalize.normalize(_gif(), CFG)
        self.assertEqual(r["ext"], "gif")
        self.assertTrue(r["animated"])
        self.assertEqual(r["data"][:6], b"GIF89a")
        img = Image.open(io.BytesIO(r["data"]))
        self.assertGreater(img.n_frames, 1)
        self.assertEqual(img.size[0], img.size[1])

    def test_oversize_gif_gets_shrunk_under_limit(self):
        cfg = Config()
        cfg.max_gif_bytes = 20_000  # 逼它降档
        r = normalize.normalize(_gif(frames=12), cfg)
        self.assertLessEqual(len(r["data"]), cfg.max_gif_bytes)
        self.assertEqual(r["ext"], "gif")


class TestIsSticker(unittest.TestCase):
    def test_too_small_rejected(self):
        ok, why = normalize.is_sticker(Image.new("RGB", (80, 80)), CFG)
        self.assertFalse(ok)
        self.assertEqual(why, "too_small")

    def test_banner_aspect_rejected(self):
        ok, why = normalize.is_sticker(Image.new("RGB", (900, 300)), CFG)
        self.assertFalse(ok)
        self.assertEqual(why, "aspect")

    def test_normal_accepted(self):
        ok, _ = normalize.is_sticker(Image.new("RGB", (240, 240)), CFG)
        self.assertTrue(ok)


class TestDedupe(unittest.TestCase):
    def test_same_image_same_hash(self):
        a = dedupe.dhash(Image.open(io.BytesIO(_png())))
        b = dedupe.dhash(Image.open(io.BytesIO(_png())))
        self.assertEqual(a, b)
        self.assertEqual(dedupe.hamming(a, b), 0)

    def test_hash_is_16_hex(self):
        h = dedupe.dhash(Image.open(io.BytesIO(_png())))
        self.assertEqual(len(h), 16)
        int(h, 16)

    def test_different_images_differ(self):
        left = Image.new("RGB", (200, 200), (0, 0, 0))
        for x in range(100):
            for y in range(200):
                left.putpixel((x, y), (255, 255, 255))
        right = Image.new("RGB", (200, 200), (0, 0, 0))
        for x in range(100, 200):
            for y in range(200):
                right.putpixel((x, y), (255, 255, 255))
        self.assertGreater(dedupe.hamming(dedupe.dhash(left), dedupe.dhash(right)), 6)

    def test_hamming_bad_input(self):
        self.assertEqual(dedupe.hamming("zz", "00"), 999)
        self.assertEqual(dedupe.hamming(None, "00"), 999)


if __name__ == "__main__":
    unittest.main()
