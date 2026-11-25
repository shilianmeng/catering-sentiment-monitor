"""门店（直营/加盟、区域）。查看：所有角色；增删改：分析师、管理员。"""
from typing import Optional

from fastapi import APIRouter, Depends

from ....schemas import StoreCreate, StoreUpdate
from ....services import store_risk_service, store_service
from ...deps import DB, CurrentUser, require_role

router = APIRouter(prefix="/stores", tags=["门店"])
_editor = require_role("analyst", "admin")


@router.get("", summary="门店列表（可按品牌过滤），带内容数和官方记录数")
def list_stores(topic_id: Optional[int] = None, user=CurrentUser, conn=DB):
    return store_service.list_stores(conn, topic_id)


@router.get("/risk", summary="门店风险评分：按品牌汇总（每百店折算、直营/加盟对比）+ 门店排名")
def risk(topic_id: Optional[int] = None, as_of: Optional[str] = None, user=CurrentUser, conn=DB):
    if topic_id is None:
        return store_risk_service.all_topics_risk(conn, as_of)
    return store_risk_service.topic_risk(conn, topic_id, as_of)


@router.get("/{sid}/risk", summary="单店风险明细：每条官方记录的档位、衰减和得分")
def store_risk(sid: int, as_of: Optional[str] = None, user=CurrentUser, conn=DB):
    return store_risk_service.store_risk_detail(conn, sid, as_of)


@router.get("/{sid}", summary="门店详情")
def detail(sid: int, user=CurrentUser, conn=DB):
    return store_service.get(conn, sid)


@router.post("", summary="新建门店")
def create(body: StoreCreate, user=Depends(_editor), conn=DB):
    return store_service.create(conn, body.model_dump())


@router.put("/{sid}", summary="修改门店（只改传了的字段）")
def update(sid: int, body: StoreUpdate, user=Depends(_editor), conn=DB):
    return store_service.update(conn, sid, body.model_dump(exclude_unset=True))


@router.delete("/{sid}", summary="删除门店（已有关联内容/官方记录时不能删）")
def delete(sid: int, user=Depends(_editor), conn=DB):
    store_service.delete(conn, sid)
    return {"ok": True}
