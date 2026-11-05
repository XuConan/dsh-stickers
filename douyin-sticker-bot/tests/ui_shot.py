"""界面冒烟：用 Playwright 打开本地控制台，收集 JS 报错并截图。

用法：.venv\\Scripts\\python.exe tests/ui_shot.py [port]
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from app.config import Config  # noqa: E402


def main() -> int:
    cfg = Config()
    cfg.ensure_dirs()
    for key in ("TMP", "TEMP"):
        os.environ[key] = str(cfg.tmp_dir)
    tempfile.tempdir = str(cfg.tmp_dir)
    port = int(sys.argv[1]) if len(sys.argv) > 1 else cfg.port
    shot = cfg.tmp_dir / "ui.png"

    errors: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1360, "height": 900})
        page.on("console", lambda m: errors.append(f"[{m.type}] {m.text}")
                if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: errors.append(f"[pageerror] {e}"))
        page.goto(f"http://127.0.0.1:{port}/", wait_until="load", timeout=20_000)
        page.wait_for_timeout(1500)
        print("title:", page.title())
        print("cards:", page.locator(".card").count())
        print("log lines:", page.locator("#log div").count())
        # 触发一次状态刷新按钮
        page.click("#btn-refresh")
        page.wait_for_timeout(800)
        page.screenshot(path=str(shot), full_page=True)
        browser.close()

    print("console issues:", len(errors))
    for e in errors[:10]:
        print("  ", e[:160])
    print("screenshot:", shot, shot.exists() and f"{shot.stat().st_size} bytes")
    return 0 if not any("pageerror" in e or "[error]" in e for e in errors) else 1


if __name__ == "__main__":
    sys.exit(main())
