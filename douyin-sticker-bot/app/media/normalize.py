"""把下载到的图片/动图归一化成微信表情规格。"""
from __future__ import annotations

import io

from PIL import Image

from ..config import Config

LANCZOS = Image.Resampling.LANCZOS


class NormalizeError(Exception):
    pass


def probe(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        return img
    except Exception as e:  # noqa: BLE001
        raise NormalizeError(f"无法识别图片: {e}") from e


def is_sticker(img: Image.Image, cfg: Config) -> tuple[bool, str]:
    w, h = img.size
    if min(w, h) < cfg.min_short_edge:
        return False, "too_small"
    if not h:
        return False, "bad_size"
    ratio = w / h
    if not (cfg.aspect_min <= ratio <= cfg.aspect_max):
        return False, "aspect"
    return True, ""


def _fit(img: Image.Image, size: int) -> Image.Image:
    w, h = img.size
    scale = min(size / w, size / h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    resized = img.resize((nw, nh), LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(resized, ((size - nw) // 2, (size - nh) // 2), resized)
    return canvas


def _to_gif_frames(frames: list[Image.Image], durations: list[int],
                   cfg: Config, size: int) -> bytes:
    p_frames, p_durations = [], []
    for canvas, dur in zip(frames, durations):
        alpha = canvas.getchannel("A").point(lambda a: 255 if a > 128 else 0)
        rgb = Image.new("RGB", canvas.size, (255, 255, 255))
        rgb.paste(canvas, mask=canvas.getchannel("A"))
        p = rgb.convert("P", palette=Image.Palette.ADAPTIVE, colors=255)
        p.paste(255, mask=Image.eval(alpha, lambda a: 255 - a))
        p_frames.append(p)
        p_durations.append(max(20, min(int(dur or 80), 500)))

    buf = io.BytesIO()
    p_frames[0].save(
        buf, format="GIF", save_all=True, append_images=p_frames[1:],
        duration=p_durations, loop=0, transparency=255, disposal=2, optimize=True,
    )
    return buf.getvalue()


def normalize(data: bytes, cfg: Config) -> dict:
    """返回 {data, ext, width, height, animated}。"""
    img = probe(data)
    frames_total = getattr(img, "n_frames", 1) or 1
    animated = frames_total > 1

    if not animated:
        canvas = _fit(img.convert("RGBA"), cfg.target_size)
        buf = io.BytesIO()
        canvas.save(buf, format="PNG", optimize=True)
        raw = buf.getvalue()
        if len(raw) > cfg.max_gif_bytes:  # 极端情况：超大 PNG 再压一档
            canvas = canvas.resize((192, 192), LANCZOS)
            buf = io.BytesIO()
            canvas.save(buf, format="PNG", optimize=True)
            raw = buf.getvalue()
        return {"data": raw, "ext": "png",
                "width": canvas.size[0], "height": canvas.size[1], "animated": False}

    # --- 动图 ---
    frames, durations = [], []
    try:
        for i in range(frames_total):
            img.seek(i)
            frames.append(img.convert("RGBA").copy())
            durations.append(int(img.info.get("duration", 80) or 80))
    except EOFError:
        pass
    if not frames:
        raise NormalizeError("动图读取失败")

    if len(frames) > cfg.max_gif_frames:
        step = len(frames) / cfg.max_gif_frames
        picked = [int(i * step) for i in range(cfg.max_gif_frames)]
        frames = [frames[i] for i in picked]
        durations = [durations[i] for i in picked]

    for size in (cfg.target_size, 200, 160, 120):
        resized = [_fit(f, size) for f in frames]
        try:
            raw = _to_gif_frames(resized, durations, cfg, size)
        except Exception as e:  # noqa: BLE001
            raise NormalizeError(f"GIF 编码失败: {e}") from e
        if len(raw) <= cfg.max_gif_bytes:
            return {"data": raw, "ext": "gif", "width": size,
                    "height": size, "animated": True}
        # 还是太大：抽帧再试
        if len(frames) > 24:
            frames = frames[::2]
            durations = durations[::2]

    # 兜底：只留首帧做静态图
    canvas = _fit(frames[0], cfg.target_size)
    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return {"data": buf.getvalue(), "ext": "png",
            "width": canvas.size[0], "height": canvas.size[1], "animated": False}
