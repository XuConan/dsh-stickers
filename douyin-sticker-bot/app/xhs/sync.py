"""抓小红书表情包：纯 HTTP，不开浏览器。

两个来源：
- ``smiles``  我的表情包（需要登录 cookie）
- ``redmoji`` 小红书自带表情（免登录，166 个）

登录态靠 ``data/xhs-cookies.json``，由 ``app/xhs/login.py`` 在用户扫码后写入。
"""
from __future__ import annotations

import threading
import time

from .. import store
from ..events import Bus
from .api import XhsApi, XhsError, XhsNeedLogin
from .parser import redmoji_to_items, smiles_to_items

MODES = {"smiles": "我的表情包", "redmoji": "小红书自带表情"}

_LOCK = threading.Lock()
_STATE = {"running": False, "mode": ""}


def is_running() -> bool:
    return bool(_STATE.get("running"))


def current_mode() -> str:
    return _STATE.get("mode") or ""


def start(mode: str, cfg=None, bus: Bus | None = None, db=None) -> bool:
    """后台线程抓取；已有任务在跑返回 False。"""
    with _LOCK:
        if _STATE["running"]:
            return False
        _STATE["running"] = True
        _STATE["mode"] = mode
    t = threading.Thread(target=_run, args=(mode, cfg, bus, db),
                         name=f"xhs-{mode}", daemon=True)
    t.start()
    return True


def _fetch(mode: str, api: XhsApi) -> list[dict]:
    """统一成 [{url, desc, ext_id, w, h}]，两条来源都走这里。"""
    if mode == "redmoji":
        return [{"external_id": it.external_id, "url": it.url,
                 "desc": it.desc, "width": it.width, "height": it.height,
                 "candidate": it.to_candidate("xhs")}
                for it in redmoji_to_items(api.redmoji())]
    items = smiles_to_items(api.my_smiles())
    return [{"external_id": it.external_id, "url": it.url,
             "desc": it.desc, "width": it.width, "height": it.height,
             "candidate": it.to_candidate("xhs")}
            for it in items]


def _run(mode: str, cfg, bus: Bus | None, db=None) -> None:
    bus = bus or Bus()
    started = time.time()
    label = MODES.get(mode, mode)
    run_id = store.create_run(f"xhs:{mode}", "", db=db)
    added = 0
    skipped = 0
    total = 0
    try:
        if cfg is None:
            from .. import config as cfg_mod
            cfg = cfg_mod.load_config()
        api = XhsApi(cfg.xhs_cookie_path, timeout=cfg.request_timeout)
        bus.emit("progress", phase="browse", count=0, msg=f"读取「{label}」…")
        rows = _fetch(mode, api)
        total = len(rows)
        bus.emit("log", msg=f"小红书：{label} 共 {total} 个")
        if not total:
            bus.emit("log", msg="你的小红书还没有收藏表情包，可以先用「小红书自带表情」"
                               if mode == "smiles" else "小红书没有返回表情")
        for i, row in enumerate(rows, 1):
            cid = store.add_candidate(row["candidate"], status="new", db=db)
            if cid:
                added += 1
                bus.emit("candidate", id=cid)
            else:
                skipped += 1
            if i % 50 == 0 or i == total:
                bus.emit("progress", phase="browse", count=i, total=total)
        store.finish_run(run_id, {
            "market": "xhs", "mode": mode, "captured": total,
            "new": added, "skipped": skipped,
            "seconds": round(time.time() - started, 1),
        }, db=db)
        bus.emit("collect_done", captured=total, new=added, skipped=skipped,
                 market="xhs", mode=mode)
        bus.emit("log", msg=f"小红书：新增 {added} 个，其余已在库里")
    except XhsNeedLogin as exc:
        store.finish_run(run_id, {
            "market": "xhs", "mode": mode, "error": str(exc),
            "seconds": round(time.time() - started, 1),
        }, db=db)
        bus.emit("need_login", market="xhs",
                 text="小红书要登录才能读到你收藏的表情包")
        bus.emit("log", msg=f"小红书未登录：{exc}")
    except XhsError as exc:
        store.finish_run(run_id, {
            "market": "xhs", "mode": mode, "error": str(exc),
            "seconds": round(time.time() - started, 1),
        }, db=db)
        bus.emit("error", msg=f"小红书抓取失败：{exc}")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)[:300]
        store.finish_run(run_id, {
            "market": "xhs", "mode": mode, "error": msg,
            "captured": total, "seconds": round(time.time() - started, 1),
        }, db=db)
        bus.emit("error", msg=msg)
    finally:
        _STATE["running"] = False
        _STATE["mode"] = ""
