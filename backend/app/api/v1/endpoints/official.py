"""官方处罚记录（真实采集，每条带原文链接和网页快照 hash）。查看：所有角色；触发采集：管理员。"""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from ....schemas import CollectIn
from ....services import official_service
from ...deps import DB, CurrentUser, require_role

router = APIRouter(prefix="/official", tags=["官方处罚"])


@router.get("/sources", summary="官方采集源及入库情况")
def sources(user=CurrentUser, conn=DB):
    return official_service.sources_status(conn)


@router.get("/records", summary="官方处罚记录检索")
def search(source_id: Optional[str] = None, investigation_status: Optional[str] = None,
           topic_id: Optional[int] = None, store_id: Optional[int] = None,
           catering: Optional[bool] = Query(None, description="只看餐饮服务主体"),
           keyword: Optional[str] = Query(None, description="匹配当事人 / 案件标题 / 案情"),
           page: int = 1, page_size: int = 20, user=CurrentUser, conn=DB):
    filters = {"source_id": source_id, "investigation_status": investigation_status, "topic_id": topic_id,
               "store_id": store_id, "catering": catering, "keyword": keyword}
    return official_service.search(conn, filters, page, page_size)


@router.get("/records/{rid}", summary="官方处罚记录详情（含快照信息）")
def detail(rid: int, user=CurrentUser, conn=DB):
    return official_service.detail(conn, rid)


@router.post("/collect", summary="立即采集一个官方源（同步执行，页数越多越慢）")
def collect(body: CollectIn, user=Depends(require_role("admin")), conn=DB):
    return official_service.collect(conn, body.source_id, body.pages)
