"""把抖音接口返回的 JSON 解析成表情候选（纯函数，方便单测）。"""
from __future__ import annotations

import re
from typing import Any, Iterable

_SEC_UID_RE = re.compile(r"/user/([A-Za-z0-9_\-]+)")


def extract_sec_uid(value: str) -> str | None:
    """从主页链接/分享文本里抠出 sec_uid。"""
    if not value:
        return None
    m = _SEC_UID_RE.search(value)
    if m:
        return m.group(1)
    v = value.strip().split()[0] if value.strip() else ""
    if re.fullmatch(r"MS4wLjABAAAA[A-Za-z0-9_\-]+", v):
        return v
    return None


def iter_awemes(node: Any, depth: int = 0) -> Iterable[dict]:
    """递归找出所有带 aweme_id 的字典（兼容 search/post/feed 等不同包装）。"""
    if depth > 12:
        return
    if isinstance(node, dict):
        if "aweme_id" in node and isinstance(node.get("aweme_id"), (str, int)):
            yield node
            return
        for v in node.values():
            yield from iter_awemes(v, depth + 1)
    elif isinstance(node, list):
        for v in node:
            yield from iter_awemes(v, depth + 1)


def _pick_urls(img: dict) -> list[str]:
    if isinstance(img, str):
        return [img] if img.startswith("http") else []
    urls = list(img.get("url_list") or [])
    for key in ("download_url_list", "origin_url_list"):
        urls.extend(img.get(key) or [])
    return [u for u in urls if isinstance(u, str) and u.startswith("http")]


def _image_list(item: dict) -> list[dict]:
    imgs = item.get("images") or []
    if not imgs:
        post = item.get("image_post_info") or {}
        imgs = post.get("images") or []
    out = []
    for img in imgs:
        urls = _pick_urls(img)
        if not urls:
            continue
        w = img.get("width") or (img.get("image_width") if isinstance(img, dict) else 0) or 0
        h = img.get("height") or (img.get("image_height") if isinstance(img, dict) else 0) or 0
        out.append({"url": urls[-1], "urls": urls, "width": int(w or 0), "height": int(h or 0)})
    return out


def _video_info(item: dict) -> dict | None:
    video = item.get("video") or {}
    play = video.get("play_addr") or video.get("playAddr") or {}
    urls = [u for u in (play.get("url_list") or []) if isinstance(u, str)]
    if not urls:
        return None
    cover = video.get("cover") or video.get("dynamic_cover") or {}
    covers = _pick_urls(cover) if isinstance(cover, dict) else []
    return {
        "urls": urls,
        "cover": covers[-1] if covers else "",
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "duration": int(video.get("duration") or 0),
    }


def candidate_from_item(item: dict) -> list[dict]:
    """一个作品 -> 若干候选（图文作品每张图一个候选）。"""
    aweme_id = str(item.get("aweme_id") or "")
    desc = (item.get("desc") or "").strip()
    author = ((item.get("author") or {}).get("nickname") or "").strip()
    out: list[dict] = []

    images = _image_list(item)
    if images:
        for idx, img in enumerate(images):
            out.append({
                "aweme_id": f"{aweme_id}_{idx}" if idx else aweme_id,
                "desc": desc,
                "author": author,
                "source_type": "image",
                "url": img["url"],
                "video_url": "",
                "width": img["width"],
                "height": img["height"],
                "is_animated": img["url"].lower().endswith(".gif")
                or img["url"].lower().endswith(".webp"),
            })
        return out

    video = _video_info(item)
    if video:
        out.append({
            "aweme_id": aweme_id,
            "desc": desc,
            "author": author,
            "source_type": "video",
            "url": video["cover"] or video["urls"][-1],
            "video_url": video["urls"][-1],
            "width": video["width"],
            "height": video["height"],
            "is_animated": True,
        })
    return out


def _sticker_url(sticker: dict) -> tuple[str, int, int, bool]:
    """贴纸优先取动图（webp/gif），没有就退回静图。"""
    for key, animated in (("animate_url", True), ("static_url", False)):
        src = sticker.get(key) or {}
        urls = [u for u in (src.get("url_list") or [])
                if isinstance(u, str) and u.startswith("http")]
        if urls:
            return urls[0], int(src.get("width") or 0), int(src.get("height") or 0), animated
    return "", 0, 0, False


def _sticker_key(sticker: dict, idx: int) -> str:
    for key in ("animate_url", "static_url"):
        uri = (sticker.get(key) or {}).get("uri") or ""
        if uri:
            return "sticker_" + uri.rstrip("/").rsplit("/", 1)[-1][:40]
    return f"sticker_{idx}"


def parse_sticker_page(data: Any) -> tuple[list[dict], int, bool]:
    """「我的表情包」接口 -> (候选列表, next_cursor, 是否已取完)。

    接口形如 /aweme/v1/web/im/resource/list/aggregation/?scenes=CUSTOM_STICKER_PAGE，
    返回 custom_sticker_page_list.resources[].stickers[]。
    """
    page = (data or {}).get("custom_sticker_page_list") or {}
    out: list[dict] = []
    seen: set[str] = set()
    for res in page.get("resources") or []:
        name = (res.get("display_name") or "").strip() or "抖音表情包"
        for idx, st in enumerate(res.get("stickers") or []):
            url, w, h, animated = _sticker_url(st)
            if not url:
                continue
            key = _sticker_key(st, idx)
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "aweme_id": key,
                "desc": name,
                "author": "",
                "source_type": "sticker",
                "url": url,
                "video_url": "",
                "width": w,
                "height": h,
                "is_animated": animated,
            })
    return out, int(page.get("next_cursor") or 0), bool(page.get("is_completed"))


def parse_payload(data: Any) -> list[dict]:
    """接口响应 -> 候选列表，按 aweme_id 去重。"""
    seen: set[str] = set()
    out: list[dict] = []
    for aweme in iter_awemes(data):
        for cand in candidate_from_item(aweme):
            key = cand["aweme_id"]
            if key in seen:
                continue
            seen.add(key)
            if not cand["url"] and not cand["video_url"]:
                continue
            out.append(cand)
    return out
