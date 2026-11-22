"""Шина событий для Server-Sent Events: подписчики получают обновления программы."""

import asyncio
import json
import threading
from collections import defaultdict
from typing import Any


class EventBus:
    """Простая шина в памяти процесса: очередь на каждого подписчика."""

    def __init__(self) -> None:
        self._subs: dict[int, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, program_id: int) -> asyncio.Queue:
        """Создаёт очередь событий для программы."""
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        with self._lock:
            self._subs[program_id].append((asyncio.get_running_loop(), q))
        return q

    def unsubscribe(self, program_id: int, q: asyncio.Queue) -> None:
        """Удаляет очередь подписчика."""
        with self._lock:
            self._subs[program_id] = [(lp, x) for lp, x in self._subs[program_id] if x is not q]

    def publish(self, program_id: int, event: str, data: dict[str, Any]) -> None:
        """Отправляет событие всем подписчикам программы (можно из любого потока)."""
        msg = {"event": event, "data": json.dumps(data, ensure_ascii=False, default=str)}
        with self._lock:
            subs = list(self._subs[program_id])
        for loop, q in subs:
            try:
                loop.call_soon_threadsafe(q.put_nowait, msg)
            except (RuntimeError, asyncio.QueueFull):
                continue


bus = EventBus()
