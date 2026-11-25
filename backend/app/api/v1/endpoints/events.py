"""事件专题：详情、溯源、改级、处置、话术草案、生成报告。"""
from typing import Optional

from fastapi import APIRouter, Depends

from ....schemas import DisposalIn, DraftAdoptIn, LevelIn
from ....services import event_service, report_service
from ...deps import DB, CurrentUser, require_role

router = APIRouter(prefix="/events", tags=["事件"])


@router.get("", summary="事件列表")
def list_events(level: Optional[str] = None, status: Optional[str] = None, user=CurrentUser, conn=DB):
    return event_service.list_events(conn, level, status)


@router.get("/{eid}", summary="事件详情")
def detail(eid: str, user=CurrentUser, conn=DB):
    return event_service.detail(conn, eid)


@router.get("/{eid}/timeline", summary="传播时间线")
def timeline(eid: str, user=CurrentUser, conn=DB):
    return event_service.timeline(conn, eid)


@router.get("/{eid}/graph", summary="实体关系图")
def graph(eid: str, user=CurrentUser, conn=DB):
    return event_service.graph(conn, eid)


@router.post("/{eid}/level", summary="人工改级（分析师、管理员）")
def change_level(eid: str, body: LevelIn, user=Depends(require_role("analyst", "admin")), conn=DB):
    return event_service.change_level(conn, eid, body.level, body.reason, user)


@router.post("/{eid}/disposal", summary="处置流转（公关、管理员）")
def dispose(eid: str, body: DisposalIn, user=Depends(require_role("pr", "admin")), conn=DB):
    return event_service.dispose(conn, eid, body.to_status, body.note, user)


@router.get("/{eid}/disposals", summary="处置记录")
def disposals(eid: str, user=CurrentUser, conn=DB):
    return event_service.disposals(conn, eid)


@router.post("/{eid}/response-draft", summary="生成回应话术草案")
def response_draft(eid: str, user=CurrentUser, conn=DB):
    return event_service.generate_draft(conn, eid, user)


@router.post("/{eid}/draft-adopt", summary="采纳话术草案（公关、管理员）")
def draft_adopt(eid: str, body: Optional[DraftAdoptIn] = None,
                user=Depends(require_role("pr", "admin")), conn=DB):
    """不传 draft_id 时采纳最新一条草案。"""
    return event_service.adopt_draft(conn, eid, body.draft_id if body else None, user)


@router.post("/{eid}/report", summary="生成事件报告（分析师、管理员）")
def make_report(eid: str, user=Depends(require_role("analyst", "admin")), conn=DB):
    return report_service.create(conn, eid, user)
