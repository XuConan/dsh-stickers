#!/usr/bin/env python3
"""Check the release artefacts before they are published.

Runs in CI (Windows) and locally:

    python dsh-stickers/scripts/verify_dist.py

Fails loudly when the portable zip is missing, when `install.bat` lost its GBK
encoding or CRLF line endings, or when the plugin inside the zip is stale.
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZIP = ROOT / "dist" / "dsh-stickers-portable.zip"
BAT = ROOT / "install.bat"
PKG = ROOT / "package.json"


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def main() -> int:
    if not PKG.is_file():
        fail(f"缺少 {PKG}")
    version = json.loads(PKG.read_text(encoding="utf-8"))["version"]

    if not BAT.is_file():
        fail(f"缺少 {BAT}（先跑 scripts/make_install_bat.py）")
    raw = BAT.read_bytes()
    if raw[:2] != b"@e":
        fail(f"install.bat 头部不是 @echo off：{raw[:8]!r}")
    if b"\r\n" not in raw or raw.replace(b"\r\n", b"").count(b"\n"):
        fail("install.bat 不是全 CRLF 换行，cmd.exe 会解析失败")
    try:
        text = raw.decode("gbk")
    except UnicodeDecodeError as exc:
        fail(f"install.bat 不是 GBK 编码：{exc}")
    if "plugin --profile" not in text or "chcp 936" not in text:
        fail("install.bat 内容不完整")
    print(f"[ok] install.bat {len(raw)} B，GBK/CRLF，含 plugin --profile 调用")

    if not ZIP.is_file():
        fail(f"缺少 {ZIP}")
    with zipfile.ZipFile(ZIP) as zf:
        names = zf.namelist()
        required = [
            "install.bat",
            "dsh-stickers/index.js",
            "dsh-stickers/package.json",
            "douyin-sticker-bot/app/__main__.py",
            "douyin-sticker-bot/run.bat",
        ]
        for name in required:
            if name not in names:
                fail(f"便携包里缺少 {name}")
        plugin_version = json.loads(zf.read("dsh-stickers/package.json"))["version"]
        if plugin_version != version:
            fail(f"包里插件版本 {plugin_version} 与 package.json {version} 不一致")
        index = zf.read("dsh-stickers/index.js").decode("utf-8")
        if "resolveDefineTool" not in index:
            fail("包里的 index.js 是旧版（仍静态依赖 @deepseek-ai/dsh-tools）")
    print(f"[ok] {ZIP.name} {ZIP.stat().st_size / 1024:.1f} KB，{len(names)} 个条目，插件 {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
