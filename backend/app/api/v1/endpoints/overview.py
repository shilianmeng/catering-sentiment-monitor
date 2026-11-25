"""态势大盘、虚拟时钟、SSE 实时推送。"""
import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ....core.exceptions import Unauthorized
from ....core.security import token_store
from ....core.sse import broadcaster
from ....engine import demo
from ....services import overview_service
from ...deps import DB, CurrentUser

router = APIRouter(tags=["态势大盘"])

KEEP_ALIVE_SECONDS = 15


@router.get("/overview", summary="大盘数据")
def overview(user=CurrentUser, conn=DB):
    return overview_service.overview(conn)


@router.get("/clock", summary="虚拟时钟状态")
def clock(user=CurrentUser, conn=DB):
    return demo.clock_state(conn)


@router.get("/stream", summary="SSE 实时推送（EventSource 不能带头，用 ?token= 鉴权）")
async def stream(request: Request, token: str = ""):
    if not token_store.get(token):
        raise Unauthorized("未登录或登录已过期，请重新登录")
    q = broadcaster.subscribe()

    async def gen():
        try:
            yield "event: hello\ndata: {}\n\n"
            while not await request.is_disconnected():
                try:
                    yield await asyncio.wait_for(q.get(), timeout=KEEP_ALIVE_SECONDS)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            broadcaster.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
