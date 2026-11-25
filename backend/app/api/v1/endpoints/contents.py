"""研判工作台：内容检索与详情。"""
from typing import Optional

from fastapi import APIRouter, Query

from ....services import content_service
from ...deps import DB, CurrentUser

router = APIRouter(prefix="/contents", tags=["内容"])


@router.get("", summary="多条件检索内容")
def search(topic_id: Optional[int] = None, source_type: Optional[str] = None,
           sentiment: Optional[str] = None, level: Optional[str] = None,
           emotion: Optional[str] = None, event_id: Optional[str] = None,
           media_type: Optional[str] = None,
           source_category: Optional[str] = Query(None, description="官方通报 / 媒体报道 / 顾客投诉 / 品牌回应"),
           store_id: Optional[int] = Query(None, description="门店 id"),
           start: Optional[str] = Query(None, description="发布时间起，YYYY-MM-DD HH:MM"),
           end: Optional[str] = Query(None, description="发布时间止"),
           keyword: Optional[str] = Query(None, description="匹配正文 / OCR / ASR / 作者"),
           include_dup: bool = Query(False, description="是否包含被合并的重复帖"),
           page: int = 1, page_size: int = 12,
           user=CurrentUser, conn=DB):
    filters = {"topic_id": topic_id, "source_type": source_type, "sentiment": sentiment, "level": level,
               "emotion": emotion, "event_id": event_id, "media_type": media_type,
               "source_category": source_category, "store_id": store_id,
               "start": start, "end": end, "keyword": keyword}
    return content_service.search(conn, filters, include_dup, page, page_size)


@router.get("/{cid}", summary="内容详情")
def detail(cid: str, user=CurrentUser, conn=DB):
    return content_service.detail(conn, cid)
