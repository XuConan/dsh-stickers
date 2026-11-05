"""本地端到端冒烟脚本（不属于单测，unittest discover 不会跑它）。

用法：
    1) 先启动服务：.venv\\Scripts\\python.exe -m app --no-browser --port 8811
    2) 再运行：.venv\\Scripts\\python.exe tests/smoke_local.py
"""
from __future__ import annotations

import functools
import http.server
import io
import json
import socketserver
import sys
import threading
import time
from pathlib import Path

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config, store  # noqa: E402
from app.wechat import open_outbox  # noqa: E402

BASE = "http://127.0.0.1:8811"
PORT = 8812


def make_png(size=(300, 300)) -> bytes:
    img = Image.new("RGB", size, (20, 160, 90))
    for x in range(120, 180):
        for y in range(80, 220):
            img.putpixel((x, y), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def main() -> int:
    cfg = config.Config()
    cfg.ensure_dirs()
    store.init(cfg.db_path)

    # ---- 本地静态服务器 ----
    serve_dir = cfg.tmp_dir / "smoke"
    serve_dir.mkdir(parents=True, exist_ok=True)
    (serve_dir / "a.png").write_bytes(make_png())
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(serve_dir))
    handler.log_message = lambda *a, **k: None
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.3)

    try:
        print("1) 健康检查 …")
        st = requests.get(BASE + "/api/state", timeout=10).json()
        print("   counts:", st["counts"], "busy:", st["busy"])

        print("2) 插入两条候选（同图不同 URL）…")
        base_item = {
            "aweme_id": "smoke1", "desc": "冒烟测试", "author": "tester",
            "source_type": "image", "video_url": "",
            "width": 300, "height": 300, "is_animated": False,
        }
        c1 = store.add_candidate({**base_item, "url": f"http://127.0.0.1:{PORT}/a.png"})
        c2 = store.add_candidate({**base_item, "aweme_id": "smoke2",
                                  "url": f"http://127.0.0.1:{PORT}/a.png?v=2"})
        assert c1 and c2, "插入失败（url 冲突？）"
        print(f"   ids: {c1}, {c2}")

        print("3) 订阅 SSE 并触发下载 …")
        sse = {"kinds": [], "stop": False}

        def listen() -> None:
            try:
                with requests.get(BASE + "/api/events", stream=True, timeout=60) as resp:
                    for line in resp.iter_lines(decode_unicode=True):
                        if sse["stop"]:
                            break
                        if line and line.startswith("data:"):
                            try:
                                sse["kinds"].append(json.loads(line[5:].strip()).get("type"))
                            except ValueError:
                                pass
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=listen, daemon=True).start()
        time.sleep(0.6)

        r = requests.post(BASE + "/api/download", json={"ids": [c1, c2]}, timeout=10).json()
        print("   ->", r)
        assert r.get("ok"), r

        deadline = time.time() + 40
        row1 = row2 = None
        while time.time() < deadline:
            row1 = store.get_candidate(c1)
            row2 = store.get_candidate(c2)
            if row1["status"] in ("downloaded", "error") and \
               row2["status"] in ("duplicate", "error", "downloaded"):
                break
            time.sleep(0.5)
        print(f"   候选1={row1['status']} 候选2={row2['status']}")
        assert row1["status"] == "downloaded", row1
        assert row2["status"] == "duplicate", row2
        p = Path(row1["path"])
        assert p.exists(), p
        with Image.open(p) as img:
            print(f"   落盘: {p.name} {img.size} {img.format}")
            assert img.size == (240, 240)

        time.sleep(0.5)
        sse["stop"] = True
        kinds = [k for k in sse["kinds"] if k]
        print(f"   SSE 收到: {sorted(set(kinds))}")
        assert "progress" in kinds and "download_done" in kinds, sse["kinds"]

        print("4) 导出到 outbox …")
        n = open_outbox.prepare_import([p], cfg.outbox_dir)
        files = sorted(x.name for x in cfg.outbox_dir.iterdir())
        print(f"   导出 {n} 个: {files}")
        assert n == 1 and files == ["001.png"], files
        store.set_setting("outbox_ids", [c1], db=cfg.db_path)

        print("5) 标记已导入 …")
        r = requests.post(BASE + "/api/import/done", json={}, timeout=10).json()
        print("   ->", r)
        assert r["imported"] == 1, r
        assert store.get_candidate(c1)["status"] == "imported"
        assert p.exists(), "素材应保留在素材库"
        assert not list(cfg.outbox_dir.iterdir())

        print("6) 缩略图接口 …")
        tr = requests.get(f"{BASE}/api/thumb/{c1}", timeout=10)
        print("   thumb:", tr.status_code, tr.headers.get("Content-Type"), len(tr.content))
        assert tr.status_code == 200

        print("\n[PASS] 冒烟测试全部通过")
        return 0
    finally:
        httpd.shutdown()
        # 清理测试数据，避免污染真实素材库
        try:
            import sqlite3
            with sqlite3.connect(str(cfg.db_path)) as conn:
                conn.execute("DELETE FROM candidates WHERE aweme_id LIKE 'smoke%'")
            for d in (cfg.outbox_dir, cfg.stickers_dir):
                for f in d.glob("*"):
                    if f.is_file():
                        f.unlink()
            for f in (cfg.tmp_dir / "smoke").glob("*"):
                f.unlink()
        except Exception as e:  # noqa: BLE001
            print("清理失败:", e)


if __name__ == "__main__":
    sys.exit(main())
