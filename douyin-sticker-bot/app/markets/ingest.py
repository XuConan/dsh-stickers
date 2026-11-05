"""把「目录型」市场（GitHub 图库）的条目灌进候选库。

只写元数据（url / 尺寸 / 分类），不预下载 —— ChineseBQB 有 6000+ 张、600 MB，
真正下载仍然走用户勾选后的 pipeline。
"""
from __future__ import annotations

import threading
import time

from .. import store
from ..events import Bus
from .base import Market

_LOCK = threading.Lock()
_STATE = {"running": False, "market": ""}


def is_running() -> bool:
    return bool(_STATE.get("running"))


def current_market() -> str:
    return _STATE.get("market") or ""


def start(market: Market, category: str = "", query: str = "",
          cfg=None, bus: Bus | None = None, db=None) -> bool:
    """后台线程入库；已有任务在跑时返回 False。"""
    with _LOCK:
        if _STATE["running"]:
            return False
        _STATE["running"] = True
        _STATE["market"] = market.id
    t = threading.Thread(
        target=_run, args=(market, category, query, cfg, bus, db),
        name=f"ingest-{market.id}", daemon=True)
    t.start()
    return True


def _run(market: Market, category: str, query: str, cfg, bus: Bus | None,
         db=None) -> None:
    bus = bus or Bus()
    started = time.time()
    run_id = store.create_run(f"{market.id}:{category or 'all'}", query or "", db=db)
    added = 0
    total = 0
    try:
        bus.emit("progress", phase="browse", count=0, msg="拉取清单…")
        market.ensure_manifest()  # 首次会下载清单（约 25s），之后走缓存
        items = market.items(category=category or None, query=query or None, limit=20000)
        total = len(items)
        bus.emit("log", msg=f"{market.name}：{category or '全部'} 共 {total} 个条目")
        for i, item in enumerate(items, 1):
            cand = item.to_candidate(market.id)
            cid = store.add_candidate(cand, status="new", db=db)
            if cid:
                added += 1
                bus.emit("candidate", id=cid)
            if i % 50 == 0 or i == total:
                bus.emit("progress", phase="browse", count=i, total=total)
        store.finish_run(run_id, {
            "market": market.id, "category": category or "all",
            "captured": total, "new": added,
            "seconds": round(time.time() - started, 1),
        }, db=db)
        bus.emit("collect_done", captured=total, new=added, skipped=0,
                 market=market.id)
        bus.emit("log", msg=f"{market.name}：新增 {added} 个，其余已在库里")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)[:300]
        store.finish_run(run_id, {
            "market": market.id, "error": msg, "captured": total,
            "seconds": round(time.time() - started, 1),
        }, db=db)
        bus.emit("error", msg=msg)
    finally:
        _STATE["running"] = False
        _STATE["market"] = ""
