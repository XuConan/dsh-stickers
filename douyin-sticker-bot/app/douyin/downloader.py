"""抖音图片/视频下载。"""
from __future__ import annotations

import time

import requests

from ..config import Config

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")


class DownloadError(Exception):
    pass


class Downloader:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })

    def fetch(self, urls: list[str], referer: str = "https://www.douyin.com/") -> bytes:
        if not urls:
            raise DownloadError("没有可用链接")
        last_err = ""
        for url in urls:
            for attempt in range(3):
                try:
                    r = self.session.get(
                        url, timeout=self.cfg.request_timeout,
                        headers={"Referer": referer}, allow_redirects=True,
                    )
                    if r.status_code == 200 and r.content:
                        return r.content
                    last_err = f"HTTP {r.status_code}"
                except requests.RequestException as e:
                    last_err = f"{type(e).__name__}: {e}"
                    time.sleep(0.8 * (attempt + 1))
        raise DownloadError(f"下载失败: {last_err}")


def video_to_gif(video: bytes, cfg: Config) -> bytes:
    """视频截前 3 秒转 GIF（需要 imageio-ffmpeg）。"""
    import subprocess
    import tempfile
    from pathlib import Path

    try:
        import imageio_ffmpeg
    except ImportError as e:  # noqa: BLE001
        raise DownloadError("未安装 imageio-ffmpeg，无法视频转 GIF") from e

    exe = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in.mp4"
        dst = Path(td) / "out.gif"
        src.write_bytes(video)
        s = cfg.target_size
        vf = (f"fps=12,scale={s}:{s}:force_original_aspect_ratio=decrease,"
              f"pad={s}:{s}:(ow-iw)/2:(oh-ih)/2:color=white,"
              f"split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse")
        cmd = [exe, "-y", "-t", "3", "-i", str(src), "-vf", vf,
               "-loop", "0", str(dst)]
        subprocess.run(cmd, capture_output=True, check=True)
        return dst.read_bytes()
