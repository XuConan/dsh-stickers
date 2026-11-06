"""把 client.js 里的卡片 CSS + 结构渲染成一张静态图，便于在没有 DSH 界面时核对排版。

用法：python scripts/preview_panel.py [输出png]
"""
from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLIENT = ROOT / "client.js"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "preview_panel.png"
STICKERS = Path(
    r"D:\Documents\deepseek-harness\default-workspace\douyin-sticker-bot\data\stickers"
)


def extract_css() -> str:
    src = CLIENT.read_text(encoding="utf-8")
    m = re.search(r"const CSS = `(.+?)`\n", src, re.S)
    if not m:
        raise SystemExit("没找到 CSS 模板块")
    return m.group(1)


def pick_images(n: int) -> list[str]:
    files = sorted(p for p in STICKERS.glob("*") if p.suffix.lower() in (".png", ".gif", ".webp", ".jpg"))
    out = []
    for p in files[:n]:
        mime = "image/png" if p.suffix.lower() == ".png" else "image/gif"
        out.append(f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode())
    return out


def card(img: str, status: str, text: str) -> str:
    return (
        '<div class="dshst-card">'
        f'<div class="dshst-photo"><img class="dshst-thumb" src="{img}" alt=""></div>'
        '<div class="dshst-tags"><span class="dshst-tag">PNG</span>'
        '<span class="dshst-tag src">chinesebqb</span>'
        f'<span class="dshst-badge {status}">{text}</span></div>'
        "</div>"
    )


def main() -> None:
    css = extract_css()
    imgs = pick_images(12)
    if not imgs:
        raise SystemExit("素材库是空的，先下载几张")
    statuses = [("wait", "未下载"), ("dl", "已下载"), ("ok", "已有")]
    cards = [card(imgs[i % len(imgs)], *statuses[i % 3]) for i in range(12)]
    html = f"""<!doctype html><meta charset="utf-8">
<style>
html,body {{ margin:0; background:#0f1115; font-family: system-ui, "Segoe UI", sans-serif; }}
.wrap {{ width: 1100px; padding: 16px 20px; box-sizing: border-box; color:#e7e9ee; }}
{css}
</style>
<div class="wrap"><div class="dshst-root" style="height:auto">
  <div class="dshst-grid">{''.join(cards)}</div>
</div></div>
"""
    html_path = ROOT / "data" / "preview_panel.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")

    from playwright.sync_api import sync_playwright

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        pg = b.new_page(viewport={"width": 1120, "height": 760})
        pg.goto(html_path.as_uri())
        pg.wait_for_timeout(600)
        pg.screenshot(path=str(OUT), full_page=True)
        b.close()
    print("shot:", OUT)


if __name__ == "__main__":
    main()
