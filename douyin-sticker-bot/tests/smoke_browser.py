"""浏览器可用性冒烟：确认 Playwright 能拉起本机 Chrome，并识别抖音验证页。

用法：.venv\\Scripts\\python.exe tests/smoke_browser.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Config  # noqa: E402
from app.douyin.worker import Collector  # noqa: E402
from app.events import Bus  # noqa: E402


def main() -> int:
    cfg = Config()
    cfg.ensure_dirs()
    cfg.headless = True
    for key in ("TMP", "TEMP"):
        os.environ[key] = str(cfg.tmp_dir)
    tempfile.tempdir = str(cfg.tmp_dir)

    bus = Bus()
    col = Collector(cfg, bus)

    print("1) 启动浏览器（headless）…")
    col._ensure_browser()  # noqa: SLF001
    page = col._page  # noqa: SLF001
    print("   page:", "ok" if page else "None")

    print("2) 打开 douyin.com 首页 …")
    resp = page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=45_000)
    print("   status:", resp.status if resp else "?")
    print("   title:", page.title()[:40])

    print("3) 验证页/登录态检测 …")
    print("   captcha:", col._captcha())  # noqa: SLF001
    print("   logged_in:", col._check_login())  # noqa: SLF001

    print("4) 关闭浏览器 …")
    col._shutdown()  # noqa: SLF001
    print("\n[PASS] 浏览器冒烟通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
