"""进程内事件总线：后台线程发事件，网页端用 SSE 收。"""
from __future__ import annotations

import queue
import threading
import time


class Bus:
    def __init__(self, history: int = 100):
        self._subs: set[queue.Queue] = set()
        self._lock = threading.Lock()
        self._history: list[dict] = []
        self._history_max = history

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subs.discard(q)

    def emit(self, kind: str, **data) -> None:
        msg = {"type": kind, "ts": time.time(), **data}
        with self._lock:
            self._history.append(msg)
            if len(self._history) > self._history_max:
                self._history = self._history[-self._history_max:]
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass

    def recent(self, n: int = 20) -> list[dict]:
        with self._lock:
            return self._history[-n:]
