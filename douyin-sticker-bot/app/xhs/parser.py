"""把小红书的原始响应转成统一的 MarketItem。

两个来源的字段不一样：

    smiles   每条 {fileId, fileName(图片直链), width, height}
    redmoji  每条 {image_name:"[微笑R]", image:"https://...png"}

``external_id`` 必须稳定——store 里 url 有唯一索引，而入库前是按 aweme_id
查重的，所以这里一律用不会被签名参数污染的字段拼出来。
"""
from __future__ import annotations

from typing import Iterable

from ..markets.base import MarketItem, is_animated_path

MARKET_ID = "xhs"
SMILES_DESC = "小红书表情包"


def smiles_to_items(smiles: Iterable[dict]) -> list[MarketItem]:
    """我的表情包 → 候选。"""
    items: list[MarketItem] = []
    seen: set[str] = set()
    for s in smiles or []:
        if not isinstance(s, dict):
            continue
        url = (s.get("fileName") or s.get("imageUrl") or "").strip()
        file_id = str(s.get("fileId") or "").strip()
        if not url or not file_id:
            continue
        ext_id = f"xhs_smile_{file_id}"
        if ext_id in seen:
            continue
        seen.add(ext_id)
        items.append(MarketItem(
            external_id=ext_id,
            url=url,
            desc=SMILES_DESC,
            author="",
            category="我的表情包",
            is_animated=is_animated_path(url),
            width=int(s.get("width") or 0),
            height=int(s.get("height") or 0),
        ))
    return items


def redmoji_to_items(emojis: Iterable[dict]) -> list[MarketItem]:
    """小红书自带表情 → 候选。desc 用原名（[微笑R]），导进微信好认。"""
    items: list[MarketItem] = []
    seen: set[str] = set()
    for e in emojis or []:
        if not isinstance(e, dict):
            continue
        url = (e.get("image") or "").strip()
        name = (e.get("image_name") or "").strip()
        if not url or not name:
            continue
        ext_id = f"xhs_redmoji_{name}"
        if ext_id in seen:
            continue
        seen.add(ext_id)
        items.append(MarketItem(
            external_id=ext_id,
            url=url,
            desc=name,
            author="",
            category="小红书表情",
            # 自带表情都是 200×200 静态图（个别是 webp 但也只有一帧），当静态处理
            is_animated=False,
        ))
    return items


def to_candidates(items: Iterable[MarketItem]) -> list[dict]:
    return [it.to_candidate(MARKET_ID) for it in items]
