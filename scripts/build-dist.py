"""Build the two distributables of the sticker bundle.

1. `dist/dsh-stickers-<version>.tgz` — plain npm tarball, installed with
   `dsh plugin --profile <name> add <tgz>`; the Python backend must already
   exist somewhere and be pointed at with `projectDir` / DSH_STICKERS_PROJECT.
2. `dist/dsh-stickers-portable.zip` — the tarball's contents plus a copy of the
   Python backend, laid out as siblings so the plugin finds it automatically:
   unzip, then `dsh plugin add <dir>/dsh-stickers`.

Run with any Python 3.9+; no third-party packages needed.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # dsh-stickers/
WORKSPACE = ROOT.parent                                 # default-workspace/


def _find_project() -> Path:
    """后端源码在哪：三种布局都认（仓库内同级 / 工作区同级 / 环境变量指定）。"""
    for cand in (os.environ.get("DSH_STICKERS_PROJECT", "").strip(),
                 ROOT / "douyin-sticker-bot",
                 WORKSPACE / "douyin-sticker-bot"):
        if cand and (Path(cand) / "app" / "__main__.py").is_file():
            return Path(cand)
    return WORKSPACE / "douyin-sticker-bot"


PROJECT = _find_project()
DIST = ROOT / "dist"

PLUGIN_FILES = [
    "index.js",
    "client.js",
    "cordis.patch.yml",
    "icon.svg",
    "package.json",
    "README.md",
    "locale/zh.json",
    "locale/en.json",
]
SKIP_DIRS = {".venv", "data", "__pycache__", ".git", ".pytest_cache", "node_modules"}
# 探查脚本会在项目根留下 tmp*.json / tmp<rand>/ 垃圾，别打进包里
SKIP_PREFIXES = ("tmp",)

README_CN = """表情包 → 微信：DSH 插件（一次性安装包）

一、安装（只有一个动作）
  1. 把整个 zip 解压到任意目录，比如 D:\sticker-kit
  2. 双击解压目录里的 install.bat（等它跑完，首次约 1-2 分钟）
  3. 出现「装好了」字样后，关掉 DSH 桌面应用再打开

  install.bat 依次做三件事：找 dsh 命令 → 建好 Python 环境 → 把插件装进
  desktop profile。要装到别的 profile：install.bat <profile名>

  Python 环境没装成也不要紧：插件第一次启动会自己建 venv 装依赖。

  若提示没找到 dsh 命令：命令行里 set DSH_CLI=完整的dsh.cmd路径 后重跑。

二、登录
  抖音、小红书各自扫码一次（面板右上角「登录/检测」）。cookie 存在
  douyin-sticker-bot\data\ 下，插件与 run.bat 启动的控制台共用。

三、目录关系（插件靠这个找后端）
  sticker-kit\
    install.bat
    package.json / index.js / client.js ...   <- 插件本体（就在根目录）
    douyin-sticker-bot\                       <- Python 后端（插件默认找它）
  把后端放到别处时，在 DSH 的 cordis.patch.yml 里给插件配 projectDir，
  或者设环境变量 DSH_STICKERS_PROJECT 指向它。

四、要求
  Windows + Python 3.10+（没装依赖时插件会自己用 py/python 建 venv）。
  首次抓抖音/小红书会让浏览器装一次 Chrome，之后复用本机 Chrome。
"""


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=str(ROOT), check=True)


def read_version() -> str:
    return json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]


def build_portable(version: str) -> Path:
    out = DIST / "dsh-stickers-portable.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        # 插件本体放在压缩包根目录：解压目录 / node_modules 装进来都能直接被
        # index.js 里的 resolveProject() 找到旁边的 douyin-sticker-bot
        for rel in PLUGIN_FILES:
            zf.write(ROOT / rel, rel)
        for base, dirs, files in os.walk(PROJECT):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(SKIP_PREFIXES)]
            for name in files:
                if name.endswith(".pyc"):
                    continue
                # 探查脚本偶尔会把临时 json 写进项目根，别打进包
                if name.startswith(SKIP_PREFIXES):
                    continue
                full = Path(base) / name
                rel = full.relative_to(PROJECT)
                zf.write(full, f"douyin-sticker-bot/{rel.as_posix()}")
        zf.writestr("安装说明.txt", README_CN)
        zf.write(ROOT / "install.bat", "install.bat")
    return out


def main() -> int:
    DIST.mkdir(exist_ok=True)
    version = read_version()
    node = os.environ.get("DSH_NODE") or shutil.which("node")
    pnpm = os.environ.get("DSH_PNPM")
    if node and pnpm:
        run([node, pnpm, "pack", "--pack-destination", "dist"])
    else:
        print("[skip] node/pnpm not found; set DSH_NODE and DSH_PNPM to build the tarball")

    zip_path = build_portable(version)
    tgz = DIST / f"dsh-stickers-{version}.tgz"
    for p in (tgz, zip_path):
        if p.exists():
            print(f"{p.relative_to(WORKSPACE)}  {p.stat().st_size / 1024:.1f} KB")
        else:
            print(f"[missing] {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
