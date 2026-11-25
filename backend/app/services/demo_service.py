"""演示控制：重置、推进虚拟时钟，并通过 SSE 把结果推给在线页面。

重置/推进是阻塞的数据库操作，放到线程池执行；SSE 发布必须在事件循环线程里做
（asyncio.Queue 不是线程安全的），所以这里的入口是 async 函数。
"""
from starlette.concurrency import run_in_threadpool

from ..core.logging import get_logger
from ..core.sse import broadcaster
from ..db.session import connect
from ..engine import demo
from ..repositories import alert_repo
from . import overview_service

log = get_logger("demo")


def _collect_messages(res: dict) -> list[tuple[str, dict]]:
    conn = connect()
    try:
        msgs = [("alert_raised", alert_repo.get_alert(conn, aid))
                for r in res["results"] for aid in r["alert_ids"]]
        msgs.append(("batch_advanced", {
            "clock": demo.clock_state(conn),
            "metrics": overview_service.metrics(conn),
            "new_contents": sum(r["ingested"] for r in res["results"]),
            "merged": sum(len(r["merged"]) for r in res["results"]),
            "label": res["current_label"],
        }))
        return msgs
    finally:
        conn.close()


async def _publish(res: dict) -> None:
    for event, data in await run_in_threadpool(_collect_messages, res):
        broadcaster.publish(event, data)


async def reset() -> dict:
    res = await run_in_threadpool(demo.reset)
    log.info("演示已重置，当前批次 %s", res["current_label"])
    broadcaster.publish("reset", {"label": res["current_label"]})
    await _publish(res)
    return res


async def advance(batches: int) -> dict:
    res = await run_in_threadpool(demo.advance, batches)
    if not res["results"]:
        return {**res, "message": f"已到最后一批（{res['current_label']}），请先重置演示"}
    log.info("虚拟时钟推进到 %s", res["current_label"])
    await _publish(res)
    return res
