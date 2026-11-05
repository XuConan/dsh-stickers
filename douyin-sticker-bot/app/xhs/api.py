"""小红书表情包接口客户端。

好消息：Facebook…不是，小红书这几个接口**不需要 x-s/x-t 签名**，只要有登录
cookie 就能直接 GET（实测 2026-11）::

    GET https://edith.xiaohongshu.com/api/im/web/smiles
        未登录 → 200 {"code":-101,"msg":"无登录信息，或登录信息为空"}
        已登录 → data.smiles[] = {fileId, fileName(图片直链), width, height}
        这就是「我的表情包」——私信表情面板里 ❤ 那一栏。

    GET https://edith.xiaohongshu.com/api/im/redmoji/detail
        免登录 → data.emoji.tabs[].collection[].emoji[]
                 = {image_name:"[微笑R]", image:"https://picasso-static.xiaohongshu.com/..."}
        共 166 个 200x200 PNG。

所以抓取走普通 requests，浏览器只在「登录一次」的时候用一下。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import requests

from ..douyin.downloader import UA

BASE = "https://edith.xiaohongshu.com"
SMILES = "/api/im/web/smiles"
REDMOJI = "/api/im/redmoji/detail"
REFERER = "https://www.xiaohongshu.com/"
LOGIN_COOKIE = "web_session"


class XhsError(RuntimeError):
    """小红书接口返回了非 0 的业务码。"""


class XhsNeedLogin(XhsError):
    """没有登录信息，或者登录态过期了。"""


def _cookie_header(cookies: list[dict]) -> str:
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies
                     if c.get("name") and c.get("value"))


class XhsApi:
    """很薄的一层：读 cookie、发 GET、把 code 翻成人话。"""

    def __init__(self, cookie_file: Optional[Path] = None,
                 timeout: float = 20.0):
        self.cookie_file = Path(cookie_file) if cookie_file else None
        self.timeout = timeout
        self.cookies: list[dict] = self._load()

    # ---- cookie 存取 ----
    def _load(self) -> list[dict]:
        if not self.cookie_file or not self.cookie_file.exists():
            return []
        try:
            data = json.loads(self.cookie_file.read_text("utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        return [c for c in data if isinstance(c, dict) and c.get("name")]

    def save(self, cookies: list[dict]) -> None:
        self.cookies = [c for c in cookies if isinstance(c, dict) and c.get("name")]
        if not self.cookie_file:
            return
        self.cookie_file.parent.mkdir(parents=True, exist_ok=True)
        self.cookie_file.write_text(
            json.dumps(self.cookies, ensure_ascii=False, indent=2), "utf-8")

    def logged_in(self) -> bool:
        return any(c.get("name") == LOGIN_COOKIE and c.get("value")
                   for c in self.cookies)

    # ---- 请求 ----
    def _get(self, path: str) -> dict:
        headers = {
            "User-Agent": UA,
            "Referer": REFERER,
            "Origin": REFERER.rstrip("/"),
            "Accept": "application/json, text/plain, */*",
        }
        if self.cookies:
            headers["Cookie"] = _cookie_header(self.cookies)
        try:
            r = requests.get(BASE + path, headers=headers,
                             timeout=self.timeout)
        except requests.RequestException as exc:
            raise XhsError(f"请求失败：{exc}") from exc
        if r.status_code == 404:
            raise XhsError("接口不存在（404 page not found）")
        try:
            payload = r.json()
        except ValueError as exc:
            raise XhsError(f"返回的不是 JSON（HTTP {r.status_code}）") from exc
        code = payload.get("code")
        if code == -101:
            raise XhsNeedLogin(payload.get("msg") or "请先登录小红书")
        if code not in (0, None) and not payload.get("success"):
            raise XhsError(payload.get("msg") or f"接口返回 code={code}")
        return payload.get("data") or {}

    # ---- 两个数据源 ----
    def my_smiles(self) -> list[dict]:
        """我的表情包（收藏）。未登录抛 XhsNeedLogin。"""
        data = self._get(SMILES)
        smiles = data.get("smiles")
        return smiles if isinstance(smiles, list) else []

    def redmoji(self) -> list[dict]:
        """小红书自带表情，免登录。"""
        data = self._get(REDMOJI)
        emoji = data.get("emoji") or {}
        out: list[dict] = []
        for tab in (emoji.get("tabs") or []):
            for coll in (tab.get("collection") or []):
                for item in (coll.get("emoji") or []):
                    if isinstance(item, dict):
                        out.append(item)
        return out
