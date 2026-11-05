"""内置市场定义 + 注册表。

内置两个：
- ``douyin``     抖音（live：要浏览器 + 登录，逻辑在 app/douyin/worker.py）
- ``chinesebqb`` 中文表情包库（GitHub 图库，免登录）

``data/markets.d/*.json`` 里丢一份配置就能再加一个 GitHub 图库型市场，不用改代码。
"""
from __future__ import annotations

import json
from typing import Optional

from .github_repo import GithubRepoMarket

DOUYIN_MODES = [
    {"id": "sticker", "name": "我的表情包"},
    {"id": "collection", "name": "我的收藏"},
    {"id": "like", "name": "我点赞的"},
    {"id": "keyword", "name": "关键词搜索"},
    {"id": "user", "name": "指定账号"},
]


class DouyinMarket:
    """抖音是 live 市场：真正的抓取在 Collector 里，这里只提供元信息。"""

    id = "douyin"
    name = "抖音表情包"
    kind = "live"
    needs_login = True
    description = "从抖音网页版抓你自己的表情包 / 收藏 / 点赞，需要扫码登录一次"
    modes = DOUYIN_MODES

    def categories(self) -> list[dict]:
        return []

    def items(self, category: Optional[str] = None, query: Optional[str] = None,
              limit: int = 500) -> list:
        raise NotImplementedError("抖音走 Collector，不通过 items() 取条目")


XHS_MODES = [
    {"id": "smiles", "name": "我的表情包"},
    {"id": "redmoji", "name": "小红书自带表情"},
]


class XhsMarket:
    """小红书表情包：接口免签名，只要登录 cookie。"""

    id = "xhs"
    name = "小红书"
    kind = "live"
    needs_login = True
    description = "小红书私信表情面板里的表情包收藏（需登录），以及 166 个自带表情（免登录）"
    modes = XHS_MODES

    def categories(self) -> list[dict]:
        return []

    def items(self, category: Optional[str] = None, query: Optional[str] = None,
              limit: int = 500) -> list:
        raise NotImplementedError("小红书走 app/xhs/sync.py，不通过 items() 取条目")


_CFG = None


def init(cfg) -> None:
    """由 app 启动时调用，告诉注册表清单放哪儿。"""
    global _CFG
    _CFG = cfg


def _mk_cfg() -> Optional[object]:
    if _CFG is not None:
        return _CFG
    try:
        from .. import config as cfg_mod
        return cfg_mod.load_config()
    except Exception:  # noqa: BLE001
        return None


def chinesebqb(cfg=None) -> GithubRepoMarket:
    cfg = cfg or _mk_cfg()
    cache = (cfg.markets_dir / "chinesebqb.json") if cfg else None
    return GithubRepoMarket(
        market_id="chinesebqb",
        name="中文表情包库",
        repo="zhaoolee/ChineseBQB",
        branch="master",
        # 这些目录不是表情包分类：站点源码、脚本、仓库说明
        exclude_dirs=("site", ".github", "README", "README.assets", "maker", "memory"),
        cache_path=cache,
        description="zhaoolee/ChineseBQB：中文梗图 / 表情包合集，按分类浏览",
    )


def load_json_markets(cfg=None, force: bool = False) -> list[GithubRepoMarket]:
    """读 data/markets.d/*.json，支持随时丢文件加市场（force 保留兼容，实际每次都重读）。"""
    cfg = cfg or _mk_cfg()
    if not cfg:
        return []
    d = cfg.markets_conf_dir
    if not d.exists():
        return []
    out: list[GithubRepoMarket] = []
    for f in sorted(d.glob("*.json")):
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if raw.get("kind") != "github-repo" or not raw.get("repo"):
            continue
        mid = str(raw.get("id") or f.stem)
        out.append(GithubRepoMarket(
            market_id=mid,
            name=str(raw.get("name") or mid),
            repo=raw["repo"],
            branch=str(raw.get("branch") or "master"),
            cdn=raw.get("cdn"),
            include_ext=tuple(raw.get("include_ext") or ("jpg", "jpeg", "png", "gif", "webp")),
            exclude_dirs=tuple(raw.get("exclude_dirs") or ()),
            cache_path=cfg.markets_dir / f"{mid}.json",
            description=str(raw.get("description") or ""),
        ))
    return out


def all_markets(cfg=None) -> list:
    cfg = cfg or _mk_cfg()
    return [DouyinMarket(), XhsMarket(), chinesebqb(cfg)] + load_json_markets(cfg)


def get(market_id: str, cfg=None):
    for m in all_markets(cfg):
        if m.id == market_id:
            return m
    return None
