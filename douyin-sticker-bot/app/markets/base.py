"""市场（表情包来源）的公共协议。

一个「市场」只要能给出分类和条目，主流程（下载 → 归一化 → 去重 → 导入微信）
就完全不用知道它是抖音、GitHub 图库还是别的什么。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

ANIMATED_EXT = ("gif", "webp")


@dataclass
class MarketItem:
    """市场里的一条表情（还没下载）。"""
    external_id: str                 # 市场内唯一键，入库时写进 aweme_id
    url: str                         # 图片直链
    desc: str = ""
    author: str = ""
    category: str = ""
    is_animated: bool = False
    width: int = 0
    height: int = 0

    def to_candidate(self, market_id: str) -> dict:
        """转成 store.add_candidate 需要的候选字典。"""
        return {
            "aweme_id": self.external_id,
            "desc": self.desc or "表情包",
            "author": self.author,
            "source_type": "sticker" if self.is_animated else "image",
            "url": self.url,
            "video_url": "",
            "width": self.width,
            "height": self.height,
            "is_animated": 1 if self.is_animated else 0,
            "market": market_id,
        }


@runtime_checkable
class Market(Protocol):
    id: str
    name: str
    kind: str                        # "live"（要浏览器/登录）| "catalog"（纯清单）
    needs_login: bool

    def categories(self) -> list[dict]:
        """[{id, name, count}]；live 市场可以返回空列表。"""
        ...

    def items(self, category: Optional[str] = None, query: Optional[str] = None,
              limit: int = 500) -> list[MarketItem]:
        ...


def ext_of(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def is_animated_path(path: str) -> bool:
    return ext_of(path) in ANIMATED_EXT
