"""下载 -> 归一化 -> 去重 -> 落盘 流水线。"""
from __future__ import annotations

import hashlib
import io
import threading
import time

from PIL import Image

from . import store
from .config import Config
from .douyin.downloader import Downloader, DownloadError, video_to_gif
from .events import Bus
from .media import dedupe, normalize

_lock = threading.Lock()
_downloading = False


def is_downloading() -> bool:
    return _downloading


def _run(ids: list[int], cfg: Config, bus: Bus) -> None:
    global _downloading
    dl = Downloader(cfg)
    ok = dup = fail = 0
    total = len(ids)
    try:
        for i, cid in enumerate(ids, 1):
            cand = store.get_candidate(cid)
            if not cand or cand["status"] not in ("new", "skipped", "error"):
                continue
            try:
                norm = None
                if cand["source_type"] == "video":
                    if not cfg.enable_video_gif:
                        store.update_candidate(cid, status="skipped")
                        bus.emit("log", msg=f"[{i}/{total}] 视频作品跳过（未开启视频转GIF）")
                        continue
                    video = dl.fetch([cand["video_url"]])
                    raw = video_to_gif(video, cfg)
                else:
                    data = dl.fetch([cand["url"]])
                    norm = normalize.normalize(data, cfg)
                    raw = norm["data"]
            except (DownloadError, normalize.NormalizeError) as e:
                store.update_candidate(cid, status="error")
                fail += 1
                bus.emit("log", msg=f"[{i}/{total}] 失败: {e}")
                continue

            sha = hashlib.sha256(raw).hexdigest()
            try:
                dh = dedupe.dhash(Image.open(io.BytesIO(raw)))
            except Exception:  # noqa: BLE001
                dh = ""
            hit = store.find_similar(sha, dh, cfg.dedupe_hamming)
            if hit:
                store.update_candidate(cid, status="duplicate", sha256=sha, dhash=dh)
                dup += 1
                bus.emit("log", msg=f"[{i}/{total}] 重复，跳过（已有 #{hit['id']}）")
                _tick(bus, i, total)
                continue

            ext = "gif" if raw[:6] in (b"GIF87a", b"GIF89a") else "png"
            path = cfg.stickers_dir / f"{sha[:16]}.{ext}"
            path.write_bytes(raw)
            extra = {}
            if norm:  # 落盘后把真实尺寸/动图标记写回去，界面显示才对
                extra = {"width": norm["width"], "height": norm["height"],
                         "is_animated": 1 if norm["animated"] else 0}
            store.update_candidate(
                cid, status="downloaded", sha256=sha, dhash=dh, path=str(path),
                **extra,
            )
            ok += 1
            _tick(bus, i, total)
    finally:
        with _lock:
            _downloading = False
        bus.emit("download_done", ok=ok, dup=dup, fail=fail)


def _tick(bus: Bus, done: int, total: int) -> None:
    bus.emit("progress", phase="download", done=done, total=total)


def start(ids: list[int], cfg: Config, bus: Bus) -> bool:
    """后台下载；已有任务在跑返回 False。"""
    global _downloading
    with _lock:
        if _downloading:
            return False
        _downloading = True
    t = threading.Thread(target=_run, args=(ids, cfg, bus), daemon=True)
    t.start()
    return True
