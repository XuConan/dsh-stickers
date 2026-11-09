"""Playwright 采集线程：登录一次、按关键词/账号抓抖音作品。"""
from __future__ import annotations

import json
import queue
import random
import threading
import time
from urllib.parse import quote

from playwright.sync_api import sync_playwright

from .. import store
from ..config import Config
from ..events import Bus
from . import parser

LOGIN_COOKIES = ("sessionid", "sessionid_ss", "sid_tt")
CAPTCHA_SEL = (
    "#captcha_container, .captcha_verify_container, "
    "iframe[src*='captcha'], .vc-captcha-container"
)
# 自己账号里的两个列表：收藏 / 点赞。value 不用填，页面里点对应标签页。
SELF_TABS = {
    "collection": ("https://www.douyin.com/user/self?showTab=collection", ("收藏",)),
    "like": ("https://www.douyin.com/user/self?showTab=like", ("喜欢",)),
}
# 每种模式只认自己那个列表的接口，避免把「作品/喜欢」也混进来：
# 收藏 = listcollection，喜欢 = favorite，主页作品 = post，搜索 = search。
MODE_ENDPOINTS = {
    "collection": ("aweme/listcollection/",),
    "like": ("aweme/favorite/",),
    "user": ("aweme/post/",),
    "keyword": ("search",),
}
# 「我的表情包」= 抖音的自定义表情/收藏贴纸，直接翻这个接口（免签名，靠登录态 cookie）。
STICKER_API = (
    "https://www-hj.douyin.com/aweme/v1/web/im/resource/list/aggregation/"
    "?device_platform=webapp&aid=1128&channel=channel_pc_web&app_id=1128"
    "&scenes=CUSTOM_STICKER_PAGE&custom_cursor={cursor}&custom_limit=50"
    "&source=CUSTOM_STICKER_PAGE&update_version_code=170400&pc_client_type=1"
    "&pc_libra_divert=Windows&support_h265=1&support_dash=1&cpu_core_num=12"
    "&version_code=170400&version_name=17.4.0&cookie_enabled=true"
    "&screen_width=1440&screen_height=900&browser_language=zh-CN"
    "&browser_platform=Win32&browser_name=Chrome&browser_version=128.0.0.0"
)


class Collector:
    def __init__(self, cfg: Config, bus: Bus):
        self.cfg = cfg
        self.bus = bus
        self._in: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._pw = None
        self._ctx = None
        self._page = None
        self._captured: dict[str, dict] = {}
        self._collecting = False
        self._mode_filter: tuple = ()
        self.busy = False
        self.logged_in = False

    # ---------------- 外部接口 ----------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="douyin-collector",
                                        daemon=True)
        self._thread.start()

    def submit(self, kind: str, **payload) -> None:
        self._in.put({"kind": kind, **payload})

    def close(self) -> None:
        self.submit("close")

    # ---------------- 线程主循环 ----------------
    def _loop(self) -> None:
        self.start_ok = False
        while True:
            cmd = self._in.get()
            try:
                kind = cmd["kind"]
                if kind == "close":
                    self._shutdown()
                    return
                if kind == "login":
                    self._ensure_browser()
                    self._ensure_login()
                elif kind == "collect":
                    self._collect(cmd.get("mode", "keyword"), cmd.get("value", ""))
                elif kind == "check":
                    self._ensure_browser()
                    self.logged_in = self._check_login()
                    self.bus.emit("login_state", logged_in=self.logged_in)
            except Exception as e:  # noqa: BLE001
                self.busy = False
                self.bus.emit("error", msg=f"{type(e).__name__}: {e}")

    # ---------------- 浏览器 ----------------
    def _ensure_browser(self) -> None:
        if self._page is not None:
            return
        self.cfg.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        errors = []
        for channel in (self.cfg.browser_channel or "chrome", "msedge", None):
            try:
                self._ctx = self._pw.chromium.launch_persistent_context(
                    user_data_dir=str(self.cfg.profile_dir),
                    channel=channel,
                    headless=self.cfg.headless,
                    viewport={"width": 1440, "height": 950},
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    args=["--disable-blink-features=AutomationControlled"],
                )
                break
            except Exception as e:  # noqa: BLE001
                errors.append(f"{channel}: {e}")
                self._ctx = None
        if self._ctx is None:
            raise RuntimeError("启动浏览器失败：" + " | ".join(errors))
        self._ctx.set_default_timeout(30_000)
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self._page.on("response", self._on_response)

    def _shutdown(self) -> None:
        try:
            if self._ctx:
                self._ctx.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:  # noqa: BLE001
            pass
        self._ctx = self._pw = self._page = None

    # ---------------- 登录 ----------------
    def _check_login(self) -> bool:
        if not self._ctx:
            return False
        try:
            for url in ("https://www.douyin.com", "https://www.douyin.com/"):
                names = {c.get("name", "") for c in self._ctx.cookies(url)}
                if names & set(LOGIN_COOKIES):
                    return True
        except Exception:  # noqa: BLE001
            return False
        return False

    def _ensure_login(self) -> None:
        if self._check_login():
            self.logged_in = True
            self.bus.emit("login_state", logged_in=True)
            return
        self.logged_in = False
        self.bus.emit("need_login",
                      msg="请在弹出的浏览器里扫码登录抖音，登录后会自动继续")
        self._open_login_page()
        deadline = time.time() + self.cfg.login_timeout
        while time.time() < deadline:
            if self._check_login():
                self.logged_in = True
                self.bus.emit("login_state", logged_in=True)
                return
            time.sleep(3)
        raise RuntimeError("等待抖音扫码登录超时，请重试")

    def _open_login_page(self) -> None:
        """把登录页打开并切到前台；打不开要说清楚，别留个白屏让人猜。"""
        # 上一轮登录把窗口关掉了：这个 page 已经死了，得整个重启浏览器
        try:
            if self._page is None or self._page.is_closed():
                self._shutdown()
                self._ensure_browser()
        except Exception:  # noqa: BLE001
            self._shutdown()
            self._ensure_browser()
        try:
            self._page.bring_to_front()
        except Exception:  # noqa: BLE001
            pass
        last = ""
        for url in ("https://www.douyin.com/", "https://www.douyin.com"):
            try:
                self._page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                last = ""
                break
            except Exception as exc:  # noqa: BLE001
                last = f"{type(exc).__name__}: {exc}".splitlines()[0]
                self.bus.emit("log", msg=f"打开登录页失败（{url}）：{last}")
                # 常见于用户把那个窗口关了：重启浏览器再来一次
                try:
                    if self._page is None or self._page.is_closed():
                        self._shutdown()
                        self._ensure_browser()
                        self._page.goto(url, wait_until="domcontentloaded",
                                        timeout=45_000)
                        last = ""
                        break
                except Exception:  # noqa: BLE001
                    pass
        try:
            self._page.bring_to_front()
        except Exception:  # noqa: BLE001
            pass
        if last:
            self.bus.emit(
                "warn", msg=f"浏览器起来了，但抖音首页没加载出来（{last}）。"
                           "可以在那个窗口里刷新一下，或手动打开 douyin.com 再扫码。")
        else:
            self.bus.emit("log", msg="登录页已打开，扫码后会自动继续")

    # ---------------- 抓取 ----------------
    def _on_response(self, resp) -> None:  # noqa: ANN001
        if not self._collecting:
            return
        try:
            url = resp.url
        except Exception:  # noqa: BLE001
            return
        if "/aweme/v1/web/" not in url:
            return
        if self._mode_filter and not any(k in url for k in self._mode_filter):
            return
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            return
        try:
            items = parser.parse_payload(data)
        except Exception:  # noqa: BLE001
            return
        for it in items:
            self._captured.setdefault(it["aweme_id"], it)

    def _captcha(self) -> bool:
        """只有「真的看得见」的验证框才算，页面上常驻的隐藏容器不算。"""
        try:
            loc = self._page.locator(CAPTCHA_SEL)
            for i in range(min(loc.count(), 5)):
                try:
                    if loc.nth(i).is_visible():
                        return True
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            pass
        try:
            title = (self._page.title() or "").strip()
            if "验证中间页" in title or "安全验证" in title:
                return True
            if "/captcha" in (self._page.url or "").lower():
                return True
        except Exception:  # noqa: BLE001
            pass
        return False

    def _wait_human(self, what: str, timeout: float) -> bool:
        """提示用户在浏览器里手动完成（滑块/登录），返回是否已解除。"""
        self.bus.emit("warn", msg=f"抖音要求{what}：请在弹出的浏览器里手动完成，完成后会自动继续")
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(1.5)
            if not self._captcha():
                return True
        return False

    def _navigate(self, url: str) -> None:
        self._page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        time.sleep(random.uniform(2.0, 3.0))

    def _open_tab(self, labels: tuple) -> None:
        """点开「收藏」「喜欢」这类标签页（URL 带了 showTab 也点一下更稳）。"""
        for lab in labels:
            try:
                loc = self._page.get_by_text(lab, exact=True)
                if loc.count() > 0:
                    loc.first.click(timeout=4_000)
                    time.sleep(random.uniform(1.5, 2.5))
                    self.bus.emit("log", msg=f"已切换到「{lab}」列表")
                    return
            except Exception:  # noqa: BLE001
                continue

    def _collect(self, mode: str, value: str) -> None:
        value = (value or "").strip()
        if mode == "sticker":
            self._collect_stickers(value)
            return
        if mode not in SELF_TABS and not value:
            raise RuntimeError("请输入关键词或账号主页链接")
        self._ensure_browser()
        self._ensure_login()
        self.busy = True
        self._captured = {}
        self._collecting = True
        self._mode_filter = MODE_ENDPOINTS.get(mode, ())
        run_id = store.create_run(mode, value or mode)
        started = time.time()
        tab_labels: tuple = ()
        try:
            if mode in SELF_TABS:
                url, tab_labels = SELF_TABS[mode]
            elif mode == "keyword":
                url = "https://www.douyin.com/search/" + quote(value)
            else:
                url = self._resolve_user_url(value)
            self.bus.emit("progress", phase="browse", count=0, msg="打开页面…")
            self._navigate(url)
            if self._captcha():
                if not self._wait_human("人机验证（拖动滑块）",
                                        min(self.cfg.login_timeout, 120)):
                    raise RuntimeError("人机验证未完成，请重试")
                self.bus.emit("log", msg="验证通过，重新打开页面…")
                self._navigate(url)
            if tab_labels:
                self._open_tab(tab_labels)

            stale, last = 0, 0
            for rnd in range(1, self.cfg.max_scroll_rounds + 1):
                if len(self._captured) >= self.cfg.max_items:
                    break
                try:
                    self._page.mouse.wheel(0, random.randint(1500, 2400))
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(random.uniform(0.8, 1.6))
                n = len(self._captured)
                if n > last:
                    stale, last = 0, n
                else:
                    stale += 1
                self.bus.emit("progress", phase="browse", count=n, round=rnd)
                if self._captcha():
                    if not self._wait_human("人机验证（拖动滑块）", 180):
                        break
                    continue
                if stale >= self.cfg.stale_rounds:
                    break
        except Exception as exc:  # noqa: BLE001
            store.finish_run(run_id, {
                "error": str(exc)[:200], "captured": len(self._captured),
                "seconds": round(time.time() - started, 1),
            })
            raise
        finally:
            self._collecting = False

        self._finish_collect(run_id, started)

    def _collect_stickers(self, value: str) -> None:
        """「我的表情包」：抖音自定义表情（收藏贴纸），直接翻接口，不用滚页面。"""
        self._ensure_browser()
        self._ensure_login()
        self.busy = True
        self._captured = {}
        self._collecting = False
        run_id = store.create_run("sticker", value or "sticker")
        started = time.time()
        try:
            self._fetch_stickers()
        except Exception as exc:  # noqa: BLE001
            self.busy = False
            store.finish_run(run_id, {
                "error": str(exc)[:200], "captured": len(self._captured),
                "seconds": round(time.time() - started, 1),
            })
            raise
        self._finish_collect(run_id, started)

    def _fetch_stickers(self) -> None:
        if "douyin.com" not in (self._page.url or ""):
            self._navigate("https://www.douyin.com/")
        cursor, pages = 0, 0
        self.bus.emit("progress", phase="browse", count=0, msg="读取表情包…")
        # 表情包是自己的库，全都要（不受搜索模式的 max_items 限制）
        while pages < 60 and len(self._captured) < 600:
            url = STICKER_API.format(cursor=cursor)
            try:
                raw = self._page.evaluate(
                    "async (u) => { const r = await fetch(u, {credentials: 'include'});"
                    " return {status: r.status, text: await r.text()}; }", url)
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"读取表情包列表失败：{exc}") from exc
            status = int((raw or {}).get("status") or 0)
            if status != 200:
                raise RuntimeError(f"读取表情包列表失败（HTTP {status}），可能未登录")
            try:
                data = json.loads((raw or {}).get("text") or "{}")
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"表情包列表不是 JSON：{exc}") from exc
            items, cursor, done = parser.parse_sticker_page(data)
            for it in items:
                if len(self._captured) >= 600:
                    break
                self._captured.setdefault(it["aweme_id"], it)
            pages += 1
            self.bus.emit("progress", phase="browse", count=len(self._captured), round=pages)
            if done or not cursor:
                break
        self.bus.emit("log", msg=f"表情包列表读取完成，共 {len(self._captured)} 个")

    def _finish_collect(self, run_id: int, started: float) -> None:
        new_count = skipped = video_skipped = 0
        for cand in list(self._captured.values()):
            w, h = cand.get("width") or 0, cand.get("height") or 0
            # 表情包（sticker）本身就是小图，别按作品的尺寸门槛筛掉
            too_small = (cand.get("source_type") != "sticker"
                         and bool(w and h and min(w, h) < self.cfg.min_short_edge))
            # 视频作品要先转 GIF 才有用，没开就是纯噪音（表情包基本都是图），直接不入库
            if cand.get("source_type") == "video" and not self.cfg.enable_video_gif:
                video_skipped += 1
                continue
            cid = store.add_candidate(cand, status="skipped" if too_small else "new")
            if not cid:
                continue
            if too_small:
                skipped += 1
                continue
            new_count += 1
            self.bus.emit("candidate", id=cid)

        store.finish_run(run_id, {
            "captured": len(self._captured), "new": new_count,
            "skipped": skipped, "skipped_video": video_skipped,
            "seconds": round(time.time() - started, 1),
        })
        self.busy = False
        if not self._captured:
            self.bus.emit(
                "warn",
                msg="这次一条都没抓到：确认已登录、浏览器里那个页面能看到内容（滑几下试试）；"
                    "如果列表是空的或网页版看不到，就换「关键词搜索」找。",
            )
        elif video_skipped:
            self.bus.emit("log", msg=f"跳过 {video_skipped} 个视频作品（表情包只收图片）")
        self.bus.emit("collect_done", captured=len(self._captured),
                      new=new_count, skipped=skipped, skipped_video=video_skipped)

    def _resolve_user_url(self, value: str) -> str:
        sec = parser.extract_sec_uid(value)
        if sec and "douyin.com/user/" in value:
            return f"https://www.douyin.com/user/{sec}"
        if value.startswith("http"):
            self._page.goto(value, wait_until="domcontentloaded", timeout=60_000)
            time.sleep(2)
            sec = parser.extract_sec_uid(self._page.url) or parser.extract_sec_uid(
                self._page.content()[:20000])
            if sec:
                return f"https://www.douyin.com/user/{sec}"
            raise RuntimeError("没从链接里找到账号，请直接粘贴主页 https://www.douyin.com/user/...")
        return f"https://www.douyin.com/user/{value}"
