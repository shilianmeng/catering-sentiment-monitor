"""报告中心。"""
from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.responses import Response

from ....services import report_service
from ...deps import DB, CurrentUser

router = APIRouter(prefix="/reports", tags=["报告"])


@router.get("", summary="报告列表")
def list_reports(user=CurrentUser, conn=DB):
    return report_service.list_reports(conn)


@router.get("/{rid}", summary="报告详情（含 Markdown 正文）")
def detail(rid: int, user=CurrentUser, conn=DB):
    return report_service.get(conn, rid)


@router.get("/{rid}/export", summary="导出 Markdown / PDF")
def export(rid: int, format: str = Query("md", pattern="^(md|pdf)$"), user=CurrentUser, conn=DB):
    data, media_type, filename = report_service.export(conn, rid, format)
    return Response(data, media_type=media_type,
                    headers={"Content-Disposition": f"attachment; filename=\"{filename}\"; "
                                                    f"filename*=UTF-8''{quote(filename)}"})
