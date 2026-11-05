"""GitHub 图库型市场：仓库里一堆图片，按一级目录当分类。

这类市场不用写代码，给 repo/branch 就够了；ChineseBQB 就是它的第一个实例。
清单走 GitHub trees API（一次拿全，1~2 MB），图片走 CDN 直链。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from .base import MarketItem, ext_of, is_animated_path

TREE_API = "https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1"
DEFAULT_CDN = (
    "https://raw.githubusercontent.com/{repo}/{branch}/",
    "https://cdn.jsdelivr.net/gh/{repo}@{branch}/",
)
IMAGE_EXT = ("jpg", "jpeg", "png", "gif", "webp")

# 「全部表情包」这个伪分类：id 给前端和 ingest 用，实际不按目录过滤
ALL_CATEGORY = "__all__"

# 至少含一个中日韩文字或 emoji，才算「像人话」的分类名（用来跳过 Funny / AI 这类英文前缀）
_HUMAN = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af\u2000-\u2bff\U0001F000-\U0001FAFF]")
# 只认中日韩文字：用来把 `Panda金馆长熊猫🐼` 前面的英文切掉
_CJK = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]")


class GithubRepoMarket:
    """把「GitHub 仓库 + 一级目录」当成一个表情包市场。"""

    kind = "catalog"
    needs_login = False

    def __init__(
        self,
        market_id: str,
        name: str,
        repo: str,
        branch: str = "master",
        cdn: Optional[list[str]] = None,
        include_ext: tuple[str, ...] = IMAGE_EXT,
        exclude_dirs: tuple[str, ...] = (),
        cache_path: Optional[Path] = None,
        ttl_seconds: int = 24 * 3600,
        description: str = "",
    ) -> None:
        self.id = market_id
        self.name = name
        self.repo = repo
        self.branch = branch
        self.cdn = tuple(cdn or DEFAULT_CDN)
        self.include_ext = tuple(e.lower().lstrip(".") for e in include_ext)
        self.exclude_dirs = tuple(exclude_dirs)
        self.cache_path = cache_path
        self.ttl_seconds = ttl_seconds
        self.description = description
        self.last_error: str = ""
        self._mem: Optional[dict] = None

    # ---------------- 清单 ----------------
    def _load_cache(self) -> Optional[dict]:
        if self._mem is not None:
            return self._mem
        if self.cache_path and self.cache_path.exists():
            try:
                self._mem = json.loads(self.cache_path.read_text(encoding="utf-8"))
                return self._mem
            except Exception:  # noqa: BLE001
                return None
        return None

    def is_fresh(self) -> bool:
        m = self._load_cache()
        if not m:
            return False
        return (time.time() - float(m.get("fetched_at") or 0)) < self.ttl_seconds

    def has_manifest(self) -> bool:
        return self._load_cache() is not None

    def fetch_manifest(self) -> dict:
        """真的去 GitHub 拉一次清单并落盘。失败抛 RuntimeError。"""
        import requests  # 本地导入，测试时可以不装

        url = TREE_API.format(repo=self.repo, branch=self.branch)
        try:
            resp = requests.get(url, timeout=180, headers={
                "User-Agent": "douyin-sticker-bot",
                "Accept": "application/vnd.github+json",
            })
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"拉取清单失败（网络）：{exc}") from exc
        if resp.status_code == 403:
            raise RuntimeError(
                "拉取清单被 GitHub 限流（未登录每小时 60 次），"
                "先用已缓存的清单，过一会儿再试")
        if resp.status_code != 200:
            raise RuntimeError(f"拉取清单失败（HTTP {resp.status_code}）")
        try:
            tree = resp.json().get("tree") or []
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"清单不是 JSON：{exc}") from exc

        files = []
        for node in tree:
            if node.get("type") != "blob":
                continue
            path = node.get("path") or ""
            if "/" not in path:            # 仓库根目录的 README 之类
                continue
            if ext_of(path) not in self.include_ext:
                continue
            if path.split("/", 1)[0] in self.exclude_dirs:
                continue
            files.append({"path": path, "size": int(node.get("size") or 0)})

        manifest = {
            "market": self.id,
            "repo": self.repo,
            "branch": self.branch,
            "fetched_at": time.time(),
            "file_count": len(files),
            "files": files,
        }
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        self._mem = manifest
        self.last_error = ""
        return manifest

    def ensure_manifest(self, force: bool = False) -> Optional[dict]:
        """有新鲜缓存就直接用；过期/没有就拉一次，拉不动就退回旧缓存。"""
        cached = self._load_cache()
        if cached and not force and self.is_fresh():
            return cached
        try:
            return self.fetch_manifest()
        except RuntimeError as exc:
            self.last_error = str(exc)
            return cached

    # ---------------- 分类 / 条目 ----------------
    def _files(self) -> list[dict]:
        m = self._load_cache()
        # 读取时再过滤一遍：缓存可能是手工改的/旧版本写的，别让非图片混进来
        out: list[dict] = []
        for f in (m or {}).get("files") or []:
            path = f.get("path") or ""
            if "/" not in path:
                continue
            if ext_of(path) not in self.include_ext:
                continue
            if path.split("/", 1)[0] in self.exclude_dirs:
                continue
            out.append(f)
        return out

    def category_label(self, category: Optional[str]) -> str:
        """分类 id → 卡片上显示的短名；「全部」或空返回空串。"""
        if not category or category in (ALL_CATEGORY, "all"):
            return ""
        return pretty_name(category)

    def categories(self) -> list[dict]:
        buckets: dict[str, dict] = {}
        for f in self._files():
            top = f["path"].split("/", 1)[0]
            b = buckets.setdefault(top, {
                "id": top,
                "name": pretty_name(top),
                "number": category_number(top),
                "count": 0,
            })
            b["count"] += 1
        # 按目录名开头的编号排（000、001…），没有编号的排在最后
        rows = sorted(buckets.values(), key=lambda x: (x["number"] or "9999", x["name"]))
        total = sum(c["count"] for c in rows)
        return [{
            "id": ALL_CATEGORY,
            "name": "全部表情包",
            "number": "",
            "count": total,
        }] + rows

    def items(self, category: Optional[str] = None, query: Optional[str] = None,
              limit: int = 500) -> list[MarketItem]:
        q = (query or "").strip().lower()
        if category in (ALL_CATEGORY, "all"):
            category = None
        out: list[MarketItem] = []
        for f in self._files():
            path = f["path"]
            top = path.split("/", 1)[0]
            if category and top != category:
                continue
            if q and q not in path.lower():
                continue
            out.append(self._item(path))
            if len(out) >= limit:
                break
        return out

    def _item(self, path: str) -> MarketItem:
        top = path.split("/", 1)[0]
        return MarketItem(
            external_id=f"{self.id}:{path}",
            url=self.image_url(path),
            desc=pretty_name(top),
            author="",
            category=pretty_name(top),
            is_animated=is_animated_path(path),
        )

    def image_url(self, path: str, cdn_index: int = 0) -> str:
        base = self.cdn[min(cdn_index, len(self.cdn) - 1)]
        return base.format(repo=self.repo, branch=self.branch) + quote(path)


def pretty_name(dirname: str) -> str:
    """`001Funny_滑稽大佬😏BQB` → `滑稽大佬😏`。

    取第一个「像人话」的片段（含中日韩文字或 emoji）；都没有就退回第一段。
    例如 `110_AI_人工智能_BQB` → `人工智能`、`112PhantomBladeZero_影之刃零_BQB` → `影之刃零`。
    """
    base = dirname[:-3] if dirname.endswith("BQB") else dirname
    base = re.sub(r"^\d+", "", base.strip()).strip("_- ")
    parts = [p.strip("_- .") for p in base.split("_")]
    parts = [p for p in parts if p]
    for p in parts:
        if _HUMAN.search(p):
            # `Panda金馆长熊猫🐼` 这种前缀英文也一并切掉，只留中文那一段
            m = _CJK.search(p)
            if m:
                return p[m.start():].strip("_- .") or p
            return p
    if parts:
        return parts[0]
    return base or dirname


def category_number(dirname: str) -> str:
    """目录名开头的编号（`112` 这种），没有就返回空串。"""
    m = re.match(r"^(\d+)", dirname)
    return m.group(1) if m else ""
