"""启动入口：python -m app"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path

from . import config, store
from .douyin.worker import Collector
from .events import Bus
from .markets import registry
from .web.server import page_opened, serve

BROWSER_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


def open_url(url: str) -> str:
    """打开控制台页面：优先直接调已知的 Chrome/Edge（最可靠），再退回系统默认。"""
    for exe in BROWSER_CANDIDATES:
        if Path(exe).exists():
            try:
                subprocess.Popen([exe, url], close_fds=True)
                return Path(exe).stem
            except Exception:  # noqa: BLE001
                continue
    try:
        if hasattr(os, "startfile"):
            os.startfile(url)  # type: ignore[attr-defined]  # noqa: S606
            return "默认浏览器"
    except Exception:  # noqa: BLE001
        pass
    try:
        if webbrowser.open(url):
            return "webbrowser"
    except Exception:  # noqa: BLE001
        pass
    return ""


def main() -> None:
    ap = argparse.ArgumentParser(description="抖音表情包采集 -> 微信表情")
    ap.add_argument("--port", type=int, default=None, help="网页端口，默认 8799")
    ap.add_argument("--no-browser", action="store_true", help="启动后不自动打开网页")
    ap.add_argument("--headless", action="store_true", help="浏览器无界面（不适合首次扫码）")
    args = ap.parse_args()

    # 立刻刷新输出，控制台日志不攒缓冲
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True)
        except Exception:  # noqa: BLE001
            pass

    cfg = config.load_config()
    if args.port:
        cfg.port = args.port
    if args.headless:
        cfg.headless = True
    cfg.ensure_dirs()
    # 浏览器/Playwright 的临时文件留在工作区，避免系统 Temp 目录权限问题
    for key in ("TMP", "TEMP"):
        os.environ[key] = str(cfg.tmp_dir)
    tempfile.tempdir = str(cfg.tmp_dir)
    store.init(cfg.db_path)
    registry.init(cfg)

    bus = Bus()
    collector = Collector(cfg, bus)
    collector.start()

    httpd = serve(cfg, bus, collector)
    url = f"http://127.0.0.1:{cfg.port}/"
    print("=" * 56)
    print("  抖音表情包 -> 微信  已启动")
    print(f"  控制台：{url}")
    print(f"  素材库：{cfg.stickers_dir}")
    print(f"  导出夹：{cfg.outbox_dir}")
    print("  关闭本窗口即退出")
    print("=" * 56)

    if not args.no_browser:
        def _open() -> None:
            how = open_url(url)
            if how:
                print(f"  已用 {how} 打开控制台")
            else:
                print("  没能自动打开浏览器")
            threading.Timer(6.0, _retry).start()

        def _retry() -> None:
            if page_opened():
                return
            try:
                os.startfile(url)  # type: ignore[attr-defined]  # noqa: S606
                print("  换个方式再打开一次控制台 …")
            except Exception:  # noqa: BLE001
                pass
            threading.Timer(8.0, _remind).start()

        def _remind() -> None:
            if not page_opened():
                print(f"  浏览器好像没弹出来，手动打开这个地址就行：{url}")

        threading.Timer(1.2, _open).start()

    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\n正在退出…")
    finally:
        collector.close()
        httpd.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    main()
