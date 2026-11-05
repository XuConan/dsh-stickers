"""表情包市场（来源）适配层。

主流程只认 ``Market`` 协议：给分类、给条目，剩下的下载/归一化/去重/导入都一样。
"""
from __future__ import annotations

from .base import Market, MarketItem, ext_of, is_animated_path
from .github_repo import GithubRepoMarket, pretty_name
from . import registry

__all__ = [
    "Market", "MarketItem", "ext_of", "is_animated_path",
    "GithubRepoMarket", "pretty_name", "registry",
]
