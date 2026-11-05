"""sqlite 存储：候选表情、抓取批次、设置。

约定：所有函数的数据库路径关键字参数统一叫 ``db``，
避免和候选表里的 ``path``（表情文件路径）字段撞名。
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Iterable, Optional

from . import config as cfg_mod

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aweme_id TEXT,
    desc TEXT,
    author TEXT,
    source_type TEXT,          -- image / video / sticker
    url TEXT,
    video_url TEXT,
    width INTEGER,
    height INTEGER,
    is_animated INTEGER DEFAULT 0,
    sha256 TEXT,
    dhash TEXT,
    path TEXT,
    status TEXT DEFAULT 'new', -- new/downloaded/skipped/duplicate/imported/error
    collected_at REAL,
    imported_at REAL,
    market TEXT DEFAULT 'douyin'  -- 来源市场：douyin / chinesebqb / 自定义
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cand_url ON candidates(url);
CREATE INDEX IF NOT EXISTS idx_cand_status ON candidates(status);

CREATE TABLE IF NOT EXISTS runs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT,
    query TEXT,
    started_at REAL,
    finished_at REAL,
    stats TEXT
);

CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def _connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init(db: Optional[Path] = None) -> None:
    db = db or cfg_mod.load_config().db_path
    db.parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect(db)) as conn:
        conn.executescript(SCHEMA)
        # 老库补列：第二期加了 market（来源市场），幂等
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(candidates)")}
        if "market" not in cols:
            conn.execute(
                "ALTER TABLE candidates ADD COLUMN market TEXT DEFAULT 'douyin'")
        conn.commit()


def add_candidate(item: dict, status: str = "new",
                  db: Optional[Path] = None) -> Optional[int]:
    """插入候选；url 或 aweme_id 重复则返回 None。

    aweme_id 也要查：表情包的图片链接带签名参数（x-expires/x-signature），
    每次抓都不一样，只靠 url 去重会重复入库。
    """
    db = db or cfg_mod.load_config().db_path
    aweme_id = str(item.get("aweme_id") or "")
    with closing(_connect(db)) as conn:
        if aweme_id and conn.execute(
                "SELECT 1 FROM candidates WHERE aweme_id = ? LIMIT 1", (aweme_id,)
        ).fetchone():
            return None
        try:
            cur = conn.execute(
                """INSERT INTO candidates
                   (aweme_id, desc, author, source_type, url, video_url,
                    width, height, is_animated, collected_at, status, path, market)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?, ?)""",
                (
                    aweme_id,
                    (item.get("desc") or "")[:500],
                    (item.get("author") or "")[:100],
                    item.get("source_type", "image"),
                    item["url"],
                    item.get("video_url") or "",
                    int(item.get("width") or 0),
                    int(item.get("height") or 0),
                    1 if item.get("is_animated") else 0,
                    time.time(),
                    status,
                    item.get("path") or None,
                    item.get("market") or "douyin",
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
        except sqlite3.IntegrityError:
            return None


def list_candidates(statuses: Optional[Iterable[str]] = None,
                    limit: int = 500, market: Optional[str] = None,
                    offset: int = 0,
                    db: Optional[Path] = None) -> list[dict]:
    """按状态/来源取候选，id 倒序；limit + offset 就是分页。"""
    db = db or cfg_mod.load_config().db_path
    sql = "SELECT * FROM candidates"
    where, args = [], []
    if statuses:
        statuses = list(statuses)
        where.append("status IN (%s)" % ",".join("?" * len(statuses)))
        args += statuses
    if market:
        where.append("market = ?")
        args.append(market)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    args += [max(1, int(limit)), max(0, int(offset))]
    with closing(_connect(db)) as conn:
        rows = conn.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def count_candidates(statuses: Optional[Iterable[str]] = None,
                     market: Optional[str] = None,
                     db: Optional[Path] = None) -> int:
    """和 list_candidates 同样的筛选条件下有多少条（给分页算总页数）。"""
    db = db or cfg_mod.load_config().db_path
    sql = "SELECT COUNT(*) n FROM candidates"
    where, args = [], []
    if statuses:
        statuses = list(statuses)
        where.append("status IN (%s)" % ",".join("?" * len(statuses)))
        args += statuses
    if market:
        where.append("market = ?")
        args.append(market)
    if where:
        sql += " WHERE " + " AND ".join(where)
    with closing(_connect(db)) as conn:
        return int(conn.execute(sql, args).fetchone()["n"])


def get_candidate(cid: int, db: Optional[Path] = None) -> Optional[dict]:
    db = db or cfg_mod.load_config().db_path
    with closing(_connect(db)) as conn:
        row = conn.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
    return dict(row) if row else None


def delete_candidates(statuses: Optional[Iterable[str]] = None,
                      market: Optional[str] = None,
                      db: Optional[Path] = None) -> int:
    """删掉某个筛选范围内的候选记录（素材库里的文件不动）。返回删除条数。"""
    db = db or cfg_mod.load_config().db_path
    sql = "DELETE FROM candidates"
    where, args = [], []
    if statuses:
        statuses = list(statuses)
        where.append("status IN (%s)" % ",".join("?" * len(statuses)))
        args += statuses
    if market:
        where.append("market = ?")
        args.append(market)
    if where:
        sql += " WHERE " + " AND ".join(where)
    with closing(_connect(db)) as conn:
        cur = conn.execute(sql, args)
        conn.commit()
        return int(cur.rowcount or 0)


def update_candidate(cid: int, db: Optional[Path] = None, **fields) -> None:
    """更新候选字段；fields 原样作为列名（例如 status / path / sha256）。"""
    if not fields:
        return
    db = db or cfg_mod.load_config().db_path
    cols = ", ".join(f"{k}=?" for k in fields)
    args = list(fields.values()) + [cid]
    with closing(_connect(db)) as conn:
        conn.execute(f"UPDATE candidates SET {cols} WHERE id=?", args)
        conn.commit()


def counts(db: Optional[Path] = None) -> dict:
    db = db or cfg_mod.load_config().db_path
    out = {"new": 0, "downloaded": 0, "skipped": 0,
           "duplicate": 0, "imported": 0, "error": 0}
    with closing(_connect(db)) as conn:
        for row in conn.execute("SELECT status, COUNT(*) n FROM candidates GROUP BY status"):
            out[row["status"]] = row["n"]
        out["total"] = sum(out.values())
        by_market = {}
        for row in conn.execute(
                "SELECT market, COUNT(*) n FROM candidates GROUP BY market"):
            by_market[row["market"] or "douyin"] = row["n"]
    out["by_market"] = by_market
    return out


def find_similar(sha256: str, dhash: Optional[str],
                 max_hamming: int = 6, db: Optional[Path] = None) -> Optional[dict]:
    """精确 sha256 命中，或 dHash 汉明距离 <= max_hamming 命中。"""
    db = db or cfg_mod.load_config().db_path
    with closing(_connect(db)) as conn:
        row = conn.execute(
            "SELECT * FROM candidates WHERE sha256=? AND status IN "
            "('downloaded','imported') LIMIT 1", (sha256,),
        ).fetchone()
        if row:
            return dict(row)
        if dhash:
            want = int(dhash, 16)
            rows = conn.execute(
                "SELECT * FROM candidates WHERE dhash IS NOT NULL AND status IN "
                "('downloaded','imported')"
            ).fetchall()
            for r in rows:
                try:
                    got = int(r["dhash"], 16)
                except (TypeError, ValueError):
                    continue
                if bin(got ^ want).count("1") <= max_hamming:
                    return dict(r)
    return None


def create_run(mode: str, query: str, db: Optional[Path] = None) -> int:
    db = db or cfg_mod.load_config().db_path
    with closing(_connect(db)) as conn:
        cur = conn.execute(
            "INSERT INTO runs(mode, query, started_at) VALUES (?,?,?)",
            (mode, query, time.time()),
        )
        conn.commit()
        return int(cur.lastrowid)


def finish_run(run_id: int, stats: dict, db: Optional[Path] = None) -> None:
    db = db or cfg_mod.load_config().db_path
    with closing(_connect(db)) as conn:
        conn.execute(
            "UPDATE runs SET finished_at=?, stats=? WHERE id=?",
            (time.time(), json.dumps(stats, ensure_ascii=False), run_id),
        )
        conn.commit()


def get_setting(key: str, default=None, db: Optional[Path] = None):
    db = db or cfg_mod.load_config().db_path
    with closing(_connect(db)) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except Exception:  # noqa: BLE001
        return default


def set_setting(key: str, value, db: Optional[Path] = None) -> None:
    db = db or cfg_mod.load_config().db_path
    with closing(_connect(db)) as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )
        conn.commit()
