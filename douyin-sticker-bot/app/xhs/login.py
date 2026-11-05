"""小红书登录：开一次带界面的浏览器，让用户扫码，然后把 cookie 存下来。

之后所有抓取都走 ``requests``（这些表情包接口免签名），不用再开浏览器。
profile 用独立目录 ``data/browser-profile-xhs``，绝不动抖音那个。
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional

from ..events import Bus
from .api import LOGIN_COOKIE

LOGIN_URL = "https://www.xiaohongshu.com/"
_COOKIE_DOMAIN_HINT = "xiaohongshu.com"

_LOCK = threading.Lock()
_STATE = {"running": False}


def is_running() -> bool:
    return bool(_STATE.get("running"))


def cookie_file(cfg) -> Path:
    return cfg.xhs_cookie_path


def cookies_from_context(ctx) -> list[dict]:
    """挑出小红书域名下的 cookie，存成 [{name,value}] 就够用了。"""
    out: list[dict] = []
    for c in ctx.cookies():
        domain = c.get("domain") or ""
        if _COOKIE_DOMAIN_HINT not in domain:
            continue
        out.append({"name": c.get("name", ""), "value": c.get("value", ""),
                    "domain": domain, "path": c.get("path") or "/"})
    return out


def save_cookies(cookies: list[dict], cfg) -> None:
    import json
    p = cookie_file(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), "utf-8")


def has_login_cookie(cookies: list[dict]) -> bool:
    return any(c.get("name") == LOGIN_COOKIE and c.get("value")
               for c in cookies)


def start(cfg, bus: Optional[Bus] = None, timeout: int = 300) -> bool:
    """后台开浏览器等扫码；已经在跑返回 False。"""
    with _LOCK:
        if _STATE["running"]:
            return False
        _STATE["running"] = True
    t = threading.Thread(target=_run, args=(cfg, bus, timeout),
                         name="xhs-login", daemon=True)
    t.start()
    return True


def _run(cfg, bus: Optional[Bus], timeout: int) -> None:
    bus = bus or Bus()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        bus.emit("error", msg="没装 playwright，无法打开小红书登录窗口")
        _STATE["running"] = False
        return

    pw = ctx = None
    try:
        cfg.xhs_profile_dir.mkdir(parents=True, exist_ok=True)
        bus.emit("log", msg="正在打开小红书登录窗口，请扫码…")
        bus.emit("need_login", market="xhs",
                 text="请在刚打开的浏览器里扫码登录小红书")
        pw = sync_playwright().start()
        errors: list[str] = []
        for channel in (cfg.browser_channel or "chrome", "msedge", None):
            try:
                ctx = pw.chromium.launch_persistent_context(
                    user_data_dir=str(cfg.xhs_profile_dir),
                    channel=channel,
                    headless=False,
                    viewport={"width": 1280, "height": 900},
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    args=["--disable-blink-features=AutomationControlled"],
                )
                break
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{channel}: {exc}")
                ctx = None
        if ctx is None:
            bus.emit("error", msg="启动浏览器失败：" + " | ".join(errors)[:300])
            return
        ctx.set_default_timeout(30_000)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45_000)
        except Exception:  # noqa: BLE001
            pass

        deadline = time.time() + max(30, timeout)
        saved = False
        while time.time() < deadline:
            cookies = cookies_from_context(ctx)
            if has_login_cookie(cookies):
                save_cookies(cookies, cfg)
                bus.emit("login_state", logged_in=True, market="xhs")
                bus.emit("log", msg="小红书登录成功，cookie 已保存")
                saved = True
                break
            time.sleep(2)
        if not saved:
            bus.emit("log", msg="没等到小红书登录，窗口先留着，下次再试")
    except Exception as exc:  # noqa: BLE001
        bus.emit("error", msg=f"小红书登录失败：{str(exc)[:200]}")
    finally:
        try:
            if ctx:
                ctx.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if pw:
                pw.stop()
        except Exception:  # noqa: BLE001
            pass
        _STATE["running"] = False
