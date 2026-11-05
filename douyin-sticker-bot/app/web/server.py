"""本地网页服务：静态页面 + JSON API + SSE 进度。"""
from __future__ import annotations

import io
import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from PIL import Image

from .. import pipeline, store
from ..config import Config
from ..douyin.downloader import UA, Downloader
from ..douyin.worker import Collector
from ..events import Bus
from ..markets import ingest, registry
from ..wechat import open_outbox
from ..xhs import login as xhs_login
from ..xhs import sync as xhs_sync
from ..xhs.api import XhsApi

# 有没有浏览器真的把首页打开了（启动自查用）
HIT = threading.Event()

# 网格缩略图的目标边长。原图动辄 800KB～3MB，60 张一页就是十几 MB，
# 缩到 360px 后普遍只剩 20-40KB，翻页才快得起来。
THUMB_BOX = 360
# 有的梗图原图十几 MB，光下载就要半分钟 —— 生成缩略图最多等这么久、拉这么多，
# 超了就放弃（这个格子先空着），下次再来才重试。
THUMB_DEADLINE = 12.0
THUMB_MAX_BYTES = 12 * 1024 * 1024

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": UA,
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
})


def fetch_capped(url: str, deadline: float = THUMB_DEADLINE,
                 max_bytes: int = THUMB_MAX_BYTES) -> bytes | None:
    """边下边看表：超时或超量就断开，别让一张图把线程吊死。"""
    started = time.time()
    try:
        with _SESSION.get(url, timeout=(3, 4), stream=True,
                          headers={"Referer": "https://www.douyin.com/"}) as r:
            if r.status_code != 200:
                return None
            buf = bytearray()
            for chunk in r.iter_content(65536):
                if not chunk:
                    continue
                buf += chunk
                if len(buf) > max_bytes or time.time() - started > deadline:
                    return None
            return bytes(buf) or None
    except Exception:                                  # noqa: BLE001
        return None


def shrink_thumb(data: bytes, box: int = THUMB_BOX) -> bytes:
    """把原图缩成小预览；动图保持动，但帧数和尺寸都收一收。失败就原样返回。"""
    try:
        with Image.open(io.BytesIO(data)) as im:
            frames = int(getattr(im, "n_frames", 1) or 1)
            still = False
            if frames > 1:
                if len(data) <= 300_000:
                    return data                     # 本来就不大的动图，别折腾
                # 大动图逐帧重编码太慢（实测一张能卡 20 秒以上），
                # 网格里只放第一帧的静态缩略图，真正的动图等下载时再拿。
                im.seek(0)
                still = True                        # 第一帧：压成 JPEG 更小
            im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
            im.thumbnail((box, box), Image.LANCZOS)
            out = io.BytesIO()
            if im.mode == "RGBA" and not still:
                im.save(out, format="PNG", optimize=True)
            else:
                if im.mode == "RGBA":
                    bg = Image.new("RGB", im.size, (255, 255, 255))
                    bg.paste(im, mask=im.split()[-1])
                    im = bg
                else:
                    im = im.convert("RGB")
                im.save(out, format="JPEG", quality=82, optimize=True,
                        progressive=True)
            got = out.getvalue()
            return got if got else data
    except Exception:                              # noqa: BLE001
        return data



def page_opened() -> bool:
    return HIT.is_set()

STATIC = Path(__file__).resolve().parent / "static"
MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def file_row(p: Path) -> dict:
    """一个文件的展示信息（名字/大小/修改时间）。"""
    try:
        st = p.stat()
    except OSError:
        return {"name": p.name, "size": 0, "mtime": 0}
    return {"name": p.name, "size": st.st_size, "mtime": st.st_mtime}


def sniff_mime(data: bytes) -> str:
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


class App:
    def __init__(self, cfg: Config, bus: Bus, collector: Collector):
        self.cfg = cfg
        self.bus = bus
        self.collector = collector
        self.dl = Downloader(cfg)
        self.hit_logged = False

    # ---------- 业务动作 ----------
    def selftest(self) -> dict:
        """能不能往自己的目录里写东西（被沙箱限制时会失败）。"""
        out: dict = {"writable": True, "dirs": {}}
        for name in ("tmp_dir", "outbox_dir", "stickers_dir"):
            target = getattr(self.cfg, name)
            item: dict = {"path": str(target)}
            out["dirs"][name] = item
            try:
                target.mkdir(parents=True, exist_ok=True)
                probe = target / ".dsh-stickers-probe"
                probe.write_bytes(b"ok")
                probe.unlink()
                item["ok"] = True
            except OSError as exc:
                item["ok"] = False
                item["error"] = f"{type(exc).__name__}: {exc}"
                out["writable"] = False
        return out

    def state(self) -> dict:
        c = store.counts()
        outbox = self.cfg.outbox_dir
        pending = len([p for p in outbox.iterdir() if p.is_file()]) if outbox.exists() else 0
        return {
            "counts": c,
            "logged_in": bool(self.collector.logged_in),
            "login": {
                "douyin": bool(self.collector.logged_in),
                "xhs": bool(XhsApi(self.cfg.xhs_cookie_path).logged_in()),
            },
            "busy": bool(self.collector.busy) or pipeline.is_downloading()
                    or ingest.is_running() or xhs_sync.is_running(),
            "ingesting": ingest.is_running() or xhs_sync.is_running(),
            "outbox": pending,
            "paths": {
                "stickers": str(self.cfg.stickers_dir),
                "outbox": str(outbox),
            },
            "config": {
                "max_items": self.cfg.max_items,
                "target_size": self.cfg.target_size,
                "enable_video_gif": self.cfg.enable_video_gif,
            },
        }

    def market_list(self) -> list[dict]:
        """所有可用来源 + 目录型市场的分类。"""
        out = []
        for m in registry.all_markets(self.cfg):
            kind = getattr(m, "kind", "catalog")
            cats: list = []
            cached = True
            if kind == "catalog":
                try:
                    cached = bool(m.has_manifest())
                    cats = m.categories() if cached else []
                except Exception:  # noqa: BLE001
                    cats, cached = [], False
            out.append({
                "id": m.id,
                "name": m.name,
                "kind": kind,
                "needs_login": bool(getattr(m, "needs_login", False)),
                "description": getattr(m, "description", ""),
                "modes": list(getattr(m, "modes", []) or []),
                "cached": cached,
                "categories": cats,
            })
        return out

    def thumb(self, cid: int) -> tuple[bytes, str] | None:
        cand = store.get_candidate(cid)
        if not cand:
            return None
        p = Path(cand["path"]) if cand.get("path") else None
        if p and p.exists():
            data = p.read_bytes()
            return data, sniff_mime(data[:12])
        cache = self.cfg.thumbs_dir / f"{cid}.img"
        if cache.exists():
            data = cache.read_bytes()
            return data, sniff_mime(data[:12])
        bad = self.cfg.thumbs_dir / f"{cid}.bad"
        if bad.exists() and time.time() - bad.stat().st_mtime < 86_400:
            return None                        # 上一次就没取下来，别每次都再等一遍
        url = cand.get("url") or cand.get("video_url")
        if not url:
            return None
        try:
            data = fetch_capped(url, deadline=THUMB_DEADLINE,
                               max_bytes=THUMB_MAX_BYTES)
        except Exception:  # noqa: BLE001
            data = None
        if not data:
            try:
                bad.write_bytes(b"")
            except Exception:  # noqa: BLE001
                pass
            return None
        data = shrink_thumb(data)
        cache.write_bytes(data)
        return data, sniff_mime(data[:12])

    def start_download(self, ids: list[int] | None, status: str | None) -> list[int]:
        if ids:
            target = ids
        else:
            target = [c["id"] for c in store.list_candidates([status or "new"], limit=1000)]
        return target if pipeline.start(target, self.cfg, self.bus) else []

    def prepare_import(self) -> dict:
        cands = [c for c in store.list_candidates(["downloaded"], limit=2000)
                 if c.get("path") and Path(c["path"]).exists()]
        files = [Path(c["path"]) for c in cands]
        n = open_outbox.prepare_import(files, self.cfg.outbox_dir)
        store.set_setting("outbox_ids", [c["id"] for c in cands])
        # 打开资源管理器 / 唤起微信失败不算错，文件已经备好了，用户手动也能拖
        try:
            open_outbox.open_folder(self.cfg.outbox_dir)
        except Exception as exc:  # noqa: BLE001
            self.bus.emit("log", msg=f"没能自动打开文件夹（{exc}），自己打开 {self.cfg.outbox_dir}")
        try:
            open_outbox.launch_wechat()
            time.sleep(0.8)
            open_outbox.focus_wechat()
        except Exception as exc:  # noqa: BLE001
            self.bus.emit("log", msg=f"没能唤起微信窗口（{exc}），手动切到微信即可")
        return {"count": n, "folder": str(self.cfg.outbox_dir)}

    def mark_imported(self) -> dict:
        """标记为已导入：素材仍留在素材库，只清空导出夹。"""
        ids = store.get_setting("outbox_ids", []) or []
        marked = 0
        for cid in ids:
            if not store.get_candidate(cid):
                continue
            store.update_candidate(cid, status="imported", imported_at=time.time())
            marked += 1
        if self.cfg.outbox_dir.exists():
            for f in self.cfg.outbox_dir.iterdir():
                if f.is_file():
                    try:
                        f.unlink()
                    except OSError:
                        pass
        store.set_setting("outbox_ids", [])
        return {"imported": marked}

    # ---------- 本地文件管理 ----------
    def local_info(self) -> dict:
        """导出夹（给微信拖的）+ 素材库（全部原图）的磁盘占用。"""
        outbox = self.cfg.outbox_dir
        files: list[dict] = []
        if outbox.exists():
            for p in sorted(outbox.iterdir()):
                if p.is_file():
                    files.append(file_row(p))
        files.sort(key=lambda f: f["name"])

        lib = self.cfg.stickers_dir
        lib_files = [p for p in lib.iterdir() if p.is_file()] if lib.exists() else []
        lib_bytes = 0
        for p in lib_files:
            try:
                lib_bytes += p.stat().st_size
            except OSError:
                pass
        return {
            "outbox": {
                "dir": str(outbox),
                "files": files,
                "count": len(files),
                "bytes": sum(f["size"] for f in files),
            },
            "library": {
                "dir": str(lib),
                "count": len(lib_files),
                "bytes": lib_bytes,
                "imported": len(store.list_candidates(["imported"], limit=5000)),
            },
        }

    def local_file(self, name: str):
        """读导出夹里的单个文件（只允许文件名，防目录穿越）。"""
        name = Path(name).name
        p = self.cfg.outbox_dir / name
        if not p.is_file():
            return None
        try:
            data = p.read_bytes()
        except OSError:
            return None
        return data, sniff_mime(data)

    def local_delete(self, name: str) -> dict:
        name = Path(name).name
        p = self.cfg.outbox_dir / name
        if not p.is_file():
            return {"ok": False, "error": "文件不存在"}
        try:
            p.unlink()
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        self.bus.emit("local_changed", removed=1)
        return {"ok": True, "removed": 1}

    def local_clear(self) -> dict:
        n = 0
        if self.cfg.outbox_dir.exists():
            for p in list(self.cfg.outbox_dir.iterdir()):
                if p.is_file():
                    try:
                        p.unlink()
                        n += 1
                    except OSError:
                        pass
        store.set_setting("outbox_ids", [])
        self.bus.emit("log", msg=f"导出夹已清空（{n} 个文件）")
        self.bus.emit("local_changed", removed=n)
        return {"ok": True, "removed": n}

    def local_purge(self, scope: str = "orphan") -> dict:
        """清素材库。scope=orphan（没人引用的孤儿文件）|
        imported（已导入的那批文件）| all（全清）。"""
        lib = self.cfg.stickers_dir
        if not lib.exists():
            return {"ok": True, "removed": 0, "bytes": 0}
        rows = store.list_candidates(limit=20000)
        name_of = {c["id"]: Path(c["path"]).name
                   for c in rows if c.get("path")}
        if scope == "orphan":
            targets = {p.name for p in lib.iterdir() if p.is_file()} \
                - set(name_of.values())
            clear_ids: list[int] = []
        elif scope == "imported":
            clear_ids = [c["id"] for c in rows
                         if c.get("status") == "imported" and c.get("path")]
            targets = {name_of[i] for i in clear_ids}
        elif scope == "all":
            clear_ids = [c["id"] for c in rows if c.get("path")]
            targets = {name_of[i] for i in clear_ids}
        else:
            return {"ok": False, "error": f"不支持的清理范围：{scope}"}

        removed = 0
        freed = 0
        for name in targets:
            p = lib / name
            if not p.is_file():
                continue
            try:
                size = p.stat().st_size
                p.unlink()
                removed += 1
                freed += size
            except OSError:
                pass
        for cid in clear_ids:
            store.update_candidate(cid, path="")
        self.bus.emit("log", msg=f"素材库清理完成：删除 {removed} 个文件，"
                                 f"释放 {freed / 1048576:.1f} MB")
        self.bus.emit("local_changed", removed=removed)
        return {"ok": True, "removed": removed, "bytes": freed}


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "StickerBot/1.0"

        # ---------- 工具 ----------
        def log_message(self, fmt, *args):  # noqa: A003
            pass

        def _json(self, obj, code: int = 200) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def _cors(self) -> None:
            """允许 DSH 插件页面（不同端口）跨域调用本服务。"""
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "600")

        def do_OPTIONS(self):  # noqa: N802
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _bytes(self, data: bytes, ctype: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "max-age=120")
            self._cors()
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            try:
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b"{}"
                return json.loads(raw.decode("utf-8") or "{}")
            except Exception:  # noqa: BLE001
                return {}

        def _static(self, rel: str) -> None:
            target = (STATIC / rel).resolve()
            if not str(target).startswith(str(STATIC.resolve())) or not target.is_file():
                self._json({"error": "not found"}, 404)
                return
            data = target.read_bytes()
            self._bytes(data, MIME.get(target.suffix.lower(), "application/octet-stream"))

        # ---------- GET ----------
        def do_GET(self):  # noqa: N802
            u = urlparse(self.path)
            path = u.path
            try:
                if path in ("/", "/index.html"):
                    HIT.set()
                    if not app.hit_logged:
                        app.hit_logged = True
                        print("  网页已连接，可以开始操作了")
                    self._static("index.html")
                elif path.startswith("/static/"):
                    self._static(path[len("/static/"):])
                elif path == "/api/state":
                    self._json(app.state())
                elif path == "/api/selftest":
                    self._json(app.selftest())
                elif path == "/api/candidates":
                    qs = parse_qs(u.query)
                    # 默认只给「还没下载到本地」的：已下载/已导入的没必要再拉一遍
                    raw = qs.get("status", ["new"])[0]
                    statuses = [] if raw in ("", "all") else [
                        s for s in raw.split(",") if s]
                    market = (qs.get("market", [""])[0] or "").strip() or None
                    if market in ("", "all"):
                        market = None
                    # 分页：默认一页 60，最多 400（6000 条全渲染会卡）
                    try:
                        limit = int(qs.get("limit", ["60"])[0])
                    except ValueError:
                        limit = 60
                    limit = max(1, min(limit, 400))
                    try:
                        offset = int(qs.get("offset", ["0"])[0])
                    except ValueError:
                        offset = 0
                    offset = max(0, offset)
                    total = store.count_candidates(statuses or None,
                                                   market=market)
                    items = store.list_candidates(statuses or None,
                                                  limit=limit, market=market,
                                                  offset=offset)
                    for it in items:
                        it.pop("sha256", None)
                    self._json({"items": items, "total": total,
                                "offset": offset, "limit": limit,
                                "has_more": offset + len(items) < total})
                elif path == "/api/local":
                    self._json(app.local_info())
                elif path == "/api/local/file":
                    name = parse_qs(u.query).get("name", [""])[0]
                    got = app.local_file(name)
                    if not got:
                        self._json({"error": "no file"}, 404)
                    else:
                        self._bytes(*got)
                elif path == "/api/markets":
                    self._json({"markets": app.market_list()})
                elif path.startswith("/api/thumb/"):
                    cid = int(path.rsplit("/", 1)[-1])
                    got = app.thumb(cid)
                    if not got:
                        self._json({"error": "no thumb"}, 404)
                    else:
                        self._bytes(*got)
                elif path == "/api/events":
                    self._sse()
                elif path == "/api/log":
                    self._json({"events": app.bus.recent(50)})
                else:
                    self._json({"error": "not found"}, 404)
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as e:  # noqa: BLE001
                try:
                    self._json({"error": f"{type(e).__name__}: {e}"}, 500)
                except Exception:  # noqa: BLE001
                    pass

        def _sse(self) -> None:
            q = app.bus.subscribe()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            try:
                for ev in app.bus.recent(5):
                    self._chunk(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode())
                while True:
                    try:
                        ev = q.get(timeout=15)
                        payload = f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                    except queue.Empty:
                        payload = ": ping\n\n"
                    self._chunk(payload.encode("utf-8"))
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                app.bus.unsubscribe(q)
                try:
                    self.wfile.write(b"0\r\n\r\n")
                except Exception:  # noqa: BLE001
                    pass

        def _chunk(self, data: bytes) -> None:
            self.wfile.write(f"{len(data):X}\r\n".encode())
            self.wfile.write(data)
            self.wfile.write(b"\r\n")
            self.wfile.flush()

        # ---------- POST ----------
        def do_POST(self):  # noqa: N802
            path = urlparse(self.path).path
            body = self._body()
            try:
                if path == "/api/collect":
                    market_id = (body.get("market") or "douyin").strip() or "douyin"
                    mode = body.get("mode", "keyword")
                    value = (body.get("value") or "").strip()
                    if market_id == "xhs":
                        if mode not in ("smiles", "redmoji"):
                            self._json({"error": "未知的抓取方式"}, 400)
                            return
                        if xhs_sync.is_running():
                            self._json({"error": "上一次抓取还没结束"}, 409)
                            return
                        if xhs_sync.start(mode, cfg=app.cfg, bus=app.bus):
                            self._json({"ok": True})
                        else:
                            self._json({"error": "上一次抓取还没结束"}, 409)
                        return
                    if market_id != "douyin":
                        m = registry.get(market_id, app.cfg)
                        if m is None:
                            self._json({"error": "没有这个来源"}, 400)
                            return
                        category = (body.get("category") or "").strip()
                        if getattr(m, "kind", "catalog") == "catalog" and not category:
                            self._json({"error": "请先选分类"}, 400)
                            return
                        if ingest.start(m, category=category, query=value,
                                        cfg=app.cfg, bus=app.bus):
                            self._json({"ok": True})
                        else:
                            self._json({"error": "上一个入库任务还没结束"}, 409)
                        return
                    if mode not in ("sticker", "keyword", "user", "collection", "like"):
                        self._json({"error": "未知的抓取方式"}, 400)
                        return
                    if mode in ("keyword", "user") and not value:
                        self._json({"error": "请输入关键词或账号链接"}, 400)
                        return
                    if app.collector.busy:
                        self._json({"error": "上一次抓取还没结束"}, 409)
                        return
                    app.collector.submit("collect", mode=mode, value=value)
                    self._json({"ok": True})
                elif path == "/api/market/refresh":
                    market_id = (body.get("market") or "").strip()
                    m = registry.get(market_id, app.cfg) if market_id else None
                    if m is None or getattr(m, "kind", "") != "catalog":
                        self._json({"error": "只有目录型来源能刷新清单"}, 400)
                        return
                    try:
                        m.ensure_manifest(force=True)
                    except Exception as exc:  # noqa: BLE001
                        self._json({"error": str(exc)[:300]}, 502)
                        return
                    cats = m.categories()
                    self._json({"ok": True, "categories": cats})
                elif path == "/api/login":
                    market_id = (body.get("market") or "douyin").strip() or "douyin"
                    if market_id == "xhs":
                        if xhs_login.is_running():
                            self._json({"ok": True, "already": True})
                        else:
                            xhs_login.start(app.cfg, app.bus,
                                            timeout=app.cfg.login_timeout)
                            self._json({"ok": True})
                        return
                    app.collector.submit("login")
                    self._json({"ok": True})
                elif path == "/api/download":
                    ids = body.get("ids")
                    if ids is not None:
                        ids = [int(i) for i in ids]
                    started = app.start_download(ids, body.get("status"))
                    self._json({"ok": bool(started), "queued": len(started),
                                "error": None if started else "已有下载任务在跑"})
                elif path == "/api/candidates/clear":
                    raw = str(body.get("status") or "all")
                    statuses = [] if raw in ("", "all") else [
                        s for s in raw.split(",") if s]
                    market = (body.get("market") or "").strip() or None
                    if market in ("", "all"):
                        market = None
                    deleted = store.delete_candidates(statuses or None,
                                                      market=market)
                    app.bus.emit("log", text=f"已清空 {deleted} 条列表记录")
                    app.bus.emit("cleared", deleted=deleted)
                    self._json({"ok": True, "deleted": deleted})
                elif path == "/api/import/prepare":
                    self._json(app.prepare_import())
                elif path == "/api/import/done":
                    self._json(app.mark_imported())
                elif path == "/api/settings":
                    from .. import config as cfg_mod
                    cfg = app.cfg
                    for k, v in body.items():
                        if hasattr(cfg, k) and not callable(getattr(cfg, k)):
                            setattr(cfg, k, v)
                    cfg_mod.save_config(cfg)
                    self._json({"ok": True})
                elif path == "/api/local/delete":
                    self._json(app.local_delete(str(body.get("name") or "")))
                elif path == "/api/local/clear":
                    self._json(app.local_clear())
                elif path == "/api/local/purge":
                    self._json(app.local_purge(str(body.get("scope") or "orphan")))
                elif path == "/api/open":
                    target = body.get("target", "stickers")
                    p = app.cfg.outbox_dir if target == "outbox" else app.cfg.stickers_dir
                    try:
                        open_outbox.open_folder(p)
                        self._json({"ok": True, "folder": str(p)})
                    except Exception as exc:  # noqa: BLE001
                        # 打开资源管理器被系统/沙箱拦住不算错，文件已经在盘上了
                        self._json({"ok": False, "folder": str(p),
                                    "error": f"{type(exc).__name__}: {exc}"})
                else:
                    self._json({"error": "not found"}, 404)
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as e:  # noqa: BLE001
                try:
                    self._json({"error": f"{type(e).__name__}: {e}"}, 500)
                except Exception:  # noqa: BLE001
                    pass

    return Handler


def serve(cfg: Config, bus: Bus, collector: Collector) -> ThreadingHTTPServer:
    app = App(cfg, bus, collector)
    httpd = ThreadingHTTPServer(("127.0.0.1", cfg.port), make_handler(app))
    httpd.daemon_threads = True
    return httpd
