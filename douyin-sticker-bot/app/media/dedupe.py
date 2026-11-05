"""感知哈希去重（纯 Pillow，不依赖 numpy）。"""
from __future__ import annotations

from PIL import Image


def dhash(img: Image.Image, size: int = 8) -> str:
    """64 位差值哈希，返回 16 位十六进制字符串。"""
    g = img.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    px = g.tobytes()  # 8bit 灰度：每行 size+1 像素，直接取字节即可
    bits = 0
    for row in range(size):
        base = row * (size + 1)
        for col in range(size):
            bits = (bits << 1) | (1 if px[base + col] > px[base + col + 1] else 0)
    return f"{bits:016x}"


def hamming(a: str, b: str) -> int:
    """两个十六进制哈希的汉明距离。"""
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except (TypeError, ValueError):
        return 999
