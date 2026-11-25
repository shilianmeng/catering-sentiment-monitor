"""监测主题 CRUD（新建/修改/删除：分析师、管理员）。"""
from fastapi import APIRouter, Depends

from ....schemas import TopicCreate, TopicUpdate
from ....services import topic_service
from ...deps import DB, CurrentUser, require_role

router = APIRouter(prefix="/topics", tags=["监测主题"])
_editor = require_role("analyst", "admin")


@router.get("", summary="主题列表")
def list_topics(user=CurrentUser, conn=DB):
    return topic_service.list_topics(conn)


@router.post("", summary="新建主题")
def create(body: TopicCreate, user=Depends(_editor), conn=DB):
    return topic_service.create(conn, body.model_dump(), user)


@router.put("/{tid}", summary="修改主题（只改传了的字段）")
def update(tid: int, body: TopicUpdate, user=Depends(_editor), conn=DB):
    return topic_service.update(conn, tid, body.model_dump(exclude_unset=True))


@router.delete("/{tid}", summary="删除主题（已关联内容或事件时不能删）")
def delete(tid: int, user=Depends(_editor), conn=DB):
    topic_service.delete(conn, tid)
    return {"ok": True}
