"""全局配置与路径。"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 插件从 GitHub 装进 node_modules 时，代码目录会被 pnpm 覆盖；DSH 插件会通过
# 这个环境变量把数据挪到用户目录，避免重装丢素材/登录态。
_DATA_ENV = os.environ.get("DSH_STICKERS_DATA", "").strip()
DATA_DIR = Path(_DATA_ENV).expanduser() if _DATA_ENV else ROOT / "data"
CONFIG_FILE = DATA_DIR / "config.json"


@dataclass
class Config:
    port: int = 8799
    browser_channel: str = "chrome"      # 用本机 Chrome，省去下载 Chromium
    headless: bool = False               # 抖音必须带界面，方便扫码
    max_items: int = 60                  # 单次抓取目标条数
    max_scroll_rounds: int = 24
    stale_rounds: int = 4                # 连续 N 轮没有新内容就停
    min_short_edge: int = 160
    aspect_min: float = 0.66
    aspect_max: float = 1.5
    target_size: int = 240               # 微信表情显示约 120px，2x 图更清晰
    max_gif_bytes: int = 1_500_000
    max_gif_frames: int = 200
    dedupe_hamming: int = 6
    download_workers: int = 3
    request_timeout: float = 20.0
    enable_video_gif: bool = False       # 视频转 GIF：需要 imageio-ffmpeg
    login_timeout: int = 300             # 扫码等待秒数

    # ---- 派生路径 ----
    @property
    def db_path(self) -> Path:
        return DATA_DIR / "stickers.db"

    @property
    def profile_dir(self) -> Path:
        return DATA_DIR / "browser-profile"

    @property
    def stickers_dir(self) -> Path:
        return DATA_DIR / "stickers"

    @property
    def outbox_dir(self) -> Path:
        return DATA_DIR / "outbox"

    @property
    def tmp_dir(self) -> Path:
        return DATA_DIR / "tmp"

    @property
    def thumbs_dir(self) -> Path:
        return DATA_DIR / "tmp" / "thumbs"

    @property
    def markets_dir(self) -> Path:
        """市场清单缓存目录（每个市场一份 json）。"""
        return DATA_DIR / "markets"

    @property
    def markets_conf_dir(self) -> Path:
        """用户自己塞 JSON 就能加市场的地方。"""
        return DATA_DIR / "markets.d"

    @property
    def xhs_profile_dir(self) -> Path:
        """小红书登录用的独立 profile，别和抖音那个混。"""
        return DATA_DIR / "browser-profile-xhs"

    @property
    def xhs_cookie_path(self) -> Path:
        """登录一次后把 cookie 存这里，抓取就不用再开浏览器。"""
        return DATA_DIR / "xhs-cookies.json"

    def ensure_dirs(self) -> None:
        for p in (
            DATA_DIR,
            self.profile_dir,
            self.stickers_dir,
            self.outbox_dir,
            self.tmp_dir,
            self.thumbs_dir,
            self.markets_dir,
            self.markets_conf_dir,
            self.xhs_profile_dir,
        ):
            p.mkdir(parents=True, exist_ok=True)


def load_config() -> Config:
    cfg = Config()
    if CONFIG_FILE.exists():
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        valid = {f.name for f in fields(Config)}
        for k, v in raw.items():
            if k in valid:
                setattr(cfg, k, v)
    return cfg


def save_config(cfg: Config) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8"
    )
