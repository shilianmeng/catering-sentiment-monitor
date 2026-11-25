"""SSE 广播器：服务端事件（新批次、预警、重置）推送给所有在线页面。"""
import asyncio
import json


class Broadcaster:
    def __init__(self, queue_size: int = 200):
        self._queues: set[asyncio.Queue] = set()
        self._queue_size = queue_size

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._queue_size)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._queues.discard(q)

    def publish(self, event: str, data) -> None:
        msg = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
        for q in list(self._queues):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass  # 慢客户端丢弃消息，不阻塞其他连接


broadcaster = Broadcaster()
