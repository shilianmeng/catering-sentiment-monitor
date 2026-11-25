"""监测配置、预警、演示控制。"""
from typing import Optional

from fastapi import APIRouter, Depends

from ....schemas import AdvanceIn, ConfigUpdate
from ....services import alert_service, config_service, demo_service
from ...deps import DB, CurrentUser, require_role

router = APIRouter()


@router.get("/config", tags=["监测配置"], summary="读取配置")
def get_config(user=CurrentUser, conn=DB):
    return config_service.get(conn)


@router.put("/config", tags=["监测配置"], summary="修改配置（管理员）")
def update_config(body: ConfigUpdate, user=Depends(require_role("admin")), conn=DB):
    return config_service.update(conn, body.model_dump(exclude_unset=True))


@router.get("/alerts", tags=["预警"], summary="预警列表")
def list_alerts(event_id: Optional[str] = None, user=CurrentUser, conn=DB):
    return alert_service.list_alerts(conn, event_id)


@router.put("/alerts/{aid}/read", tags=["预警"], summary="标记已读")
def mark_read(aid: int, user=CurrentUser, conn=DB):
    alert_service.mark_read(conn, aid)
    return {"ok": True}


@router.post("/demo/reset", tags=["演示控制"], summary="重置演示（管理员）")
async def demo_reset(user=Depends(require_role("admin"))):
    return await demo_service.reset()


@router.post("/demo/advance", tags=["演示控制"], summary="推进虚拟时钟（管理员）")
async def demo_advance(body: Optional[AdvanceIn] = None, user=Depends(require_role("admin"))):
    return await demo_service.advance(body.batches if body else 1)
